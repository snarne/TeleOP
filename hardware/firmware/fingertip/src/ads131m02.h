// TI ADS131M02: 2-channel simultaneous-sampling 24-bit delta-sigma ADC (SPI mode 1).
//
// Frame (24-bit words, the reset default): host sends [command, 0, 0, 0] (input CRC off);
// the device returns [response to the previous command (or STATUS), ch0, ch1, CRC]. The output
// CRC is CRC-16/CCITT (seed 0xFFFF) over the preceding words and cannot be disabled.
//
// The frame codec and command encoders are pure functions (host-tested). The SPI transport is
// built for the target only.
//
// Register addresses, reset values and the ID value come from the datasheet register map
// (SBAS950, §8.6). VERIFY on the first board: the boot log prints the ID and the GAIN read-back.
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace fgs {

namespace ads {
constexpr uint8_t kRegId = 0x00, kRegStatus = 0x01, kRegMode = 0x02, kRegClock = 0x03, kRegGain = 0x04,
                  kRegCfg = 0x06;
constexpr uint16_t kCmdNull = 0x0000, kCmdReset = 0x0011, kCmdStandby = 0x0022, kCmdWakeup = 0x0033,
                   kCmdLock = 0x0555, kCmdUnlock = 0x0655;
constexpr uint16_t kResetAck = 0xFF22;     // response to RESET on a 2-channel part
constexpr size_t kWordBytes = 3, kFrameWords = 4, kFrameBytes = kWordBytes * kFrameWords;

inline uint16_t rreg(uint8_t addr, uint8_t n = 1) { return (uint16_t)(0xA000 | ((addr & 0x3F) << 7) | ((n - 1) & 0x7F)); }
inline uint16_t wreg(uint8_t addr, uint8_t n = 1) { return (uint16_t)(0x6000 | ((addr & 0x3F) << 7) | ((n - 1) & 0x7F)); }
// WREG acknowledgement: 010a aaaa ammm mmmm
inline uint16_t wreg_ack(uint8_t addr, uint8_t n = 1) { return (uint16_t)(0x4000 | ((addr & 0x3F) << 7) | ((n - 1) & 0x7F)); }
inline uint16_t gain_word(uint8_t code0, uint8_t code1) { return (uint16_t)(((code1 & 7) << 4) | (code0 & 7)); }

inline int32_t sign_extend24(uint32_t v) { return (int32_t)(v << 8) >> 8; }

struct Frame {
  uint16_t response;   // 16-bit response / STATUS, MSB-aligned in word 0
  int32_t ch0, ch1;    // two's complement counts
  uint16_t crc_rx;
  bool crc_ok;
};

// Fill a host → device frame with a 16-bit command in word 0 (MSB-aligned) and optional data in
// word 1 (for single-register WREG). Words 2..3 are zero.
void build_command(uint16_t cmd, uint16_t data, uint8_t out[kFrameBytes]);
// Parse a device → host frame.
Frame parse(const uint8_t in[kFrameBytes]);
}  // namespace ads

#ifdef ARDUINO
class Ads131m02 {
 public:
  // Reset, check ID, set both PGAs to `gain_code`, verify. Returns true when the part answered.
  bool begin(uint8_t gain_code);
  bool ok() const { return ok_; }
  uint16_t id() const { return id_; }
  uint16_t gain_readback() const { return gain_rb_; }
  // Read one conversion (call after /DRDY falls). Sends NULL.
  ads::Frame read();
  uint32_t crc_errors() const { return crc_errors_; }

 private:
  ads::Frame transfer(uint16_t cmd, uint16_t data = 0);
  bool ok_ = false, in_txn_ = false;
  uint16_t id_ = 0, gain_rb_ = 0;
  uint32_t crc_errors_ = 0;
};
#endif

}  // namespace fgs
