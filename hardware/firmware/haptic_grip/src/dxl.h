// Minimal Dynamixel Protocol 2.0 master for a single X-series servo on a half-duplex
// TTL bus (UART + 74LVC2G241 direction buffer). Blocking with short timeouts, sized for a
// 1 kHz loop at 4 Mbps.
#pragma once

#include <Arduino.h>
#include <SerialUART.h>

namespace dxl {

// X-series (XC330) control-table addresses
enum Addr : uint16_t {
  kBaudRate = 8,
  kReturnDelay = 9,
  kOperatingMode = 11,
  kCurrentLimit = 38,
  kTorqueEnable = 64,
  kStatusReturnLevel = 68,
  kHardwareError = 70,
  kPositionPGain = 84,
  kGoalCurrent = 102,
  kProfileAccel = 108,
  kProfileVelocity = 112,
  kGoalPosition = 116,
  kPresentCurrent = 126,
  kPresentVelocity = 128,
  kPresentPosition = 132,
  kPresentVoltage = 144,
  kPresentTemperature = 146,
};

constexpr uint8_t kModeCurrentBasedPosition = 5;

class Bus {
 public:
  Bus(SerialUART& port, uint8_t dir_pin) : port_(port), dir_(dir_pin) {}
  void begin(uint32_t baud);
  void set_baud(uint32_t baud);

  bool ping(uint8_t id, uint16_t* model = nullptr);
  bool read(uint8_t id, uint16_t addr, uint16_t len, uint8_t* out, uint8_t* err = nullptr);
  bool write(uint8_t id, uint16_t addr, const uint8_t* data, uint16_t len, bool expect_status);
  bool reboot(uint8_t id);

  bool write8(uint8_t id, uint16_t a, uint8_t v, bool st) { return write(id, a, &v, 1, st); }
  bool write16(uint8_t id, uint16_t a, uint16_t v, bool st) {
    uint8_t b[2] = {(uint8_t)v, (uint8_t)(v >> 8)};
    return write(id, a, b, 2, st);
  }
  bool write32(uint8_t id, uint16_t a, int32_t v, bool st) {
    uint8_t b[4] = {(uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24)};
    return write(id, a, b, 4, st);
  }
  bool read8(uint8_t id, uint16_t a, uint8_t* v) { return read(id, a, 1, v); }
  bool read16(uint8_t id, uint16_t a, uint16_t* v) {
    uint8_t b[2];
    if (!read(id, a, 2, b)) return false;
    *v = (uint16_t)(b[0] | (b[1] << 8));
    return true;
  }

  uint32_t errors() const { return errors_; }
  uint32_t timeouts() const { return timeouts_; }

 private:
  void send(uint8_t id, uint8_t inst, const uint8_t* params, uint16_t n);
  bool receive(uint8_t id, uint8_t* params, uint16_t max_params, uint16_t* n_params, uint8_t* err);

  SerialUART& port_;
  uint8_t dir_;
  uint32_t byte_us_x16_ = 40;  // 16 × byte time in µs (for timeouts)
  uint32_t errors_ = 0, timeouts_ = 0;
};

uint16_t crc16(const uint8_t* data, size_t len);

}  // namespace dxl
