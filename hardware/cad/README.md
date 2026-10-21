# CAD

Every model is ready to open: **STEP** for SolidWorks, Fusion, Onshape, FreeCAD, Creo or
Inventor, **STL** for printing, plus renders and an interactive 3D viewer. The `.py` files
are the parametric source the models are generated from; you only need them to change a
dimension.

## Where the files are

### Haptic grip trigger (leader handle), 2 per station

| What | File |
|---|---|
| Full assembly (STEP) | [`out/hgm_assembly.step`](out/hgm_assembly.step) |
| Individual parts (STEP, assembly frame) | [`out/step/`](out/step/): housing halves, lever, blade, blade skin, drive disc, encoder cover, button caps, mount adapter |
| Print-ready parts (STL, already in print orientation) | [`out/stl/`](out/stl/), with orientation and settings in [`out/print_table.json`](out/print_table.json) |
| Renders | [`out/renders/`](out/renders/): assembly, x-ray, exploded, spring-pack sections, travel, placement on the leader wrist, print layout |
| Interactive 3D viewer (explode, hide parts) | [`viewer/index.html`](viewer/index.html): download and open in a browser |
| 3D model for web/AR (GLB) | [`out/hgm_assembly.glb`](out/hgm_assembly.glb) |
| Design checks: interference, clearances, spring stress, wall thickness, mass | [`out/checks.md`](out/checks.md) |

### Force-sensing fingertips (follower gripper), 1 set per gripper

| What | File |
|---|---|
| Full assembly on the stock gripper (STEP) | [`fgs/out/fgs_assembly.step`](fgs/out/fgs_assembly.step) |
| Individual parts (STEP) | [`fgs/out/step/`](fgs/out/step/): finger (machined 7075-T6), pad, gauge cover, clamp, cable clip, enclosure base and lid |
| Parts as STL (printable parts; the finger STL is for reference or a printed fit-check) | [`fgs/out/stl/`](fgs/out/stl/) |
| Renders | [`fgs/out/renders/`](fgs/out/renders/): finger, finger front, on the gripper, FEA stress plot |
| Design checks and FEA results | [`fgs/out/checks.md`](fgs/out/checks.md), [`fgs/out/fea.json`](fgs/out/fea.json) |

Dimensions, tolerances, materials and assembly order:
[docs/hardware/README.md](../../docs/hardware/README.md) (start here),
[haptic-trigger.md](../../docs/hardware/haptic-trigger.md),
[fingertip-sensor.md](../../docs/hardware/fingertip-sensor.md),
[assembly-guide.md](../../docs/hardware/assembly-guide.md). Circuits are in
[`../electronics/`](../electronics/).

## Changing the design

The models are fully parametric (CadQuery). Change dimensions in one file, then rebuild:

```bash
pip install cadquery pyvista trimesh rtree      # Python 3.10–3.13
python hardware/cad/build.py                    # trigger: STEP/STL, renders, design checks (~10 min)
python hardware/cad/build.py --quick            # trigger: 2×2 motion grid only
python hardware/cad/fgs/fgs_build.py            # fingertips: STEP/STL, renders, checks
```

* Trigger dimensions live in **`params.py`**, fingertip dimensions in **`fgs/fgs_params.py`**.
  Lines tagged `VERIFY` depend on vendor drawings or your leader arm; confirm them first.
* Each trigger part is a module in `parts/` that returns a CadQuery `Workplane` in the
  shared frame (Y = pivot axis, X forward, Z up).
* `assembly.parts(phi, delta)` places everything for a trigger angle φ (0 = open, 30° =
  squeezed) and a spring deflection δ (0 = preload, 13.2° = overload rim).
* `checks.py` proves the trigger design: a full-motion interference sweep, hard-stop
  proofs, minimum clearances, spring solid-height margin and stress, mass budget and
  ray-cast wall thickness. `fgs/fgs_fea.py` runs the fingertip flexure FEA.
* STEP files in `out/step/` are in the assembly frame, for editing; STL files in `out/stl/`
  are rotated for printing.
