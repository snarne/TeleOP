#!/usr/bin/env python3
"""Build the FGS (follower fingertip sensor): STEP/STL exports, renders and design checks.

    python hardware/cad/fgs/fgs_build.py                 # exports, renders, checks, FEA (~3 min)
    python hardware/cad/fgs/fgs_build.py --no-fea

The stock-gripper context (placement render, interference against the gripper body and the stock
carriages) needs the i2rt repository: set I2RT_PATH to a checkout of
https://github.com/i2rt-robotics/i2rt (MIT). Without it those checks are skipped and say so.

Outputs in hardware/cad/fgs/out/: step/*.step (part frames), stl/*.stl (print/machining
orientation), fgs_assembly.step, renders/*.png, checks.json, checks.md, fea.json.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))   # hardware/cad: shared render helpers

import cadquery as cq  # noqa: E402
import numpy as np  # noqa: E402

import fgs_params as P  # noqa: E402
import fgs_parts as F  # noqa: E402

OUT = os.path.join(HERE, "out")
T0 = time.time()


def log(m: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {m}", flush=True)


# --------------------------------------------------------------------------- parts
# name: (factory, frame, material, density g/cm³, colour, print/machining note)
PARTS = {
    "fgs_finger": (F.make_finger, "finger", "7075-T6 (CNC + wire EDM)", P.RHO_AL7075, "#a9adb3",
                   "machined; flexure profile wire-EDM through x"),
    "fgs_pad": (F.make_pad, "finger", "TPU 85A", P.RHO_TPU, "#e8742c", "print ridges up, 0.1 mm layers"),
    "fgs_gauge_cover": (F.make_cover, "finger", "PETG", P.RHO_PETG, "#5b6573", "print outer face down"),
    "fgs_cable_clip": (F.make_clip, "finger", "PETG", P.RHO_PETG, "#e8742c", "print flat"),
    "fgs_enclosure_base": (F.make_enclosure_base, "gripper", "PETG", P.RHO_PETG, "#3a3f47", "print open side up"),
    "fgs_enclosure_lid": (F.make_enclosure_lid, "gripper", "PETG", P.RHO_PETG, "#4a515c", "print outer face down"),
    "fgs_clamp": (F.make_clamp, "gripper", "PETG", P.RHO_PETG, "#3a3f47", "print flat (ring axis vertical)"),
}
VISUAL = {
    "gauges": (F.make_gauges, "finger", "#2f7dd1", 0.05),
    "cable": (F.make_cable_stub, "finger", "#111111", 6.0),    # Ø2.8 4-core cable, first 40 mm
    "board": (F.make_board, "gripper", "#1f6e43", 7.0),          # board + XIAO + ADC + passives
}


def shape(w: cq.Workplane) -> cq.Shape:
    vals = [v for v in w.vals() if isinstance(v, cq.Shape)]
    return vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)


def to_gripper(w: cq.Workplane, side: str, q_mm: float) -> cq.Workplane:
    """Interface frame → MuJoCo gripper frame for the left/right finger at opening q (mm per finger)."""
    if side == "left":
        o = P.LEFT_ORIGIN_G
        return w.translate((o[0], o[1] - q_mm, o[2]))
    o = P.RIGHT_ORIGIN_G
    return w.rotate((0, 0, 0), (0, 0, 1), 180).translate((o[0], o[1] + q_mm, o[2]))


# --------------------------------------------------------------------------- stock context
def stock_meshes():
    """gripper body and the two stock tips (trimesh, mm, gripper frame, q = 0), or None."""
    root = os.environ.get("I2RT_PATH", "")
    a = os.path.join(root, "i2rt", "robot_models", "gripper", "linear_4310", "assets")
    if not root or not os.path.isdir(a):
        return None
    import trimesh
    from scipy.spatial.transform import Rotation as R

    def T(pos, q):
        M = np.eye(4)
        w, x, y, z = q
        M[:3, :3] = R.from_quat([x, y, z, w]).as_matrix()
        M[:3, 3] = pos
        return M

    tf = {  # from linear_4310.xml (body pos/quat × geom pos/quat)
        "gripper": T([-0.014, -0.0463995, 0.0731], [1, 0, 0, 0]),
        "tip_left": T([-0.0238981, 0.0450619, -0.0545599], [0.499998, -0.5, -0.5, -0.500002])
        @ T([0.129783, 0.00999321, -0.0914614], [0.499998, 0.5, 0.500002, 0.5]),
        "tip_right": T([0.0238981, -0.0450619, -0.0545599], [0.707105, 0.707108, 0, 0])
        @ T([-0.0379932, 0.129783, 0.00133753], [0.707105, -0.707108, 0, 0]),
    }
    out = {}
    for n, M in tf.items():
        m = trimesh.load(os.path.join(a, f"{n}.stl"))
        m.apply_transform(M)
        m.apply_scale(1000.0)
        out[n] = m
    return out


def to_trimesh(w: cq.Workplane):
    import trimesh
    verts, tris = shape(w).tessellate(0.05, 0.2)
    return trimesh.Trimesh(np.array([(v.x, v.y, v.z) for v in verts]), np.array(tris), process=True)


def overlap(a, b) -> float:
    import manifold3d as mf
    if (a.bounds[1] < b.bounds[0]).any() or (b.bounds[1] < a.bounds[0]).any():
        return 0.0

    def man(m):
        return mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, dtype=np.float32),
                                   tri_verts=np.asarray(m.faces, dtype=np.uint32)))
    try:
        return float((man(a) ^ man(b)).volume())
    except Exception:
        return float("nan")


# --------------------------------------------------------------------------- build
def build(args) -> dict:
    os.makedirs(os.path.join(OUT, "step"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "stl"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "renders"), exist_ok=True)
    log("building parts")
    shapes = {n: f() for n, (f, *_rest) in PARTS.items()}
    vis = {n: f() for n, (f, *_r) in VISUAL.items()}
    res: dict = {"parts": {}}

    log("exporting STEP/STL")
    for n, (f, frame, mat, rho, col, note) in PARTS.items():
        s = shapes[n]
        assert shape(s).isValid(), n
        cq.exporters.export(s, os.path.join(OUT, "step", f"{n}.step"))
        bb = shape(s).BoundingBox()
        st = s.translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
        cq.exporters.export(st, os.path.join(OUT, "stl", f"{n}.stl"), tolerance=0.02, angularTolerance=0.1)
        vol = shape(s).Volume() / 1000
        res["parts"][n] = {"material": mat, "frame": frame, "volume_cm3": round(vol, 3), "mass_g": round(vol * rho, 1),
                           "bbox_mm": [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)], "note": note}

    # assembly STEP: both fingers at q = 20 mm, enclosure on the gripper
    q = 20.0
    assy = cq.Assembly(name="FGS")
    for n, (f, frame, mat, rho, col, note) in PARTS.items():
        rgb = tuple(int(col.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
        if frame == "finger":
            for side in ("left", "right"):
                assy.add(to_gripper(shapes[n], side, q), name=f"{n}_{side}", color=cq.Color(*rgb))
        else:
            assy.add(shapes[n], name=n, color=cq.Color(*rgb))
    assy.export(os.path.join(OUT, "fgs_assembly.step"))

    # ---- mass
    per_finger = sum(res["parts"][n]["mass_g"] for n in ("fgs_finger", "fgs_pad", "fgs_gauge_cover", "fgs_cable_clip"))
    per_finger += VISUAL["gauges"][3] + VISUAL["cable"][3]
    enc = sum(res["parts"][n]["mass_g"] for n in ("fgs_enclosure_base", "fgs_enclosure_lid", "fgs_clamp")) + VISUAL["board"][3]
    res["mass"] = {"per_finger_g": round(per_finger, 1), "stock_finger_below_interface_g": 37.8,
                   "enclosure_and_board_g": round(enc, 1), "added_total_g": round(2 * (per_finger - 37.8) + enc, 1),
                   "note": "stock finger: 27.82 cm³ below the interface × 1.36 g/cm³ implied by the MJCF tip mass"}

    # ---- geometry vs stock
    res["geometry"] = {
        "contact_face_y": P.CONTACT_Y, "tip_z": P.TIP_Z, "pad_xz_mm": [round(P.B - 2 * P.PAD_MARGIN_X, 2),
                                                                      round(P.PAD_Z[0] - P.PAD_Z[1], 2)],
        "pad_centre_z": round(sum(P.PAD_Z) / 2, 2), "beam_mid_z": round(P.BEAM_MID_Z, 2),
        "finger_thickness_at_tip_mm": round(P.CONTACT_Y - (P.NECK_BACK_Y - P.COVER_T), 2),
        "stock_thickness_at_tip_mm": 6.0, "stroke_per_finger_mm": P.STROKE,
    }

    # ---- interference with the stock gripper
    stock = stock_meshes()
    if stock is None:
        res["interference"] = {"skipped": "set I2RT_PATH to an i2rt checkout"}
        log("stock meshes not found: interference vs gripper skipped (set I2RT_PATH)")
    else:
        log("interference vs stock gripper")
        import trimesh
        body = stock["gripper"]
        carr = {s: stock[f"tip_{s}"].slice_plane([0, 0, P.LEFT_ORIGIN_G[2]], [0, 0, 1], cap=True) for s in ("left", "right")}
        stock_overlap_q0 = overlap(stock["tip_left"], stock["tip_right"])
        rows = []
        fparts = ["fgs_finger", "fgs_pad", "fgs_gauge_cover", "fgs_cable_clip"]
        gparts = ["fgs_enclosure_base", "fgs_enclosure_lid", "fgs_clamp"]
        gm = {n: to_trimesh(shapes[n]) for n in gparts}
        gm["board"] = to_trimesh(vis["board"])
        for qq in (0.0, P.STROKE / 2, P.STROKE):
            fm = {}
            for side in ("left", "right"):
                for n in fparts:
                    fm[f"{n}_{side}"] = to_trimesh(to_gripper(shapes[n], side, qq))
                c = carr[side].copy()
                c.apply_translation((0, -qq if side == "left" else qq, 0))
                fm[f"stock_carriage_{side}"] = c
            items = {**fm, **gm, "gripper_body": body}
            names = list(items)
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    a, b = names[i], names[j]
                    if a.startswith("stock_carriage") and b.startswith("stock_carriage"):
                        continue
                    if {a.split("_left")[0].split("_right")[0], b.split("_left")[0].split("_right")[0]} <= set(fparts) and \
                            (a.endswith("left") == b.endswith("left")):
                        continue  # parts of the same finger touch by design (pad on finger, cover on neck)
                    if a in gm and b in gm:
                        continue  # enclosure parts touch each other by design
                    v = overlap(items[a], items[b])
                    if v > 0.05:
                        rows.append({"q_mm": qq, "a": a, "b": b, "overlap_mm3": round(v, 2)})
        expected = [r for r in rows if r["q_mm"] == 0.0 and {"fgs_pad_left", "fgs_pad_right"} == {r["a"], r["b"]}]
        clamp_contact = [r for r in rows if {"gripper_body"} & {r["a"], r["b"]} and ({"fgs_clamp", "fgs_enclosure_base"} & {r["a"], r["b"]})]
        stock_only = [r for r in rows if not (r["a"].startswith("fgs") or r["b"].startswith("fgs") or "board" in (r["a"], r["b"]))]
        other = [r for r in rows if r not in expected and r not in clamp_contact and r not in stock_only]
        rows = [r for r in rows if r not in stock_only]   # stock carriage inside the stock body: MJCF, not ours
        res["interference"] = {"rows": rows, "unexpected": other,
                               "stock_tips_overlap_at_q0_mm3": round(stock_overlap_q0, 1),
                               "note": "at q = 0 the pads meet exactly where the stock tips meet (the MJCF tips "
                                       "overlap at q = 0 too); the real gripper stops on contact"}
        log(f"interference rows {len(rows)}, unexpected {len(other)}")

    # ---- section stresses of the finger body at the ultimate load (analytic, from CAD sections)
    res["sections"] = sections(shapes["fgs_finger"])

    # ---- FEA
    if not args.no_fea:
        log("FEA")
        import fgs_fea
        fea = fgs_fea.run(write=True)
        u = fea["uniform"]
        res["fea"] = {k: v for k, v in u.items() if not k.startswith("profile")}
        res["fea"]["position_sensitivity_pct"] = fea["position_sensitivity_pct"]
        res["fea"]["edge_loads"] = {lc: {"vm_max_beams_MPa": fea[lc]["vm_max_beams_MPa"],
                                         "vm_max_at_yz": fea[lc]["vm_max_at_yz"]} for lc in ("top", "bottom")}
        res["fea"]["convergence"] = fea["convergence"]
        s = P.F_ULT / u["F_N"]
        y, fat = P.YIELD_AL7075, P.FATIGUE_AL7075
        smax_stall = u["vm_max_beams_MPa"] * P.F_STALL / u["F_N"]
        res["strength"] = {
            "vm_peak_at_500N_uniform_MPa": round(u["vm_max_beams_MPa"] * s, 1),
            "safety_on_yield_500N_uniform": round(y / (u["vm_max_beams_MPa"] * s), 2),
            "vm_peak_at_500N_top_edge_MPa": round(fea["top"]["vm_max_beams_MPa"] * s, 1),
            "goodman_480N_repeated_uniform": round(smax_stall / 2 / fat + smax_stall / 2 / 572.0, 2),
        }

    # ---- renders
    renders(shapes, vis, stock)
    with open(os.path.join(OUT, "checks.json"), "w") as f:
        json.dump(res, f, indent=1, default=float)
    write_md(res)
    return res


def sections(finger: cq.Workplane) -> list:
    """Bending stress at the ultimate load from the actual CAD sections (moment about x)."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    out = []
    zc = sum(P.PAD_Z) / 2
    for z in (-9.5, -20.0, -30.0, -40.0, P.NECK_BOTTOM_Z + 0.5, P.NECK_BOTTOM_Z - 2.0):
        sec = finger.section(z) if False else finger.intersect(F.box((-60, 60), (-60, 60), (z - 0.005, z + 0.005)))
        # thin slab → area properties from volume properties / thickness
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape(sec).wrapped, props)
        h = 0.01
        A = props.Mass() / h
        c = props.CentreOfMass()
        M = props.MatrixOfInertia()
        # Ixx about the centroid for the slab ≈ ∫(y² + z²) dV; subtract the z part (h³ term negligible)
        Iyy_area = (M.Value(1, 1) - A * h * (h ** 2) / 12) / h       # ∫ y² dA about the centroid
        bb = shape(sec).BoundingBox()
        cmax = max(c.Y() - bb.ymin, bb.ymax - c.Y())
        Mx = P.F_ULT * (z - zc)  # N·mm
        sigma = abs(Mx) * cmax / Iyy_area
        out.append({"z": round(z, 2), "area_mm2": round(A, 1), "I_mm4": round(Iyy_area, 0),
                    "moment_Nm_at_500N": round(abs(Mx) / 1000, 2), "sigma_MPa": round(sigma, 1)})
    return out


