// FGS signal processing. Pure C++, host-testable.
//
// The RP2040's Cortex-M0+ has no FPU, so the 4 kSPS per-sample path is fixed point:
//   * biquads in Direct Form I with Q30 coefficients and a 64-bit accumulator
//   * signal words are ADC counts << kInputShift (24-bit → 28-bit, 8× headroom)
// Floats are used only for filter design (rare) and at the telemetry rate (≤ 1 kHz).
//
// Per channel:
//   force:  raw → 2nd-order Butterworth low-pass (100 Hz) → boxcar mean over the telemetry
//           interval (nulls at multiples of the telemetry rate, so nothing aliases to DC)
//   slip:   raw → 4th-order Butterworth high-pass (lo) → 2nd-order Butterworth low-pass (hi)
//           → square → EMA (τ = 8 ms) → sqrt at telemetry time. The 4th-order high-pass has
//           zero steady-state response to a force ramp, so a steady squeeze doesn't read as slip.
#pragma once

#include <stdint.h>

namespace fgs {

constexpr int kInputShift = 4;
constexpr int kQ = 30;

struct BiquadDesign { double b0, b1, b2, a1, a2; };   // a0 normalised to 1

// RBJ-cookbook designs (bilinear with pre-warping: the -3 dB point lands exactly on fc).
BiquadDesign design_lowpass(double fc, double q, double fs);
BiquadDesign design_highpass(double fc, double q, double fs);
// Magnitude of the design at frequency f (for tests and docs).
double magnitude(const BiquadDesign& d, double f, double fs);

// Butterworth section Qs
constexpr double kQ2 = 0.70710678118654752;             // 2nd order
constexpr double kQ4a = 0.54119610014619698, kQ4b = 1.30656296487637652;  // 4th order

struct BiquadQ30 {
  int32_t b0 = 1 << kQ, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
  int32_t x1 = 0, x2 = 0, y1 = 0, y2 = 0;

  void set(const BiquadDesign& d);     // keeps the state (coefficient updates are glitch-free enough)
  void reset(int32_t x_steady);        // state for a steady input x (low-pass: y = x; high-pass: y = 0)
  inline int32_t step(int32_t x) {
    int64_t acc = (int64_t)b0 * x + (int64_t)b1 * x1 + (int64_t)b2 * x2 - (int64_t)a1 * y1 - (int64_t)a2 * y2;
    int32_t y = (int32_t)((acc + (1LL << (kQ - 1))) >> kQ);
    x2 = x1; x1 = x; y2 = y1; y1 = y;
    return y;
  }
};

struct BandConfig {
  double fs = 4000.0;
  double force_lp_hz = 100.0;
  double band_lo_hz = 60.0;
  double band_hi_hz = 400.0;
  uint8_t rms_shift = 5;
};

// One strain channel.
class ChannelDsp {
 public:
  void configure(const BandConfig& c);   // designs and loads all sections (state kept)
  void step(int32_t raw);                // one ADC sample (counts)

  // Telemetry-side accessors (call between samples, or with the producer paused).
  // Mean of the force low-pass output since the last take, in counts. n = samples averaged.
  double take_mean(uint32_t* n);
  double rms_counts() const;             // current slip-band RMS (counts)
  int32_t last_raw() const { return last_raw_; }
  int32_t lp_counts() const { return lp_y_ >> kInputShift; }

 private:
  BiquadQ30 lp_, hp1_, hp2_, bl_;
  uint8_t rms_shift_ = 5;
  bool primed_ = false;
  int64_t ms_ = 0;         // EMA of (bp >> 8)^2, i.e. (counts · 2^-4)^2
  int64_t sum_ = 0;        // boxcar accumulator of lp output (shifted counts)
  uint32_t n_ = 0;
  int32_t lp_y_ = 0;
  int32_t last_raw_ = 0;
};

// Floating-point reference of the same chain, used by the host tests only.
class ChannelRef {
 public:
  void configure(const BandConfig& c);
  void step(double raw);
  double lp() const { return lp_; }
  double bp() const { return bp_; }
  double ms() const { return ms_; }

 private:
  struct Sec { BiquadDesign d; double x1 = 0, x2 = 0, y1 = 0, y2 = 0; double step(double x); };
  Sec lp_s_, hp1_, hp2_, bl_;
  double alpha_ = 1.0 / 32.0;
  double lp_ = 0, bp_ = 0, ms_ = 0;
  bool primed_ = false;
};

// TARE: average the force low-pass over N samples on both channels.
class Tare {
 public:
  void start(uint32_t n) { target_ = n; n_ = 0; sa_ = sb_ = 0; active_ = true; done_ = false; }
  void feed(int32_t lp_a, int32_t lp_b) {
    if (!active_) return;
    sa_ += lp_a; sb_ += lp_b;
    if (++n_ >= target_) { active_ = false; done_ = true; }
  }
  bool active() const { return active_; }
  // True once, when finished; returns the offsets (counts).
  bool take(float* off_a, float* off_b) {
    if (!done_) return false;
    done_ = false;
    *off_a = (float)((double)sa_ / n_);
    *off_b = (float)((double)sb_ / n_);
    return true;
  }

 private:
  uint32_t target_ = 0, n_ = 0;
  int64_t sa_ = 0, sb_ = 0;
  bool active_ = false, done_ = false;
};

}  // namespace fgs
