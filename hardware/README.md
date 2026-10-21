# Hardware: Haptic Grip Module (HGM), fingertip sensor (FGS) and station electrical

Building it? Start at [docs/hardware/README.md](../docs/hardware/README.md).

```
hardware/
├── cad/                      parametric CadQuery source → STEP / STL / GLB / renders / checks
│   ├── params.py             every key dimension (mm), with VERIFY tags on vendor dimensions
│   ├── parts/                one module per part: housing, lever (+ blade), drive_disc,
│   │                         encoder_cover, button_cap, mount_adapter, purchased, wrist (context)
│   ├── assembly.py           places all parts for a trigger angle φ and spring deflection δ
│   ├── checks.py             interference sweep, stop proofs, clearances, wall thickness, mass, spring
│   ├── build.py              python hardware/cad/build.py  (--quick, --no-render, --no-checks)
│   ├── out/                  step/, stl/ (print-oriented), hgm_assembly.step/.glb, renders/, checks.md
│   ├── viewer/index.html     interactive 3D viewer (explode, φ, δ, x-ray; GLB embedded)
│   └── fgs/                  follower fingertip sensor: fgs_params.py, fgs_parts.py, fgs_fea.py (2D FEA),
│                             fgs_build.py → out/ (step/, stl/, fgs_assembly.step, renders/, checks.md, fea.json)
├── electronics/
│   ├── src/                  schemdraw / matplotlib sources for every sheet
│   ├── out/                  hgm_1_power, hgm_2_dxl, hgm_3_mcu, station_power, usb_can_topology,
│   │                         protoboard_layout  (SVG + PNG)
│   ├── bom.csv               single source of truth for the BOM (docs/hardware/bom.md is generated)
│   └── pinout.md             XIAO pin map, connectors, netlist, Numato channel map
└── firmware/
    ├── common/hgm_protocol/  shared wire-protocol codec (HGM and FGS), host-testable
    ├── haptic_grip/          HGM PlatformIO project (Seeed XIAO RP2040, arduino-pico core)
    │   ├── src/              main, control law, cues + DRV2605L (v1.1), Dynamixel 2.0, AS5600, params
    │   └── test/native/      host-side tests: protocol vectors, control law vs. plant, cues, LRA isolation, loop budget
    ├── fingertip/            FGS PlatformIO project: ADS131M02 driver, fixed-point DSP, two-core sampling
    │   └── test/native/      host-side tests: DSP vs float reference, noise, slip, tare, params, ADC codec
    └── tools/
        ├── gen_vectors.py    regenerates tests/vectors/haptic_protocol.json
        └── hgm_console.py    bench console (ping, live telemetry, render/position, tare, params)
```

## Quick start

```bash
pip install cadquery pyvista trimesh rtree schemdraw matplotlib pyserial
python hardware/cad/build.py                      # ~10 min: exports, renders, design checks
make -C hardware/firmware/haptic_grip/test/native  # HGM firmware unit tests on the host
make -C hardware/firmware/fingertip/test/native    # FGS firmware unit tests
I2RT_PATH=<i2rt checkout> python hardware/cad/fgs/fgs_build.py   # FGS CAD, checks, FEA
cd hardware/firmware/haptic_grip && pio run -t upload
python hardware/firmware/tools/hgm_console.py /dev/hgm_left
```

## Documents

* [Design report](../docs/hardware/haptic-trigger.md): requirements, trade study, spring
  and stiffness calculations, control and stability, calibration, failure modes,
  verification
* [Electronics](../docs/hardware/electronics.md): HGM schematic walk-through, station
  power and E-stop, USB/CAN topology, grounding and cable routing
* [Fingertip sensor](../docs/hardware/fingertip-sensor.md): trade study, flexure FEA,
  noise, calibration with weights, manufacturing
* [Assembly guide](../docs/hardware/assembly-guide.md)
* [Bill of materials](../docs/hardware/bom.md)
* [Wire protocol](../docs/protocol/haptic-protocol.md)
