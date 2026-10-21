// Haptic Grip Module firmware: Seeed XIAO RP2040 + XC330 (SEA trigger) + AS5600.
//
// 1 kHz loop: read lever angle (AS5600) → read servo position/current (Dynamixel 2.0 at
// 4 Mbps) → run the SEA force law → write the servo goal position → service USB.
// TELEMETRY goes out at 1 kHz / telemetry_div (500 Hz by default).
//
// Safety:
//  * Servo power is gated by a P-MOSFET that is enabled only after the servo answers a ping.
//  * Current-based position mode with Goal Current = current limit caps torque in the servo.
//  * Host watchdog: in RENDER, no SETPOINT for watchdog_ms → fall back to SPRING (passive return).
//  * RP2040 hardware watchdog (100 ms): a hung loop reboots the MCU and the gate drops servo power.
//  * Servo hardware-error bits, over-force and magnet faults are reported in TELEMETRY.status.

#include <Adafruit_NeoPixel.h>
#include <Arduino.h>
#include <Wire.h>
#include <pico/unique_id.h>

#include "as5600.h"
#include "config.h"
#include "control.h"
#include "cue.h"
#include "drv2605.h"
#include "dxl.h"
#include "filters.h"
#include "params_store.h"
#include "protocol.h"

using namespace hgm;

