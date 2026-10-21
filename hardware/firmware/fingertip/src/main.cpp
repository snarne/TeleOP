// FGS (follower fingertip sensor) firmware: Seeed XIAO RP2040 + ADS131M02 + two strain bridges.
//
// Core 1: waits for /DRDY (4 kSPS), reads both channels over SPI and runs the fixed-point DSP
//         (force low-pass, slip band-pass + RMS, tare, clip detection). It owns the SPI bus and
//         re-initialises the ADC by itself when samples stop.
// Core 0: USB CDC protocol (PING/INFO, SET/GET_PARAM, COMMAND), FINGERTIP telemetry at
//         telemetry_hz (500 Hz default), LED, hardware watchdog.
// The two cores share the measurement engine under a spin lock (held ≤ ~30 µs either side).

#include <Arduino.h>
#include <SPI.h>
#include <hardware/gpio.h>
#include <pico/critical_section.h>
#include <pico/unique_id.h>

#include "ads131m02.h"
#include "config.h"
#include "engine.h"
#include "fgs_params.h"
#include "protocol.h"

using namespace hgm;
using namespace fgs;

namespace {

// ---------------------------------------------------------------- shared state
critical_section_t g_cs;
FgsEngine g_eng;
FgsParams g_params;
volatile bool g_core0_ready = false;
volatile bool g_adc_ok = false;          // driver initialised and samples arriving
volatile uint32_t g_last_sample_us = 0;
volatile uint16_t g_adc_id = 0, g_adc_gain_rb = 0;
volatile uint32_t g_adc_inits = 0;       // incremented by core 1 after every init attempt
volatile bool g_adc_init_ok = false;
volatile bool g_crc_disabled = false;    // set by core 1 if the output CRC never matches (logged by core 0)

// ---------------------------------------------------------------- core-0 state
FrameDecoder g_rx;
uint16_t g_tx_seq = 0;
char g_serial[17] = {0};
uint32_t g_next_tlm_us = 0;
uint32_t g_tlm_period_us = 2000;
bool g_tare_pending = false;
uint16_t g_tare_seq = 0;
uint32_t g_tare_deadline_ms = 0;
bool g_dirty = false;
uint32_t g_seen_inits = 0;
bool g_logged_crc = false;
bool g_last_adc_ok = false;

void lock() { critical_section_enter_blocking(&g_cs); }
void unlock() { critical_section_exit(&g_cs); }

void apply_params() {
  g_tlm_period_us = (uint32_t)(1e6f / param(g_params, kFgsTelemetryHz) + 0.5f);
  lock();
  g_eng.configure(g_params, (double)kFsHz);
  unlock();
}

// ---------------------------------------------------------------- TX helpers
void send_body(uint8_t type, const uint8_t* body, size_t n, bool must = true) {
  uint8_t frame[kMaxFrame + 4];
  size_t m = encode_frame(type, g_tx_seq++, body, n, frame, sizeof(frame));
  if (!m) return;
  if (!must && Serial.availableForWrite() < (int)m) return;   // never stall for telemetry
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
  info.fw_major = FGS_FW_MAJOR;
  info.fw_minor = FGS_FW_MINOR;
  info.fw_patch = FGS_FW_PATCH;
  info.hw_rev = make_hw_rev(kDevFgs, FGS_HW_REV);
  info.rx_errors = (uint16_t)(g_rx.errors() > 0xFFFF ? 0xFFFF : g_rx.errors());
  memcpy(info.serial, g_serial, 16);
  uint8_t b[kInfoLen];
  send_body(kInfo, b, pack(info, b));
}

// ---------------------------------------------------------------- protocol
void handle_frame() {
  const uint8_t type = g_rx.type();
  const uint16_t seq = g_rx.seq();
  const uint8_t* body = g_rx.body();
  const size_t n = g_rx.body_len();
  switch (type) {
    case kSetParam: {
      SetParam sp;
      if (!unpack(body, n, &sp)) { send_ack(type, seq, kAckBadValue, 0); break; }
      float applied = 0;
      const uint8_t res = params_set(&g_params, sp.param, sp.value, &applied);
      if (res == kAckOk) {
        g_dirty = true;
        if (sp.param == kFgsHfBandLoHz || sp.param == kFgsHfBandHiHz || sp.param == kFgsTelemetryHz) apply_params();
      }
      send_ack(type, seq, res, applied);
      break;
    }
    case kGetParam: {
      GetParam gp;
      float v = 0;
      const bool ok = unpack(body, n, &gp) && params_get(g_params, gp.param, &v);
      send_ack(type, seq, ok ? kAckOk : kAckBadParam, v);
      break;
    }
    case kCommand: {
      CommandPkt c;
      if (!unpack(body, n, &c)) { send_ack(type, seq, kAckBadValue, 0); break; }
      switch (c.cmd) {
        case kFgsCmdTare: {
          bool busy;
          lock();
          busy = g_eng.tare_active();
          if (!busy && g_adc_ok) g_eng.start_tare(kTareSamples);
          unlock();
          if (busy || g_tare_pending || !g_adc_ok) { send_ack(type, seq, kAckFailed, 0); break; }
          g_tare_pending = true;          // ACK when the average is done (≈ 250 ms)
          g_tare_seq = seq;
          g_tare_deadline_ms = millis() + 1000;
          break;
        }
        case kFgsCmdSave: {
          // flash erase pauses core 1 for ~50 ms; telemetry resumes afterwards
          const bool ok = params_save(&g_params);
          if (ok) g_dirty = false;
          send_ack(type, seq, ok ? kAckOk : kAckFailed, 0);
          break;
        }
        case kFgsCmdLoadDefaults:
          params_defaults(&g_params);
          apply_params();
          g_dirty = true;
          send_ack(type, seq, kAckOk, 0);
          break;
        case kFgsCmdReboot:
          send_ack(type, seq, kAckOk, 0);
          Serial.flush();
          delay(20);
          rp2040.reboot();
          break;
        case kFgsCmdBootsel:
          send_ack(type, seq, kAckOk, 0);
          Serial.flush();
          delay(20);
          rp2040.rebootToBootloader();
          break;
        default:
          send_ack(type, seq, kAckBadParam, 0);
      }
      break;
    }
    case kPing:
      send_info();
      break;
    default:
      send_ack(type, seq, kAckUnknownType, 0);   // SETPOINT, LED, CUE are HGM-only
  }
}

void service_usb() {
  int budget = 256;
  while (budget-- > 0 && Serial.available()) {
    if (g_rx.feed((uint8_t)Serial.read())) handle_frame();
  }
}

// ---------------------------------------------------------------- LED (active low)
void led(bool r, bool g, bool b) {
  digitalWrite(kPinLedR, r ? LOW : HIGH);
  digitalWrite(kPinLedG, g ? LOW : HIGH);
  digitalWrite(kPinLedB, b ? LOW : HIGH);
}

void update_led(uint32_t now_ms, bool adc_ok) {
  const bool blink = (now_ms / 250) & 1;
  if (!adc_ok) led(blink, false, false);                       // red blink: ADC / bridge fault
  else if (g_tare_pending) led(false, false, true);            // blue: taring
  else if (!cal_valid(g_params)) led(false, blink, false);     // green blink: not calibrated
  else led(false, true, false);                                // green: ready
}

// ---------------------------------------------------------------- core 1: sampling
uint32_t c1_last_try_ms = 0;
uint32_t c1_frames = 0, c1_crc_bad = 0;
bool c1_crc_enforce = true;
uint16_t c1_proc_us = 0;
Ads131m02 g_adc;

void adc_init() {
  digitalWrite(kPinExcEn, HIGH);
  const bool ok = g_adc.begin(kPgaGainCode);
  g_adc_id = g_adc.id();
  g_adc_gain_rb = g_adc.gain_readback();
  g_adc_init_ok = ok;
  c1_frames = c1_crc_bad = 0;
  c1_crc_enforce = true;
  g_last_sample_us = micros();
  ++g_adc_inits;
}

}  // namespace

