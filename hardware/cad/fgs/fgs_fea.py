"""2D plane-stress FEA of the FGS flexure (y–z section, thickness B along x).

    python hardware/cad/fgs/fgs_fea.py            # prints the results, writes out/fea.json + plots

Mesh: Triangle (quality-constrained Delaunay) on the exact section from fgs_params, arcs
discretised, refined twice around the beams; quadratic triangles (scikit-fem ElementTriP2).
Boundary conditions: the neck section at z = Z_TOP is fixed. Loads: the pad force as a traction on
the arm/floating-block front face over the pad (uniform), or concentrated (2 mm patch) at the pad
top / centre / bottom to measure load-position sensitivity.

Outputs: stiffness, gauge-averaged strains and the full-bridge output (mV/V per 100 N), beam
stresses (von Mises and max principal, scaled to the design loads), first natural frequency.
"""

from __future__ import annotations

import json
import math
import os
import sys
from typing import Dict, List, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fgs_params as P  # noqa: E402

Z_TOP = P.NECK_BOTTOM_Z + 8.0      # model the neck 8 mm above the ground block, fixed there
NU = 0.33
RHO = P.RHO_AL7075 * 1e-9          # t/mm³ (N, mm, s units)


def _arc(c, r, a0, a1, n) -> List[Tuple[float, float]]:
    return [(c[0] + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             c[1] + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def section_polygons():
    """Outer boundary (y, z) counter-clockwise, and the inter-beam slot as a hole."""
    kc = (P.GAP_Y[0] + P.KEYHOLE_R, P.BEAM_Z[1])
    # keyhole arc: from the front-beam face (angle 180°) down and around to the arm back face
    yy = P.GAP_Y[1] - kc[0]
    a_end = 360.0 + math.degrees(math.acos(yy / P.KEYHOLE_R))
    key = _arc(kc, P.KEYHOLE_R, 180.0, a_end, 40)
    outer = [(P.NECK_BACK_Y, Z_TOP), (P.FRONT_Y, Z_TOP), (P.FRONT_Y, P.NECK_BOTTOM_Z), (P.GAP_Y[0], P.NECK_BOTTOM_Z)]
    outer += key   # first point = (GAP_Y[0], BEAM_Z[1])
    outer += [(P.GAP_Y[1], P.ARM_TOP_Z), (P.FRONT_Y, P.ARM_TOP_Z), (P.FRONT_Y, P.TIP_Z), (P.TIP_CHAMFER_Y, P.TIP_Z),
              (P.BACK_Y, P.TIP_CHAMFER_Z), (P.BACK_Y, P.NECK_BOTTOM_Z), (P.NECK_BACK_Y, P.NECK_BOTTOM_Z)]
    # the polygon above is clockwise in (y, z) → reverse to CCW
    outer = outer[::-1]
    r = P.SLOT_W / 2
    yc = (P.SLOT_Y[0] + P.SLOT_Y[1]) / 2
    zt, zb = P.BEAM_Z[0] - r, P.BEAM_Z[1] + r
    slot = _arc((yc, zt), r, 0, 180, 24) + _arc((yc, zb), r, 180, 360, 24)
    return outer, slot, (yc, (zt + zb) / 2)


def build_mesh(refine: int = 2):
    import triangle
    from skfem import MeshTri
    outer, slot, hole_pt = section_polygons()

    def ring(pts, off):
        n = len(pts)
        return [[off + i, off + (i + 1) % n] for i in range(n)]

    # densify long straight edges so the boundary is well resolved
    def densify(pts, h=0.25):
        out = []
        for i in range(len(pts)):
            a, b = np.array(pts[i]), np.array(pts[(i + 1) % len(pts)])
            n = max(1, int(np.ceil(np.linalg.norm(b - a) / h)))
            out += [tuple(a + (b - a) * k / n) for k in range(n)]
        return out

    o = densify(outer)
    s = densify(slot, 0.1)
    verts = np.array(o + s)
    segs = np.array(ring(o, 0) + ring(s, len(o)))
    tri = triangle.triangulate({"vertices": verts, "segments": segs, "holes": [hole_pt]}, "pq30a0.02")
    m = MeshTri(tri["vertices"].T, tri["triangles"].T)
    for _ in range(refine):
        c = m.p[:, m.t].mean(axis=1)
        mark = np.nonzero((c[0] < P.GAP_Y[1] + 1.2) & (c[1] < P.BEAM_Z[0] + 1.5) & (c[1] > P.BEAM_Z[1] - 1.5))[0]
        m = m.refined(mark)
    return m


def solve(mesh, load: str = "uniform", F: float = 100.0, modal: bool = False) -> Dict:
    from scipy.sparse.linalg import eigsh
    from skfem import (Basis, BilinearForm, ElementTriP1, ElementTriP2, ElementVector, FacetBasis, LinearForm, asm,
                       condense)
    from skfem import solve as fem_solve
    from skfem.helpers import dot
    from skfem.models.elasticity import lame_parameters, linear_elasticity

    lam, mu = lame_parameters(P.E_AL7075, NU)
    lam_ps = 2 * lam * mu / (lam + 2 * mu)            # plane stress
    e = ElementVector(ElementTriP2())
    basis = Basis(mesh, e, intorder=4)
    K = asm(linear_elasticity(lam_ps, mu), basis)

    zp0, zp1 = P.PAD_Z[1], P.PAD_Z[0]                 # pad z range (low, high)
    if load == "uniform":
        z0, z1 = zp0, zp1
    elif load == "top":
        z0, z1 = zp1 - 2.0, zp1
    elif load == "bottom":
        z0, z1 = zp0, zp0 + 2.0
    elif load == "centre":
        zc = (zp0 + zp1) / 2
        z0, z1 = zc - 1.0, zc + 1.0
    else:
        raise ValueError(load)
    facets = mesh.facets_satisfying(lambda x: np.isclose(x[0], P.FRONT_Y) & (x[1] >= z0 - 1e-6) & (x[1] <= z1 + 1e-6))
    fb = FacetBasis(mesh, e, facets=facets, intorder=4)
    ty = -F / (P.B * (z1 - z0))                       # N/mm² per unit thickness → total F over B

    @LinearForm
    def traction(v, w):
        return v.value[0] * ty

    f = asm(traction, fb)
    D = basis.get_dofs(lambda x: np.isclose(x[1], Z_TOP)).all()
    u = fem_solve(*condense(K, f, D=D))

    # floating-block displacement (mean over its nodes)
    nodes = basis.nodal_dofs
    pts = basis.doflocs[:, nodes[0]]
    fl = (pts[1] < P.BEAM_Z[1] - 0.3) & (pts[0] > P.BACK_Y + 0.5) & (pts[0] < P.FRONT_Y - 0.5)
    uy = u[nodes[0]][fl].mean() if False else u[nodes[0][fl]].mean()   # dof 0 = y component
    k = F / abs(uy)

    # strains and stresses projected to P1
    sb = basis.with_element(ElementTriP1())
    ui = basis.interpolate(u)
    G = ui.grad
    eyy, ezz, eyz = G[0][0], G[1][1], 0.5 * (G[0][1] + G[1][0])
    c = P.E_AL7075 / (1 - NU ** 2)
    syy = c * (eyy + NU * ezz)
    szz = c * (ezz + NU * eyy)
    syz = P.E_AL7075 / (1 + NU) * eyz
    vm = np.sqrt(syy ** 2 - syy * szz + szz ** 2 + 3 * syz ** 2)
    s1 = (syy + szz) / 2 + np.sqrt(((syy - szz) / 2) ** 2 + syz ** 2)
    s3 = (syy + szz) / 2 - np.sqrt(((syy - szz) / 2) ** 2 + syz ** 2)
    P_ezz = sb.project(ezz)
    P_vm = sb.project(vm)
    P_s1 = sb.project(s1)
    P_s3 = sb.project(s3)

    # gauge averages along the back face (rear beam), grid length GAUGE_GRID[0]
    gl = P.GAUGE_GRID[0]
    zt = P.BEAM_Z[0] - P.GAUGE_INSET
    zb = P.BEAM_Z[1] + P.GAUGE_INSET

    def line_avg(field, zc):
        zs = np.linspace(zc - gl / 2, zc + gl / 2, 61)
        probes = np.vstack([np.full_like(zs, P.BACK_Y + 0.005), zs])
        return float((sb.probes(probes) @ field).mean())

    e_top, e_bot = line_avg(P_ezz, zt), line_avg(P_ezz, zb)
    bridge_mv_v = P.GAUGE_FACTOR / 2 * (e_top - e_bot) * 1e3
    # strain profile along the back face (for the plot / docs)
    zs = np.linspace(P.TIP_CHAMFER_Z + 0.2, P.BEAM_Z[0] + 3, 241)
    prof = sb.probes(np.vstack([np.full_like(zs, P.BACK_Y + 0.005), zs])) @ P_ezz

    # stresses in the beam zone (both beams, incl. root fillets), excluding the load patch
    nod = sb.doflocs
    zone = (nod[1] < P.BEAM_Z[0] + 1.2) & (nod[1] > P.BEAM_Z[1] - 1.2) & (nod[0] < P.GAP_Y[0] + 1.6)
    res = {
        "load": load, "F_N": F, "k_N_per_mm": k, "uy_mm": float(uy),
        "eps_gauge_top": e_top, "eps_gauge_bottom": e_bot, "bridge_mV_per_V": bridge_mv_v,
        "vm_max_beams_MPa": float(P_vm[zone].max()), "s1_max_beams_MPa": float(P_s1[zone].max()),
        "s3_min_beams_MPa": float(P_s3[zone].min()),
        "vm_max_all_MPa": float(P_vm.max()),
        "profile_z": zs.tolist(), "profile_eps": prof.tolist(),
        "n_elements": int(mesh.t.shape[1]), "n_dofs": int(basis.N),
    }
    # where is the peak?
    i = int(np.argmax(np.where(zone, P_vm, -1)))
    res["vm_max_at_yz"] = [float(nod[0][i]), float(nod[1][i])]
    # mean axial stress in each beam at mid-length (load-position couple)
    zm = P.BEAM_MID_Z
    for name, (y0, y1) in (("beam_rear", P.BEAM2_Y), ("beam_front", P.BEAM1_Y)):
        ys = np.linspace(y0 + 0.02, y1 - 0.02, 21)
        szz_p = sb.project(szz)
        vals = sb.probes(np.vstack([ys, np.full_like(ys, zm)])) @ szz_p
        res[f"{name}_axial_MPa"] = float(vals.mean())
    if modal:
        @BilinearForm
        def mass(u_, v_, w):
            return RHO * dot(u_, v_)
        M = asm(mass, basis)
        I = basis.complement_dofs(D)
        vals, _ = eigsh(K[I][:, I], k=3, M=M[I][:, I], sigma=0, which="LM")
        res["f_modes_Hz"] = sorted(float(np.sqrt(max(v, 0)) / (2 * np.pi)) for v in vals)
    return res, (mesh, sb, P_vm)


def run(write: bool = True, refine: int = 2) -> Dict:
    mesh = build_mesh(refine)
    out = {}
    uni, (m, sb, vm) = solve(mesh, "uniform", modal=True)
    out["uniform"] = uni
    for lc in ("top", "centre", "bottom"):
        out[lc], _ = solve(mesh, lc)
    base = uni["bridge_mV_per_V"]
    out["position_sensitivity_pct"] = {lc: 100 * (out[lc]["bridge_mV_per_V"] / base - 1) for lc in ("top", "centre", "bottom")}
    # convergence: one refinement less
    coarse, _ = solve(build_mesh(refine - 1), "uniform")
    out["convergence"] = {"bridge_coarse": coarse["bridge_mV_per_V"], "bridge_fine": base,
                          "vm_coarse": coarse["vm_max_beams_MPa"], "vm_fine": uni["vm_max_beams_MPa"],
                          "k_coarse": coarse["k_N_per_mm"], "k_fine": uni["k_N_per_mm"]}
    if write:
        od = os.path.join(HERE, "out")
        os.makedirs(od, exist_ok=True)
        slim = {k: ({kk: vv for kk, vv in v.items() if not kk.startswith("profile")} if isinstance(v, dict) else v)
                for k, v in out.items()}
        with open(os.path.join(od, "fea.json"), "w") as f:
            json.dump(slim, f, indent=1)
        _plots(out, m, sb, vm, od)
    return out


def _plots(out, mesh, sb, vm, od) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.tri as mtri
    rd = os.path.join(od, "renders")
    os.makedirs(rd, exist_ok=True)
    scale = P.F_ULT / out["uniform"]["F_N"]
    fig, ax = plt.subplots(1, 2, figsize=(11, 7.5), gridspec_kw={"width_ratios": [1.1, 1]})
    T = mtri.Triangulation(mesh.p[0], mesh.p[1], mesh.t.T)
    vals = vm[: mesh.p.shape[1]] * scale
    tc = ax[0].tripcolor(T, vals, shading="gouraud", cmap="inferno", vmin=0, vmax=max(260, float(vals.max())))
    ax[0].set_aspect("equal")
    ax[0].set_xlabel("y (mm, + toward the object)")
    ax[0].set_ylabel("z (mm)")
    ax[0].set_title(f"von Mises at {P.F_ULT:.0f} N (uniform on the pad)")
    fig.colorbar(tc, ax=ax[0], label="MPa", shrink=0.8)
    for k in ("top", "centre", "bottom"):
        pass
    z = np.array(out["uniform"]["profile_z"])
    e = np.array(out["uniform"]["profile_eps"]) * 1e6
    ax[1].plot(e, z, color="#2f7dd1", lw=2, label="ε_zz on the gauge face, 100 N")
    for zc in (P.BEAM_Z[0] - P.GAUGE_INSET, P.BEAM_Z[1] + P.GAUGE_INSET):
        ax[1].axhspan(zc - P.GAUGE_GRID[0] / 2, zc + P.GAUGE_GRID[0] / 2, color="#e8742c", alpha=0.25)
    for zz in P.BEAM_Z:
        ax[1].axhline(zz, color="#888", lw=0.8, ls="--")
    ax[1].axvline(0, color="#444", lw=0.6)
    ax[1].set_xlabel("strain (µε) at 100 N")
    ax[1].set_title(f"bridge {out['uniform']['bridge_mV_per_V']:.3f} mV/V per 100 N; "
                    f"k = {out['uniform']['k_N_per_mm']:.0f} N/mm")
    ax[1].legend(loc="lower right", fontsize=9)
    ax[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(rd, "fgs_fea.png"), dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    r = run()
    u = r["uniform"]
    print(f"elements {u['n_elements']}, dofs {u['n_dofs']}")
    print(f"k = {u['k_N_per_mm']:.0f} N/mm, uy(100 N) = {u['uy_mm']*1e3:.1f} µm")
    print(f"gauge strain top {u['eps_gauge_top']*1e6:.0f} µε, bottom {u['eps_gauge_bottom']*1e6:.0f} µε → "
          f"{u['bridge_mV_per_V']:.3f} mV/V per 100 N")
    print(f"beams at 100 N: vm max {u['vm_max_beams_MPa']:.1f} MPa at {u['vm_max_at_yz']}, s1 {u['s1_max_beams_MPa']:.1f}, s3 {u['s3_min_beams_MPa']:.1f}")
    print(f"axial at beam mid: rear {u['beam_rear_axial_MPa']:.2f} MPa, front {u['beam_front_axial_MPa']:.2f} MPa")
    print("modes Hz", [round(f) for f in u["f_modes_Hz"]])
    print("position sensitivity %", {k: round(v, 2) for k, v in r["position_sensitivity_pct"].items()})
    for lc in ("top", "centre", "bottom"):
        print(lc, r[lc]["vm_max_at_yz"], f"vm {r[lc]["vm_max_beams_MPa"]:.1f} MPa, axial rear {r[lc]['beam_rear_axial_MPa']:.1f} front {r[lc]['beam_front_axial_MPa']:.1f}")
    print("convergence", r["convergence"])
