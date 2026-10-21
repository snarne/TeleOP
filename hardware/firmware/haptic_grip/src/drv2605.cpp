#include "drv2605.h"

#include <math.h>

namespace {
enum Reg : uint8_t {
  kStatus = 0x00, kMode = 0x01, kRtpInput = 0x02, kLibrary = 0x03, kGo = 0x0C, kRatedVoltage = 0x16,
  kOdClamp = 0x17, kAutoCalComp = 0x18, kAutoCalBemf = 0x19, kFeedback = 0x1A, kControl1 = 0x1B,
  kControl2 = 0x1C, kControl3 = 0x1D, kControl4 = 0x1E,
};
constexpr uint8_t kModeAutoCal = 7, kModeRtp = 5;
}  // namespace

// Datasheet §8.5.2.1 (closed-loop LRA): V_rms = 20.71 mV · RATED_VOLTAGE / sqrt(1 − (4·t_sample + 300 µs)·f_LRA)
uint8_t DRV2605::rated_voltage_reg(const LraSpec& l, float ts) {
  const float k = sqrtf(1.f - (4.f * ts + 300e-6f) * l.f_hz);
  float v = l.rated_vrms * k / 20.71e-3f;
  return (uint8_t)(v > 255.f ? 255.f : (v < 0.f ? 0.f : v + 0.5f));
}

// Datasheet §8.5.2.2 (closed-loop LRA): V_peak = 21.22 mV · OD_CLAMP
uint8_t DRV2605::od_clamp_reg(const LraSpec& l) {
  float v = l.peak_v / 21.22e-3f;
  return (uint8_t)(v > 255.f ? 255.f : v + 0.5f);
}

// DRIVE_TIME = half the resonance period: 0.5 ms + 0.1 ms · DRIVE_TIME[4:0]
uint8_t DRV2605::drive_time_reg(const LraSpec& l) {
  float half_ms = 500.f / l.f_hz;
  int v = (int)lroundf((half_ms - 0.5f) / 0.1f);
  return (uint8_t)(v < 0 ? 0 : (v > 31 ? 31 : v));
}

bool DRV2605::write(uint8_t reg, uint8_t v) {
  wire_.beginTransmission(kAddr);
  wire_.write(reg);
  wire_.write(v);
  return wire_.endTransmission() == 0;
}

bool DRV2605::read(uint8_t reg, uint8_t* v) {
  wire_.beginTransmission(kAddr);
  wire_.write(reg);
  if (wire_.endTransmission(false) != 0) return false;
  if (wire_.requestFrom((int)kAddr, 1) != 1) return false;
  *v = (uint8_t)wire_.read();
  return true;
}

bool DRV2605::begin_and_calibrate(const LraSpec& lra, void (*service)()) {
  uint8_t st = 0;
  present_ = read(kStatus, &st) && ((st >> 5) == 7 || (st >> 5) == 3);  // 7 = DRV2605L, 3 = DRV2605
  if (!present_) return false;
  write(kMode, 0x00);                                   // out of standby, internal trigger
  write(kRatedVoltage, rated_voltage_reg(lra));
  write(kOdClamp, od_clamp_reg(lra));
  write(kFeedback, 0x80 | (3 << 4) | (1 << 2) | 2);     // LRA, brake ×4, loop gain medium, BEMF gain 2
  write(kControl1, 0x80 | drive_time_reg(lra));         // startup boost + drive time
  write(kControl2, 0xF5);                               // bidir input, brake stabiliser, 300 µs sample
  write(kControl4, 0x30);                               // auto-cal time 1000 ms (best accuracy)
  write(kMode, kModeAutoCal);
  write(kGo, 1);
  const uint32_t t0 = millis();
  uint8_t go = 1;
  while (millis() - t0 < 1600) {
    if (service) service();
    delay(10);
    if (read(kGo, &go) && go == 0) break;
  }
  read(kStatus, &st);
  cal_ok_ = (go == 0) && !(st & 0x08);                  // DIAG_RESULT = 0 → pass
  read(kAutoCalComp, &cal_comp_);
  read(kAutoCalBemf, &cal_bemf_);
  write(kControl3, 0xA8);                                // NG_THRESH 2 (default), RTP data unsigned, LRA closed loop
  write(kLibrary, 6);                                    // LRA library (not used in RTP, set for completeness)
  write(kMode, kModeRtp);
  write(kRtpInput, 0);
  return cal_ok_;
}

bool DRV2605::rtp(uint8_t amplitude) { return present_ && write(kRtpInput, amplitude); }
