#include "dsp.h"

#include <math.h>

namespace fgs {

namespace {
constexpr double kPi = 3.14159265358979323846;

int32_t q30(double v) {
  double s = v * (double)(1LL << kQ);
  if (s > 2147483647.0) s = 2147483647.0;
  if (s < -2147483648.0) s = -2147483648.0;
  return (int32_t)llround(s);
}
}  // namespace

BiquadDesign design_lowpass(double fc, double q, double fs) {
  const double w = 2 * kPi * fc / fs, c = cos(w), al = sin(w) / (2 * q), a0 = 1 + al;
  return {(1 - c) / 2 / a0, (1 - c) / a0, (1 - c) / 2 / a0, -2 * c / a0, (1 - al) / a0};
}

BiquadDesign design_highpass(double fc, double q, double fs) {
  const double w = 2 * kPi * fc / fs, c = cos(w), al = sin(w) / (2 * q), a0 = 1 + al;
  return {(1 + c) / 2 / a0, -(1 + c) / a0, (1 + c) / 2 / a0, -2 * c / a0, (1 - al) / a0};
}

double magnitude(const BiquadDesign& d, double f, double fs) {
  const double w = 2 * kPi * f / fs;
  // H(e^jw) = (b0 + b1 z^-1 + b2 z^-2) / (1 + a1 z^-1 + a2 z^-2)
  const double nr = d.b0 + d.b1 * cos(w) + d.b2 * cos(2 * w), ni = -(d.b1 * sin(w) + d.b2 * sin(2 * w));
  const double dr = 1 + d.a1 * cos(w) + d.a2 * cos(2 * w), di = -(d.a1 * sin(w) + d.a2 * sin(2 * w));
  return sqrt((nr * nr + ni * ni) / (dr * dr + di * di));
}

void BiquadQ30::set(const BiquadDesign& d) {
  b0 = q30(d.b0); b1 = q30(d.b1); b2 = q30(d.b2); a1 = q30(d.a1); a2 = q30(d.a2);
}

void BiquadQ30::reset(int32_t x_ss) {
  // steady-state output for a constant input: y = x · (b0+b1+b2)/(1+a1+a2)
  const double g = ((double)b0 + b1 + b2) / ((double)(1LL << kQ) + a1 + a2);
  const int32_t y = (int32_t)llround(x_ss * g);
  x1 = x2 = x_ss;
  y1 = y2 = y;
}

// ---------------------------------------------------------------- fixed-point channel
void ChannelDsp::configure(const BandConfig& c) {
  lp_.set(design_lowpass(c.force_lp_hz, kQ2, c.fs));
  hp1_.set(design_highpass(c.band_lo_hz, kQ4a, c.fs));
  hp2_.set(design_highpass(c.band_lo_hz, kQ4b, c.fs));
  bl_.set(design_lowpass(c.band_hi_hz, kQ2, c.fs));
  rms_shift_ = c.rms_shift;
}

void ChannelDsp::step(int32_t raw) {
  last_raw_ = raw;
  const int32_t x = raw * (1 << kInputShift);
  if (!primed_) {  // start at steady state: no power-up transient in either path
    lp_.reset(x);
    hp1_.reset(x);
    hp2_.reset(0);
    bl_.reset(0);
    primed_ = true;
  }
  lp_y_ = lp_.step(x);
  sum_ += lp_y_;
  ++n_;
  const int32_t bp = bl_.step(hp2_.step(hp1_.step(x)));
  const int64_t sq = ((int64_t)bp * bp) >> (2 * kInputShift);   // counts²
  ms_ += (sq - ms_) >> rms_shift_;
}

double ChannelDsp::take_mean(uint32_t* n) {
  const uint32_t k = n_;
  const double m = k ? (double)sum_ / k / (1 << kInputShift) : (double)lp_y_ / (1 << kInputShift);
  sum_ = 0;
  n_ = 0;
  if (n) *n = k;
  return m;
}

double ChannelDsp::rms_counts() const { return sqrt((double)(ms_ > 0 ? ms_ : 0)); }

// ---------------------------------------------------------------- float reference
double ChannelRef::Sec::step(double x) {
  const double y = d.b0 * x + d.b1 * x1 + d.b2 * x2 - d.a1 * y1 - d.a2 * y2;
  x2 = x1; x1 = x; y2 = y1; y1 = y;
  return y;
}

void ChannelRef::configure(const BandConfig& c) {
  lp_s_.d = design_lowpass(c.force_lp_hz, kQ2, c.fs);
  hp1_.d = design_highpass(c.band_lo_hz, kQ4a, c.fs);
  hp2_.d = design_highpass(c.band_lo_hz, kQ4b, c.fs);
  bl_.d = design_lowpass(c.band_hi_hz, kQ2, c.fs);
  alpha_ = 1.0 / (double)(1u << c.rms_shift);
}

void ChannelRef::step(double raw) {
  if (!primed_) {
    lp_s_.x1 = lp_s_.x2 = lp_s_.y1 = lp_s_.y2 = raw;
    hp1_.x1 = hp1_.x2 = raw;
    primed_ = true;
  }
  lp_ = lp_s_.step(raw);
  bp_ = bl_.step(hp2_.step(hp1_.step(raw)));
  ms_ += alpha_ * (bp_ * bp_ - ms_);
}

}  // namespace fgs
