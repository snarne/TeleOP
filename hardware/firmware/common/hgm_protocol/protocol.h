// HGM / FGS wire protocol v1.1: see docs/protocol/haptic-protocol.md.
//
// Pure C++ (no Arduino dependencies), so the same code is unit-tested on the host
// against tests/vectors/haptic_protocol.json, which the Python reference codec generates.
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace hgm {

constexpr uint16_t kProtoVersion = 1;
constexpr size_t kMaxPayload = 64;                       // type..crc
constexpr size_t kMaxFrame = kMaxPayload + kMaxPayload / 254 + 2;  // COBS overhead + delimiter

enum PacketType : uint8_t {
  kSetpoint = 0x01,
  kSetParam = 0x02,
  kGetParam = 0x03,
  kCommand = 0x04,
  kPing = 0x05,
  kLed = 0x06,
  kCue = 0x07,        // v1.1: vibrotactile cue on the trigger pad
  kTelemetry = 0x81,
  kAck = 0x82,
  kLog = 0x83,
  kInfo = 0x84,
  kFingertip = 0x91,  // v1.1: FGS fingertip telemetry
};

enum Mode : uint8_t { kModeOff = 0, kModeSpring = 1, kModeRender = 2, kModePosition = 3 };

enum Param : uint8_t {
  kParamKTheta = 1,
  kParamFingerRadius = 2,
  kParamThetaOpen = 3,
  kParamThetaClosed = 4,
  kParamSeaZero = 5,
  kParamKi = 6,
  kParamCurrentLimitMa = 7,
  kParamTelemetryDiv = 8,
  kParamServoPGain = 9,
  kParamWatchdogMs = 10,
  kParamLeverDir = 11,
  kParamServoDir = 12,
  kParamPreloadNm = 13,   // spring preload torque at the backstop (extension of the v1 table)
  kParamCount = 14,
};

enum Command : uint8_t {
  kCmdTareSea = 1,
  kCmdSaveParams = 2,
  kCmdLoadDefaults = 3,
  kCmdReboot = 4,
  kCmdBootsel = 5,
  kCmdClearFaults = 6,
  kCmdIdentify = 7,
};

enum StatusBit : uint16_t {
  kStServoOk = 1u << 0,
  kStEncoderOk = 1u << 1,
  kStCalValid = 1u << 2,
  kStWatchdog = 1u << 3,
  kStServoHwError = 1u << 4,
  kStOverforce = 1u << 5,
  kStMagnetFault = 1u << 6,
  kStServoPower = 1u << 7,
  kStParamsDirty = 1u << 8,
  kStLraOk = 1u << 9,      // v1.1: DRV2605L present and LRA auto-calibration passed
};

// ---- v1.1: cues (HGM) and the follower fingertip sensor (FGS)
enum CueWave : uint8_t { kCueTap = 1, kCueSlip = 2, kCueRelease = 3, kCueBuzz = 4 };
enum DeviceKind : uint8_t { kDevHgm = 0x0, kDevFgs = 0x1 };   // INFO.hw_rev high nibble
inline uint8_t make_hw_rev(DeviceKind kind, uint8_t rev) { return (uint8_t)((kind << 4) | (rev & 0x0F)); }

enum FgsStatusBit : uint16_t {
  kFgsAdcOk = 1u << 0,
  kFgsCalValid = 1u << 1,
  kFgsOverloadA = 1u << 2,
  kFgsOverloadB = 1u << 3,
};

enum FgsParam : uint8_t {
  kFgsScaleA = 20,       // N per ADC count
  kFgsScaleB = 21,
  kFgsOffsetA = 22,      // counts (TARE)
  kFgsOffsetB = 23,
  kFgsHfBandLoHz = 24,
  kFgsHfBandHiHz = 25,
  kFgsTelemetryHz = 26,
};

enum FgsCommand : uint8_t { kFgsCmdTare = 1, kFgsCmdSave = 2, kFgsCmdLoadDefaults = 3, kFgsCmdReboot = 4,
                            kFgsCmdBootsel = 5 };

enum AckResult : uint8_t { kAckOk = 0, kAckBadParam = 1, kAckBadValue = 2, kAckFailed = 3, kAckUnknownType = 4 };

// ---------------------------------------------------------------- packet bodies
struct Setpoint {
  uint8_t mode = kModeSpring;
  float haptic_n = 0.f;
  float spring_n = 1.5f;
  float spring_min_n = 1.2f;
  float damping = 0.02f;
  float max_n = 12.f;
  float pos_cmd = 0.f;
};
constexpr size_t kSetpointLen = 25;

struct SetParam { uint8_t param; float value; };
constexpr size_t kSetParamLen = 5;
struct GetParam { uint8_t param; };
struct CommandPkt { uint8_t cmd; };
struct Led { uint8_t r, g, b, pattern; };
constexpr size_t kLedLen = 4;

struct Telemetry {
  uint32_t t_us;
  float pos, vel, force_op_n, force_cmd_n, lever_rad, servo_rad;
  int16_t servo_ma;
  uint8_t buttons, mode;
  uint16_t status, loop_us_max;
};
constexpr size_t kTelemetryLen = 36;

struct CuePkt { uint8_t waveform; uint8_t amplitude; uint16_t duration_ms; };
constexpr size_t kCueLen = 4;

struct FingertipTelemetry {
  uint32_t t_us;
  float force_a_n, force_b_n, hf_a_n, hf_b_n;
  uint16_t status, loop_us_max;
};
constexpr size_t kFingertipLen = 24;

struct Ack { uint8_t req_type; uint16_t req_seq; uint8_t result; float value; };
constexpr size_t kAckLen = 8;

struct Info {
  uint16_t proto;
  uint8_t fw_major, fw_minor, fw_patch, hw_rev;
  uint16_t rx_errors;
  char serial[16];  // ASCII, NUL-padded (not NUL-terminated when 16 chars long)
};
constexpr size_t kInfoLen = 24;

// ---------------------------------------------------------------- primitives
uint16_t crc16_ccitt_false(const uint8_t* data, size_t len, uint16_t crc = 0xFFFF);

// COBS encode `len` bytes; returns the encoded length (no delimiter). `out` needs len + len/254 + 1.
size_t cobs_encode(const uint8_t* in, size_t len, uint8_t* out);
// COBS decode; returns decoded length, or -1 on a malformed frame / overflow.
int cobs_decode(const uint8_t* in, size_t len, uint8_t* out, size_t out_cap);

// ---------------------------------------------------------------- body pack / unpack (little-endian)
size_t pack(const Setpoint& v, uint8_t* out);
size_t pack(const SetParam& v, uint8_t* out);
size_t pack(const Telemetry& v, uint8_t* out);
size_t pack(const Ack& v, uint8_t* out);
size_t pack(const Info& v, uint8_t* out);
size_t pack(const Led& v, uint8_t* out);
size_t pack(const CuePkt& v, uint8_t* out);
size_t pack(const FingertipTelemetry& v, uint8_t* out);
bool unpack(const uint8_t* in, size_t len, Setpoint* v);
bool unpack(const uint8_t* in, size_t len, SetParam* v);
bool unpack(const uint8_t* in, size_t len, GetParam* v);
bool unpack(const uint8_t* in, size_t len, CommandPkt* v);
bool unpack(const uint8_t* in, size_t len, Led* v);
bool unpack(const uint8_t* in, size_t len, Telemetry* v);
bool unpack(const uint8_t* in, size_t len, Ack* v);
bool unpack(const uint8_t* in, size_t len, Info* v);
bool unpack(const uint8_t* in, size_t len, CuePkt* v);
bool unpack(const uint8_t* in, size_t len, FingertipTelemetry* v);

// Build a full on-wire frame: COBS(type|flags|seq|body|crc) + 0x00. Returns the length, 0 on error.
size_t encode_frame(uint8_t type, uint16_t seq, const uint8_t* body, size_t body_len, uint8_t* out, size_t cap);

// ---------------------------------------------------------------- stream decoder
class FrameDecoder {
 public:
  // Feed one byte. Returns true when a complete, CRC-valid frame is available.
  bool feed(uint8_t byte);
  uint8_t type() const { return payload_[0]; }
  uint16_t seq() const { return (uint16_t)(payload_[2] | (payload_[3] << 8)); }
  const uint8_t* body() const { return payload_ + 4; }
  size_t body_len() const { return payload_len_ >= 6 ? payload_len_ - 6 : 0; }
  uint32_t errors() const { return errors_; }

 private:
  uint8_t raw_[kMaxFrame];
  size_t raw_len_ = 0;
  bool overflow_ = false;
  uint8_t payload_[kMaxPayload];
  size_t payload_len_ = 0;
  uint32_t errors_ = 0;
};

}  // namespace hgm
