// Persistent module parameters: defaults, validation, and flash storage (EEPROM emulation).
#pragma once

#include <stdint.h>

#include "protocol.h"

namespace hgm {

struct StoredParams {
  uint32_t magic;
  uint16_t version;
  uint16_t cal_mask;     // bit0: SEA tared, bit1: travel range set, bit2: k_theta calibrated
  float values[kParamCount];  // indexed by Param id (index 0 unused)
  uint16_t crc;
};

constexpr uint32_t kParamsMagic = 0x48474D31;  // "HGM1"
constexpr uint16_t kParamsVersion = 2;
constexpr uint16_t kCalTared = 1, kCalRange = 2, kCalKTheta = 4;

void params_defaults(StoredParams* p);
// Validate and apply a value. Returns an AckResult; on success *applied holds the stored value.
uint8_t params_set(StoredParams* p, uint8_t id, float value, float* applied);
bool params_get(const StoredParams& p, uint8_t id, float* value);
uint16_t params_crc(const StoredParams& p);

// Flash storage (implemented in params_flash.cpp for the target only)
bool params_load(StoredParams* p);
bool params_save(StoredParams* p);

}  // namespace hgm