namespace {

dxl::Bus g_dxl(Serial1, kPinDxlDir);
AS5600 g_enc(Wire1);
DRV2605 g_drv(Wire);           // I2C0 on GP28/GP29, 400 kHz
CueEngine g_cue;
Biquad g_notch;                // LRA-frequency notch on the lever angle (always in the path)
uint32_t g_vbus_warn_ms = 0;
Adafruit_NeoPixel g_led(1, kPinLed, NEO_GRB + NEO_KHZ800);
TriggerController g_ctl;
StoredParams g_params;
FrameDecoder g_rx;

Setpoint g_sp;                 // last setpoint from the host
uint32_t g_last_sp_ms = 0;
bool g_host_seen = false;
uint8_t g_mode = kModeOff;     // effective mode after the watchdog
uint16_t g_status = 0;
uint16_t g_tx_seq = 0;
uint8_t g_servo_id = kDxlDefaultId;
bool g_servo_ok = false;
bool g_torque_on = false;
uint8_t g_hw_err = 0;
uint16_t g_loop_us_max = 0;
uint32_t g_tick = 0;
uint32_t g_next_us = 0;
float g_lever_rad = 0.f, g_servo_rad = 0.f;
int16_t g_servo_ma = 0;
ControlOutput g_out;
char g_serial[17] = {0};

// buttons
struct Debounce {
  uint8_t pin;
  bool state = false;
  bool last_raw = false;
  uint32_t since = 0;
  void begin(uint8_t p) { pin = p; pinMode(p, INPUT_PULLUP); }
  void update(uint32_t now_ms) {
    bool raw = digitalRead(pin) == LOW;  // pressed pulls to GND
    if (raw != last_raw) { last_raw = raw; since = now_ms; }
    if ((now_ms - since) >= kDebounceMs) state = raw;
  }
} g_btn_a, g_btn_b;

// LED: host override (valid for 2 s after the last LED packet), else status colours
Led g_host_led{0, 0, 0, 0};
uint32_t g_host_led_ms = 0;
uint32_t g_identify_until = 0;

// TARE procedure state
enum class Tare { kIdle, kRelax, kSample } g_tare = Tare::kIdle;
uint32_t g_tare_t0 = 0;
float g_tare_acc = 0.f;
uint32_t g_tare_n = 0;
uint8_t g_tare_mode_before = kModeSpring;
uint16_t g_tare_seq = 0;

float P(Param id) { return g_params.values[id]; }

void apply_params_to_controller() {
  ControlParams c = g_ctl.params();
  c.k_theta = P(kParamKTheta);
  c.finger_radius = P(kParamFingerRadius);
  c.theta_open = P(kParamThetaOpen);
  c.theta_closed = P(kParamThetaClosed);
  c.sea_zero = P(kParamSeaZero);
  c.ki = P(kParamKi);
  c.preload_nm = P(kParamPreloadNm);
  g_ctl.set_params(c);
}

// ---------------------------------------------------------------- TX helpers
void send_body(uint8_t type, const uint8_t* body, size_t n, bool must = true) {
  uint8_t frame[kMaxFrame + 4];
  size_t m = encode_frame(type, g_tx_seq++, body, n, frame, sizeof(frame));
  if (!m) return;
  if (!must && Serial.availableForWrite() < (int)m) return;  // never block the loop for telemetry
  Serial.write(frame, m);
}

void send_ack(uint8_t req_type, uint16_t req_seq, uint8_t result, float value) {
  Ack a{req_type, req_seq, result, value};
  uint8_t b[kAckLen];
  send_body(kAck, b, pack(a, b));
}

void send_log(uint8_t level, const char* text) {
  uint8_t b[kMaxPayload];
  size_t n = strlen(text);
  if (n > kMaxPayload - 7) n = kMaxPayload - 7;
  b[0] = level;
  memcpy(b + 1, text, n);
  send_body(kLog, b, n + 1);
}

void send_info() {
  Info info{};
  info.proto = kProtoVersion;
  info.fw_major = HGM_FW_MAJOR;
  info.fw_minor = HGM_FW_MINOR;
  info.fw_patch = HGM_FW_PATCH;
  info.hw_rev = make_hw_rev(kDevHgm, HGM_HW_REV);
  info.rx_errors = (uint16_t)(g_rx.errors() > 0xFFFF ? 0xFFFF : g_rx.errors());
  memcpy(info.serial, g_serial, 16);
  uint8_t b[kInfoLen];
  send_body(kInfo, b, pack(info, b));
}

// ---------------------------------------------------------------- servo
bool servo_configure() {
  const uint8_t id = g_servo_id;
  // EEPROM area: only write when different (limits wear), torque must be off
  g_dxl.write8(id, dxl::kTorqueEnable, 0, true);
  uint8_t v8 = 0;
  uint16_t v16 = 0;
  if (g_dxl.read8(id, dxl::kReturnDelay, &v8) && v8 != 0) g_dxl.write8(id, dxl::kReturnDelay, 0, true);
  if (g_dxl.read8(id, dxl::kOperatingMode, &v8) && v8 != dxl::kModeCurrentBasedPosition)
    g_dxl.write8(id, dxl::kOperatingMode, dxl::kModeCurrentBasedPosition, true);
  const uint16_t ilim = (uint16_t)P(kParamCurrentLimitMa);
  if (g_dxl.read16(id, dxl::kCurrentLimit, &v16) && v16 != ilim) g_dxl.write16(id, dxl::kCurrentLimit, ilim, true);
  // RAM area
  g_dxl.write16(id, dxl::kPositionPGain, (uint16_t)P(kParamServoPGain), true);
  g_dxl.write32(id, dxl::kProfileAccel, 0, true);
  g_dxl.write32(id, dxl::kProfileVelocity, 0, true);
  g_dxl.write16(id, dxl::kGoalCurrent, ilim, true);
  // From now on WRITE gets no status packet (saves ~30 µs per tick); PING/READ still answer.
  return g_dxl.write8(id, dxl::kStatusReturnLevel, 1, true);
}

bool servo_bringup() {
  digitalWrite(kPinServoEn, HIGH);
  delay(120);  // gate soft-start (≈5 ms) + servo boot
  const uint32_t bauds[] = {kDxlBaud, 1000000, 57600};
  for (uint32_t b : bauds) {
    g_dxl.set_baud(b);
    for (uint8_t id : {kDxlDefaultId, (uint8_t)0, (uint8_t)2, (uint8_t)3}) {
      rp2040.wdt_reset();
      if (g_dxl.ping(id)) {
        g_servo_id = id;
        if (b != kDxlBaud) {  // move the servo to 4 Mbps once
          g_dxl.write8(id, dxl::kTorqueEnable, 0, true);
          g_dxl.write8(id, dxl::kBaudRate, kDxlBaudIndex, true);
          delay(20);
          g_dxl.set_baud(kDxlBaud);
          if (!g_dxl.ping(id)) return false;
        }
        return servo_configure();
      }
    }
  }
  g_dxl.set_baud(kDxlBaud);
  return false;
}

void set_torque(bool on) {
  if (!g_servo_ok || on == g_torque_on) return;
  if (on) g_dxl.write32(g_servo_id, dxl::kGoalPosition, (int32_t)lroundf(P(kParamServoDir) * g_servo_rad * 4096.f / 6.2831853f), false);
  g_dxl.write8(g_servo_id, dxl::kTorqueEnable, on ? 1 : 0, false);
  g_torque_on = on;
}

bool read_servo() {
  uint8_t b[10];  // present current (2), velocity (4), position (4)
  if (!g_dxl.read(g_servo_id, dxl::kPresentCurrent, 10, b)) return false;
  g_servo_ma = (int16_t)(b[0] | (b[1] << 8));
  int32_t pos = (int32_t)((uint32_t)b[6] | ((uint32_t)b[7] << 8) | ((uint32_t)b[8] << 16) | ((uint32_t)b[9] << 24));
  g_servo_rad = P(kParamServoDir) * (float)pos * (6.2831853f / 4096.f);
  return true;
}

// ---------------------------------------------------------------- host packets
void handle_frame() {
  const uint8_t type = g_rx.type();
  const uint16_t seq = g_rx.seq();
  const uint8_t* body = g_rx.body();
  const size_t n = g_rx.body_len();
  switch (type) {
    case kSetpoint: {
      Setpoint sp;
      if (unpack(body, n, &sp) && sp.mode <= kModePosition) {
        g_sp = sp;
        g_last_sp_ms = millis();
        g_host_seen = true;
      }
      break;
    }
    case kSetParam: {
      SetParam sp;
      float applied = NAN;
      uint8_t res = unpack(body, n, &sp) ? params_set(&g_params, sp.param, sp.value, &applied) : kAckBadValue;
      if (res == kAckOk) {
        g_status |= kStParamsDirty;
        apply_params_to_controller();
        if (sp.param == kParamCurrentLimitMa && g_servo_ok) {
          bool was = g_torque_on;
          set_torque(false);
          g_dxl.write16(g_servo_id, dxl::kCurrentLimit, (uint16_t)applied, false);
          g_dxl.write16(g_servo_id, dxl::kGoalCurrent, (uint16_t)applied, false);
          set_torque(was);
        }
        if (sp.param == kParamServoPGain && g_servo_ok)
          g_dxl.write16(g_servo_id, dxl::kPositionPGain, (uint16_t)applied, false);
      }
      send_ack(type, seq, res, applied);
      break;
    }
    case kGetParam: {
      GetParam gp;
      float v = NAN;
      bool ok = unpack(body, n, &gp) && params_get(g_params, gp.param, &v);
      send_ack(type, seq, ok ? kAckOk : kAckBadParam, v);
      break;
    }
    case kCommand: {
      CommandPkt c;
      if (!unpack(body, n, &c)) { send_ack(type, seq, kAckBadValue, 0); break; }
      switch (c.cmd) {
        case kCmdTareSea:
          if (g_tare != Tare::kIdle) { send_ack(type, seq, kAckFailed, 0); break; }
          g_tare = Tare::kRelax;
          g_tare_t0 = millis();
          g_tare_mode_before = g_sp.mode;
          g_tare_seq = seq;
          break;  // ACK is sent when the tare finishes
        case kCmdSaveParams: {
          bool ok = params_save(&g_params);
          if (ok) g_status &= ~kStParamsDirty;
          send_ack(type, seq, ok ? kAckOk : kAckFailed, 0);
          break;
        }
        case kCmdLoadDefaults:
          params_defaults(&g_params);
          apply_params_to_controller();
          g_status |= kStParamsDirty;
          send_ack(type, seq, kAckOk, 0);
          break;
        case kCmdReboot:
          send_ack(type, seq, kAckOk, 0);
          Serial.flush();
          delay(20);
          rp2040.reboot();
          break;
        case kCmdBootsel:
          send_ack(type, seq, kAckOk, 0);
          Serial.flush();
          delay(20);
          rp2040.rebootToBootloader();
          break;
        case kCmdClearFaults:
          g_status &= ~(kStWatchdog | kStServoHwError | kStOverforce | kStMagnetFault);
          if (g_hw_err && g_servo_ok) { g_dxl.reboot(g_servo_id); delay(50); servo_configure(); g_torque_on = false; }
          g_hw_err = 0;
          send_ack(type, seq, kAckOk, 0);
          break;
        case kCmdIdentify:
          g_identify_until = millis() + 3000;
          send_ack(type, seq, kAckOk, 0);
          break;
        default:
          send_ack(type, seq, kAckBadParam, 0);
      }
      break;
    }
    case kPing:
      send_info();
      break;
    case kCue: {  // fire-and-forget (no ACK), host sends at ≤ 50 Hz
      CuePkt c;
      if (unpack(body, n, &c) && (g_status & kStLraOk)) g_cue.trigger(c, millis());
      break;
    }
    case kLed: {
      Led l;
      if (unpack(body, n, &l)) { g_host_led = l; g_host_led_ms = millis(); }
      break;
    }
    default:
      send_ack(type, seq, kAckUnknownType, 0);
  }
}

void service_usb() {
  int budget = 128;  // bounded work per tick
  while (budget-- > 0 && Serial.available()) {
    if (g_rx.feed((uint8_t)Serial.read())) handle_frame();
  }
}

// ---------------------------------------------------------------- LED
uint32_t rgb(uint8_t r, uint8_t g, uint8_t b) { return g_led.Color(r, g, b); }

void update_led(uint32_t now) {
  uint32_t c;
  uint8_t pattern = 0;
  if (now < g_identify_until) {
    c = rgb(255, 255, 255); pattern = 1;
  } else if (g_host_led_ms && now - g_host_led_ms < 2000) {
    c = rgb(g_host_led.r, g_host_led.g, g_host_led.b); pattern = g_host_led.pattern;
  } else if (g_status & (kStServoHwError | kStMagnetFault) || !g_servo_ok) {
    c = rgb(255, 0, 0); pattern = 1;
  } else if (g_status & kStWatchdog) {
    c = rgb(255, 120, 0); pattern = 1;
  } else if (g_mode == kModeRender) {
    c = rgb(0, 160, 255);
  } else if (g_mode == kModeSpring) {
    c = rgb(0, 200, 60);
  } else {
    c = rgb(40, 40, 40); pattern = 2;
  }
  float k = 1.f;
  if (pattern == 1) k = ((now / 250) & 1) ? 1.f : 0.f;
  if (pattern == 2) k = 0.25f + 0.75f * (0.5f + 0.5f * sinf((float)now * 0.004f));
  uint8_t r = (uint8_t)(((c >> 16) & 0xFF) * k * 0.25f), g = (uint8_t)(((c >> 8) & 0xFF) * k * 0.25f),
          b = (uint8_t)((c & 0xFF) * k * 0.25f);
  g_led.setPixelColor(0, rgb(r, g, b));
  g_led.show();
}

// ---------------------------------------------------------------- slow housekeeping (20 Hz)
void housekeeping(uint32_t now) {
  static uint8_t phase = 0;
  phase = (phase + 1) % 3;
  if (phase == 0) {
    uint8_t st = 0;
    bool ok = g_enc.magnet_ok(&st);
    if (!ok) g_status |= kStMagnetFault;
    if (st & AS5600::kMD) g_status |= kStEncoderOk; else g_status &= ~kStEncoderOk;
  } else if (phase == 1 && g_servo_ok) {
    uint8_t e = 0;
    if (g_dxl.read8(g_servo_id, dxl::kHardwareError, &e) && e) {
      g_hw_err = e;
      g_status |= kStServoHwError;
    }
  }
  update_led(now);
  if (phase == 2) {  // bus voltage: warn once per 5 s if the leader's 5 V sags
    const float v = analogRead(kPinVbusSense) * (3.3f / 4095.f) * 2.f;
    if (v < 4.5f && v > 0.5f && now - g_vbus_warn_ms > 5000) {
      char msg[40];
      snprintf(msg, sizeof msg, "5V bus low: %.2f V", v);
      send_log(2, msg);
      g_vbus_warn_ms = now;
    }
  }
}

void wdt_service() { rp2040.wdt_reset(); }

}  // namespace

