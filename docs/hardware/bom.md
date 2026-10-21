# Bill of materials

Generated from [`hardware/electronics/bom.csv`](../../hardware/electronics/bom.csv) by `hardware/electronics/src/bom_md.py`. Prices are approximate single-quantity USD (late 2026) for budgeting only; check the suppliers before ordering.

## HGM (per handle - order x2)

| Ref | Qty | Part | MPN | Supplier | Unit $ | Line $ | Notes |
|---|---:|---|---|---|---:|---:|---|
| M1 | 1 | Dynamixel XC330-M288-T servo (5 V, metal gear, 4 Mbps TTL) | XC330-M288-T | ROBOTIS / Trossen / RobotShop | 40.00 | 40.00 | Comes with horn and a 3-pin cable. Set the ID to 1 (firmware auto-detects baud). |
| U1 | 1 | Seeed Studio XIAO RP2040 | 102010428 | Seeed / Digi-Key | 5.40 | 5.40 | USB-C to the station PC |
| U2 | 1 | Dual buffer, 3-state (half-duplex DXL interface) | SN74LVC2G241DCUR | TI via Digi-Key/Mouser | 0.60 | 0.60 | VSSOP-8: hand-solder onto an MSOP-8→DIP adapter for v0 |
| J3 | 1 | AS5600 12-bit magnetic encoder breakout | AS5600 breakout (generic) | Amazon / AliExpress / Seeed Grove | 4.00 | 4.00 | Set AS5600_BOARD in params.py to your board size (23 mm default; Grove is 20 mm) |
| MAG1 | 1 | Diametric magnet Ø6 × 2.5 mm, N52 | generic (often bundled with AS5600 boards) | Amazon / K&J Magnetics | 0.80 | 0.80 | Must be DIAMETRICALLY magnetised. K&J D42DIA (6.35×3.18) also fits if MAGNET_D/T are updated |
| Q1 | 1 | P-MOSFET −30 V / −4 A, SOT-23 | AO3401A | Alpha & Omega via LCSC/Digi-Key | 0.15 | 0.15 | High-side servo power switch |
| Q2 | 1 | NPN 40 V, SOT-23 | MMBT3904 | onsemi / Nexperia | 0.05 | 0.05 | Gate driver for Q1 |
| F1 | 1 | PTC resettable fuse 1.5 A hold, 1812 | MF-MSMF150-2 | Bourns | 0.40 | 0.40 |  |
| D1 | 1 | TVS 5.0 V standoff, SMB | SMBJ5.0A | Littelfuse | 0.30 | 0.30 | Clamps bus transients below the XC330's 6 V maximum |
| C2 | 1 | 470 µF 10 V low-ESR electrolytic, Ø6.3 mm | EEU-FR1A471 (or equiv.) | Panasonic | 0.35 | 0.35 | Bulk reservoir at the servo |
| C3 | 1 | 10 µF 16 V X5R, 0805 | GRM21BR61C106KE15L | Murata | 0.10 | 0.10 |  |
| C1 | 1 | 1 µF 16 V X7R, 0805 | generic | any | 0.05 | 0.05 | Q1 soft-start |
| C4,C5,C6,C7 | 4 | 100 nF 50 V X7R, 0805 | generic | any | 0.02 | 0.08 | decoupling, VSENSE filter, button filters |
| R1,R2,R5,R6 | 4 | 10 kΩ 1 %, 0805 | generic | any | 0.01 | 0.04 |  |
| R3 | 1 | 4.7 kΩ, 0805 | generic | any | 0.01 | 0.01 |  |
| R4,R10,R11 | 3 | 100 kΩ 1 %, 0805 | generic | any | 0.01 | 0.03 |  |
| R7 | 1 | 22 Ω, 0805 | generic | any | 0.01 | 0.01 | DXL line damping |
| R8,R9 | 2 | 2.2 kΩ, 0805 | generic | any | 0.01 | 0.02 | 1 MHz I²C pull-ups |
| SW1,SW2 | 2 | Omron D2F-01 micro switch | D2F-01 | Omron via Digi-Key | 1.60 | 3.20 | Thumb buttons A and B |
| J1,J2 | 2 | JST-EH 3-pin header, 2.5 mm | B3B-EH-A | JST | 0.15 | 0.30 | Plus EHR-3 housings and SEH-001T-P0.6 crimps for the J6 lead |
| PCB1 | 1 | Perfboard 0.1" cut to 20 × 44 mm + MSOP-8 and 2× SOT-23 adapters | generic | any | 3.00 | 3.00 | v0 build; a 2-layer PCB is a drop-in later |
| B1 | 1 | Deep-groove bearing 6700ZZ (10 × 15 × 4) | 6700ZZ | any bearing supplier | 1.20 | 1.20 | Lever hub |
| B2 | 1 | Bearing MR63ZZ (3 × 6 × 2.5) | MR63ZZ | any bearing supplier | 0.60 | 0.60 | Pilot for the disc pin |
| PIN1 | 1 | Dowel pin Ø3 × 8 mm, h6, hardened | ISO 8734 3×8 | McMaster / Misumi | 0.20 | 0.20 | Press + Loctite 638 into the drive disc |
| SPR1 | 1 | Compression spring: music wire Ø0.9, OD 5.5, L0 15.0, 8.5 active / 10.5 total coils, closed & ground (≈ 7.9 N/mm) | custom or nearest stock | Lee Spring / Century Spring | 1.50 | 1.50 | Rate is calibrated in place (k_theta); a ±15 % stock substitute is fine |
| HW1 | 9 | M2.5 × 4 heat-set insert (Ø3.6 bore) | generic (e.g. Ruthex RX-M2.5x4) | any | 0.08 | 0.72 | 5 clamshell + 4 mount |
| HW2 | 3 | M2 × 3 heat-set insert (Ø3.2 bore) | generic | any | 0.08 | 0.24 | 2 encoder cover + 1 blade |
| HW3 | 5 | M2.5 × 16 socket head cap screw | ISO 4762 | any | 0.10 | 0.50 | clamshell |
| HW4 | 4 | M2.5 × 8 socket head cap screw | ISO 4762 | any | 0.08 | 0.32 | housing → mount adapter |
| HW5 | 4 | M2 × 4 button head screw | ISO 7380 | any | 0.08 | 0.32 | drive disc → XC330 horn |
| HW6 | 7 | M2 × 6 socket/pan head screw | ISO 4762 | any | 0.06 | 0.42 | encoder cover (2), blade (1), adapter → J6 horn (4) |
| CBL1 | 1 | USB-C cable, high-flex silicone, 1.5–2 m | generic | any | 9.00 | 9.00 | HGM → station USB hub; route along the leader arm |
| FIL1 | 75 | PETG filament (g), plus 2 g TPU 95A for button caps | generic | any | 0.03 | 1.88 | printed parts at 0.8 effective density |
| U3 | 1 | DRV2605L haptic driver module (I²C, LRA closed-loop auto-resonance) — v1.1 | Adafruit 2305 (DRV2605L) | Adafruit / Digi-Key 1528-1375-ND | 7.95 | 7.95 | v1.1. Or a bare DRV2605LDGSR (MSOP-10) on the protoboard. Wire VIN and EN to 3V3. |
| M2 | 1 | Coin LRA Ø8 × 3.2 mm, ~235 Hz, 2.0 Vrms | VG0832012L (VERIFY) or equiv. Ø8 coin LRA | Vybronics / Digi-Key | 2.50 | 2.50 | v1.1. In the blade pocket on 0.25 mm VHB/acrylic tape; firmware auto-calibrates at boot |
| R12,R13 | 2 | 4.7 kΩ, 0805 | generic | any | 0.01 | 0.02 | v1.1 haptic I²C pull-ups (400 kHz) |
| C8 | 1 | 10 µF 10 V X5R, 0805 | generic | any | 0.05 | 0.05 | v1.1 bulk at the DRV2605L module |
| W1 | 1 | 2 × 30 AWG silicone wire, 0.25 m each | generic | any | 0.50 | 0.50 | v1.1 LRA leads: pocket → blade groove → pivot groove → clip post → board |
| TAPE1 | 1 | VHB / acrylic foam tape 0.25 mm, Ø8 disc | 3M 4910 (or 9473 transfer tape) | any | 0.10 | 0.10 | v1.1 LRA mounting |
| FIL2 | 1 | TPU 95A filament (g) for the blade skin | generic | any | 0.05 | 0.05 | v1.1 blade_skin, 1.0 mm |
| | | **Section total** | | | | **86.95** | |

