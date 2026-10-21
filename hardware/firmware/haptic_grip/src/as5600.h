// AS5600 12-bit magnetic angle sensor over I²C at 1 MHz (Fast-mode Plus).
#pragma once

#include <Arduino.h>
#include <Wire.h>

class AS5600 {
 public:
  static constexpr uint8_t kAddr = 0x36;
  enum Reg : uint8_t { kConfHi = 0x07, kConfLo = 0x08, kRawAngleHi = 0x0C, kStatus = 0x0B, kAgc = 0x1A, kMagHi = 0x1B };
  enum StatusBits : uint8_t { kMH = 1 << 3, kML = 1 << 4, kMD = 1 << 5 };

  explicit AS5600(TwoWire& w) : wire_(w) {}
  bool begin();
  // Raw angle 0..4095, or -1 on bus error.
  int16_t raw();
  float angle_rad();  // 0 … 2π
  // Magnet status: detected and within field-strength limits.
  bool magnet_ok(uint8_t* status_out = nullptr, uint8_t* agc_out = nullptr);
  uint32_t errors() const { return errors_; }

 private:
  bool read_regs(uint8_t reg, uint8_t* out, uint8_t n);
  bool write_reg(uint8_t reg, uint8_t v);
  TwoWire& wire_;
  uint32_t errors_ = 0;
};