// ---------------------------------------------------------------- Arduino entry points
void setup() {
  pinMode(kPinServoEn, OUTPUT);
  digitalWrite(kPinServoEn, LOW);
  pinMode(kPinLedPwr, OUTPUT);
  digitalWrite(kPinLedPwr, HIGH);
  g_led.begin();
  g_led.setPixelColor(0, g_led.Color(0, 0, 40));
  g_led.show();
  g_btn_a.begin(kPinBtnA);
  g_btn_b.begin(kPinBtnB);
  analogReadResolution(12);

  pico_unique_board_id_t uid;
  pico_get_unique_board_id(&uid);
  for (int i = 0; i < 8; ++i) snprintf(g_serial + 2 * i, 3, "%02X", uid.id[i]);

  Serial.begin(115200);  // USB CDC; the baud rate is ignored
  params_load(&g_params);
  apply_params_to_controller();
  g_sp.mode = kModeSpring;

  Wire1.setSDA(kPinI2cSda);
  Wire1.setSCL(kPinI2cScl);
  Wire1.begin();
  Wire1.setClock(1000000);
  if (g_enc.begin()) g_status |= kStEncoderOk;

  // v1.1: haptic driver on its own I²C bus, auto-calibrated at every boot (≈ 1 s, a short buzz)
  Wire.setSDA(kPinHapSda);
  Wire.setSCL(kPinHapScl);
  Wire.begin();
  Wire.setClock(kHapticI2cHz);
  g_notch = Biquad::notch(kLraNotchHz, kLraNotchQ, 1e6f / (float)kLoopPeriodUs);

  Serial1.setTX(kPinDxlTx);
  Serial1.setRX(kPinDxlRx);
  pinMode(kPinDxlRx, INPUT_PULLUP);
  g_dxl.begin(kDxlBaud);
  rp2040.wdt_begin(2000);  // generous during bring-up
  {
    LraSpec lra;
    if (g_drv.begin_and_calibrate(lra, wdt_service)) g_status |= kStLraOk;
  }
  g_servo_ok = servo_bringup();
  if (g_servo_ok) {
    g_status |= kStServoOk | kStServoPower;
    read_servo();
  } else {
    digitalWrite(kPinServoEn, LOW);  // nothing answered: keep the bus unpowered
  }
  send_info();
  send_log(g_servo_ok ? 1 : 3, g_servo_ok ? "hgm ready" : "servo not found on any baud/id");
  if (!g_drv.present()) send_log(2, "DRV2605L not found: cues disabled");
  else if (!(g_status & kStLraOk)) send_log(2, "LRA auto-calibration failed: cues disabled");
  rp2040.wdt_begin(kHwWatchdogMs);
  g_next_us = micros() + kLoopPeriodUs;
}