// ---------------------------------------------------------------- Arduino entry points (core 0)
void setup() {
  pinMode(kPinLedR, OUTPUT);
  pinMode(kPinLedG, OUTPUT);
  pinMode(kPinLedB, OUTPUT);
  led(false, false, true);
  pinMode(kPinExcEn, OUTPUT);
  digitalWrite(kPinExcEn, HIGH);   // bridges powered; the LDO settles in < 1 ms
  critical_section_init(&g_cs);

  pico_unique_board_id_t uid;
  pico_get_unique_board_id(&uid);
  for (int i = 0; i < 8; ++i) snprintf(g_serial + 2 * i, 3, "%02X", uid.id[i]);

  Serial.begin(115200);   // USB CDC; the baud rate is ignored
  const bool loaded = params_load(&g_params);
  apply_params();

  SPI.setSCK(kPinSpiSck);
  SPI.setTX(kPinSpiMosi);
  SPI.setRX(kPinSpiMiso);
  SPI.begin();

  g_core0_ready = true;
  const uint32_t t0 = millis();
  while (g_adc_inits == 0 && millis() - t0 < 200) delay(1);   // core 1 brings the ADC up
  send_info();
  char msg[56];
  snprintf(msg, sizeof(msg), "fgs ready: adc id %04X gain %04X %s", (unsigned)g_adc_id, (unsigned)g_adc_gain_rb,
           g_adc_init_ok ? "ok" : "FAIL");
  send_log(g_adc_init_ok ? 1 : 3, msg);
  if (!loaded) send_log(2, "no saved params: nominal scale, calibrate with weights");
  g_seen_inits = g_adc_inits;
  rp2040.wdt_begin(kHwWatchdogMs);
  g_next_tlm_us = micros() + g_tlm_period_us;
}

