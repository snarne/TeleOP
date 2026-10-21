#include "cue.h"

namespace hgm {

namespace {
inline bool after(uint32_t a, uint32_t b) { return (int32_t)(a - b) >= 0; }  // a >= b, wrap-safe
}  // namespace

void CueEngine::trigger(const CuePkt& c, uint32_t now_ms) {
  if (c.waveform < kCueTap || c.waveform > kCueBuzz || c.amplitude == 0) {
    if (c.amplitude == 0) active_ = false;  // amplitude 0 = stop
    return;
  }
  uint16_t dur = c.duration_ms;
  if (dur == 0) {
    dur = c.waveform == kCueTap ? kTapDefaultMs
        : c.waveform == kCueSlip ? kSlipDefaultMs
        : c.waveform == kCueRelease ? kReleaseDefaultMs
        : kBuzzDefaultMs;
  }
  if (dur > kMaxMs) dur = kMaxMs;
  if (c.waveform == kCueSlip && active_ && wave_ == kCueSlip && !after(now_ms, end_ms_)) {
    // extend the running train; keep its phase so the pulses stay regular
    uint32_t e = now_ms + dur;
    if (after(e, end_ms_)) end_ms_ = e;
    amp_ = c.amplitude;
    return;
  }
  active_ = true;
  wave_ = c.waveform;
  amp_ = c.waveform == kCueRelease ? (uint8_t)(c.amplitude / 2) : c.amplitude;
  start_ms_ = now_ms;
  end_ms_ = now_ms + dur;
}

uint8_t CueEngine::amplitude_at(uint32_t now_ms) {
  if (!active_) return 0;
  if (after(now_ms, end_ms_)) {
    active_ = false;
    return 0;
  }
  const uint32_t t = now_ms - start_ms_;
  switch (wave_) {
    case kCueSlip: return ((t / 15u) % 2u) == 0 ? amp_ : 0;
    case kCueBuzz: return ((t / 100u) % 2u) == 0 ? amp_ : 0;
    default: return amp_;  // TAP, RELEASE: one burst
  }
}

bool CueEngine::update(uint32_t now_ms, uint8_t* amp_out) {
  const uint8_t a = amplitude_at(now_ms);
  if (a == last_out_) return false;
  last_out_ = a;
  *amp_out = a;
  return true;
}

}  // namespace hgm
