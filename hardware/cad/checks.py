"""Design checks: interference over the motion range, clearances, wall thickness, mass.

Run through build.py. Results go to out/checks.json and out/checks.md.
"""

from __future__ import annotations

import itertools
import json
import math
from typing import Dict, List

import cadquery as cq
import numpy as np
from OCP.BRepExtrema import BRepExtrema_DistShapeShape

import params as P
from assembly import Part, parts

# Pairs that may touch by design (zero-volume contact or press fits):
ALLOWED_CONTACT = {
    frozenset({"lever", "bearing_6700zz"}),          # shaft in bearing bore
    frozenset({"housing_encoder_half", "bearing_6700zz"}),
    frozenset({"lever", "bearing_mr63zz"}),
    frozenset({"pin_3x8", "bearing_mr63zz"}),
    frozenset({"pin_3x8", "drive_disc"}),
    frozenset({"drive_disc", "servo_horn"}),
    frozenset({"servo_xc330", "servo_horn"}),
    frozenset({"lever", "magnet_6x2.5"}),
    frozenset({"lever", "blade"}),
    frozenset({"blade", "blade_skin"}),
    frozenset({"blade", "lra"}),
    frozenset({"blade_skin", "lra"}),
    frozenset({"lever", "lra"}),
    frozenset({"lever", "blade_skin"}),
    frozenset({"lever", "drive_disc"}),               # backstop (δ = 0) and overload rim (δ = max) contacts
    frozenset({"spring", "lever"}),
    frozenset({"spring", "drive_disc"}),
    frozenset({"housing_servo_half", "servo_xc330"}),
    frozenset({"housing_servo_half", "housing_encoder_half"}),
    frozenset({"housing_servo_half", "switch_a"}),
    frozenset({"housing_servo_half", "switch_b"}),
    frozenset({"servo_xc330", "switch_a"}),
    frozenset({"servo_xc330", "switch_b"}),
    frozenset({"housing_encoder_half", "encoder_cover"}),
    frozenset({"encoder_cover", "as5600_board"}),
    frozenset({"encoder_cover", "bearing_6700zz"}),
    frozenset({"housing_servo_half", "electronics"}),
    frozenset({"housing_servo_half", "mount_adapter"}),
    frozenset({"housing_encoder_half", "mount_adapter"}),
    frozenset({"button_cap_a", "switch_a"}),
    frozenset({"button_cap_b", "switch_b"}),
}

VOL_TOL = 0.05   # mm³: anything above this counts as a real collision


def _solid(w: cq.Workplane) -> cq.Shape:
    vals = [v for v in w.vals() if isinstance(v, cq.Shape)]
    return vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)


def overlap_volume(a: cq.Shape, b: cq.Shape) -> float:
    bb_a, bb_b = a.BoundingBox(), b.BoundingBox()
    if (bb_a.xmax < bb_b.xmin or bb_b.xmax < bb_a.xmin or bb_a.ymax < bb_b.ymin or bb_b.ymax < bb_a.ymin
            or bb_a.zmax < bb_b.zmin or bb_b.zmax < bb_a.zmin):
        return 0.0
    try:
        return a.intersect(b).Volume()
    except Exception:
        return float("nan")


def min_distance(a: cq.Shape, b: cq.Shape) -> float:
    d = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
    d.Perform()
    return d.Value() if d.IsDone() else float("nan")


def interference_sweep(phis=(0.0, 10.0, 20.0, P.TRAVEL), deltas=(0.0, P.DELTA_MID, P.DELTA_MAX)) -> Dict:
    """Check every moving part against every other part over the motion grid."""
    report = {"states": [], "collisions": [], "min_clearance": {}}
    for phi, delta in itertools.product(phis, deltas):
        ps = {p.name: p for p in parts(phi, delta)}
        shapes = {n: _solid(p.shape) for n, p in ps.items()}
        moving = [n for n, p in ps.items() if p.moving != "fixed"]
        state = {"phi": phi, "delta": delta, "pairs_checked": 0}
        for m in moving:
            for o in shapes:
                if o == m or (ps[o].moving == ps[m].moving and o < m):
                    continue
                key = frozenset({m, o})
                state["pairs_checked"] += 1
                v = overlap_volume(shapes[m], shapes[o])
                if v > VOL_TOL and key not in ALLOWED_CONTACT:
                    report["collisions"].append({"phi": phi, "delta": delta, "a": m, "b": o, "volume_mm3": round(v, 3)})
        report["states"].append(state)
    return report


def clearances(phi_list=(0.0, P.TRAVEL / 2, P.TRAVEL), delta_list=(0.0, P.DELTA_MAX)) -> Dict[str, float]:
    """Minimum distance between the lever/disc and the housing halves over the grid."""
    res: Dict[str, float] = {}
    for phi, delta in itertools.product(phi_list, delta_list):
        ps = {p.name: p for p in parts(phi, delta)}
        for m in ("lever", "blade", "drive_disc"):
            for o in ("housing_servo_half", "housing_encoder_half", "servo_xc330"):
                d = min_distance(_solid(ps[m].shape), _solid(ps[o].shape))
                k = f"{m} ↔ {o}"
                res[k] = min(res.get(k, 1e9), round(d, 3))
    return res