void loop() {
  // fixed-rate scheduling
  while ((int32_t)(micros() - g_next_us) < 0) {
    if (Serial.available()) service_usb();
  }
  const uint32_t t0 = micros();
  g_next_us += kLoopPeriodUs;
  if ((int32_t)(t0 - g_next_us) > (int32_t)(5 * kLoopPeriodUs)) g_next_us = t0 + kLoopPeriodUs;  // resync
  const uint32_t now = millis();
  rp2040.wdt_reset();

  // ---- sense
  float raw = g_enc.angle_rad();
  if (raw == raw) {
    const float mid = 0.5f * (P(kParamThetaOpen) + P(kParamThetaClosed));
    // the notch removes LRA vibration (235 Hz) from the force estimate and the servo command;
    // below 30 Hz it adds < 2° of phase and 0.45 ms of group delay
    g_lever_rad = g_notch.step(unwrap_near(P(kParamLeverDir) * raw, mid));
  }
  bool servo_read_ok = g_servo_ok && read_servo();
  g_btn_a.update(now);
  g_btn_b.update(now);
  service_usb();

  // ---- effective mode: watchdog + tare + faults
  uint8_t mode = g_sp.mode;
  const uint32_t wd = (uint32_t)P(kParamWatchdogMs);
  if (mode == kModeRender && (!g_host_seen || now - g_last_sp_ms > wd)) {
    mode = kModeSpring;
    g_status |= kStWatchdog;
  } else if (mode == kModeRender) {
    g_status &= ~kStWatchdog;
  }
  if (!g_servo_ok || (g_status & kStServoHwError) || !servo_read_ok) mode = kModeOff;
  if (g_tare != Tare::kIdle) {
    mode = kModeOff;  // servo limp: the preload seats the tab on the backstop → δ = δ0
    if (g_tare == Tare::kRelax && now - g_tare_t0 > 300) { g_tare = Tare::kSample; g_tare_acc = 0; g_tare_n = 0; }
    if (g_tare == Tare::kSample) {
      g_tare_acc += wrap_pi(g_lever_rad - g_servo_rad);
      if (++g_tare_n >= 100) {
        float applied = 0;
        uint8_t res = params_set(&g_params, kParamSeaZero, g_tare_acc / (float)g_tare_n, &applied);
        apply_params_to_controller();
        g_status |= kStParamsDirty;
        send_ack(kCommand, g_tare_seq, res, applied);
        g_tare = Tare::kIdle;
        g_ctl.reset();
      }
    }
  }
  g_mode = mode;

  // ---- control
  ControlInput in;
  in.lever_rad = g_lever_rad;
  in.servo_rad = g_servo_rad;
  in.dt = kLoopPeriodUs * 1e-6f;
  in.sp = g_sp;
  in.sp.mode = mode;
  g_out = g_ctl.step(in);
  set_torque(g_out.torque_on);
  if (g_torque_on) {
    const int32_t goal = (int32_t)lroundf(P(kParamServoDir) * g_out.servo_cmd_rad * (4096.f / 6.2831853f));
    g_dxl.write32(g_servo_id, dxl::kGoalPosition, goal, false);
  }
  if (g_out.overforce) g_status |= kStOverforce;
  if (digitalRead(kPinServoEn)) g_status |= kStServoPower; else g_status &= ~kStServoPower;
  uint16_t cm = g_params.cal_mask;
  if ((cm & kCalTared) && (cm & kCalRange)) g_status |= kStCalValid; else g_status &= ~kStCalValid;
  if (g_servo_ok) g_status |= kStServoOk; else g_status &= ~kStServoOk;

  // ---- cues: at most one I²C write per tick, and only when the amplitude changes
  {
    uint8_t amp;
    if (g_cue.update(now, &amp)) g_drv.rtp(amp);
  }

  // ---- slow tasks
  if (g_tick % kSlowEveryTicks == 0) housekeeping(now);

  // ---- telemetry
  const uint32_t div = (uint32_t)P(kParamTelemetryDiv);
  if (div && g_tick % div == 0) {
    Telemetry t;
    t.t_us = t0;
    t.pos = g_out.pos;
    t.vel = g_out.vel;
    t.force_op_n = g_out.force_op_n;
    t.force_cmd_n = g_out.torque_on ? g_out.force_cmd_n : 0.f;
    t.lever_rad = g_lever_rad;
    t.servo_rad = g_servo_rad;
    t.servo_ma = g_servo_ma;
    t.buttons = (uint8_t)((g_btn_a.state ? 1 : 0) | (g_btn_b.state ? 2 : 0));
    t.mode = mode;
    t.status = g_status;
    t.loop_us_max = g_loop_us_max;
    uint8_t b[kTelemetryLen];
    send_body(kTelemetry, b, pack(t, b), /*must=*/false);
    g_loop_us_max = 0;
  }
  ++g_tick;
  const uint32_t dt = micros() - t0;
  if (dt > g_loop_us_max) g_loop_us_max = (uint16_t)(dt > 0xFFFF ? 0xFFFF : dt);
}
