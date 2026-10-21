#include "engine.h"

#include <math.h>

#include "config.h"

namespace fgs {

void FgsEngine::configure(const FgsParams& p, double fs) {
  BandConfig c;
  c.fs = fs;
  c.force_lp_hz = kForceLpHz;
  c.band_lo_hz = param(p, hgm::kFgsHfBandLoHz);
  c.band_hi_hz = param(p, hgm::kFgsHfBandHiHz);
  c.rms_shift = kRmsEmaShift;
  a_.configure(c);
  b_.configure(c);
}

void FgsEngine::on_sample(int32_t raw_a, int32_t raw_b, uint16_t proc_us) {
  a_.step(raw_a);
  b_.step(raw_b);
  tare_.feed(a_.lp_counts(), b_.lp_counts());
  if (raw_a > kClipCounts || raw_a < -kClipCounts) clip_a_ = true;
  if (raw_b > kClipCounts || raw_b < -kClipCounts) clip_b_ = true;
  if (proc_us > proc_max_) proc_max_ = proc_us;
  ++samples_;
}

hgm::FingertipTelemetry FgsEngine::make_telemetry(uint32_t t_us, const FgsParams& p, bool adc_ok) {
  const float sa = param(p, hgm::kFgsScaleA), sb = param(p, hgm::kFgsScaleB);
  uint32_t na = 0, nb = 0;
  const double ma = a_.take_mean(&na), mb = b_.take_mean(&nb);
  fa_ = (float)(ma - param(p, hgm::kFgsOffsetA)) * sa;
  fb_ = (float)(mb - param(p, hgm::kFgsOffsetB)) * sb;
  hgm::FingertipTelemetry t{};
  t.t_us = t_us;
  t.force_a_n = fa_;
  t.force_b_n = fb_;
  t.hf_a_n = (float)a_.rms_counts() * fabsf(sa);
  t.hf_b_n = (float)b_.rms_counts() * fabsf(sb);
  uint16_t st = 0;
  if (adc_ok) st |= hgm::kFgsAdcOk;
  if (cal_valid(p)) st |= hgm::kFgsCalValid;
  if (clip_a_ || fabsf(fa_) > kOverloadN) st |= hgm::kFgsOverloadA;
  if (clip_b_ || fabsf(fb_) > kOverloadN) st |= hgm::kFgsOverloadB;
  t.status = st;
  t.loop_us_max = proc_max_;
  proc_max_ = 0;
  clip_a_ = clip_b_ = false;
  return t;
}

}  // namespace fgs
