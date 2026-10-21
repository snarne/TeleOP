#include "ads131m02.h"

#include <string.h>

#include "protocol.h"   // crc16_ccitt_false: same polynomial and seed as the ADS131M0x CCITT CRC

namespace fgs {
namespace ads {

void build_command(uint16_t cmd, uint16_t data, uint8_t out[kFrameBytes]) {
  memset(out, 0, kFrameBytes);
  out[0] = (uint8_t)(cmd >> 8);
  out[1] = (uint8_t)cmd;
  out[3] = (uint8_t)(data >> 8);
  out[4] = (uint8_t)data;
}

Frame parse(const uint8_t in[kFrameBytes]) {
  Frame f;
  f.response = (uint16_t)((in[0] << 8) | in[1]);
  f.ch0 = sign_extend24(((uint32_t)in[3] << 16) | ((uint32_t)in[4] << 8) | in[5]);
  f.ch1 = sign_extend24(((uint32_t)in[6] << 16) | ((uint32_t)in[7] << 8) | in[8]);
  f.crc_rx = (uint16_t)((in[9] << 8) | in[10]);
  // CRC over every bit of the preceding words, padding included (§8.5.1.11)
  f.crc_ok = hgm::crc16_ccitt_false(in, kWordBytes * 3) == f.crc_rx;
  return f;
}

}  // namespace ads
}  // namespace fgs

#ifdef ARDUINO
#include <Arduino.h>
#include <SPI.h>
#include <hardware/gpio.h>

#include "config.h"

namespace fgs {

ads::Frame Ads131m02::transfer(uint16_t cmd, uint16_t data) {
  uint8_t buf[ads::kFrameBytes];
  ads::build_command(cmd, data, buf);
  gpio_put(kPinAdcCs, 0);
  SPI.transfer(buf, ads::kFrameBytes);   // in-place full duplex
  gpio_put(kPinAdcCs, 1);
  ads::Frame f = ads::parse(buf);
  if (!f.crc_ok) ++crc_errors_;
  return f;
}

ads::Frame Ads131m02::read() { return transfer(ads::kCmdNull); }

bool Ads131m02::begin(uint8_t gain_code) {
  ok_ = false;
  pinMode(kPinAdcCs, OUTPUT);
  digitalWrite(kPinAdcCs, HIGH);
  pinMode(kPinAdcDrdy, INPUT);
  pinMode(kPinAdcSync, OUTPUT);
  // hardware reset: /SYNC_RESET low for > 2048 CLKIN periods (250 µs at 8.192 MHz)
  digitalWrite(kPinAdcSync, LOW);
  delayMicroseconds(400);
  digitalWrite(kPinAdcSync, HIGH);
  delay(2);   // t_REGACQ + first conversions
  if (in_txn_) SPI.endTransaction();
  SPI.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE1));   // left open: the ADC is the only SPI device
  in_txn_ = true;
  transfer(ads::kCmdNull);
  transfer(ads::rreg(ads::kRegId));
  ads::Frame f = transfer(ads::kCmdNull);
  id_ = f.response;
  if ((id_ >> 8) != 0x22) return false;   // ADS131M02: ID = 22xxh (family 2, channel count 2)
  // both PGAs to the requested gain; leave CLOCK at its reset value (both channels on, OSR 1024,
  // high-resolution) and MODE at its reset value (24-bit words, /DRDY on the slower channel)
  transfer(ads::wreg(ads::kRegGain), ads::gain_word(gain_code, gain_code));
  transfer(ads::rreg(ads::kRegGain));
  f = transfer(ads::kCmdNull);
  gain_rb_ = f.response;
  ok_ = gain_rb_ == ads::gain_word(gain_code, gain_code);
  crc_errors_ = 0;
  return ok_;
}

}  // namespace fgs
#endif
