# HGM pinout and netlist (v1.1)

v1.1 boards add the DRV2605L haptic driver and remap D0–D3 and D10. Firmware 1.1.x expects
this map; v1.0 boards keep firmware 1.0.0 (`prebuilt/hgm-fw-1.0.0-xiao_rp2040.uf2`).

## Seeed XIAO RP2040 pin assignment

| XIAO pin | RP2040 GPIO | Function | Net | Notes |
|---|---|---|---|---|
| D0 | GP26 / ADC0 | Bus-voltage sense | `VSENSE` | 5V_IN / 2 through R10/R11, 100 nF filter (v1.1; was D2) |
| D1 | GP27 | Thumb button A | `BTN_A` | Active low, internal pull-up, 8 ms debounce (v1.1; was D0) |
| D2 | GP28 (I2C0 SDA) | DRV2605L SDA | `HSDA` | v1.1 haptic bus, 400 kHz, 4.7 k pull-up R12 |
| D3 | GP29 (I2C0 SCL) | DRV2605L SCL | `HSCL` | v1.1 haptic bus, 400 kHz, 4.7 k pull-up R13 |
| D4 | GP6 (I2C1 SDA) | AS5600 SDA | `SDA` | 1 MHz, 2.2 k pull-up |
| D5 | GP7 (I2C1 SCL) | AS5600 SCL | `SCL` | 1 MHz, 2.2 k pull-up |
| D6 | GP0 (UART0 TX) | Dynamixel TX | `TX` | → U2 pin 5 (2A) |
| D7 | GP1 (UART0 RX) | Dynamixel RX | `RX` | ← U2 pin 6 (1Y), 10 k pull-up R6 |
| D8 | GP2 | Bus direction | `DIR` | → U2 pins 1 (1OE̅) and 7 (2OE); 1 = transmit |
| D9 | GP4 | Servo power enable | `SERVO_EN` | → R3 → Q2 base; 1 = servo powered |
| D10 | GP3 | Thumb button B | `BTN_B` | Active low, internal pull-up (v1.1; was D1) |
| 3V3 | — | 3.3 V out | `3V3` | U2 VCC, AS5600 VCC, pull-ups |
| GND | — | ground | `GND` | common with the leader bus and servo |
| 5V | VBUS | USB 5 V | — | **not connected** to the servo supply |
| — | GP12 / GP11 | onboard NeoPixel / its power enable | | status LED |

## Connectors

| Ref | Type | Pin 1 | Pin 2 | Pin 3 | Pin 4 | Goes to |
|---|---|---|---|---|---|---|
| J1 | JST-EH 3P | GND | VDD (5V_IN) | DATA (n.c.) | — | Spare port on the leader arm's J6 XL330 (same pinout as Dynamixel X-series) |
| J2 | JST-EH 3P | GND | 5V_SERVO | DXL_DATA | — | XC330-M288-T (standard ROBOTIS 3-pin cable) |
| J3 | 1×4 0.1" | 3V3 | GND | SDA | SCL | AS5600 breakout (tie its DIR pin to GND on the breakout) |
| SW1/SW2 | 2 wires each | BTN_A/BTN_B | GND | | | D2F-01 COM and NO terminals |
| J4 (v1.1) | 2 wires | LRA+ | LRA− | | | Coin LRA in the trigger blade (polarity irrelevant) |

## Netlist (point-to-point build list)

| Net | Connections |
|---|---|
| `5V_IN` | J1.2 → F1 → D1 cathode, Q1 source, R1, C1, R10 |
| `5V_SERVO` | Q1 drain, C2 +, C3, J2.2 |
| `Q1_GATE` | Q1 gate, R1 (to 5V_IN), C1 (to 5V_IN), R2 |
| `Q2_C` | R2, Q2 collector |
| `SERVO_EN` | XIAO D9, R3 |
| `Q2_B` | R3, Q2 base, R4 (to GND) |
| `VSENSE` | R10/R11 junction, C6, XIAO D0 |
| `DXL_DATA` | J2.3, R5 (to 3V3), U2 pin 2 (1A), R7 → U2 pin 3 (2Y) |
| `TX` | XIAO D6 → U2 pin 5 (2A) |
| `RX` | U2 pin 6 (1Y) → XIAO D7, R6 (to 3V3) |
| `DIR` | XIAO D8 → U2 pin 1 (1OE̅) and pin 7 (2OE) |
| `3V3` | XIAO 3V3, U2 pin 8, C4, R5, R6, R8, R9, R12, R13, J3.1, U3 VIN and EN (+ 10 µF bulk at U3) |
| `SDA` | XIAO D4, R8, J3.3 |
| `SCL` | XIAO D5, R9, J3.4 |
| `BTN_A` / `BTN_B` | XIAO D1 / D10, SW1 / SW2, optional 100 nF to GND |
| `HSDA` | XIAO D2, R12 (to 3V3), U3 SDA |
| `HSCL` | XIAO D3, R13 (to 3V3), U3 SCL |
| `LRA+` / `LRA−` | U3 OUT+ / OUT− → 2 × 30 AWG silicone leads through the pivot groove → LRA in the blade |
| `GND` | J1.1, J2.1, D1 anode, C2 −, C3, C4, C6, R4, R11, Q2 emitter, U2 pin 4, XIAO GND, J3.2, SW1/SW2 |

Wire colours used in the assembly guide: red = 5 V, orange = 5V_SERVO, yellow = DXL_DATA,
black = GND, blue = SDA, white = SCL, green = buttons.

## Station side (see station_power.svg)

| Numato channel | Function | Default state |
|---|---|---|
| K1 | Left follower SSR control (in series with E-stop NC1) | off at boot |
| K2 | Right follower SSR control (in series with E-stop NC2) | off at boot |
| K3 | Left leader 5 V bus | off at boot |
| K4 | Right leader 5 V bus | off at boot |
| K5–K8 | spare (lights, camera hub, …) | |
| GPIO0 | E-stop sense via NC3 (low = released, high = pressed or wire broken) | input, 10 k pull-up |
