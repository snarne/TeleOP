// FGS measurement engine: two strain channels, tare, overload flags and FINGERTIP packet
// assembly. Pure C++, host-testable. On the target the producer (on_sample, core 1 at 4 kHz)
// and the consumer (make_telemetry / configure / tare, core 0) are serialised by a spin lock.
#pragma once

#include <stdint.h>

#include "dsp.h"
#include "fgs_params.h"
#include "protocol.h"

namespace fgs {

class FgsEngine {
 public:
  void configure(const FgsParams& p, double fs);
  void on_sample(int32_t raw_a, int32_t raw_b, uint16_t proc_us);

  // Build one FINGERTIP packet from everything since the last call. adc_ok comes from the
  // driver/staleness check. Clears the per-interval maxima and sticky flags.
  hgm::FingertipTelemetry make_telemetry(uint32_t t_us, const FgsParams& p, bool adc_ok);

  void start_tare(uint32_t n) { tare_.start(n); }
  bool tare_active() const { return tare_.active(); }
  bool tare_take(float* off_a, float* off_b) { return tare_.take(off_a, off_b); }
  uint32_t samples() const { return samples_; }

  // last computed values (for logs and tests)
  float force_a() const { return fa_; }
  float force_b() const { return fb_; }

 private:
  ChannelDsp a_, b_;
  Tare tare_;
  uint32_t samples_ = 0;
  uint16_t proc_max_ = 0;
  bool clip_a_ = false, clip_b_ = false;
  float fa_ = 0, fb_ = 0;
};

}  // namespace fgs
