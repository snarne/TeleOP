// Host-native tests for the HGM firmware's pure modules:
//   1. protocol.cpp against the shared vectors (tests/vectors/haptic_protocol.json)
//   2. control.cpp against a physical simulation of the series-elastic trigger
//   3. params_store.cpp validation rules
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>

#include "../../src/control.h"
#include "../../src/cue.h"
#include "../../src/filters.h"
#include "../../src/params_store.h"
#include "protocol.h"
#include "minijson.h"

using namespace hgm;
using minijson::unhex;

static int g_fail = 0, g_pass = 0;
#define CHECK(cond, ...)                                    \
  do {                                                      \
    if (cond) { ++g_pass; } else {                          \
      ++g_fail; printf("FAIL %s:%d: ", __FILE__, __LINE__); \
      printf(__VA_ARGS__); printf("\n");                    \
    }                                                       \
  } while (0)

static bool near(double a, double b, double tol = 1e-5) { return std::fabs(a - b) <= tol * (1 + std::fabs(b)); }

static std::string read_file(const char* path) {
  std::ifstream f(path);
  std::stringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

// ------------------------------------------------------------------ protocol vectors
static void test_vectors(const char* path) {
  std::string text = read_file(path);
  CHECK(!text.empty(), "cannot read %s", path);
  if (text.empty()) return;
  minijson::Value v = minijson::Parser(text).parse();
  CHECK((int)v["proto"].num == kProtoVersion, "protocol version");

  for (const auto& c : v["crc"].arr) {
    auto d = unhex(c["data"].str);
    CHECK(crc16_ccitt_false(d.data(), d.size()) == (uint16_t)c["crc"].num, "crc mismatch len %zu", d.size());
  }
  for (const auto& c : v["cobs"].arr) {
    auto raw = unhex(c["raw"].str), enc = unhex(c["encoded"].str);
    std::vector<uint8_t> out(raw.size() + raw.size() / 254 + 2);
    size_t n = cobs_encode(raw.data(), raw.size(), out.data());
    CHECK(n == enc.size() && memcmp(out.data(), enc.data(), n) == 0, "cobs encode len %zu", raw.size());
    std::vector<uint8_t> dec(raw.size() + 4);
    int m = cobs_decode(enc.data(), enc.size(), dec.data(), dec.size());
    CHECK(m == (int)raw.size() && memcmp(dec.data(), raw.data(), raw.size()) == 0, "cobs decode len %zu", raw.size());
  }

  for (const auto& p : v["packets"].arr) {
    const std::string& name = p["name"].str;
    const auto& f = p["fields"];
    uint8_t type = (uint8_t)p["type"].num;
    uint16_t seq = (uint16_t)p["seq"].num;
    auto body_ref = unhex(p["body"].str), frame_ref = unhex(p["frame"].str);
    uint8_t body[kMaxPayload];
    size_t bn = 0;
    switch (type) {
      case kSetpoint: {
        Setpoint s;
        s.mode = (uint8_t)f["mode"].num; s.haptic_n = (float)f["haptic_n"].num; s.spring_n = (float)f["spring_n"].num;
        s.spring_min_n = (float)f["spring_min_n"].num; s.damping = (float)f["damping"].num;
        s.max_n = (float)f["max_n"].num; s.pos_cmd = (float)f["pos_cmd"].num;
        bn = pack(s, body);
        Setpoint back;
        CHECK(unpack(body_ref.data(), body_ref.size(), &back) && back.mode == s.mode && back.haptic_n == s.haptic_n,
              "%s unpack", name.c_str());
        break;
      }
      case kSetParam: {
        SetParam s{(uint8_t)f["param"].num, (float)f["value"].num};
        bn = pack(s, body);
        break;
      }
      case kCommand: body[0] = (uint8_t)f["cmd"].num; bn = 1; break;
      case kPing: bn = 0; break;
      case kLed: {
        Led l{(uint8_t)f["r"].num, (uint8_t)f["g"].num, (uint8_t)f["b"].num, (uint8_t)f["pattern"].num};
        bn = pack(l, body);
        break;
      }
      case kTelemetry: {
        Telemetry t;
        t.t_us = (uint32_t)f["t_us"].num; t.pos = (float)f["pos"].num; t.vel = (float)f["vel"].num;
        t.force_op_n = (float)f["force_op_n"].num; t.force_cmd_n = (float)f["force_cmd_n"].num;
        t.lever_rad = (float)f["lever_rad"].num; t.servo_rad = (float)f["servo_rad"].num;
        t.servo_ma = (int16_t)f["servo_ma"].num; t.buttons = (uint8_t)f["buttons"].num;
        t.mode = (uint8_t)f["mode"].num; t.status = (uint16_t)f["status"].num;
        t.loop_us_max = (uint16_t)f["loop_us_max"].num;
        bn = pack(t, body);
        Telemetry back;
        CHECK(unpack(body_ref.data(), body_ref.size(), &back) && back.servo_ma == t.servo_ma && back.t_us == t.t_us,
              "%s unpack", name.c_str());
        break;
      }
      case kAck: {
        Ack a{(uint8_t)f["req_type"].num, (uint16_t)f["req_seq"].num, (uint8_t)f["result"].num, (float)f["value"].num};
        bn = pack(a, body);
        break;
      }
      case kInfo: {
        Info in{};
        in.proto = (uint16_t)f["proto"].num; in.fw_major = (uint8_t)f["fw_major"].num;
        in.fw_minor = (uint8_t)f["fw_minor"].num; in.fw_patch = (uint8_t)f["fw_patch"].num;
        in.hw_rev = (uint8_t)f["hw_rev"].num; in.rx_errors = (uint16_t)f["rx_errors"].num;
        memset(in.serial, 0, 16);
        memcpy(in.serial, f["serial"].str.data(), std::min<size_t>(16, f["serial"].str.size()));
        bn = pack(in, body);
        break;
      }
      case kCue: {
        CuePkt c{(uint8_t)f["waveform"].num, (uint8_t)f["amplitude"].num, (uint16_t)f["duration_ms"].num};
        bn = pack(c, body);
        CuePkt back{};
        CHECK(unpack(body_ref.data(), body_ref.size(), &back) && back.waveform == c.waveform &&
                  back.duration_ms == c.duration_ms, "%s unpack", name.c_str());
        break;
      }
      case kFingertip: {
        FingertipTelemetry t{};
        t.t_us = (uint32_t)f["t_us"].num; t.force_a_n = (float)f["force_a_n"].num; t.force_b_n = (float)f["force_b_n"].num;
        t.hf_a_n = (float)f["hf_a_n"].num; t.hf_b_n = (float)f["hf_b_n"].num; t.status = (uint16_t)f["status"].num;
        t.loop_us_max = (uint16_t)f["loop_us_max"].num;
        bn = pack(t, body);
        FingertipTelemetry back{};
        CHECK(unpack(body_ref.data(), body_ref.size(), &back) && back.force_a_n == t.force_a_n &&
                  back.status == t.status, "%s unpack", name.c_str());
        break;
      }
      default: CHECK(false, "unknown type in vectors 0x%02x", type);
    }
    CHECK(bn == body_ref.size() && memcmp(body, body_ref.data(), bn) == 0, "%s body", name.c_str());
    uint8_t frame[kMaxFrame + 4];
    size_t fn = encode_frame(type, seq, body, bn, frame, sizeof(frame));
    CHECK(fn == frame_ref.size() && memcmp(frame, frame_ref.data(), fn) == 0, "%s frame", name.c_str());
    // stream decode, with a garbage prefix and a split delivery
    FrameDecoder d;
    const uint8_t junk[] = {0x13, 0x37, 0x00};
    for (uint8_t b : junk) d.feed(b);
    bool got = false;
    for (uint8_t b : frame_ref) got = d.feed(b) || got;
    CHECK(got && d.type() == type && d.seq() == seq && d.body_len() == body_ref.size() &&
              memcmp(d.body(), body_ref.data(), body_ref.size()) == 0, "%s stream decode", name.c_str());
    // corrupt one byte → must be rejected
    if (frame_ref.size() > 4) {
      FrameDecoder d2;
      auto bad = frame_ref;
      bad[2] ^= 0x40;
      if (bad[2] == 0) bad[2] = 0x41;
      bool ok = false;
      for (uint8_t b : bad) ok = d2.feed(b) || ok;
      CHECK(!ok && d2.errors() >= 1, "%s corruption detected", name.c_str());
    }
  }
}

// ------------------------------------------------------------------ control law vs. plant
// Plant: lever with inertia J and viscous friction, spring (preloaded, one-sided against the
// backstop), finger = stiff virtual wall pressing toward "closed" with force Ff, servo = first-order
// position tracking (bandwidth ~ 25 Hz, speed-limited at 8.5 rad/s like an XC330 at 5 V).
struct Plant {
  double k = 3.144, tau_p = 0.0472, rf = 0.045;
  double J = 4e-6, b = 2e-4;
  double th_l = 0.0, w_l = 0.0, th_s = 0.0;
  double th_open = 0.0, th_closed = 0.5236, delta0 = 0.0;
  double spring_torque() const {
    double d = th_l - th_s - delta0;
    return d >= 0 ? tau_p + k * d : 0.0;  // backstop: no tension through the spring
  }
  void step(double servo_cmd, double finger_n, double dt) {
    // servo
    double vmax = 8.5, wn = 2 * M_PI * 25.0;
    double dv = (servo_cmd - th_s) * wn;
    if (dv > vmax) dv = vmax;
    if (dv < -vmax) dv = -vmax;
    th_s += dv * dt;
    // backstop is rigid: the lever cannot be less deflected than delta0
    double tau = finger_n * rf - spring_torque() - b * w_l;
    w_l += tau / J * dt;
    th_l += w_l * dt;
    if (th_l - th_s < delta0) { th_l = th_s + delta0; if (w_l < 0) w_l = 0; }
    if (th_l < th_open) { th_l = th_open; if (w_l < 0) w_l = 0; }
    if (th_l > th_closed) { th_l = th_closed; if (w_l > 0) w_l = 0; }
  }
};

static void test_control() {
  TriggerController c;
  ControlParams p;
  p.k_theta = 3.144f; p.preload_nm = 0.0472f; p.finger_radius = 0.045f;
  c.set_params(p);
  Plant pl;
  const double dt = 1e-3;
  // 1) No finger: spring mode holds the lever on the open stop, F_op reported 0
  Setpoint sp; sp.mode = kModeSpring; sp.spring_min_n = 1.2f; sp.spring_n = 1.5f; sp.damping = 0.02f; sp.max_n = 12.f;
  ControlOutput o{};
  for (int i = 0; i < 2000; ++i) {
    for (int k = 0; k < 10; ++k) pl.step(o.servo_cmd_rad, 0.0, dt / 10);
    ControlInput in{(float)pl.th_l, (float)pl.th_s, (float)dt, sp};
    o = c.step(in);
  }
  CHECK(o.on_open_stop && o.force_op_n == 0.f, "spring mode at rest: on stop, Fop=0 (p=%f)", o.pos);
  CHECK(near(o.force_spring_n, 1.2, 0.08), "rest spring force ~ spring_min (got %f)", o.force_spring_n);

  // 2) Finger pushes 5 N in RENDER with 3 N haptic: equilibrium position where 5 = 1.2 + 1.5 p + 3
  sp.mode = kModeRender; sp.haptic_n = 3.0f;
  for (int i = 0; i < 4000; ++i) {
    for (int k = 0; k < 10; ++k) pl.step(o.servo_cmd_rad, 5.0, dt / 10);
    ControlInput in{(float)pl.th_l, (float)pl.th_s, (float)dt, sp};
    o = c.step(in);
  }
  double p_expect = (5.0 - 1.2 - 3.0) / 1.5;
  CHECK(near(o.pos, p_expect, 0.06), "render equilibrium p=%f expect %f", o.pos, p_expect);
  CHECK(near(o.force_op_n, 5.0, 0.04), "measured F_op=%f expect 5 N", o.force_op_n);

  // 3) Haptic force larger than the finger force: lever pushed back to the open stop
  sp.haptic_n = 8.0f;
  for (int i = 0; i < 3000; ++i) {
    for (int k = 0; k < 10; ++k) pl.step(o.servo_cmd_rad, 5.0, dt / 10);
    ControlInput in{(float)pl.th_l, (float)pl.th_s, (float)dt, sp};
    o = c.step(in);
  }
  CHECK(o.on_open_stop, "haptic 8 N > finger 5 N: lever on open stop (p=%f)", o.pos);

  // 4) Command clamps: never exceed max_n / hard max, never below the preload floor
  sp.haptic_n = 100.0f;
  ControlInput in{(float)pl.th_l, (float)pl.th_s, (float)dt, sp};
  for (int i = 0; i < 1000; ++i) o = c.step(in);
  CHECK(o.force_cmd_n <= 12.0f + 1e-4, "clamped to max_n (got %f)", o.force_cmd_n);
  sp.haptic_n = 0.f; sp.spring_min_n = 0.f; sp.spring_n = 0.f;
  for (int i = 0; i < 1000; ++i) o = c.step(in);
  CHECK(o.force_cmd_n >= p.preload_nm / p.finger_radius, "floor keeps tab off the backstop (got %f)", o.force_cmd_n);

  // 5) Slew limit: a step in haptic force ramps at <= 300 N/s
  c.reset();
  sp.spring_min_n = 1.2f; sp.spring_n = 1.5f; sp.haptic_n = 0.f;
  for (int i = 0; i < 50; ++i) o = c.step(ControlInput{0.f, 0.f, 1e-3f, sp});
  float f0 = o.force_cmd_n;
  sp.haptic_n = 10.f;
  o = c.step(ControlInput{0.f, 0.f, 1e-3f, sp});
  CHECK(o.force_cmd_n - f0 <= 0.3f + 1e-4, "slew limited step %f", o.force_cmd_n - f0);

  // 6) OFF mode: torque off, command = current servo position
  sp.mode = kModeOff;
  o = c.step(ControlInput{0.1f, 0.05f, 1e-3f, sp});
  CHECK(!o.torque_on && near(o.servo_cmd_rad, 0.05), "off mode");

  // 7) Position mode tracks the requested position
  sp.mode = kModePosition; sp.pos_cmd = 0.5f;
  o = c.step(ControlInput{0.f, 0.f, 1e-3f, sp});
  CHECK(near(o.servo_cmd_rad, 0.5 * 0.5236, 1e-3), "position mode command %f", o.servo_cmd_rad);

  // 8) wrap helpers
  CHECK(near(unwrap_near(6.2f, 0.26f), 6.2 - 2 * M_PI, 1e-4), "unwrap");
  CHECK(near(wrap_pi(3.5f), 3.5 - 2 * M_PI, 1e-4), "wrap");
}

// ------------------------------------------------------------------ v1.1 cue engine
static void test_cues() {
  CueEngine e;
  uint8_t a = 0;
  // TAP: one 20 ms burst at the requested amplitude
  e.trigger(CuePkt{kCueTap, 220, 0}, 1000);
  CHECK(e.amplitude_at(1000) == 220 && e.amplitude_at(1019) == 220 && e.amplitude_at(1020) == 0, "tap 20 ms");
  // RELEASE plays at half amplitude
  e.trigger(CuePkt{kCueRelease, 200, 0}, 2000);
  CHECK(e.amplitude_at(2005) == 100 && e.amplitude_at(2012) == 0, "release half amplitude, 12 ms");
  // SLIP: 15 on / 15 off and extended by repeated cues
  e.trigger(CuePkt{kCueSlip, 180, 60}, 3000);
  CHECK(e.amplitude_at(3001) == 180 && e.amplitude_at(3016) == 0 && e.amplitude_at(3031) == 180, "slip pulse train");
  e.trigger(CuePkt{kCueSlip, 180, 60}, 3050);  // still slipping
  CHECK(e.amplitude_at(3091) == 180 && e.amplitude_at(3106) == 0 && e.amplitude_at(3108) == 0 &&
            e.amplitude_at(3110) == 0, "slip extended to 3110 ms, phase kept");
  // BUZZ default 400 ms, 100/100
  e.trigger(CuePkt{kCueBuzz, 255, 0}, 5000);
  CHECK(e.amplitude_at(5050) == 255 && e.amplitude_at(5150) == 0 && e.amplitude_at(5250) == 255 &&
            e.amplitude_at(5400) == 0, "buzz pattern");
  // invalid waveform ignored, amplitude 0 stops
  e.trigger(CuePkt{kCueBuzz, 255, 0}, 6000);
  e.trigger(CuePkt{9, 255, 0}, 6010);
  CHECK(e.amplitude_at(6011) == 255, "invalid waveform ignored");
  e.trigger(CuePkt{kCueTap, 0, 0}, 6012);
  CHECK(e.amplitude_at(6013) == 0, "amplitude 0 stops");
  // millis() wrap-around
  e.trigger(CuePkt{kCueTap, 99, 30}, 0xFFFFFFF0u);
  CHECK(e.amplitude_at(0xFFFFFFF5u) == 99 && e.amplitude_at(0x00000008u) == 99 && e.amplitude_at(0x0000000Fu) == 0,
        "wrap-safe");
  // update() reports only changes → ≤ 1 I²C write per tick
  CueEngine e2;
  int writes = 0;
  e2.trigger(CuePkt{kCueSlip, 150, 200}, 0);
  for (uint32_t t = 0; t < 300; ++t) if (e2.update(t, &a)) ++writes;
  CHECK(writes == 14, "slip 200 ms at 15/15 ms → 14 amplitude changes (got %d)", writes);
}

// ------------------------------------------------------------------ v1.1: LRA vibration vs the SEA loop
// Plant with the finger resting on the blade (J = 2e-5 kg m²) and the LRA's 235 Hz force applied at
// the pad. Measures the servo-command jitter and force-estimate noise with and without the notch,
// with 12-bit quantisation on both encoders, while rendering 5 N.
struct VibResult { double cmd_jitter_mrad, force_noise_n, force_mean_n; };

static double quant(double a) { const double q = 2 * M_PI / 4096.0; return std::round(a / q) * q; }

static VibResult run_vibration(double lra_force_n, bool use_notch) {
  TriggerController c;
  ControlParams p; p.k_theta = 3.144f; p.preload_nm = 0.0472f; p.finger_radius = 0.045f;
  c.set_params(p);
  Plant pl; pl.J = 2e-5; pl.b = 4e-3;  // finger tissue adds inertia and damping
  Setpoint sp; sp.mode = kModeRender; sp.haptic_n = 3.0f; sp.spring_min_n = 1.2f; sp.spring_n = 1.5f; sp.damping = 0.02f;
  Biquad notch = Biquad::notch(235.f, 1.5f, 1000.f);
  ControlOutput o{};
  const double dt = 1e-3;
  double t = 0, sum_c = 0, sum_c2 = 0, sum_f = 0, sum_f2 = 0;
  int n = 0;
  double cmd_lp = 0;
  for (int i = 0; i < 3000; ++i) {
    for (int k = 0; k < 20; ++k) {  // 20 kHz plant
      const double fl = (i >= 1000) ? lra_force_n * std::sin(2 * M_PI * 235.0 * t) : 0.0;
      pl.step(o.servo_cmd_rad, 5.0 + fl, dt / 20);
      t += dt / 20;
    }
    float lev = (float)quant(pl.th_l);
    if (use_notch) lev = notch.step(lev);
    ControlInput in{lev, (float)quant(pl.th_s), (float)dt, sp};
    o = c.step(in);
    if (i == 999) cmd_lp = o.servo_cmd_rad;
    cmd_lp += 0.02 * (o.servo_cmd_rad - cmd_lp);
    if (i >= 1500) {
      double j = o.servo_cmd_rad - cmd_lp;
      sum_c += j; sum_c2 += j * j; sum_f += o.force_op_n; sum_f2 += (double)o.force_op_n * o.force_op_n; ++n;
    }
  }
  double mc = sum_c / n, mf = sum_f / n;
  return {1e3 * std::sqrt(std::max(0.0, sum_c2 / n - mc * mc)), std::sqrt(std::max(0.0, sum_f2 / n - mf * mf)), mf};
}

static void test_lra_isolation() {
  // LRA reaction force ≈ 1.2 N peak at 235 Hz (1.2 G on the datasheet's 100 g reference mass), applied
  // rigidly at the pad. Mechanical isolation at 235 Hz is impossible while the pad must carry 15 N
  // statically (see haptic-trigger.md §12), so the isolation is the notch on the lever angle.
  VibResult base = run_vibration(0.0, true);
  VibResult raw = run_vibration(1.2, false), raw_n = run_vibration(1.2, true);
  printf("  LRA vs SEA (render 5 N, finger on pad): quiescent jitter %.3f mrad, force noise %.3f N\n",
         base.cmd_jitter_mrad, base.force_noise_n);
  printf("  during a cue, no notch : servo-cmd jitter %.3f mrad, force noise %.3f N rms, mean %.3f N\n",
         raw.cmd_jitter_mrad, raw.force_noise_n, raw.force_mean_n);
  printf("  during a cue, notch    : servo-cmd jitter %.3f mrad, force noise %.3f N rms, mean %.3f N\n",
         raw_n.cmd_jitter_mrad, raw_n.force_noise_n, raw_n.force_mean_n);
  CHECK(raw_n.cmd_jitter_mrad < 0.5 * raw.cmd_jitter_mrad, "notch removes most LRA jitter from the servo command");
  CHECK(raw_n.force_noise_n < 0.044, "with notch: cue adds less than the 0.044 N quantisation floor (%.3f N)",
        raw_n.force_noise_n);
  CHECK(std::fabs(raw_n.force_mean_n - 5.0) < 0.15, "with notch: mean force still 5 N (%.3f)", raw_n.force_mean_n);
}

// ------------------------------------------------------------------ v1.1: loop-time budget with cues
// Per-tick cost model (µs, measured/estimated for 4 Mbps DXL, 1 MHz I2C1, 400 kHz I2C0). Cues are
// fired at the host's maximum rate (50 Hz, random waveform); the engine allows ≤ 1 DRV write/tick.
static void test_loop_budget() {
  const double kAs5600 = 45, kDxlRead = 100, kControl = 45, kDxlWrite = 45, kUsb = 20, kTelemetry = 15,
               kHousekeeping = 140, kDrvWrite = 75;
  CueEngine e;
  uint32_t seed = 12345;
  double worst = 0, sum = 0;
  int max_writes_per_tick = 0, ticks = 0;
  for (uint32_t t = 0; t < 10000; ++t) {
    if (t % 20 == 0) {
      seed = seed * 1103515245u + 12345u;
      e.trigger(CuePkt{(uint8_t)(1 + (seed >> 16) % 4), 200, (uint16_t)((seed >> 8) % 80)}, t);
    }
    int writes = 0;
    uint8_t a;
    if (e.update(t, &a)) ++writes;
    double us = kAs5600 + kDxlRead + kControl + kDxlWrite + kUsb + (t % 2 == 0 ? kTelemetry : 0) +
                (t % 50 == 0 ? kHousekeeping : 0) + writes * kDrvWrite;
    worst = std::max(worst, us);
    sum += us;
    max_writes_per_tick = std::max(max_writes_per_tick, writes);
    ++ticks;
  }
  printf("  loop budget with 50 Hz cues: mean %.0f µs, worst %.0f µs of 1000 µs\n", sum / ticks, worst);
  CHECK(max_writes_per_tick <= 1, "≤ 1 DRV write per tick");
  CHECK(worst < 600.0, "worst-case tick %.0f µs < 600 µs (40 %% margin)", worst);
}

static void test_params() {
  StoredParams p;
  params_defaults(&p);
  float v = 0;
  CHECK(params_get(p, kParamKTheta, &v) && near(v, 3.14), "default k_theta");
  CHECK(params_set(&p, kParamLeverDir, 0.5f, &v) == kAckBadValue, "dir must be ±1");
  CHECK(params_set(&p, kParamLeverDir, -1.0f, &v) == kAckOk && v == -1.0f, "dir -1 ok");
  CHECK(params_set(&p, kParamCurrentLimitMa, 5000.f, &v) == kAckBadValue, "current limit range");
  CHECK(params_set(&p, 99, 1.f, &v) == kAckBadParam, "unknown param");
  CHECK(params_set(&p, kParamSeaZero, 0.01f, &v) == kAckOk && (p.cal_mask & kCalTared), "tare sets cal bit");
  uint16_t crc = params_crc(p);
  p.values[1] += 1;
  CHECK(params_crc(p) != crc, "crc covers values");
}

int main(int argc, char** argv) {
  const char* vec = argc > 1 ? argv[1] : "../../../../../tests/vectors/haptic_protocol.json";
  test_vectors(vec);
  test_control();
  test_cues();
  test_lra_isolation();
  test_loop_budget();
  test_params();
  printf("%d passed, %d failed\n", g_pass, g_fail);
  return g_fail ? 1 : 0;
}
