# HGM CAD (CadQuery, fully parametric)

```bash
pip install cadquery pyvista trimesh rtree      # Python 3.10–3.13
python hardware/cad/build.py                    # exports, renders, design checks (~10 min)
python hardware/cad/build.py --quick            # 2×2 motion grid only
```

* Change dimensions in **`params.py`** only. Lines tagged `VERIFY` depend on vendor
  drawings or your leader arm.
* Each part is a module in `parts/` that returns a CadQuery `Workplane` in the shared HGM
  frame (Y = pivot axis, X forward, Z up).
* `assembly.parts(phi, delta)` places everything for a trigger angle φ (0 = open, 30° =
  squeezed) and a spring deflection δ (0 = preload, 13.2° = overload rim).
* `checks.py` proves the design. It runs a full-motion interference sweep, hard-stop
  proofs, minimum clearances, spring solid-height margin and stress, mass budget and
  ray-cast wall thickness. Results go to `out/checks.md`.
* `out/stl/` STLs are **already in print orientation** (see `out/print_table.json`), and
  `out/step/` holds the same parts in the assembly frame for editing in any CAD package.
* `viewer/index.html` is a self-contained interactive viewer. The model is embedded;
  three.js loads from jsDelivr.

| Render | |
|---|---|
| `assembly.png`, `assembly_back.png` | encoder side; servo side with buttons and mount |
| `assembly_xray.png` | housing transparent |
| `exploded.png` | assembly order |
| `section_sea_rest.png`, `section_sea_loaded.png` | cut through the spring pack at 0 N and 12 N |
| `travel.png` | open vs squeezed |
| `placement.png` | on a simplified leader-arm wrist (J5 pitch + J6 roll) |
| `print_layout.png` | all printed parts in print orientation |
