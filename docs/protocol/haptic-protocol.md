# Haptic Grip Module serial protocol, v1

Transport: USB CDC-ACM (virtual serial port; the baud rate setting is ignored). Each
module enumerates with the RP2040's unique board ID as its USB serial number. udev maps
that ID to `/dev/hgm_left` and `/dev/hgm_right` (see `scripts/udev/99-teleop-station.rules`).

## Framing

```
wire:     COBS( payload ) 0x00
payload:  type:u8 | flags:u8 | seq:u16 | body:… | crc:u16
```

* All multi-byte fields are **little-endian**. Floats are IEEE-754 `f32`.
* `crc` is **CRC-16/CCITT-FALSE** (poly 0x1021, init 0xFFFF, no reflection, xorout 0x0000)
  over `type … body`. Check value for ASCII `"123456789"`: `0x29B1`.
* `flags` is reserved (send 0). `seq` increments per packet per direction and wraps.
* Max payload is 64 bytes. Receivers drop frames that fail CRC or length checks and
  count them (`rx_errors` in INFO).

## Host → module

| Type | Name | Body | Notes |
|---|---|---|---|
| `0x01` | SETPOINT | `mode:u8, haptic_n:f32, spring_n:f32, spring_min_n:f32, damping:f32, max_n:f32, pos_cmd:f32` (25 B) | Send at ≥ 100 Hz. Doubles as the heartbeat. |
| `0x02` | SET_PARAM | `param:u8, value:f32` | Replied to with ACK carrying the applied value |
| `0x03` | GET_PARAM | `param:u8` | ACK carries the value |
| `0x04` | COMMAND | `cmd:u8` | See the command table |
| `0x05` | PING | — | Module replies with INFO |
| `0x06` | LED | `r:u8, g:u8, b:u8, pattern:u8` | pattern 0 solid, 1 blink, 2 pulse |

**Modes:** `0` OFF (servo torque disabled), `1` SPRING, `2` RENDER, `3` POSITION.

**Params:**

| ID | Name | Unit | Default |
|---|---|---|---|
| 1 | `k_theta` | N·m/rad | 3.14 |
| 2 | `finger_radius` | m | 0.045 |
| 3 | `theta_open` | rad (lever encoder) | 0.0 |
| 4 | `theta_closed` | rad | 0.5236 (30°) |
| 5 | `sea_zero` (δ₀) | rad | 0.0 |
| 6 | `ki` | rad/(N·s) | 0.0 |
| 7 | `current_limit_ma` | mA | 1200 |
| 8 | `telemetry_div` | loops per telemetry packet | 2 |
| 9 | `servo_p_gain` | Dynamixel units | 1600 |
| 10 | `watchdog_ms` | ms | 100 |
| 11 | `lever_dir` | ±1 | 1 |
| 12 | `servo_dir` | ±1 | 1 |
| 13 | `preload_nm` | N·m (spring preload torque; the firmware won't render below it) | 0.047 |

**Commands:** `1` TARE_SEA (δ₀ ← current deflection; call with the hand off the trigger),
`2` SAVE_PARAMS (to flash), `3` LOAD_DEFAULTS, `4` REBOOT, `5` BOOTSEL (UF2 bootloader),
`6` CLEAR_FAULTS, `7` IDENTIFY (blink the LED for 3 s).

## Module → host

| Type | Name | Body |
|---|---|---|
| `0x81` | TELEMETRY | `t_us:u32, pos:f32, vel:f32, force_op_n:f32, force_cmd_n:f32, lever_rad:f32, servo_rad:f32, servo_ma:i16, buttons:u8, mode:u8, status:u16, loop_us_max:u16` (36 B) |
| `0x82` | ACK | `req_type:u8, req_seq:u16, result:u8, value:f32` (result 0 ok, 1 bad_param, 2 bad_value, 3 failed, 4 unknown_type) |
| `0x83` | LOG | `level:u8 (0 debug … 3 error), text: utf-8` |
| `0x84` | INFO | `proto:u16 (=1), fw_major:u8, fw_minor:u8, fw_patch:u8, hw_rev:u8, rx_errors:u16, serial: 16 × ASCII` |

**Status bits:** 0 SERVO_OK, 1 ENCODER_OK, 2 CAL_VALID, 3 WATCHDOG, 4 SERVO_HW_ERROR,
5 OVERFORCE, 6 MAGNET_FAULT, 7 SERVO_POWER, 8 PARAMS_DIRTY.

**Buttons:** bit 0 = A (upper thumb), bit 1 = B (lower thumb), active high (pressed = 1).

## Timing

The module sends TELEMETRY every `telemetry_div` control ticks (500 Hz by default), INFO
once on boot and on every PING, and LOG only for state changes and faults. The host should
treat a module that has sent no TELEMETRY for 50 ms as disconnected.

## Reference implementations

* Python: `station/hardware/haptic_protocol.py` (codec) and
  `station/hardware/haptic_trigger.py` (device and simulator)
* C++: `hardware/firmware/haptic_grip/src/protocol.{h,cpp}`
* Shared test vectors: `tests/vectors/haptic_protocol.json`, checked by both the
  Python and the C++ unit tests.

---

## v1.1 additions (backward compatible)

### HGM: vibrotactile cues

A small LRA in the trigger pad, driven by a DRV2605L on the HGM board (I²C 0x5A, on its own
I²C bus at 400 kHz; the AS5600 encoder bus runs at 1 MHz, faster than the DRV2605L allows), plays short cues that the series-elastic loop is too slow to
render. These are the "fast-adapting" half of touch: contact onset and slip.

| Type | Name | Body |
|---|---|---|
| `0x07` | CUE | `waveform:u8, amplitude:u8 (0–255), duration_ms:u16` |

Waveforms: `1` TAP (contact onset, crisp ~20 ms pulse), `2` SLIP (burst, repeated while
slip persists), `3` RELEASE (soft tick), `4` BUZZ (fault alert). The module ACKs nothing for
CUE (fire-and-forget at ≤ 50 Hz). It sets status bit **9 `LRA_OK`** once the DRV2605L
answers and its auto-calibration has passed. The cue doesn't disturb the force loop: the
LRA's vibration is far above the SEA loop's bandwidth.

### FGS: follower fingertip sensor

The FGS is a separate USB module on each follower gripper. It reads one strain-gauge load
cell per jaw pad and uses the same framing, CRC and PING/INFO/ACK/COMMAND/SET_PARAM packets.
`INFO.hw_rev` high nibble = device kind (`0` HGM, `1` FGS).

| Type | Name | Body |
|---|---|---|
| `0x91` | FINGERTIP | `t_us:u32, force_a_n:f32, force_b_n:f32, hf_a_n:f32, hf_b_n:f32, status:u16, loop_us_max:u16` (24 B) |

* `force_*`: normal force on each jaw pad (N), low-pass at 100 Hz.
* `hf_*`: RMS of the strain signal in the slip band (default 60–400 Hz, in N). Slip and
  stick-slip show up here before the mean force changes.
* Status bits: 0 `ADC_OK`, 1 `CAL_VALID`, 2 `OVERLOAD_A`, 3 `OVERLOAD_B`.
* Params: 20 `scale_a`, 21 `scale_b` (N/count), 22 `offset_a`, 23 `offset_b` (counts),
  24 `hf_band_lo_hz`, 25 `hf_band_hi_hz`, 26 `telemetry_hz` (default 500).
* Commands: `1` TARE (zero both channels; jaws open, no contact), `2` SAVE_PARAMS,
  `3` LOAD_DEFAULTS, `4` REBOOT, `5` BOOTSEL.