## FGS fingertip sensor (per gripper - order x2)

| Ref | Qty | Part | MPN | Supplier | Unit $ | Line $ | Notes |
|---|---:|---|---|---|---:|---:|---|
| FGS-F | 2 | fgs_finger (both fingers are the same part) | fgs_finger.step | CNC shop with wire EDM | 90.00 | 180.00 | 7075-T6 plate 12 mm; flexure profile wire-EDM (beams 2.20 ±0.01); see fingertip-sensor.md |
| FGS-P | 2 | fgs_pad, TPU 85A print (or cast silicone 30A) | fgs_pad.stl | print | 0.10 | 0.20 | bond with CA + polyolefin primer (Loctite 406 + 770) |
| FGS-C | 2 | fgs_gauge_cover, PETG print | fgs_gauge_cover.stl | print | 0.10 | 0.20 | 4 × M2 × 6 screws |
| FGS-CL | 2 | fgs_cable_clip, PETG print | fgs_cable_clip.stl | print | 0.05 | 0.10 | 1 × M2 × 6 screw |
| FGS-E | 1 | fgs_enclosure_base + fgs_enclosure_lid + fgs_clamp, PETG print | *.stl | print | 0.60 | 0.60 | clamps on the Ø57 motor can |
| SG1-SG8 | 12 | Strain gauge 350 Ω, 3 mm grid, single (8 + 4 spare) | BF350-3AA (VERIFY gauge factor of the lot) | AliExpress / gauge vendor | 0.40 | 4.80 | 4 per finger on the rear-beam back face, full bridge |
| ADH1 | 1 | Strain-gauge cyanoacrylate kit | Kyowa CC-33A or Micro-Measurements M-Bond 200 | gauge vendor | 25.00 | 25.00 | with surface prep: 400-grit, conditioner/neutraliser or IPA |
| TERM1 | 1 | Gauge solder terminals (pads) + 36 AWG enamelled wire | generic | gauge vendor | 6.00 | 6.00 | one terminal pad per finger near the cable channel |
| COAT1 | 1 | Protective coating for the gauges | Dow 3140 RTV or M-Coat A | any | 15.00 | 15.00 | thin layer; keep it off the beam faces outside the gauges |
| CBL2 | 2 | 4-core shielded high-flex cable, 28 AWG, Ø ≤ 3 mm, 0.5 m | generic (e.g. PUR drag-chain 4 × 0.08 mm²) | any | 3.00 | 6.00 | finger → enclosure, with a service loop for the 47.5 mm stroke |
| U4 | 1 | Seeed Studio XIAO RP2040 | 102010428 | Seeed / Digi-Key | 5.40 | 5.40 | USB-C to the station |
| U5 | 1 | ADS131M02 2-ch 24-bit simultaneous ΔΣ ADC, TSSOP-20 | ADS131M02IPWR | TI / Digi-Key | 4.20 | 4.20 | on a TSSOP-20 adapter for a protoboard build; a 2-layer PCB is better |
| U6 | 1 | Low-noise LDO 3.3 V 300 mA (AVDD) | TPS7A2033PDBVR | TI | 0.60 | 0.60 | from 5 V VBUS |
| U7 | 1 | Low-noise LDO 1.8 V 300 mA (bridge excitation) | TPS7A2018PDBVR | TI | 0.60 | 0.60 | EN on D1; 1.8 V keeps the inputs inside AVDD − 1.8 V at PGA 128 |
| Y1 | 1 | 8.192 MHz 3.3 V CMOS oscillator, 2.5 × 2.0 mm | ECS-2520MV-081.9-BN-TR (VERIFY) | ECS / Digi-Key | 1.20 | 1.20 | ADC CLKIN |
| R20-R23 | 4 | 1 kΩ 0.1 % thin film, 0805 | ERA-6AEB102V (or equiv.) | Panasonic | 0.30 | 1.20 | input RC filter, one per leg |
| C20-C21 | 2 | 10 nF C0G 50 V, 0805 | generic | any | 0.05 | 0.10 | differential filter caps (≈ 7.6 kHz) |
| C22-C25 | 4 | 1 nF C0G 50 V, 0805 | generic | any | 0.03 | 0.12 | common-mode filter caps |
| C26-C33 | 8 | 1 µF X7R + 100 nF X7R (decoupling, LDO in/out), 0805 | generic | any | 0.05 | 0.40 | per datasheets; CAP pin 220 nF |
| C34 | 1 | 220 nF X7R, 0805 | generic | any | 0.05 | 0.05 | ADS131M02 CAP pin |
| R24-R25 | 2 | 10 kΩ / 100 kΩ, 0805 | generic | any | 0.01 | 0.02 | /SYNC_RESET pull-up; excitation EN pull-down |
| J20-J21 | 2 | JST-SH 4-pin header + housings/crimps | SM04B-SRSS-TB | JST | 0.60 | 1.20 | bridge A (left jaw), bridge B (right jaw) |
| PCB2 | 1 | Protoboard 30 × 26 mm + TSSOP-20 adapter, or 2-layer PCB | generic | any | 4.00 | 4.00 | keep the analog inputs short; copper ground pour |
| HW7 | 12 | M2 × 6 socket head cap screw | ISO 4762 | any | 0.06 | 0.72 | covers (8), clips (2), board (2, self-tapping) |
| HW8 | 2 | M3 × 12 socket head cap screw + M3 nut | ISO 4762 / ISO 4032 | any | 0.10 | 0.20 | enclosure clamp |
| HW9 | 4 | M4 SHCS (stock gripper screws, reused) | reuse | — | 0.00 | 0.00 | 2 per finger; 5 mm grip under the head as stock |
| CBL3 | 1 | USB-C cable, high-flex, 2 m | generic | any | 9.00 | 9.00 | enclosure → station USB hub, along the follower arm |
| | | **Section total** | | | | **266.91** | |