def spring_check() -> Dict[str, float]:
    k = P.spring_rate_n_per_mm()
    d = P.SPRING_WIRE
    D = P.SPRING_OD - P.SPRING_WIRE
    C = D / d
    kw = (4 * C - 1) / (4 * C - 4) + 0.615 / C
    x_max = P.spring_compression_mm(P.DELTA_MAX)
    f_max = k * x_max
    tau = 8 * f_max * D * kw / (math.pi * d ** 3)  # MPa (N, mm)
    l_min = P.SPRING_L0 - x_max
    return {
        "rate_n_per_mm": round(k, 3),
        "k_theta_nm_per_rad": round(P.k_theta_nm_per_rad(), 4),
        "spring_index_C": round(C, 2),
        "wahl_factor": round(kw, 3),
        "preload_n": round(k * P.SPRING_PRELOAD, 2),
        "preload_torque_nm": round(k * P.SPRING_PRELOAD * P.R_T / 1000, 4),
        "preload_finger_n": round(k * P.SPRING_PRELOAD * P.R_T / P.R_FINGER, 2),
        "compression_at_overload_mm": round(x_max, 3),
        "length_at_overload_mm": round(l_min, 3),
        "solid_length_mm": round(P.SPRING_SOLID, 3),
        "margin_to_solid_mm": round(l_min - P.SPRING_SOLID, 3),
        "force_at_overload_n": round(f_max, 2),
        "finger_force_at_overload_n": round(P.finger_force_n(P.DELTA_MAX), 2),
        "shear_stress_at_overload_mpa": round(tau, 0),
    }


def mass_budget(ps: List[Part]) -> Dict:
    from parts.purchased import MASS_G
    printed = {}
    for p in ps:
        if p.group == "printed":
            vol_cm3 = _solid(p.shape).Volume() / 1000.0
            dens = P.DENSITY["PETG"] if (p.material or "").startswith("PETG") else 1.21
            printed[p.name] = {"volume_cm3": round(vol_cm3, 2),
                               "mass_g": round(vol_cm3 * dens * P.PRINT_FILL_FACTOR, 1)}
    printed_total = sum(v["mass_g"] for v in printed.values())
    purchased_total = sum(MASS_G.values())
    return {"printed": printed, "printed_total_g": round(printed_total, 1),
            "purchased": MASS_G, "purchased_total_g": round(purchased_total, 1),
            "total_g": round(printed_total + purchased_total, 1), "target_g": 135.0}


def wall_thickness(mesh_path: str, n_samples: int = 6000, seed: int = 1) -> Dict[str, float]:
    """Ray-cast wall thickness. From random surface samples, shoot inward along −normal and
    measure the distance to the first exit. Only "opposed-face" hits count (exit face normal
    within 60° of anti-parallel). That rejects grazing rays near edges and fillets, which
    otherwise report false thin walls."""
    import trimesh
    m = trimesh.load(mesh_path)
    pts, fidx = trimesh.sample.sample_surface(m, n_samples, seed=seed)
    normals = m.face_normals[fidx]
    origins = pts - normals * 1e-3
    locs, ray_idx, tri_idx = m.ray.intersects_location(origins, -normals, multiple_hits=False)
    if len(ray_idx) == 0:
        return {}
    d = np.linalg.norm(locs - origins[ray_idx], axis=1)
    opposed = np.einsum("ij,ij->i", normals[ray_idx], m.face_normals[tri_idx]) < -0.5
    d = d[opposed & (d > 0.05)]
    thin = d < (P.WALL_MIN - 0.1)
    return {"samples": int(len(d)), "min_mm": round(float(np.min(d)), 2),
            "p1_mm": round(float(np.percentile(d, 1)), 2), "p5_mm": round(float(np.percentile(d, 5)), 2),
            "median_mm": round(float(np.median(d)), 2),
            "frac_below_1.5": round(float(np.mean(thin)), 4)}


def stop_verification() -> Dict[str, Dict]:
    """Prove the hard stops do their job: just past each stop the parts must collide,
    and at the stop they must be in (near-)contact."""
    import params as P
    out = {}

    def vol(phi, delta, a, b):
        ps = {p.name: p for p in parts(phi, delta)}
        return overlap_volume(_solid(ps[a].shape), _solid(ps[b].shape))

    def dist(phi, delta, a, b):
        ps = {p.name: p for p in parts(phi, delta)}
        return min_distance(_solid(ps[a].shape), _solid(ps[b].shape))

    cases = {
        "open stop (lever vs housing)": (0.0, -1.0, "lever", ("housing_servo_half", "housing_encoder_half"), 0.0),
        "closed stop (lever vs housing)": (P.TRAVEL, P.TRAVEL + 1.0, "lever", ("housing_servo_half", "housing_encoder_half"), 0.0),
    }
    for name, (at, past, a, bs, delta) in cases.items():
        d_at = min(dist(at, delta, a, b) for b in bs)
        v_past = max(vol(past, delta, a, b) for b in bs)
        out[name] = {"distance_at_stop_mm": round(d_at, 3), "overlap_1deg_past_mm3": round(v_past, 2),
                     "ok": bool(d_at < 0.3 and v_past > VOL_TOL)}
    # SEA stops: backstop at delta = 0, overload rim at delta = DELTA_MAX
    for name, (at, past) in {"SEA backstop (tab vs lever)": (0.0, -0.5),
                             "SEA overload rim (tab vs lever)": (P.DELTA_MAX, P.DELTA_MAX + 0.5)}.items():
        d_at = dist(10.0, at, "drive_disc", "lever")
        v_past = vol(10.0, past, "drive_disc", "lever")
        out[name] = {"distance_at_stop_mm": round(d_at, 3), "overlap_0.5deg_past_mm3": round(v_past, 2),
                     "ok": bool(d_at < 0.3 and v_past > VOL_TOL)}
    return out
