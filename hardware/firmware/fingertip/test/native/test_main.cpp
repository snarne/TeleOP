// Host-native tests for the FGS firmware's pure modules:
//   1. FINGERTIP / INFO packets against the shared vectors (tests/vectors/haptic_protocol.json)
//   2. fixed-point DSP against a double-precision reference, frequency response, ramp rejection,
//      noise floor, slip detection, overflow at full scale, latency
//   3. engine: tare, overload flags, CAL_VALID, telemetry decimation
//   4. parameter validation
//   5. ADS131M02 frame codec and command encoding
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <random>
#include <sstream>
#include <string>

#include "ads131m02.h"
#include "config.h"
#include "dsp.h"
#include "engine.h"
#include "fgs_params.h"
#include "minijson.h"
#include "protocol.h"

using namespace fgs;
using minijson::unhex;

static int g_fail = 0, g_pass = 0;
#define CHECK(cond, ...)                                    \
  do {                                                      \
    if (cond) { ++g_pass; } else {                          \
      ++g_fail; printf("FAIL %s:%d: ", __FILE__, __LINE__); \
      printf(__VA_ARGS__); printf("\n");                    \
    }                                                       \
  } while (0)

static const double kPi = 3.14159265358979323846;
static const double kFs = (double)kFsHz;
static const double kNperCount = (double)kNominalNPerCount;