def renders(shapes, vis, stock) -> None:
    from render import render
    rd = os.path.join(OUT, "renders")
    log("render: finger")
    items = [(shapes["fgs_finger"], "#a9adb3", 1.0), (shapes["fgs_pad"], "#e8742c", 1.0),
             (vis["gauges"], "#2f7dd1", 1.0), (shapes["fgs_gauge_cover"], "#5b6573", 0.3),
             (shapes["fgs_cable_clip"], "#e8742c", 1.0), (vis["cable"], "#111111", 1.0)]
    render(items, os.path.join(rd, "fgs_finger.png"), camera=((110, -110, 5), (2, 6, -40), (0, 0, 1)),
           title="FGS finger: 7075 flexure, 4 gauges on the rear beam, TPU pad")
    render([(shapes["fgs_finger"], "#a9adb3", 1.0), (shapes["fgs_pad"], "#e8742c", 1.0)],
           os.path.join(rd, "fgs_finger_front.png"), camera=((90, 120, -20), (2, 8, -45), (0, 0, 1)),
           title="FGS finger, contact side")
    if stock is not None:
        log("render: placement on the gripper")
        q = 25.0
        pl = []
        for side in ("left", "right"):
            for n, col in (("fgs_finger", "#a9adb3"), ("fgs_pad", "#e8742c"), ("fgs_gauge_cover", "#5b6573"),
                           ("fgs_cable_clip", "#e8742c")):
                pl.append((to_gripper(shapes[n], side, q), col, 1.0))
        for n in ("fgs_enclosure_base", "fgs_clamp"):
            pl.append((shapes[n], "#3a3f47", 1.0))
        pl.append((shapes["fgs_enclosure_lid"], "#4a515c", 0.5))
        pl.append((vis["board"], "#1f6e43", 1.0))
        import pyvista as pv
        import render as R
        p = pv.Plotter(off_screen=True, window_size=(1600, 1200), lighting="none")
        p.set_background("white", top="#e9edf2")
        p.add_light(pv.Light(position=(250, -350, 400), focal_point=(0, 0, -60), intensity=0.85, light_type="scene light"))
        p.add_light(pv.Light(position=(-300, 200, 150), focal_point=(0, 0, -60), intensity=0.35, light_type="scene light"))
        p.add_light(pv.Light(light_type="headlight", intensity=0.3))
        for s, col, op in pl:
            p.add_mesh(R.to_mesh(s), color=col, opacity=op, smooth_shading=True, specular=0.3)
        for n, col in (("gripper", "#2f4f1f"), ("tip_left", "#7aa7c7"), ("tip_right", "#7aa7c7")):
            m = stock[n]
            if n.startswith("tip"):
                m = m.slice_plane([0, 0, P.LEFT_ORIGIN_G[2]], [0, 0, 1], cap=True)   # stock carriage only
                m = m.copy()
                m.apply_translation((0, -q if n == "tip_left" else q, 0))
            p.add_mesh(pv.wrap(m), color=col, opacity=0.55 if n == "gripper" else 0.9, smooth_shading=True)
        p.camera_position = [(260, -230, 60), (0, 0, -70), (0, 0, 1)]
        p.add_text("FGS on the linear_4310 gripper (stock body and carriages; fingers replaced)",
                   position="upper_left", font_size=12, color="#222222")
        p.enable_anti_aliasing("ssaa")
        p.screenshot(os.path.join(rd, "fgs_on_gripper.png"))
        p.close()


