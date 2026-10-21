// FGS (follower fingertip sensor) firmware configuration: pins, versions, timing, sensor constants.
#pragma once

#include <stdint.h>

#define FGS_FW_MAJOR 1
#define FGS_FW_MINOR 0
#define FGS_FW_PATCH 0
#define FGS_HW_REV 1   // INFO.hw_rev = (DeviceKind FGS << 4) | 1 = 0x11

namespace fgs {

// ---- Seeed XIAO RP2040 pin map (GPIO numbers); see hardware/electronics/fgs_pinout.md
constexpr uint8_t kPinAdcDrdy = 0;    // D6 ← ADS131M02 /DRDY (falls when both channels are ready)
constexpr uint8_t kPinAdcCs = 1;      // D7 → ADS131M02 /CS
constexpr uint8_t kPinSpiSck = 2;     // D8 → SCLK (SPI0)
constexpr uint8_t kPinSpiMosi = 3;    // D10 → DIN
constexpr uint8_t kPinSpiMiso = 4;    // D9 ← DOUT
constexpr uint8_t kPinAdcSync = 26;   // D0 → /SYNC_RESET (hold low ≥ 2048 CLKIN periods = reset)
constexpr uint8_t kPinExcEn = 27;     // D1 → bridge-excitation LDO EN (high = bridges powered)
constexpr uint8_t kPinLedR = 17;      // onboard RGB LED, active low
constexpr uint8_t kPinLedG = 16;
constexpr uint8_t kPinLedB = 25;

// ---- ADC: ADS131M02, CLKIN 8.192 MHz from a CMOS oscillator, high-resolution mode, OSR 1024
constexpr uint32_t kFsHz = 4000;            // f_DATA = f_CLKIN / 2 / OSR = 8.192 MHz / 2048
constexpr uint32_t kSpiHz = 8000000;        // ≤ 25 MHz allowed; 8 MHz keeps edges clean on the flex
constexpr uint8_t kPgaGainCode = 7;         // 2^7 = 128 → FSR ±9.375 mV
constexpr float kAdcVref = 1.2f;
constexpr float kAdcGain = 128.0f;
constexpr float kCountsPerVolt = 8388608.0f / (kAdcVref / kAdcGain);   // 8.948e8 counts/V
constexpr int32_t kClipCounts = 7969177;    // 95 % of full scale: treat as clipped / open bridge

// ---- sensor (see docs/hardware/fingertip-sensor.md §Sensitivity)
constexpr float kExcitationV = 1.8f;        // TPS7A2018 bridge excitation (keeps AIN ≤ AVDD − 1.8 V at G ≥ 8)
constexpr float kBridgeMvPerVAt100N = 0.525f; // full-bridge output at 100 N from the flexure FEA (VERIFY: calibrate)
constexpr float kNominalNPerCount =
    100.0f / (kBridgeMvPerVAt100N * 1e-3f * kExcitationV * kCountsPerVolt);   // ≈ 1.18e-4 N/count
constexpr float kOverloadN = 450.0f;        // flexure is elastic to the gripper stall force (~480 N); flag above 450 N

// ---- DSP
constexpr float kForceLpHz = 100.0f;        // force channel: 2nd-order Butterworth + boxcar to telemetry
constexpr uint8_t kRmsEmaShift = 5;         // slip RMS: EMA time constant 2^5 / 4 kHz = 8 ms
constexpr uint32_t kTareSamples = 1000;     // 250 ms average

// ---- timing
constexpr uint32_t kHwWatchdogMs = 100;
constexpr uint32_t kAdcStaleUs = 20000;     // no sample for 20 ms → ADC_OK cleared, re-init
constexpr uint32_t kAdcRetryMs = 500;

}  // namespace fgs