static std::string read_file(const char* path) {
  std::ifstream f(path);
  std::stringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

// ------------------------------------------------------------------ 1. vectors
static void test_vectors(const char* path) {
  std::string text = read_file(path);
  CHECK(!text.empty(), "cannot read %s", path);
  if (text.empty()) return;
  minijson::Value v = minijson::Parser(text).parse();
  int n_ft = 0, n_info = 0;
  for (const auto& c : v["packets"].arr) {
    const int type = (int)c["type"].num;
    const auto& f = c["fields"];
    auto body_ref = unhex(c["body"].str), frame_ref = unhex(c["frame"].str);
    uint8_t body[hgm::kMaxPayload];
    size_t bn = 0;
    if (type == hgm::kFingertip) {
      hgm::FingertipTelemetry t{};
      t.t_us = (uint32_t)f["t_us"].num; t.force_a_n = (float)f["force_a_n"].num; t.force_b_n = (float)f["force_b_n"].num;
      t.hf_a_n = (float)f["hf_a_n"].num; t.hf_b_n = (float)f["hf_b_n"].num; t.status = (uint16_t)f["status"].num;
      t.loop_us_max = (uint16_t)f["loop_us_max"].num;
      bn = pack(t, body);
      ++n_ft;
    } else if (type == hgm::kInfo && ((int)f["hw_rev"].num >> 4) == hgm::kDevFgs) {
      hgm::Info i{};
      i.proto = (uint16_t)f["proto"].num; i.fw_major = (uint8_t)f["fw_major"].num; i.fw_minor = (uint8_t)f["fw_minor"].num;
      i.fw_patch = (uint8_t)f["fw_patch"].num; i.hw_rev = (uint8_t)f["hw_rev"].num; i.rx_errors = (uint16_t)f["rx_errors"].num;
      memcpy(i.serial, f["serial"].str.data(), f["serial"].str.size() < 16 ? f["serial"].str.size() : 16);
      bn = pack(i, body);
      CHECK(i.hw_rev == hgm::make_hw_rev(hgm::kDevFgs, FGS_HW_REV), "FGS hw_rev in vectors = 0x%02x, firmware 0x%02x",
            i.hw_rev, hgm::make_hw_rev(hgm::kDevFgs, FGS_HW_REV));
      ++n_info;
    } else {
      continue;
    }
    CHECK(bn == body_ref.size() && memcmp(body, body_ref.data(), bn) == 0, "%s body", c["name"].str.c_str());
    uint8_t frame[hgm::kMaxFrame + 4];
    size_t fn = hgm::encode_frame((uint8_t)type, (uint16_t)c["seq"].num, body, bn, frame, sizeof(frame));
    CHECK(fn == frame_ref.size() && memcmp(frame, frame_ref.data(), fn) == 0, "%s frame", c["name"].str.c_str());
  }
  CHECK(n_ft >= 2 && n_info >= 1, "vectors: %d FINGERTIP, %d FGS INFO", n_ft, n_info);
}

// ------------------------------------------------------------------ helpers
static BandConfig default_band() {
  BandConfig c;
  c.fs = kFs; c.force_lp_hz = kForceLpHz; c.band_lo_hz = 60; c.band_hi_hz = 400; c.rms_shift = kRmsEmaShift;
  return c;
}

// expected chain magnitudes
static double mag_lp(double f, const BandConfig& c) { return magnitude(design_lowpass(c.force_lp_hz, kQ2, c.fs), f, c.fs); }
static double mag_bp(double f, const BandConfig& c) {
  return magnitude(design_highpass(c.band_lo_hz, kQ4a, c.fs), f, c.fs) *
         magnitude(design_highpass(c.band_lo_hz, kQ4b, c.fs), f, c.fs) *
         magnitude(design_lowpass(c.band_hi_hz, kQ2, c.fs), f, c.fs);
}

// Measure the steady-state amplitude of the fixed-point LP and BP outputs for a sine.
static void measure_sine(double f, double amp, double* g_lp, double* g_bp, double* rms_c) {
  // the fixed-point chain is private; drive a copy of the same sections
  BandConfig c = default_band();
  BiquadQ30 lp, h1, h2, bl;
  lp.set(design_lowpass(c.force_lp_hz, kQ2, c.fs));
  h1.set(design_highpass(c.band_lo_hz, kQ4a, c.fs));
  h2.set(design_highpass(c.band_lo_hz, kQ4b, c.fs));
  bl.set(design_lowpass(c.band_hi_hz, kQ2, c.fs));
  ChannelDsp ch;
  ch.configure(c);
  const int settle = (int)(0.5 * kFs), meas = (int)(0.5 * kFs);
  double s_lp = 0, s_bp = 0;   // amplitude from the mean square (peaks of a sampled sine read low)
  for (int i = 0; i < settle + meas; ++i) {
    const int32_t raw = (int32_t)llround(amp * sin(2 * kPi * f * i / kFs));
    const int32_t x = raw * (1 << kInputShift);
    const int32_t ylp = lp.step(x), ybp = bl.step(h2.step(h1.step(x)));
    ch.step(raw);
    if (i >= settle) {
      s_lp += (double)ylp * ylp;
      s_bp += (double)ybp * ybp;
    }
  }
  *g_lp = std::sqrt(2 * s_lp / meas) / (1 << kInputShift) / amp;
  *g_bp = std::sqrt(2 * s_bp / meas) / (1 << kInputShift) / amp;
  *rms_c = ch.rms_counts();
}

// ------------------------------------------------------------------ 2. DSP
static void test_designs() {
  BandConfig c = default_band();
  CHECK(std::fabs(mag_lp(c.force_lp_hz, c) - std::sqrt(0.5)) < 1e-6, "LP -3 dB at fc: %f", mag_lp(100, c));
  CHECK(std::fabs(mag_lp(0.001, c) - 1.0) < 1e-6, "LP DC gain");
  const double hp60 = magnitude(design_highpass(60, kQ4a, kFs), 60, kFs) * magnitude(design_highpass(60, kQ4b, kFs), 60, kFs);
  CHECK(std::fabs(hp60 - std::sqrt(0.5)) < 1e-6, "4th-order Butterworth HP -3 dB at fc: %f", hp60);
  // all Q30 coefficients in range for the whole allowed band (a1 → -2 as fc → 0)
  for (double lo : {10.0, 60.0, 200.0, 1000.0}) {
    BiquadDesign d = design_highpass(lo, kQ4b, kFs);
    CHECK(std::fabs(d.a1) < 2.0 && std::fabs(d.b1) < 2.0, "Q30 range at lo %.0f Hz: a1 %f b1 %f", lo, d.a1, d.b1);
  }
}

static void test_fixed_vs_float() {
  BandConfig c = default_band();
  ChannelDsp q;
  ChannelRef r;
  q.configure(c);
  r.configure(c);
  std::mt19937 rng(7);
  std::normal_distribution<double> noise(0.0, 3000.0);
  double max_lp = 0, max_bp_rel = 0;
  // 20 N static + 250 Hz vibration + noise + a 100 N squeeze ramp, 2 s
  for (int i = 0; i < (int)(2 * kFs); ++i) {
    const double t = i / kFs;
    const double force_n = 20 + (t > 0.5 ? std::min(1.0, (t - 0.5) / 0.2) * 80 : 0);
    const double raw = force_n / kNperCount + 20000 * sin(2 * kPi * 250 * t) + noise(rng);
    const int32_t ri = (int32_t)llround(raw);
    q.step(ri);
    r.step((double)ri);
    if (i > 100) max_lp = std::max(max_lp, std::fabs(q.lp_counts() - r.lp()));
  }
  const double rms_q = q.rms_counts(), rms_r = std::sqrt(r.ms());
  max_bp_rel = std::fabs(rms_q - rms_r) / rms_r;
  printf("  fixed vs float: max |LP diff| %.2f counts (%.2e N), slip RMS rel diff %.2e\n", max_lp, max_lp * kNperCount,
         max_bp_rel);
  CHECK(max_lp <= 2.0, "fixed-point LP within 2 counts of float (got %.2f)", max_lp);
  CHECK(max_bp_rel < 0.005, "fixed-point slip RMS within 0.5 %% of float (got %.4f)", max_bp_rel);
}

static void test_frequency_response() {
  BandConfig c = default_band();
  printf("  f (Hz)   LP gain (exp)        slip-band gain (exp)\n");
  for (double f : {5.0, 30.0, 60.0, 100.0, 200.0, 400.0, 800.0, 1600.0}) {
    double glp, gbp, rms;
    measure_sine(f, 200000.0, &glp, &gbp, &rms);
    printf("  %6.0f   %.4f (%.4f)      %.4f (%.4f)\n", f, glp, mag_lp(f, c), gbp, mag_bp(f, c));
    CHECK(std::fabs(glp - mag_lp(f, c)) < 0.003 + 0.003 * mag_lp(f, c), "LP gain at %.0f Hz: %f vs %f", f, glp, mag_lp(f, c));
    CHECK(std::fabs(gbp - mag_bp(f, c)) < 0.003 + 0.003 * mag_bp(f, c), "BP gain at %.0f Hz: %f vs %f", f, gbp, mag_bp(f, c));
  }
  // the spec numbers: slip band 60-400 Hz (≥ 400 Hz bandwidth), DC and slow force rejected
  CHECK(mag_bp(400, c) > 0.69 && mag_bp(60, c) > 0.69, "slip band edges at -3 dB");
  CHECK(mag_bp(10, c) < 1e-3, "10 Hz (squeeze dynamics) rejected by > 60 dB: %g", mag_bp(10, c));
  // RMS accuracy for a 200 Hz sine
  double glp, gbp, rms;
  measure_sine(200, 50000.0, &glp, &gbp, &rms);
  const double exp_rms = 50000.0 / std::sqrt(2.0) * mag_bp(200, c);
  CHECK(std::fabs(rms / exp_rms - 1) < 0.03, "slip RMS of a 200 Hz sine: %.0f vs %.0f", rms, exp_rms);
}

static void test_full_scale() {
  ChannelDsp ch;
  ch.configure(default_band());
  // alternating full-scale steps: worst case for overshoot and accumulator range
  int32_t mx = 0, mn = 0;
  for (int k = 0; k < 8; ++k) {
    const int32_t v = (k & 1) ? -8388608 : 8388607;
    for (int i = 0; i < 400; ++i) {
      ch.step(v);
      mx = std::max(mx, ch.lp_counts());
      mn = std::min(mn, ch.lp_counts());
    }
    CHECK(std::abs(ch.lp_counts() - v) <= 2, "LP settles to full-scale step %d (got %d)", v, ch.lp_counts());
  }
  // a 2nd-order Butterworth overshoots 4.3 % of the step, i.e. 8.6 % of FS for a ±FS swing; the
  // shifted 28-bit word has 8× headroom, so nothing wraps
  printf("  full-scale ±FS steps: LP range [%d, %d] counts (FS ±8388608)\n", mn, mx);
  CHECK(mx < 8388608 * 1.10 && mn > -8388608 * 1.10, "no wrap-around at full scale");
  CHECK(std::isfinite(ch.rms_counts()) && ch.rms_counts() > 0, "RMS finite at full scale");
}

// run the engine like the firmware: 4 kHz samples, telemetry every fs/telemetry_hz samples
struct Sim {
  FgsEngine eng;
  FgsParams p;
  int div;
  Sim() {
    params_defaults(&p);
    eng.configure(p, kFs);
    div = (int)(kFs / param(p, hgm::kFgsTelemetryHz));
  }
};

static void test_ramp_rejection() {
  // 0 → 100 N in 200 ms (noise-free), then hold: what the slip channel sees from a firm squeeze alone
  for (int order : {4, 2}) {
    double peak_after = 0, peak = 0, during = 0;
    ChannelDsp ch;
    BandConfig c = default_band();
    ch.configure(c);
    BiquadQ30 h2a, bl;   // 2nd-order variant for comparison (docs)
    h2a.set(design_highpass(c.band_lo_hz, kQ2, kFs));
    bl.set(design_lowpass(c.band_hi_hz, kQ2, kFs));
    double ms2 = 0;
    for (int i = 0; i < (int)(0.5 * kFs); ++i) {
      const double t = i / kFs;
      const double f = t < 0.05 ? 0 : std::min(1.0, (t - 0.05) / 0.2) * 100.0;
      const int32_t raw = (int32_t)llround(f / kNperCount);
      double rms_n;
      if (order == 4) {
        ch.step(raw);
        rms_n = ch.rms_counts() * kNperCount;
      } else {
        const double y = bl.step(h2a.step(raw * 16)) / 16.0;
        ms2 += (y * y - ms2) / 32;
        rms_n = std::sqrt(ms2) * kNperCount;
      }
      peak = std::max(peak, rms_n);
      if (t > 0.13 && t < 0.25) during = std::max(during, rms_n);       // steady ramp, ≥ 80 ms in
      if (t > 0.33) peak_after = std::max(peak_after, rms_n);           // ≥ 80 ms after the ramp ends
    }
    printf("  squeeze ramp 100 N / 200 ms, %d-order HP: slip RMS peak %.3f N (at the slope corners), mid-ramp %.4f N, after %.4f N\n",
           order, peak, during, peak_after);
    if (order == 4) {
      CHECK(during < 0.02, "steady squeeze ramp does not read as slip (%.4f N)", during);
      CHECK(peak_after < 0.02, "slip channel quiet after the squeeze (%.4f N)", peak_after);
    }
  }
}

static void test_noise_and_slip() {
  // ADC noise: 1.20 µV rms input-referred at G = 128, OSR 1024 (datasheet Table 7-1)
  const double noise_counts = 1.20e-6 * kCountsPerVolt;
  Sim s;
  std::mt19937 rng(3);
  std::normal_distribution<double> n(0.0, noise_counts);
  const double base = 20.0 / kNperCount;
  double sf = 0, sf2 = 0, shf = 0;
  int k = 0;
  double hf_before = 0, hf_after = 0, f_before = 0, f_after = 0;
  int n_before = 0, n_after = 0;
  double t_detect = -1;
  for (int i = 0; i < (int)(1.5 * kFs); ++i) {
    const double t = i / kFs;
    // 0.3 N rms 250 Hz stick-slip vibration from t = 1.0 s
    const double vib = t >= 1.0 ? 0.3 * std::sqrt(2.0) / kNperCount * sin(2 * kPi * 250 * t) : 0;
    s.eng.on_sample((int32_t)llround(base + n(rng) + vib), (int32_t)llround(n(rng)), 30);
    if ((i + 1) % s.div == 0) {
      hgm::FingertipTelemetry tl = s.eng.make_telemetry((uint32_t)(t * 1e6), s.p, true);
      if (t > 0.3 && t < 1.0) {
        sf += tl.force_a_n; sf2 += tl.force_a_n * tl.force_a_n; shf += tl.hf_b_n; ++k;
        hf_before = std::max(hf_before, (double)tl.hf_a_n); f_before += tl.force_a_n; ++n_before;
      }
      if (t > 1.1) { hf_after += tl.hf_a_n; f_after += tl.force_a_n; ++n_after; }
      if (t >= 1.0 && t_detect < 0 && tl.hf_a_n > 0.15) t_detect = t - 1.0;
    }
  }
  const double mean = sf / k, sd = std::sqrt(sf2 / k - mean * mean);
  hf_after /= n_after;
  printf("  ADC noise %.0f counts rms (%.4f N raw): force noise %.4f N rms at 500 Hz, slip-band floor %.4f N\n",
         noise_counts, noise_counts * kNperCount, sd, shf / k);
  printf("  0.3 N rms 250 Hz slip: hf %.3f N (floor max %.3f N), detected (> 0.15 N) after %.1f ms; force shift %.4f N\n",
         hf_after, hf_before, t_detect * 1e3, f_after / n_after - f_before / n_before);
  CHECK(std::fabs(mean - 20.0) < 0.02, "static force reads 20 N (got %.4f)", mean);
  CHECK(sd < 0.04, "force noise < 0.04 N rms (got %.4f)", sd);
  CHECK(shf / k < 0.07, "slip-band noise floor < 0.07 N (got %.4f)", shf / k);
  CHECK(std::fabs(hf_after - 0.3 * mag_bp(250, default_band())) < 0.03, "slip RMS reads the vibration (%.3f)", hf_after);
  CHECK(t_detect >= 0 && t_detect < 0.015, "slip detected within 15 ms (%.1f ms)", t_detect * 1e3);
  CHECK(std::fabs(f_after / n_after - f_before / n_before) < 0.02, "vibration does not bias the force channel");
}

static void test_latency() {
  // step 0 → 10 N: time from the step to 50 % / 90 % in the telemetry (includes the boxcar)
  Sim s;
  double t50 = -1, t90 = -1;
  const double step_t = 0.1;
  for (int i = 0; i < (int)(0.2 * kFs); ++i) {
    const double t = i / kFs;
    s.eng.on_sample(t >= step_t ? (int32_t)llround(10.0 / kNperCount) : 0, 0, 0);
    if ((i + 1) % s.div == 0) {
      const double tt = (i + 1) / kFs;   // packet time
      hgm::FingertipTelemetry tl = s.eng.make_telemetry(0, s.p, true);
      if (t50 < 0 && tl.force_a_n >= 5.0) t50 = tt - step_t;
      if (t90 < 0 && tl.force_a_n >= 9.0) t90 = tt - step_t;
    }
  }
  printf("  10 N step: 50 %% after %.2f ms, 90 %% after %.2f ms (telemetry 500 Hz; ADC sinc3 adds ~0.4 ms)\n",
         t50 * 1e3, t90 * 1e3);
  CHECK(t50 > 0 && t50 <= 0.005, "force latency to 50 %% ≤ 5 ms (%.2f ms)", t50 * 1e3);
}

// ------------------------------------------------------------------ 3. engine
static void test_engine() {
  Sim s;
  std::mt19937 rng(11);
  std::normal_distribution<double> n(0.0, 1074.0);
  // TARE with a bridge offset and noise
  s.eng.start_tare(kTareSamples);
  int samples = 0;
  float oa = 0, ob = 0;
  bool done = false;
  for (int i = 0; i < 4000 && !done; ++i) {
    s.eng.on_sample((int32_t)llround(123456 + n(rng)), (int32_t)llround(-65432 + n(rng)), 40);
    ++samples;
    done = s.eng.tare_take(&oa, &ob);
  }
  CHECK(done && samples == (int)kTareSamples, "tare finishes after %u samples (%d)", kTareSamples, samples);
  CHECK(std::fabs(oa - 123456) < 60 && std::fabs(ob + 65432) < 60, "tare offsets %.1f %.1f", oa, ob);
  CHECK(!s.eng.tare_take(&oa, &ob), "tare result is taken once");
  float applied = 0;
  CHECK(params_set(&s.p, hgm::kFgsOffsetA, oa, &applied) == hgm::kAckOk, "set offset a");
  CHECK(params_set(&s.p, hgm::kFgsOffsetB, ob, nullptr) == hgm::kAckOk, "set offset b");
  for (int i = 0; i < 400; ++i) s.eng.on_sample((int32_t)llround(123456 + n(rng)), (int32_t)llround(-65432 + n(rng)), 40);
  hgm::FingertipTelemetry t = s.eng.make_telemetry(5, s.p, true);
  CHECK(std::fabs(t.force_a_n) < 0.05 && std::fabs(t.force_b_n) < 0.05, "after tare: %.4f %.4f N", t.force_a_n, t.force_b_n);
  CHECK(t.status == hgm::kFgsAdcOk, "status ADC_OK only (not calibrated): 0x%x", t.status);
  CHECK(t.loop_us_max == 40, "loop_us_max carried");
  CHECK(t.t_us == 5, "t_us carried");
  // calibrated scales → CAL_VALID
  params_set(&s.p, hgm::kFgsScaleA, (float)kNperCount, nullptr);
  CHECK(!(s.eng.make_telemetry(0, s.p, true).status & hgm::kFgsCalValid), "one scale is not enough for CAL_VALID");
  params_set(&s.p, hgm::kFgsScaleB, -(float)kNperCount, nullptr);   // mirrored bridge wiring
  for (int i = 0; i < 400; ++i) s.eng.on_sample(123456, -65432 - 100000, 10);
  t = s.eng.make_telemetry(0, s.p, true);
  CHECK(t.status & hgm::kFgsCalValid, "both scales → CAL_VALID");
  CHECK(t.force_b_n > 10.0, "negative scale flips the sign (%.3f N)", t.force_b_n);
  CHECK(t.status & hgm::kFgsAdcOk, "adc ok passed through");
  CHECK(!(s.eng.make_telemetry(0, s.p, false).status & hgm::kFgsAdcOk), "adc fault clears ADC_OK");
  // overload by force (> 450 N) and by clipping, sticky for one interval only
  for (int i = 0; i < 400; ++i) s.eng.on_sample((int32_t)llround(123456 + 470.0 / kNperCount), -65432, 10);
  t = s.eng.make_telemetry(0, s.p, true);
  CHECK((t.status & hgm::kFgsOverloadA) && !(t.status & hgm::kFgsOverloadB), "470 N → OVERLOAD_A (%.1f N)", t.force_a_n);
  for (int i = 0; i < 400; ++i) s.eng.on_sample(123456, -65432, 10);
  s.eng.on_sample(123456, -8388608, 10);   // one clipped sample (open bridge / spike)
  t = s.eng.make_telemetry(0, s.p, true);
  CHECK((t.status & hgm::kFgsOverloadB) && !(t.status & hgm::kFgsOverloadA), "clip → OVERLOAD_B: 0x%x", t.status);
  for (int i = 0; i < 8; ++i) s.eng.on_sample(123456, -65432, 10);
  t = s.eng.make_telemetry(0, s.p, true);
  CHECK(!(t.status & (hgm::kFgsOverloadA | hgm::kFgsOverloadB)), "overload flags clear when the cause is gone");
  // the default scale is the designed sensitivity
  printf("  nominal scale %.4e N/count (%.2f mV/V at 100 N, %.1f V excitation, G=128); FS at the ADC %.0f N\n",
         kNperCount, kBridgeMvPerVAt100N, kExcitationV, 8388608.0 * kNperCount);
  CHECK(8388608.0 * kNperCount > 600.0, "ADC full scale stays above the gripper stall force");
}

// ------------------------------------------------------------------ 4. params
static void test_params() {
  FgsParams p;
  params_defaults(&p);
  float v = 0, a = 0;
  CHECK(params_get(p, hgm::kFgsTelemetryHz, &v) && v == 500.f, "telemetry_hz default 500");
  CHECK(params_get(p, hgm::kFgsHfBandLoHz, &v) && v == 60.f, "band lo default 60");
  CHECK(params_get(p, hgm::kFgsHfBandHiHz, &v) && v == 400.f, "band hi default 400");
  CHECK(!params_get(p, 19, &v) && !params_get(p, 27, &v) && !params_get(p, 1, &v), "ids outside 20..26 rejected");
  CHECK(params_set(&p, 13, 1.f, &a) == hgm::kAckBadParam, "HGM param id is bad on the FGS");
  CHECK(params_set(&p, hgm::kFgsScaleA, 0.f, &a) == hgm::kAckBadValue, "zero scale rejected");
  CHECK(params_set(&p, hgm::kFgsScaleA, NAN, &a) == hgm::kAckBadValue, "NaN rejected");
  CHECK(params_set(&p, hgm::kFgsScaleA, INFINITY, &a) == hgm::kAckBadValue, "inf rejected");
  CHECK(params_set(&p, hgm::kFgsHfBandLoHz, 300.f, &a) == hgm::kAckBadValue, "lo too close to hi rejected");
  CHECK(params_set(&p, hgm::kFgsHfBandHiHz, 80.f, &a) == hgm::kAckBadValue, "hi below 1.5 lo rejected");
  CHECK(params_set(&p, hgm::kFgsHfBandHiHz, 1600.f, &a) == hgm::kAckBadValue, "hi above 0.375 fs rejected");
  CHECK(params_set(&p, hgm::kFgsHfBandHiHz, 800.f, &a) == hgm::kAckOk && a == 800.f, "hi 800 ok");
  CHECK(params_set(&p, hgm::kFgsHfBandLoHz, 100.f, &a) == hgm::kAckOk, "lo 100 ok");
  CHECK(params_set(&p, hgm::kFgsTelemetryHz, 249.6f, &a) == hgm::kAckOk && a == 250.f, "telemetry_hz rounds");
  CHECK(params_set(&p, hgm::kFgsTelemetryHz, 2000.f, &a) == hgm::kAckBadValue, "telemetry_hz ≤ 1000");
  CHECK(!cal_valid(p), "defaults are not calibrated");
  const uint16_t c0 = params_crc(p);
  params_set(&p, hgm::kFgsScaleA, 3.1e-5f, &a);
  CHECK(params_crc(p) != c0 && (p.cal_mask & kCalScaleA), "scale set marks calibration and changes the CRC");
  FgsParams d;
  params_defaults(&d);
  CHECK(std::fabs(param(d, hgm::kFgsScaleA) - kNominalNPerCount) < 1e-12f, "default scale = nominal");
}

// ------------------------------------------------------------------ 5. ADS131M02 codec
static void test_ads_codec() {
  CHECK(ads::sign_extend24(0x7FFFFF) == 8388607 && ads::sign_extend24(0x800000) == -8388608 &&
            ads::sign_extend24(0xFFFFFF) == -1 && ads::sign_extend24(0) == 0, "24-bit sign extension");
  CHECK(ads::rreg(ads::kRegId) == 0xA000, "RREG ID = 0xA000");
  CHECK(ads::rreg(ads::kRegGain) == 0xA200, "RREG GAIN = 0xA200");
  CHECK(ads::wreg(ads::kRegGain) == 0x6200, "WREG GAIN = 0x6200");
  CHECK(ads::wreg_ack(ads::kRegGain) == 0x4200, "WREG ack");
  CHECK(ads::rreg(ads::kRegClock, 2) == 0xA181, "RREG CLOCK×2");
  CHECK(ads::gain_word(7, 7) == 0x0077 && ads::gain_word(7, 0) == 0x0007, "gain codes");
  uint8_t f[ads::kFrameBytes];
  ads::build_command(ads::wreg(ads::kRegGain), 0x0077, f);
  const uint8_t exp[ads::kFrameBytes] = {0x62, 0x00, 0x00, 0x00, 0x77, 0x00, 0, 0, 0, 0, 0, 0};
  CHECK(memcmp(f, exp, sizeof(exp)) == 0, "WREG frame layout");
  // synthetic device frame: STATUS 0x0503, ch0 = -2, ch1 = +1234567, CRC over words 0..2
  uint8_t r[ads::kFrameBytes] = {0x05, 0x03, 0x00, 0xFF, 0xFF, 0xFE, 0x12, 0xD6, 0x87, 0, 0, 0};
  const uint16_t crc = hgm::crc16_ccitt_false(r, 9);
  r[9] = (uint8_t)(crc >> 8);
  r[10] = (uint8_t)crc;
  ads::Frame fr = ads::parse(r);
  CHECK(fr.response == 0x0503 && fr.ch0 == -2 && fr.ch1 == 1234567 && fr.crc_ok, "frame parse %d %d", fr.ch0, fr.ch1);
  r[5] ^= 1;
  CHECK(!ads::parse(r).crc_ok, "corrupted frame fails CRC");
}

int main(int argc, char** argv) {
  const char* vectors = argc > 1 ? argv[1] : "../../../../../tests/vectors/haptic_protocol.json";
  printf("FGS native tests\n");
  test_vectors(vectors);
  test_designs();
  test_fixed_vs_float();
  test_frequency_response();
  test_full_scale();
  test_ramp_rejection();
  test_noise_and_slip();
  test_latency();
  test_engine();
  test_params();
  test_ads_codec();
  printf("%d passed, %d failed\n", g_pass, g_fail);
  return g_fail ? 1 : 0;
}
