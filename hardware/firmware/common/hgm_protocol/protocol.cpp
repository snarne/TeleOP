#include "protocol.h"

#include <string.h>

namespace hgm {

uint16_t crc16_ccitt_false(const uint8_t* data, size_t len, uint16_t crc) {
  for (size_t i = 0; i < len; ++i) {
    crc ^= (uint16_t)data[i] << 8;
    for (int b = 0; b < 8; ++b) crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
  }
  return crc;
}

size_t cobs_encode(const uint8_t* in, size_t len, uint8_t* out) {
  // Canonical COBS (no trailing 0x01 after a final full 254-byte block); matches the Python codec.
  uint8_t* enc = out;
  uint8_t* codep = enc++;
  uint8_t code = 1;
  for (size_t i = 0; i < len; ++i) {
    uint8_t b = in[i];
    if (b) { *enc++ = b; ++code; }
    if (!b || code == 0xFF) {
      *codep = code;
      code = 1;
      codep = enc;
      if (!b || i + 1 < len) ++enc;
    }
  }
  *codep = code;
  return (size_t)(enc - out);
}

int cobs_decode(const uint8_t* in, size_t len, uint8_t* out, size_t out_cap) {
  size_t read = 0, write = 0;
  while (read < len) {
    uint8_t code = in[read];
    if (code == 0 || read + code > len) return -1;
    ++read;
    for (uint8_t i = 1; i < code; ++i) {
      if (write >= out_cap) return -1;
      out[write++] = in[read++];
    }
    if (code != 0xFF && read < len) {
      if (write >= out_cap) return -1;
      out[write++] = 0;
    }
  }
  return (int)write;
}

// ---------------------------------------------------------------- LE helpers
namespace {
inline void put_u8(uint8_t*& p, uint8_t v) { *p++ = v; }
inline void put_u16(uint8_t*& p, uint16_t v) { *p++ = (uint8_t)v; *p++ = (uint8_t)(v >> 8); }
inline void put_u32(uint8_t*& p, uint32_t v) {
  for (int i = 0; i < 4; ++i) *p++ = (uint8_t)(v >> (8 * i));
}
inline void put_f32(uint8_t*& p, float v) { uint32_t u; memcpy(&u, &v, 4); put_u32(p, u); }
inline uint8_t get_u8(const uint8_t*& p) { return *p++; }
inline uint16_t get_u16(const uint8_t*& p) { uint16_t v = (uint16_t)(p[0] | (p[1] << 8)); p += 2; return v; }
inline uint32_t get_u32(const uint8_t*& p) {
  uint32_t v = (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
  p += 4;
  return v;
}
inline float get_f32(const uint8_t*& p) { uint32_t u = get_u32(p); float f; memcpy(&f, &u, 4); return f; }
}  // namespace

size_t pack(const Setpoint& v, uint8_t* out) {
  uint8_t* p = out;
  put_u8(p, v.mode); put_f32(p, v.haptic_n); put_f32(p, v.spring_n); put_f32(p, v.spring_min_n);
  put_f32(p, v.damping); put_f32(p, v.max_n); put_f32(p, v.pos_cmd);
  return (size_t)(p - out);
}
size_t pack(const SetParam& v, uint8_t* out) { uint8_t* p = out; put_u8(p, v.param); put_f32(p, v.value); return 5; }
size_t pack(const Led& v, uint8_t* out) { out[0] = v.r; out[1] = v.g; out[2] = v.b; out[3] = v.pattern; return 4; }
size_t pack(const Telemetry& v, uint8_t* out) {
  uint8_t* p = out;
  put_u32(p, v.t_us); put_f32(p, v.pos); put_f32(p, v.vel); put_f32(p, v.force_op_n); put_f32(p, v.force_cmd_n);
  put_f32(p, v.lever_rad); put_f32(p, v.servo_rad); put_u16(p, (uint16_t)v.servo_ma); put_u8(p, v.buttons);
  put_u8(p, v.mode); put_u16(p, v.status); put_u16(p, v.loop_us_max);
  return (size_t)(p - out);
}
size_t pack(const Ack& v, uint8_t* out) {
  uint8_t* p = out;
  put_u8(p, v.req_type); put_u16(p, v.req_seq); put_u8(p, v.result); put_f32(p, v.value);
  return (size_t)(p - out);
}
size_t pack(const Info& v, uint8_t* out) {
  uint8_t* p = out;
  put_u16(p, v.proto); put_u8(p, v.fw_major); put_u8(p, v.fw_minor); put_u8(p, v.fw_patch); put_u8(p, v.hw_rev);
  put_u16(p, v.rx_errors);
  memcpy(p, v.serial, 16); p += 16;
  return (size_t)(p - out);
}

bool unpack(const uint8_t* in, size_t len, Setpoint* v) {
  if (len != kSetpointLen) return false;
  const uint8_t* p = in;
  v->mode = get_u8(p); v->haptic_n = get_f32(p); v->spring_n = get_f32(p); v->spring_min_n = get_f32(p);
  v->damping = get_f32(p); v->max_n = get_f32(p); v->pos_cmd = get_f32(p);
  return true;
}
bool unpack(const uint8_t* in, size_t len, SetParam* v) {
  if (len != kSetParamLen) return false;
  const uint8_t* p = in; v->param = get_u8(p); v->value = get_f32(p); return true;
}
bool unpack(const uint8_t* in, size_t len, GetParam* v) { if (len != 1) return false; v->param = in[0]; return true; }
bool unpack(const uint8_t* in, size_t len, CommandPkt* v) { if (len != 1) return false; v->cmd = in[0]; return true; }
bool unpack(const uint8_t* in, size_t len, Led* v) {
  if (len != kLedLen) return false;
  v->r = in[0]; v->g = in[1]; v->b = in[2]; v->pattern = in[3]; return true;
}
bool unpack(const uint8_t* in, size_t len, Telemetry* v) {
  if (len != kTelemetryLen) return false;
  const uint8_t* p = in;
  v->t_us = get_u32(p); v->pos = get_f32(p); v->vel = get_f32(p); v->force_op_n = get_f32(p);
  v->force_cmd_n = get_f32(p); v->lever_rad = get_f32(p); v->servo_rad = get_f32(p);
  v->servo_ma = (int16_t)get_u16(p); v->buttons = get_u8(p); v->mode = get_u8(p); v->status = get_u16(p);
  v->loop_us_max = get_u16(p);
  return true;
}
bool unpack(const uint8_t* in, size_t len, Ack* v) {
  if (len != kAckLen) return false;
  const uint8_t* p = in;
  v->req_type = get_u8(p); v->req_seq = get_u16(p); v->result = get_u8(p); v->value = get_f32(p);
  return true;
}
bool unpack(const uint8_t* in, size_t len, Info* v) {
  if (len != kInfoLen) return false;
  const uint8_t* p = in;
  v->proto = get_u16(p); v->fw_major = get_u8(p); v->fw_minor = get_u8(p); v->fw_patch = get_u8(p);
  v->hw_rev = get_u8(p); v->rx_errors = get_u16(p);
  memcpy(v->serial, p, 16);
  return true;
}

size_t pack(const CuePkt& v, uint8_t* out) {
  uint8_t* p = out;
  put_u8(p, v.waveform); put_u8(p, v.amplitude); put_u16(p, v.duration_ms);
  return (size_t)(p - out);
}
size_t pack(const FingertipTelemetry& v, uint8_t* out) {
  uint8_t* p = out;
  put_u32(p, v.t_us); put_f32(p, v.force_a_n); put_f32(p, v.force_b_n); put_f32(p, v.hf_a_n); put_f32(p, v.hf_b_n);
  put_u16(p, v.status); put_u16(p, v.loop_us_max);
  return (size_t)(p - out);
}
bool unpack(const uint8_t* in, size_t len, CuePkt* v) {
  if (len != kCueLen) return false;
  const uint8_t* p = in;
  v->waveform = get_u8(p); v->amplitude = get_u8(p); v->duration_ms = get_u16(p);
  return true;
}
bool unpack(const uint8_t* in, size_t len, FingertipTelemetry* v) {
  if (len != kFingertipLen) return false;
  const uint8_t* p = in;
  v->t_us = get_u32(p); v->force_a_n = get_f32(p); v->force_b_n = get_f32(p); v->hf_a_n = get_f32(p);
  v->hf_b_n = get_f32(p); v->status = get_u16(p); v->loop_us_max = get_u16(p);
  return true;
}

size_t encode_frame(uint8_t type, uint16_t seq, const uint8_t* body, size_t body_len, uint8_t* out, size_t cap) {
  uint8_t payload[kMaxPayload];
  size_t n = 4 + body_len + 2;
  if (n > kMaxPayload) return 0;
  payload[0] = type;
  payload[1] = 0;
  payload[2] = (uint8_t)seq;
  payload[3] = (uint8_t)(seq >> 8);
  if (body_len) memcpy(payload + 4, body, body_len);
  uint16_t crc = crc16_ccitt_false(payload, 4 + body_len);
  payload[4 + body_len] = (uint8_t)crc;
  payload[5 + body_len] = (uint8_t)(crc >> 8);
  if (cap < n + n / 254 + 2) return 0;
  size_t m = cobs_encode(payload, n, out);
  out[m++] = 0x00;
  return m;
}

bool FrameDecoder::feed(uint8_t byte) {
  if (byte != 0x00) {
    if (raw_len_ < sizeof(raw_)) {
      raw_[raw_len_++] = byte;
    } else {
      overflow_ = true;
    }
    return false;
  }
  // delimiter
  bool ok = false;
  if (raw_len_ > 0) {
    if (overflow_) {
      ++errors_;
    } else {
      int n = cobs_decode(raw_, raw_len_, payload_, sizeof(payload_));
      if (n >= 6) {
        uint16_t crc_rx = (uint16_t)(payload_[n - 2] | (payload_[n - 1] << 8));
        if (crc16_ccitt_false(payload_, (size_t)n - 2) == crc_rx) {
          payload_len_ = (size_t)n;
          ok = true;
        } else {
          ++errors_;
        }
      } else {
        ++errors_;
      }
    }
  }
  raw_len_ = 0;
  overflow_ = false;
  return ok;
}

}  // namespace hgm