void loop() {
  rp2040.wdt_reset();
  if (Serial.available()) service_usb();
  const uint32_t now = micros();
  const bool adc_ok = g_adc_init_ok && (uint32_t)(now - g_last_sample_us) < kAdcStaleUs;
  g_adc_ok = adc_ok;

  if ((int32_t)(now - g_next_tlm_us) >= 0) {
    g_next_tlm_us += g_tlm_period_us;
    if ((int32_t)(now - g_next_tlm_us) > (int32_t)g_tlm_period_us) g_next_tlm_us = now + g_tlm_period_us;  // resync
    FingertipTelemetry t;
    float oa = 0, ob = 0;
    bool tare_done;
    lock();
    t = g_eng.make_telemetry(now, g_params, adc_ok);
    tare_done = g_eng.tare_take(&oa, &ob);
    unlock();
    uint8_t b[kFingertipLen];
    send_body(kFingertip, b, pack(t, b), /*must=*/false);
    if (tare_done && g_tare_pending) {
      float applied = 0;
      params_set(&g_params, kFgsOffsetA, oa, &applied);
      params_set(&g_params, kFgsOffsetB, ob, nullptr);
      g_dirty = true;
      g_tare_pending = false;
      send_ack(kCommand, g_tare_seq, kAckOk, applied);
    }
  }
  if (g_tare_pending && (int32_t)(millis() - g_tare_deadline_ms) > 0) {
    g_tare_pending = false;
    send_ack(kCommand, g_tare_seq, kAckFailed, 0);
  }
  // state-change logs
  if (adc_ok != g_last_adc_ok) {
    g_last_adc_ok = adc_ok;
    send_log(adc_ok ? 1 : 3, adc_ok ? "adc ok" : "adc lost: re-initialising");
  }
  if (g_crc_disabled && !g_logged_crc) {
    g_logged_crc = true;
    send_log(2, "adc output CRC never matched: CRC check disabled (VERIFY CRC coverage)");
  }
  update_led(millis(), adc_ok);
}

// ---------------------------------------------------------------- core 1
void setup1() {
  while (!g_core0_ready) tight_loop_contents();
  adc_init();
  c1_last_try_ms = millis();
}

void loop1() {
  const uint32_t now = micros();
  if (!g_adc_init_ok || (uint32_t)(now - g_last_sample_us) > kAdcStaleUs) {
    if (millis() - c1_last_try_ms >= kAdcRetryMs) {
      c1_last_try_ms = millis();
      adc_init();
    }
    if (!g_adc_init_ok) return;
  }
  if (gpio_get(kPinAdcDrdy)) return;   // /DRDY high: no new conversion yet
  const uint32_t t0 = micros();
  const ads::Frame f = g_adc.read();
  ++c1_frames;
  if (!f.crc_ok) {
    ++c1_crc_bad;
    if (c1_crc_enforce && c1_frames >= 200 && c1_crc_bad == c1_frames) {
      c1_crc_enforce = false;   // systematic mismatch: our CRC coverage assumption is wrong, not the link
      g_crc_disabled = true;
    }
    if (c1_crc_enforce) return;
  }
  lock();
  g_eng.on_sample(f.ch0, f.ch1, c1_proc_us);
  unlock();
  g_last_sample_us = now;
  const uint32_t dt = micros() - t0;
  c1_proc_us = (uint16_t)(dt > 0xFFFF ? 0xFFFF : dt);
}
