// TI DRV2605L haptic driver: LRA closed-loop auto-calibration plus real-time playback (RTP).
// I²C address 0x5A. The device supports Standard and Fast mode (≤ 400 kHz), so it has its own
// I²C bus (I2C0 on GP28/GP29) and the AS5600 keeps I2C1 at 1 MHz.
#pragma once

#include <Arduino.h>
#include <Wire.h>

struct LraSpec {
  float rated_vrms = 2.0f;   // VERIFY against the LRA datasheet
  float peak_v = 2.8f;       // overdrive clamp (V peak), ≤ LRA absolute max
  float f_hz = 235.0f;       // nominal resonance; auto-resonance tracks the real value
};

class DRV2605 {
 public:
  static constexpr uint8_t kAddr = 0x5A;
  explicit DRV2605(TwoWire& w) : wire_(w) {}

  // Probe, configure for LRA closed loop and run auto-calibration. `service` is called while
  // waiting (feed the watchdog there). Returns true when calibration passed.
  bool begin_and_calibrate(const LraSpec& lra, void (*service)() = nullptr);
  bool present() const { return present_; }
  bool calibrated() const { return cal_ok_; }
  // Real-time playback amplitude 0..255 (unsigned format). One 2-byte register write.
  bool rtp(uint8_t amplitude);
  uint8_t cal_comp() const { return cal_comp_; }
  uint8_t cal_bemf() const { return cal_bemf_; }

  // Register values derived from the LRA spec (exposed for tests and docs).
  static uint8_t rated_voltage_reg(const LraSpec& l, float sample_time_s = 300e-6f);
  static uint8_t od_clamp_reg(const LraSpec& l);
  static uint8_t drive_time_reg(const LraSpec& l);

 private:
  bool write(uint8_t reg, uint8_t v);
  bool read(uint8_t reg, uint8_t* v);
  TwoWire& wire_;
  bool present_ = false, cal_ok_ = false;
  uint8_t cal_comp_ = 0, cal_bemf_ = 0;
};
