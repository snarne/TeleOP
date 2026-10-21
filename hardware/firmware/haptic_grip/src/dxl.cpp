#include "dxl.h"

#include "config.h"

namespace dxl {

// CRC-16 as specified by ROBOTIS (poly 0x8005, init 0, no reflection)
uint16_t crc16(const uint8_t* data, size_t len) {
  uint16_t crc = 0;
  for (size_t i = 0; i < len; ++i) {
    crc ^= (uint16_t)data[i] << 8;
    for (int b = 0; b < 8; ++b) crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x8005) : (uint16_t)(crc << 1);
  }
  return crc;
}

void Bus::begin(uint32_t baud) {
  pinMode(dir_, OUTPUT);
  digitalWrite(dir_, LOW);
  set_baud(baud);
}

void Bus::set_baud(uint32_t baud) {
  port_.end();
  port_.setFIFOSize(256);
  port_.begin(baud);
  byte_us_x16_ = (uint32_t)((16ull * 10ull * 1000000ull) / baud) + 1;
}

void Bus::send(uint8_t id, uint8_t inst, const uint8_t* params, uint16_t n) {
  // Header + byte stuffing (insert 0xFD after any FF FF FD sequence in the instruction/params)
  uint8_t pkt[64];
  uint16_t w = 0;
  pkt[w++] = 0xFF; pkt[w++] = 0xFF; pkt[w++] = 0xFD; pkt[w++] = 0x00;
  pkt[w++] = id;
  uint16_t len_idx = w;
  w += 2;
  pkt[w++] = inst;
  for (uint16_t i = 0; i < n && w < sizeof(pkt) - 3; ++i) {
    pkt[w++] = params[i];
    if (w >= 3 + 8 && pkt[w - 1] == 0xFD && pkt[w - 2] == 0xFF && pkt[w - 3] == 0xFF) pkt[w++] = 0xFD;
  }
  uint16_t length = (uint16_t)(w - 7 + 2);  // instruction + params (+stuffing) + CRC
  pkt[len_idx] = (uint8_t)length;
  pkt[len_idx + 1] = (uint8_t)(length >> 8);
  uint16_t crc = crc16(pkt, w);
  pkt[w++] = (uint8_t)crc;
  pkt[w++] = (uint8_t)(crc >> 8);

  while (port_.available()) port_.read();  // drop stale bytes
  digitalWrite(dir_, HIGH);
  port_.write(pkt, w);
  port_.flush();  // returns once the last stop bit has been shifted out
  digitalWrite(dir_, LOW);
}

bool Bus::receive(uint8_t id, uint8_t* params, uint16_t max_params, uint16_t* n_params, uint8_t* err) {
  // State machine over the incoming byte stream with an overall timeout.
  uint8_t buf[80];
  uint16_t n = 0;
  uint16_t need = 7;  // header(4) + id + len(2)
  const uint32_t t0 = micros();
  const uint32_t limit = kDxlTimeoutUs + (byte_us_x16_ * (max_params + 11)) / 16;
  while ((uint32_t)(micros() - t0) < limit) {
    while (port_.available() && n < sizeof(buf)) {
      uint8_t b = (uint8_t)port_.read();
      // resynchronise on the header
      if (n < 4) {
        static const uint8_t hdr[4] = {0xFF, 0xFF, 0xFD, 0x00};
        if (b != hdr[n]) { n = (b == 0xFF) ? 1 : 0; continue; }
      }
      buf[n++] = b;
      if (n == 7) need = 7 + (uint16_t)(buf[5] | (buf[6] << 8));
      if (n >= 7 && n == need) {
        uint16_t crc_rx = (uint16_t)(buf[n - 2] | (buf[n - 1] << 8));
        if (crc16(buf, n - 2) != crc_rx || buf[4] != id || buf[7] != 0x55) { ++errors_; return false; }
        if (err) *err = buf[8];
        // un-stuff parameters
        uint16_t out = 0;
        for (uint16_t i = 9; i < n - 2; ++i) {
          if (i >= 11 && buf[i] == 0xFD && buf[i - 1] == 0xFD && buf[i - 2] == 0xFF && buf[i - 3] == 0xFF) continue;
          if (out < max_params) params[out++] = buf[i];
        }
        if (n_params) *n_params = out;
        return true;
      }
    }
  }
  ++timeouts_;
  return false;
}

bool Bus::ping(uint8_t id, uint16_t* model) {
  send(id, 0x01, nullptr, 0);
  uint8_t p[3];
  uint16_t n = 0;
  uint8_t err = 0;
  if (!receive(id, p, sizeof(p), &n, &err) || n < 3) return false;
  if (model) *model = (uint16_t)(p[0] | (p[1] << 8));
  return true;
}

bool Bus::read(uint8_t id, uint16_t addr, uint16_t len, uint8_t* out, uint8_t* err) {
  uint8_t prm[4] = {(uint8_t)addr, (uint8_t)(addr >> 8), (uint8_t)len, (uint8_t)(len >> 8)};
  send(id, 0x02, prm, 4);
  uint16_t n = 0;
  uint8_t e = 0;
  if (!receive(id, out, len, &n, &e) || n != len) return false;
  if (err) *err = e;
  return (e & 0x7F) == 0;
}

bool Bus::write(uint8_t id, uint16_t addr, const uint8_t* data, uint16_t len, bool expect_status) {
  uint8_t prm[2 + 16];
  if (len > 16) return false;
  prm[0] = (uint8_t)addr;
  prm[1] = (uint8_t)(addr >> 8);
  memcpy(prm + 2, data, len);
  send(id, 0x03, prm, (uint16_t)(2 + len));
  if (!expect_status) return true;
  uint8_t dummy[1];
  uint16_t n = 0;
  uint8_t e = 0;
  return receive(id, dummy, 0, &n, &e) && (e & 0x7F) == 0;
}

bool Bus::reboot(uint8_t id) {
  send(id, 0x08, nullptr, 0);
  uint8_t d[1];
  uint16_t n;
  uint8_t e;
  return receive(id, d, 0, &n, &e);
}

}  // namespace dxl
