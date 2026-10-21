#include "params_store.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

namespace hgm {

namespace {
struct Range { float lo, hi, def; };
// Index = Param id
const Range kRanges[kParamCount] = {
    {0, 0, 0},                 // 0 unused
    {0.2f, 50.0f, 3.14f},      // 1 k_theta N·m/rad (designed 3.144, calibrate per module)
    {0.02f, 0.08f, 0.045f},    // 2 finger_radius m
    {-6.4f, 6.4f, 0.0f},       // 3 theta_open rad
    {-6.4f, 6.4f, 0.5236f},    // 4 theta_closed rad
    {-6.4f, 6.4f, 0.0f},       // 5 sea_zero rad
    {0.0f, 0.2f, 0.0f},        // 6 ki rad/(N·s)
    {100.0f, 1750.0f, 1200.0f},  // 7 current_limit_ma (XC330 stall 1.8 A at 5 V)
    {1.0f, 100.0f, 2.0f},      // 8 telemetry_div
    {100.0f, 16000.0f, 1600.0f},  // 9 servo_p_gain
    {20.0f, 2000.0f, 100.0f},  // 10 watchdog_ms
    {-1.0f, 1.0f, 1.0f},       // 11 lever_dir (±1)
    {-1.0f, 1.0f, 1.0f},       // 12 servo_dir (±1)
    {0.0f, 0.3f, 0.047f},      // 13 preload_nm (designed 0.0472)
};
}  // namespace

uint16_t params_crc(const StoredParams& p) {
  return crc16_ccitt_false(reinterpret_cast<const uint8_t*>(&p), offsetof(StoredParams, crc));
}

void params_defaults(StoredParams* p) {
  memset(p, 0, sizeof(*p));
  p->magic = kParamsMagic;
  p->version = kParamsVersion;
  p->cal_mask = 0;
  for (uint8_t i = 1; i < kParamCount; ++i) p->values[i] = kRanges[i].def;
  p->crc = params_crc(*p);
}

uint8_t params_set(StoredParams* p, uint8_t id, float value, float* applied) {
  if (id == 0 || id >= kParamCount) return kAckBadParam;
  if (!(value == value)) return kAckBadValue;  // NaN
  if (id == kParamLeverDir || id == kParamServoDir) {
    if (fabsf(fabsf(value) - 1.0f) > 1e-3f) return kAckBadValue;
    value = value > 0 ? 1.0f : -1.0f;
  }
  if (id == kParamTelemetryDiv) value = floorf(value + 0.5f);
  if (value < kRanges[id].lo || value > kRanges[id].hi) return kAckBadValue;
  p->values[id] = value;
  if (id == kParamThetaOpen || id == kParamThetaClosed) p->cal_mask |= kCalRange;
  if (id == kParamSeaZero) p->cal_mask |= kCalTared;
  if (id == kParamKTheta) p->cal_mask |= kCalKTheta;
  if (applied) *applied = value;
  return kAckOk;
}

bool params_get(const StoredParams& p, uint8_t id, float* value) {
  if (id == 0 || id >= kParamCount) return false;
  *value = p.values[id];
  return true;
}

}  // namespace hgm