def write_md(res: dict) -> None:
    L = ["# FGS design checks (generated by fgs_build.py)", "", f"Generated {time.strftime('%Y-%m-%d %H:%M')}.", "",
         "## Parts", "", "| Part | Material | Mass g | BBox mm | Note |", "|---|---|---:|---|---|"]
    for n, d in res["parts"].items():
        L.append(f"| {n} | {d['material']} | {d['mass_g']} | {' × '.join(map(str, d['bbox_mm']))} | {d['note']} |")
    m = res["mass"]
    L += ["", "## Mass", "", f"* Per finger (finger, pad, cover, clip, gauges, cable stub): **{m['per_finger_g']} g** "
          f"(stock finger below the interface ≈ {m['stock_finger_below_interface_g']} g)",
          f"* Enclosure, clamp and board: {m['enclosure_and_board_g']} g",
          f"* Added to the gripper in total: **{m['added_total_g']} g**", ""]
    g = res["geometry"]
    L += ["## Grasp geometry vs stock", "", "| Quantity | FGS | Stock |", "|---|---|---|",
          f"| contact face (interface y) | {g['contact_face_y']} mm | 17.6 mm |",
          f"| tip bottom (interface z) | {g['tip_z']} mm | −74.2 mm |",
          f"| stroke per finger | {g['stroke_per_finger_mm']} mm | 47.5 mm |",
          f"| finger thickness at the tip | {g['finger_thickness_at_tip_mm']} mm | ≈ 6 mm |",
          f"| sensing pad (x × z) | {g['pad_xz_mm'][0]} × {g['pad_xz_mm'][1]} mm | — |", ""]
    it = res["interference"]
    L += ["## Interference with the stock gripper (q = 0, 23.75, 47.5 mm)", ""]
    if "skipped" in it:
        L += [f"Skipped: {it['skipped']}.", ""]
    else:
        L += [f"Unexpected overlaps: **{len(it['unexpected'])}**.", ""]
        for r in it["rows"]:
            L.append(f"* q = {r['q_mm']} mm: {r['a']} ↔ {r['b']}: {r['overlap_mm3']} mm³")
        L += ["", f"The stock tips themselves overlap {it['stock_tips_overlap_at_q0_mm3']} mm³ at q = 0 in the "
              "MJCF; {}.".format(it["note"]), ""]
    L += ["## Finger body bending at 500 N (CAD sections)", "", "| z mm | A mm² | I mm⁴ | M N·m | σ MPa |",
          "|---:|---:|---:|---:|---:|"]
    for s in res["sections"]:
        L.append(f"| {s['z']} | {s['area_mm2']} | {s['I_mm4']} | {s['moment_Nm_at_500N']} | {s['sigma_MPa']} |")
    if "fea" in res:
        f, s = res["fea"], res["strength"]
        L += ["", "## Flexure FEA (2D plane stress, P2 triangles)", "",
              f"* {f['n_elements']} elements, {f['n_dofs']} DOF; convergence: bridge "
              f"{f['convergence']['bridge_coarse']:.4f} → {f['convergence']['bridge_fine']:.4f} mV/V",
              f"* Stiffness **{f['k_N_per_mm']:.0f} N/mm**; first modes {', '.join(str(round(x)) for x in f['f_modes_Hz'])} Hz",
              f"* Gauge strain at 100 N: top {f['eps_gauge_top']*1e6:.0f} µε, bottom {f['eps_gauge_bottom']*1e6:.0f} µε → "
              f"**{abs(f['bridge_mV_per_V']):.3f} mV/V per 100 N** (GF {P.GAUGE_FACTOR})",
              f"* Load-position sensitivity (2 mm patch vs uniform): top {f['position_sensitivity_pct']['top']:.1f} %, "
              f"centre {f['position_sensitivity_pct']['centre']:.1f} %, bottom {f['position_sensitivity_pct']['bottom']:.1f} %",
              f"* Peak von Mises in the flexure at 500 N, uniform on the pad: **{s['vm_peak_at_500N_uniform_MPa']} MPa** "
              f"(yield {P.YIELD_AL7075:.0f}; safety {s['safety_on_yield_500N_uniform']})",
              f"* Peak at 500 N concentrated on the top 2 mm of the pad: {s['vm_peak_at_500N_top_edge_MPa']} MPa "
              f"(local, at the gap end)",
              f"* Goodman sum for repeated 0 → 480 N squeezes (uniform): {s['goodman_480N_repeated_uniform']} (< 1 = infinite life)",
              "", "![FEA](renders/fgs_fea.png)"]
    with open(os.path.join(OUT, "checks.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fea", action="store_true")
    a = ap.parse_args()
    r = build(a)
    log(f"done: finger {r['parts']['fgs_finger']['mass_g']} g, per finger {r['mass']['per_finger_g']} g")
