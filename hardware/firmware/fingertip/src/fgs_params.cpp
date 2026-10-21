#include "fgs_params.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "config.h"

namespace fgs {

namespace {
struct Range { float lo, hi, def; };
// index = id - 20
const Range kRanges[kNumParams] = {
    {-1e-3f, 1e-3f, kNominalNPerCount},   // 20 scale_a N/count (sign = bridge wiring; |v| ≥ 1e-7)
    {-1e-3f, 1e-3f, kNominalNPerCount},   // 21 scale_b
    {-8388608.f, 8388607.f, 0.f},         // 22 offset_a counts
    {-8388608.f, 8388607.f, 0.f},         // 23 offset_b
    {10.f, 1000.f, 60.f},                 // 24 hf_band_lo_hz
    {50.f, 1500.f, 400.f},                // 25 hf_band_hi_hz (≤ 0.375 f_s)
    {50.f, 1000.f, 500.f},                // 26 telemetry_hz
};
}  // namespace

uint16_t params_crc(const FgsParams& p) {
  return hgm::crc16_ccitt_false(reinterpret_cast<const uint8_t*>(&p), offsetof(FgsParams, crc));
}

void params_defaults(FgsParams* p) {
  memset(p, 0, sizeof(*p));
  p->magic = kFgsMagic;
  p->version = kFgsParamsVersion;
  for (uint8_t i = 0; i < kNumParams; ++i) p->v[i] = kRanges[i].def;
  p->crc = params_crc(*p);
}

uint8_t params_set(FgsParams* p, uint8_t id, float value, float* applied) {
  if (id < kFirstParam || id >= kFirstParam + kNumParams) return hgm::kAckBadParam;
  if (!(value == value) || isinf(value)) return hgm::kAckBadValue;
  const uint8_t i = id - kFirstParam;
  if (id == hgm::kFgsTelemetryHz) value = floorf(value + 0.5f);
  if (value < kRanges[i].lo || value > kRanges[i].hi) return hgm::kAckBadValue;
  if ((id == hgm::kFgsScaleA || id == hgm::kFgsScaleB) && fabsf(value) < 1e-7f) return hgm::kAckBadValue;
  // the slip band must stay a band: hi ≥ 1.5 · lo
  if (id == hgm::kFgsHfBandLoHz && param(*p, hgm::kFgsHfBandHiHz) < 1.5f * value) return hgm::kAckBadValue;
  if (id == hgm::kFgsHfBandHiHz && value < 1.5f * param(*p, hgm::kFgsHfBandLoHz)) return hgm::kAckBadValue;
  p->v[i] = value;
  if (id == hgm::kFgsScaleA) p->cal_mask |= kCalScaleA;
  if (id == hgm::kFgsScaleB) p->cal_mask |= kCalScaleB;
  if (id == hgm::kFgsOffsetA || id == hgm::kFgsOffsetB) p->cal_mask |= kCalTared;
  if (applied) *applied = value;
  return hgm::kAckOk;
}

bool params_get(const FgsParams& p, uint8_t id, float* value) {
  if (id < kFirstParam || id >= kFirstParam + kNumParams) return false;
  *value = p.v[id - kFirstParam];
  return true;
}

}  // namespace fgs