## Station (one-time)

| Ref | Qty | Part | MPN | Supplier | Unit $ | Line $ | Notes |
|---|---:|---|---|---|---:|---:|---|
| K1-K8 | 1 | Numato Lab 8-Channel USB Relay Module (USB CDC; ASCII commands; GPIO inputs) | 8 Channel USB Relay Module | numato.com | 45.00 | 45.00 | K1/K2 follower SSR control; K3/K4 leader 5 V; GPIO0 E-stop sense. Ethernet alternative: Waveshare Modbus POE ETH Relay |
| SSR1-2 | 2 | DC solid-state relay, 3.5–32 VDC control, 1–100 VDC 20 A load | D1D20 | Sensata Crydom | 55.00 | 110.00 | Mount on a small heatsink; one per follower 24 V line |
| HS1-2 | 2 | Heatsink for panel SSR | HS301 (or equiv.) | Crydom | 12.00 | 24.00 |  |
| ESTOP1 | 1 | Emergency stop, 40 mm mushroom, twist-release, in yellow enclosure, 3 contact blocks (NC1, NC2, NC3) | e.g. Schneider XB5AS8442 + 2× ZBE102 | Schneider / Automation Direct | 45.00 | 45.00 | Must be NC contacts; IEC 60947-5-5 direct-opening action |
| FL/FR | 2 | ATO blade fuse 10 A + inline holder | generic | any | 3.00 | 6.00 | Follower 24 V lines |
| FC | 2 | ATO blade fuse 0.5 A + holder | generic | any | 3.00 | 6.00 | SSR control loops |
| DL/DR | 2 | TVS 28 V standoff, SMC 3 kW | SMDJ28A | Littelfuse | 1.20 | 2.40 | Across each follower supply input |
| PSU-LD | 2 | 5 V 6 A desktop supply (one per leader arm) | GST40A05-P1J | Mean Well | 18.00 | 36.00 | Feeds the U2D2 power hub; covers 6× XL330 + HGM servo |
| FLD | 2 | 5 A fuse + holder | generic | any | 3.00 | 6.00 | Leader 5 V lines |
| HUB1 | 1 | Powered USB 2.0/3.0 hub, 7-port, external supply | generic | any | 35.00 | 35.00 | Arm-side devices (CANable ×2, U2D2 ×2, HGM ×2) |
| R-ES | 1 | 10 kΩ pull-up resistor | generic | any | 0.01 | 0.01 | GPIO0 E-stop sense |
| CAM1-3 | 3 | UVC USB camera, MJPEG 640×480 @ 30 fps (global-shutter preferred for wrists) | e.g. Arducam OV9782 global-shutter UVC (wrists) + any 1080p UVC (overhead) | Arducam / any | 40.00 | 120.00 | The station also supports Intel RealSense D405/D435 via pyrealsense2 |
| WIRE | 1 | 16 AWG silicone wire (24 V), 22 AWG (5 V), ferrules, DIN rail + terminal blocks | generic | any | 25.00 | 25.00 |  |
| | | **Section total** | | | | **460.41** | |

## Summary

| Item | $ |
|---|---:|
| One Haptic Grip Module | 86.95 |
| Two HGMs (left + right) | 173.91 |
| One fingertip sensor set (FGS, one gripper) | 266.91 |
| Two FGS sets (left + right follower) | 533.82 |
| Station power, safety and cameras (one-time) | 460.41 |
| **Total for one bimanual station** (excluding the YAM arms, leader arms, PC) | **1168.14** |
