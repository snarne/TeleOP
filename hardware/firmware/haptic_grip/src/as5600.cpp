#include "as5600.h"

bool AS5600::read_regs(uint8_t reg, uint8_t* out, uint8_t n) {
  wire_.beginTransmission(kAddr);
  wire_.write(reg);
  if (wire_.endTransmission(false) != 0) { ++errors_; return false; }
  if (wire_.requestFrom((int)kAddr, (int)n) != n) { ++errors_; return false; }
  for (uint8_t i = 0; i < n; ++i) out[i] = (uint8_t)wire_.read();
  return true;
}

bool AS5600::write_reg(uint8_t reg, uint8_t v) {
  wire_.beginTransmission(kAddr);
  wire_.write(reg);
  wire_.write(v);
  return wire_.endTransmission() == 0;
}

bool AS5600::begin() {
  // CONF: SF = 0b11 (fastest slow filter, 0.286 ms step response), FTH = 0, HYST = 0,
  //       PM = always on, OUTS = analog (unused). Only RAM is written, never the OTP burn.
  bool ok = write_reg(kConfHi, 0x03);
  ok &= write_reg(kConfLo, 0x00);
  uint8_t s;
  return ok && read_regs(kStatus, &s, 1);
}

int16_t AS5600::raw() {
  uint8_t b[2];
  if (!read_regs(kRawAngleHi, b, 2)) return -1;
  return (int16_t)(((b[0] & 0x0F) << 8) | b[1]);
}

float AS5600::angle_rad() {
  int16_t r = raw();
  if (r < 0) return NAN;
  return (float)r * (6.28318530718f / 4096.0f);
}

bool AS5600::magnet_ok(uint8_t* status_out, uint8_t* agc_out) {
  uint8_t s = 0, agc = 0;
  if (!read_regs(kStatus, &s, 1)) return false;
  read_regs(kAgc, &agc, 1);
  if (status_out) *status_out = s;
  if (agc_out) *agc_out = agc;
  return (s & kMD) && !(s & kML) && !(s & kMH);
}
