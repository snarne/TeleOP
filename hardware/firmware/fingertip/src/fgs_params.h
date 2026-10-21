// FGS persistent parameters (protocol ids 20..26): defaults, validation, flash storage.
#pragma once

#include <stdint.h>

#include "protocol.h"

namespace fgs {

constexpr uint8_t kFirstParam = hgm::kFgsScaleA;   // 20
constexpr uint8_t kNumParams = 7;                  // 20..26

struct FgsParams {
  uint32_t magic;
  uint16_t version;
  uint16_t cal_mask;          // bit0 scale_a calibrated, bit1 scale_b calibrated, bit2 tared
  float v[kNumParams];        // v[id - 20]
  uint16_t crc;
};

constexpr uint32_t kFgsMagic = 0x46475331;  // "FGS1"
constexpr uint16_t kFgsParamsVersion = 1;
constexpr uint16_t kCalScaleA = 1, kCalScaleB = 2, kCalTared = 4;

void params_defaults(FgsParams* p);
// Validate and store. Returns an hgm::AckResult; *applied gets the stored value.
uint8_t params_set(FgsParams* p, uint8_t id, float value, float* applied);
bool params_get(const FgsParams& p, uint8_t id, float* value);
uint16_t params_crc(const FgsParams& p);
inline float param(const FgsParams& p, uint8_t id) { return p.v[id - kFirstParam]; }
// CAL_VALID: both scales were calibrated with known weights (and saved or set this session)
inline bool cal_valid(const FgsParams& p) { return (p.cal_mask & (kCalScaleA | kCalScaleB)) == (kCalScaleA | kCalScaleB); }

bool params_load(FgsParams* p);   // target only (params_flash.cpp)
bool params_save(FgsParams* p);

}  // namespace fgs
