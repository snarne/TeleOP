# Firmware (Seeed XIAO RP2040): HGM and FGS

Two PlatformIO projects share `common/hgm_protocol/` (the wire codec):

* `haptic_grip/`: the HGM. 1.1.0 adds the CUE packet, the DRV2605L driver, the LRA notch and the v1.1 pin map. Prebuilt `hgm-fw-1.1.0` is for v1.1 boards; keep `hgm-fw-1.0.0` for v1.0 boards.
* `fingertip/`: the FGS (follower fingertip sensor). Prebuilt `fgs-fw-1.0.0`. Tests: `make -C fingertip/test/native` (102 checks). Design notes are in [fingertip-sensor.md §8](../../docs/hardware/fingertip-sensor.md#8-firmware-hardwarefirmwarefingertip).

## HGM

The project is in `haptic_grip/` (PlatformIO, earlephilhower arduino-pico core 4.6). It
builds as-is: **RAM 4.2 %, flash 6.0 %**, and `prebuilt/hgm-fw-1.1.0-xiao_rp2040.uf2`
is included.

## Flash

* **No toolchain needed.** Hold BOOT on the XIAO, plug it in, and drag
  `haptic_grip/prebuilt/hgm-fw-1.1.0-xiao_rp2040.uf2` onto the `RPI-RP2` drive (v1.0 boards: `hgm-fw-1.0.0`).
* **From source:** `cd haptic_grip && pio run -t upload`.
* **Later updates:** the station can send `COMMAND BOOTSEL` (or run
  `hgm_console.py --bootsel`) to reboot into the UF2 bootloader without pressing BOOT.

## Source map

| File | What | Arduino deps |
|---|---|---|
| `src/main.cpp` | 1 kHz scheduler, mode/watchdog/tare state machine, host packet handling, LED, housekeeping | yes |
| `src/control.{h,cpp}` | SEA force law (position-sourced), velocity filter, slew limit, clamps | **no** |
| `../common/hgm_protocol/protocol.{h,cpp}` | COBS, CRC-16/CCITT-FALSE, packet pack/unpack, stream decoder (shared with the FGS) | **no** |
| `src/cue.{h,cpp}` | v1.1 cue engine (TAP/SLIP/RELEASE/BUZZ envelopes, ≤ 1 write per tick) | **no** |
| `src/filters.h` | biquad notch at the LRA frequency on the lever angle | **no** |
| `src/drv2605.{h,cpp}` | DRV2605L: LRA auto-calibration, real-time playback | yes |
| `src/params_store.{h,cpp}` | Parameter table, ranges, calibration bits, CRC | **no** |
| `src/params_flash.cpp` | Flash persistence (EEPROM emulation) | yes |
| `src/dxl.{h,cpp}` | Minimal Dynamixel Protocol 2.0 master: byte stuffing, CRC-16 (0x8005), half-duplex DIR | yes |
| `src/as5600.{h,cpp}` | AS5600 over I²C at 1 MHz, fastest filter, magnet status | yes |
| `src/config.h` | Pins, timing, versions | — |

## Timing per 1 kHz tick (4 Mbps DXL, 1 MHz I²C)

| Step | Approx. time |
|---|---|
| AS5600 raw angle read (2 B) | ~45 µs |
| DXL READ present current/velocity/position (10 B): 14 B request + 21 B status | ~100 µs |
| Control law (float, Cortex-M0+ software FP) | ~40 µs |
| DXL WRITE goal position (no status packet, SRL = 1) | ~45 µs |
| USB RX parse + TELEMETRY every 2nd tick (44 B) | ~20 µs |
| **Total** | **≈ 0.25–0.35 ms**, reported in TELEMETRY.loop_us_max |

## Tests

```bash
make -C haptic_grip/test/native        # 104 checks: shared protocol vectors, control law vs plant, params
python tools/gen_vectors.py            # regenerate tests/vectors/haptic_protocol.json from the Python codec
pytest tests/test_haptic_vectors.py    # the Python codec against the same vectors
```

The control-law test simulates the lever (inertia, viscous friction), the one-sided
preloaded spring with its rigid backstop, the open and closed stops, and a
speed-limited first-order servo. It checks rest behaviour, render equilibrium
(`F_op` within 4 %), push-back when the haptic force exceeds the finger force, clamps,
slew limiting, and the OFF/POSITION modes.

## Building without the PlatformIO registry

If your network blocks `api.registry.platformio.org`, everything else in the build comes
from GitHub: the platform, the arduino-pico core, the toolchain, and the NeoPixel library
(pinned by git tag in `platformio.ini`). The only registry package is `tool-scons`;
install SCons with pip and register it as a local PlatformIO package (see the comments
in `platformio.ini`).
