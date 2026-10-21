# Hardware: start here (mechanical and electronics build)

This page is the entry point for building the station's two hardware modules. Each module is
one per arm, so build two of each.

| Module | What it does | Where it goes |
|---|---|---|
| **HGM v1.1** (Haptic Grip Module) | Series-elastic trigger that pushes back with the follower's grip force; an LRA in the blade plays contact and slip cues | on each **leader** arm's J6 |
| **FGS** (follower fingertip sensor) | Replacement fingers for the I2RT `linear_4310` gripper that measure the jaw force on each pad (0 to the full gripper force) and a 60–400 Hz slip band | on each **follower** gripper |

Both are Seeed XIAO RP2040 USB devices that speak the same protocol
([haptic-protocol.md](../protocol/haptic-protocol.md)). The station tells them apart by
`INFO.hw_rev`: `0x02` is an HGM v1.1, `0x11` is an FGS.

## 1. Read first

* HGM: [design report](haptic-trigger.md) (§12 covers v1.1)
* FGS: [design report](fingertip-sensor.md)
* [Electronics](electronics.md), [pinouts](../../hardware/electronics/pinout.md)
* [Bill of materials](bom.md): one generated table, with a section per module

## 2. Generate the CAD outputs (optional, they are checked in)

```bash
pip install cadquery pyvista trimesh rtree manifold3d scikit-fem triangle schemdraw matplotlib
python hardware/cad/build.py                                       # HGM: STEP/STL, renders, checks (~10 min)
I2RT_PATH=<i2rt checkout> python hardware/cad/fgs/fgs_build.py     # FGS: STEP/STL, renders, checks, FEA (~4 min)
```

The FGS build checks interference against the stock gripper meshes from the
[i2rt](https://github.com/i2rt-robotics/i2rt) repository. Without `I2RT_PATH` it skips
those checks and says so.

## 3. Order and print

| Step | HGM (×2) | FGS (×2) |
|---|---|---|
| **Machine** (lead time, start first) | — | `fgs_finger` × 2 per gripper (7075-T6, CNC + wire EDM): send `hardware/cad/fgs/out/step/fgs_finger.step` and [fingertip-sensor.md §10](fingertip-sensor.md#10-manufacturing-and-assembly) |
| **Buy** | [bom.md](bom.md) "HGM" section: XC330 servo, XIAO, AS5600, bearings, spring, switches; v1.1 adds the DRV2605L module and the Ø8 LRA | [bom.md](bom.md) "FGS" section: XIAO, ADS131M02, LDOs, oscillator, 8 strain gauges + spares, gauge adhesive, cables |
| **Print** | `hardware/cad/out/stl/*.stl`, PETG; `blade_skin` in TPU 95A ([haptic-trigger.md §9](haptic-trigger.md#9-printing)) | `hardware/cad/fgs/out/stl/`: `fgs_pad` in TPU 85A; `fgs_gauge_cover`, `fgs_cable_clip`, `fgs_enclosure_*` and `fgs_clamp` in PETG |

## 4. Assemble (in this order)

1. **Electronics, on the bench.** Build the HGM board ([assembly-guide.md §1](assembly-guide.md#1-electronics-protoboard-v0))
   and the FGS board ([fingertip-sensor.md §7](fingertip-sensor.md#7-electronics)). Flash
   the prebuilt UF2s: hold BOOT, plug in, and drag the file onto the drive.
   * HGM v1.1: `hardware/firmware/haptic_grip/prebuilt/hgm-fw-1.1.0-xiao_rp2040.uf2`.
     Use `hgm-fw-1.0.0` on v1.0 boards, which have the old pin map.
   * FGS: `hardware/firmware/fingertip/prebuilt/fgs-fw-1.0.0-xiao_rp2040.uf2`.
2. **HGM mechanics.** Follow [assembly-guide.md §2](assembly-guide.md#2-mechanics),
   including the v1.1 LRA steps.
3. **FGS fingers.** Bond and wire the gauges, coat them, and fit the pad, cover and clip
   ([fingertip-sensor.md §10](fingertip-sensor.md#10-manufacturing-and-assembly)). Then
   calibrate each finger with weights ([§9](fingertip-sensor.md#9-calibration-with-known-weights)).
4. **Install.** Mount the HGMs on the leader J6 horns. Swap the follower fingers (stock
   M4 screws, from below), clamp the FGS enclosure on the motor can, and route the cables
   with their service loops.
5. **Bring-up.** Plug everything into the station hub, then run the trigger calibration
   wizard. Check the FGS live force and slip band in **Diagnostics**.

## 5. Drawings

The STEP files carry the full geometry. The machined part's critical dimensions are listed
in [fingertip-sensor.md §10](fingertip-sensor.md#10-manufacturing-and-assembly). There are
no dimensioned 2D drawings yet. If your shop needs one, generate it from the STEP file in
your CAD package, using those tolerances.

## 6. Where things are

```
hardware/cad/              HGM CadQuery source; out/ = STEP, STL, renders, checks.md
hardware/cad/fgs/          FGS CadQuery source, FEA; out/ = STEP, STL, renders, checks.md, fea.json
hardware/electronics/      schematic sources and outputs (out/), bom.csv, pinout.md
hardware/firmware/         haptic_grip/ (HGM), fingertip/ (FGS), common/hgm_protocol/ (shared codec), tools/
docs/hardware/             this page, design reports, electronics, assembly guide, BOM
```
