// Vibrotactile cue engine (HGM v1.1). Pure C++, host-testable.
//
// Turns CUE packets into an amplitude envelope for the DRV2605L in real-time-playback (RTP)
// mode. The DRV's closed-loop auto-resonance gives crisp starts and active braking, so the
// envelope only needs on/off levels:
//   TAP      one burst at amplitude A for duration (default 20 ms)       contact onset
//   SLIP     15 ms on / 15 ms off at A; each SLIP cue extends the train   slip, stick-slip
//   RELEASE  one burst at A/2 (default 12 ms)                            object released
//   BUZZ     100 ms on / 100 ms off at A (default 400 ms)                fault alert
// A new cue replaces the current one, except that SLIP during SLIP extends the train.
// The engine reports a new amplitude only when it changes, so the firmware makes at most one
// I²C write per 1 kHz tick (≈ 75 µs at 400 kHz). That bound is checked by the host tests.
#pragma once

#include <stdint.h>

#include "protocol.h"

namespace hgm {

class CueEngine {
 public:
  static constexpr uint16_t kTapDefaultMs = 20;
  static constexpr uint16_t kSlipDefaultMs = 60;
  static constexpr uint16_t kReleaseDefaultMs = 12;
  static constexpr uint16_t kBuzzDefaultMs = 400;
  static constexpr uint16_t kMaxMs = 2000;  // a single cue never runs longer than 2 s

  void trigger(const CuePkt& c, uint32_t now_ms);
  void stop() { active_ = false; }
  // Amplitude 0..255 to play at `now_ms` (0 = silent). Pure function of state and time.
  uint8_t amplitude_at(uint32_t now_ms);
  bool active() const { return active_; }
  uint8_t waveform() const { return wave_; }

  // Returns true (and the new amplitude) only when the output must change. Call once per tick.
  bool update(uint32_t now_ms, uint8_t* amp_out);

 private:
  bool active_ = false;
  uint8_t wave_ = 0;
  uint8_t amp_ = 0;
  uint32_t start_ms_ = 0;
  uint32_t end_ms_ = 0;
  uint8_t last_out_ = 0;
};

}  // namespace hgm
