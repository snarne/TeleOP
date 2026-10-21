#!/usr/bin/env python3
"""Build the Haptic Grip Module: export STEP/STL/GLB, run the design checks, render figures.

    python hardware/cad/build.py              # everything (about 10 min, most of it the checks)
    python hardware/cad/build.py --quick      # exports + renders, checks reduced to the 4 extremes
    python hardware/cad/build.py --no-render

Outputs land in hardware/cad/out/:
    step/<part>.step          assembly frame (mm)
    stl/<part>.stl            print orientation, sitting on z = 0
    hgm_assembly.step         full assembly, coloured
    hgm_assembly.glb          per-part meshes for the web viewer
    renders/*.png
    checks.json / checks.md
and hardware/cad/viewer/index.html (GLB embedded, opens offline apart from the three.js CDN).
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cadquery as cq  # noqa: E402
import numpy as np  # noqa: E402

import params as P  # noqa: E402
from assembly import exploded, parts  # noqa: E402

OUT = os.path.join(HERE, "out")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _shape(w: cq.Workplane) -> cq.Shape:
    vals = [v for v in w.vals() if isinstance(v, cq.Shape)]
    return vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)


# --------------------------------------------------------------------------- exports


def export_parts(ps) -> dict:
    os.makedirs(os.path.join(OUT, "step"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "stl"), exist_ok=True)
    table = {}
    for p in ps:
        if p.group != "printed":
            continue
        shp = p.shape
        cq.exporters.export(shp, os.path.join(OUT, "step", f"{p.name}.step"))
        axis, deg = p.print_rot
        pr = shp.rotate((0, 0, 0), axis, deg) if deg else shp
        bb = _shape(pr).BoundingBox()
        pr = pr.translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
        cq.exporters.export(pr, os.path.join(OUT, "stl", f"{p.name}.stl"), tolerance=0.02, angularTolerance=0.1)
        bb2 = _shape(pr).BoundingBox()
        table[p.name] = {"material": p.material, "orientation": p.note,
                         "print_bbox_mm": [round(bb2.xlen, 1), round(bb2.ylen, 1), round(bb2.zlen, 1)]}
    return table


def export_assembly(ps) -> None:
    from render import PALETTE
    assy = cq.Assembly(name="HGM")
    for p in ps:
        hexc = PALETTE[p.color].lstrip("#")
        rgb = tuple(int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))
        assy.add(p.shape, name=p.name, color=cq.Color(*rgb))
    assy.export(os.path.join(OUT, "hgm_assembly.step"))


def export_glb(ps) -> str:
    import trimesh
    from render import PALETTE, to_mesh
    scene = trimesh.Scene()
    for p in ps:
        m = to_mesh(p.shape, tol=0.08, angular=0.3)
        faces = m.faces.reshape(-1, 4)[:, 1:]
        tm = trimesh.Trimesh(vertices=np.asarray(m.points), faces=faces, process=False)
        hexc = PALETTE[p.color].lstrip("#")
        rgba = [int(hexc[i:i + 2], 16) for i in (0, 2, 4)] + [255]
        mat = trimesh.visual.material.PBRMaterial(name=p.name, baseColorFactor=rgba,
                                                  metallicFactor=0.6 if p.color in ("steel", "spring", "horn") else 0.05,
                                                  roughnessFactor=0.35 if p.color in ("steel", "spring") else 0.55)
        tm.visual = trimesh.visual.TextureVisuals(material=mat)
        scene.add_geometry(tm, node_name=p.name, geom_name=p.name)
    path = os.path.join(OUT, "hgm_assembly.glb")
    scene.export(path)
    return path


def write_viewer(glb_path: str, ps) -> None:
    tpl = open(os.path.join(HERE, "viewer", "template.html"), encoding="utf-8").read()
    b64 = base64.b64encode(open(glb_path, "rb").read()).decode("ascii")
    meta = {p.name: {"group": p.group, "explode": p.explode, "material": p.material or "",
                     "label": p.name.replace("_", " ")} for p in ps}
    html = tpl.replace("__GLB_BASE64__", b64).replace("__PART_META__", json.dumps(meta))
    with open(os.path.join(HERE, "viewer", "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


# --------------------------------------------------------------------------- renders


def section(ps, y_cut: float, keep_below: bool = True):
    big = 400
    if keep_below:
        box = cq.Workplane("XY").box(big, big, big).translate((0, y_cut - big / 2, 0))
    else:
        box = cq.Workplane("XY").box(big, big, big).translate((0, y_cut + big / 2, 0))
    out = []
    for p in ps:
        try:
            s = p.shape.intersect(box)
            if s.vals() and _shape(s).Volume() > 1e-3:
                out.append((p, s))
        except Exception:
            pass
    return out


def renders(quick: bool = False) -> None:
    from render import PALETTE, render
    rdir = os.path.join(OUT, "renders")
    os.makedirs(rdir, exist_ok=True)
    cam_iso = [(190, 265, 70), (0, -3, -46), (0, 0, 1)]
    cam_iso_back = [(-210, -250, 80), (0, -3, -46), (0, 0, 1)]

    log("render: assembly")
    ps = parts(6.0, 2.0)
    render([(p.shape, PALETTE[p.color], 1.0) for p in ps], os.path.join(rdir, "assembly.png"),
           camera=cam_iso, title="Haptic Grip Module: assembly", zoom=1.12)
    render([(p.shape, PALETTE[p.color], 1.0) for p in ps], os.path.join(rdir, "assembly_back.png"),
           camera=cam_iso_back, title="Haptic Grip Module: servo side, thumb buttons, mount", zoom=1.12)

    log("render: x-ray")
    render([(p.shape, PALETTE[p.color], 0.18 if p.name.startswith("housing") or p.name == "encoder_cover" else 1.0)
            for p in ps], os.path.join(rdir, "assembly_xray.png"), camera=cam_iso, edges=True,
           title="X-ray: servo, SEA pocket, lever, electronics bay", zoom=1.12)

    log("render: exploded")
    ex = exploded(parts(0.0, 0.0), 1.0)
    render([(p.shape, PALETTE[p.color], 1.0) for p in ex], os.path.join(rdir, "exploded.png"),
           camera=[(260, 330, 150), (0, 5, -35), (0, 0, 1)], size=(1800, 1350), title="Exploded view")

    log("render: SEA section")
    for name, phi, delta in (("section_sea_rest", 0.0, 0.0), ("section_sea_loaded", 15.0, 9.0)):
        sec = section(parts(phi, delta), P.SPRING_Y, keep_below=True)
        items = [(s, PALETTE[p.color], 1.0) for p, s in sec if p.name not in ("encoder_cover", "as5600_board")]
        f = P.finger_force_n(delta)
        render(items, os.path.join(rdir, f"{name}.png"),
               camera=[(10, 230, -5), (10, 0, -5), (0, 0, 1)], size=(1500, 1300), zoom=2.2,
               title=f"Section y = {P.SPRING_Y} mm through the spring pack — phi = {phi:.0f} deg, "
                     f"delta = {delta:.1f} deg (spring force at finger ~ {f:.1f} N)")

    log("render: travel overlay")
    items = []
    for phi, op in ((0.0, 1.0), (P.TRAVEL, 0.35)):
        for p in parts(phi, 1.0):
            if p.name in ("lever", "blade"):
                items.append((p.shape, PALETTE["lever"], op))
    for p in parts(0.0, 0.0):
        if p.name in ("housing_servo_half",):
            items.append((p.shape, PALETTE[p.color], 1.0))
    render(items, os.path.join(rdir, "travel.png"), camera=[(10, 260, -30), (-5, 0, -35), (0, 0, 1)],
           size=(1400, 1400), zoom=1.25, title=f"Lever travel 0 deg → {P.TRAVEL:.0f} deg (ghost = squeezed)")

    log("render: placement on leader wrist")
    ps = parts(6.0, 2.0, with_wrist=True)
    render([(p.shape, PALETTE[p.color], 1.0) for p in ps], os.path.join(rdir, "placement.png"),
           camera=[(140, 300, 150), (-40, -3, -25), (0, 0, 1)], size=(1800, 1300),
           title="Placement: HGM on the leader-arm wrist (J5 pitch + J6 roll)")

    log("render: print layout")
    from render import to_mesh  # noqa: F401
    plate = []
    xoff = 0.0
    for p in parts(0.0, 0.0):
        if p.group != "printed":
            continue
        axis, deg = p.print_rot
        pr = p.shape.rotate((0, 0, 0), axis, deg) if deg else p.shape
        bb = _shape(pr).BoundingBox()
        pr = pr.translate((xoff - bb.xmin, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
        xoff += bb.xlen + 8
        plate.append((pr, PALETTE[p.color], 1.0))
    bed = cq.Workplane("XY").box(xoff + 10, 140, 1).translate((xoff / 2 - 4, 0, -0.5))
    plate.append((bed, "#d8dce2", 1.0))
    render(plate, os.path.join(rdir, "print_layout.png"), camera=[(xoff / 2, -1.05 * xoff, 0.75 * xoff), (xoff / 2, 0, 0), (0, 0, 1)],
           size=(1900, 900), title="Print orientation of every printed part (support-free)")


# --------------------------------------------------------------------------- checks


def run_checks(quick: bool) -> dict:
    import checks
    res = {}
    log("checks: spring")
    res["spring"] = checks.spring_check()
    log("checks: mass")
    res["mass"] = checks.mass_budget(parts(0, 0))
    log("checks: stops")
    res["stops"] = checks.stop_verification()
    log("checks: interference sweep")
    if quick:
        res["interference"] = checks.interference_sweep(phis=(0.0, P.TRAVEL), deltas=(0.0, P.DELTA_MAX))
    else:
        res["interference"] = checks.interference_sweep()
    log("checks: clearances")
    res["clearance_mm"] = checks.clearances()
    log("checks: wall thickness")
    res["wall"] = {}
    for n in ("housing_servo_half", "housing_encoder_half", "lever", "blade", "drive_disc", "encoder_cover",
              "mount_adapter", "blade_skin"):
        res["wall"][n] = checks.wall_thickness(os.path.join(OUT, "stl", f"{n}.stl"))
    res["generated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(OUT, "checks.json"), "w") as f:
        json.dump(res, f, indent=2, default=str)
    write_checks_md(res)
    return res


def write_checks_md(res: dict) -> None:
    L = ["# HGM design checks (generated by build.py)", "", f"Generated {res['generated']}.", ""]
    s = res["spring"]
    L += ["## Spring and SEA", "", "| Quantity | Value |", "|---|---|"]
    L += [f"| {k.replace('_', ' ')} | {v} |" for k, v in s.items()]
    m = res["mass"]
    L += ["", "## Mass budget", "", "| Part | Volume cm³ | Mass g |", "|---|---:|---:|"]
    L += [f"| {k} (printed) | {v['volume_cm3']} | {v['mass_g']} |" for k, v in m["printed"].items()]
    L += [f"| {k} | — | {v} |" for k, v in m["purchased"].items()]
    L += [f"| **Total** | | **{m['total_g']}** (target ≤ {m['target_g']}) |"]
    L += ["", "## Hard stops", "", "| Stop | Distance at stop (mm) | Overlap just past (mm³) | OK |", "|---|---:|---:|---|"]
    for k, v in res["stops"].items():
        past = [vv for kk, vv in v.items() if kk.startswith("overlap")][0]
        L.append(f"| {k} | {v['distance_at_stop_mm']} | {past} | {'✅' if v['ok'] else '❌'} |")
    it = res["interference"]
    n_pairs = sum(st["pairs_checked"] for st in it["states"])
    L += ["", "## Interference over the motion range", "",
          f"{len(it['states'])} states (phi × delta grid), {n_pairs} part-pair checks. "
          f"Collisions: **{len(it['collisions'])}**.", ""]
    for c in it["collisions"]:
        L.append(f"- phi={c['phi']} delta={c['delta']}: {c['a']} ↔ {c['b']} {c['volume_mm3']} mm³")
    L += ["", "## Minimum clearance (moving ↔ fixed)", "", "| Pair | mm |", "|---|---:|"]
    L += [f"| {k} | {v} |" for k, v in res["clearance_mm"].items()]
    L += ["", "## Wall thickness (ray-cast on the STL)", "",
          "Opposed-face ray casting (6000 samples per part). Thin samples are listed by location in "
          "docs/hardware/haptic-trigger.md §Verification.", "",
          "| Part | samples | min | p1 | p5 | median | fraction < 1.5 mm |", "|---|---:|---:|---:|---:|---:|---:|"]
    for k, v in res["wall"].items():
        if v:
            L.append(f"| {k} | {v['samples']} | {v['min_mm']} | {v['p1_mm']} | {v['p5_mm']} | {v['median_mm']} | "
                     f"{v['frac_below_1.5']} |")
    with open(os.path.join(OUT, "checks.md"), "w") as f:
        f.write("\n".join(L) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--no-checks", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    log("building parts")
    ps = parts(0.0, 0.0)
    log("exporting parts")
    table = export_parts(ps)
    with open(os.path.join(OUT, "print_table.json"), "w") as f:
        json.dump(table, f, indent=2)
    log("exporting assembly STEP")
    export_assembly(ps)
    log("exporting GLB + viewer")
    glb = export_glb(parts(0.0, 0.0, with_wrist=True))
    write_viewer(glb, parts(0.0, 0.0, with_wrist=True))
    if not a.no_render:
        renders(a.quick)
    if not a.no_checks:
        res = run_checks(a.quick)
        log(f"collisions: {len(res['interference']['collisions'])}, mass {res['mass']['total_g']} g")
    log("done")


if __name__ == "__main__":
    main()
