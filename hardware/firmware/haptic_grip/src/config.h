// HGM firmware configuration: pins, versions and timing.
#pragma once

#include <stdint.h>

#define HGM_FW_MAJOR 1
#define HGM_FW_MINOR 1
#define HGM_FW_PATCH 0
#define HGM_HW_REV 2   // v1.1 board: DRV2605L + LRA; INFO.hw_rev = (DeviceKind HGM << 4) | rev

// ---- Seeed XIAO RP2040 pin map (GPIO numbers); see hardware/electronics/pinout.md
constexpr uint8_t kPinDxlTx = 0;       // D6 → 74LVC2G241 2A (TX buffer input)
constexpr uint8_t kPinDxlRx = 1;       // D7 ← 74LVC2G241 1Y (RX buffer output)
constexpr uint8_t kPinDxlDir = 2;      // D8 → both OE pins: HIGH = transmit, LOW = receive
constexpr uint8_t kPinServoEn = 4;     // D9 → NPN base → AO3401A gate (HIGH = servo powered)
constexpr uint8_t kPinI2cSda = 6;      // D4 AS5600 SDA (I2C1)
constexpr uint8_t kPinI2cScl = 7;      // D5 AS5600 SCL (I2C1)
// v1.1 pin map: D2/D3 become I2C0 for the DRV2605L (≤ 400 kHz), so VSENSE moves to D0 (ADC0)
// and the buttons to D1 / D10.
constexpr uint8_t kPinVbusSense = 26;  // D0 ADC0 ← 100k/100k divider from 5V_IN
constexpr uint8_t kPinBtnA = 27;       // D1 thumb button A (active low, internal pull-up)
constexpr uint8_t kPinBtnB = 3;        // D10 thumb button B
constexpr uint8_t kPinHapSda = 28;     // D2 I2C0 SDA → DRV2605L
constexpr uint8_t kPinHapScl = 29;     // D3 I2C0 SCL → DRV2605L
constexpr uint8_t kPinLed = 12;    // onboard RGB LED
constexpr uint8_t kPinLedPwr = 11;

// ---- timing
constexpr uint32_t kLoopPeriodUs = 1000;     // 1 kHz control loop
constexpr uint32_t kSlowEveryTicks = 50;     // 20 Hz housekeeping
constexpr uint32_t kDxlTimeoutUs = 600;
constexpr uint32_t kDebounceMs = 8;
constexpr uint32_t kHwWatchdogMs = 100;      // RP2040 hardware watchdog
constexpr uint32_t kHapticI2cHz = 400000;    // DRV2605L maximum (Fast mode)
constexpr float kLraNotchHz = 235.0f;        // notch on the lever angle at the LRA frequency
constexpr float kLraNotchQ = 1.5f;

// ---- Dynamixel
constexpr uint32_t kDxlBaud = 4000000;
constexpr uint8_t kDxlBaudIndex = 6;         // X-series Baud Rate register value for 4 Mbps
constexpr uint8_t kDxlDefaultId = 1;
