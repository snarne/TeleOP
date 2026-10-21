"""FGS parts. Every function returns a CadQuery Workplane in the interface frame of the left
finger (see fgs_params), except the electronics enclosure parts, which are in the gripper frame."""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import cadquery as cq

import fgs_params as P

XC = P.FINGER_XC
HB = P.B / 2


# --------------------------------------------------------------------------- helpers
def yz_prism(pts_yz: Sequence[Tuple[float, float]], x0: float, x1: float) -> cq.Workplane:
    """Closed polygon in the YZ plane, extruded along +x from x0 to x1."""
    plane = cq.Plane(origin=(x0, 0, 0), xDir=(0, 1, 0), normal=(1, 0, 0))   # local (u, v) = (y, z)
    return cq.Workplane(plane).polyline(list(pts_yz)).close().extrude(x1 - x0)


def xz_prism(pts_xz: Sequence[Tuple[float, float]], y0: float, y1: float) -> cq.Workplane:
    """Closed polygon in the XZ plane, extruded along +y from y0 to y1."""
    plane = cq.Plane(origin=(0, y0, 0), xDir=(1, 0, 0), normal=(0, 1, 0))   # local v = −z
    return cq.Workplane(plane).polyline([(x, -z) for x, z in pts_xz]).close().extrude(y1 - y0)


def box(x: Tuple[float, float], y: Tuple[float, float], z: Tuple[float, float]) -> cq.Workplane:
    return (cq.Workplane("XY").box(x[1] - x[0], y[1] - y[0], z[1] - z[0])
            .translate(((x[0] + x[1]) / 2, (y[0] + y[1]) / 2, (z[0] + z[1]) / 2)))


def zcyl(x: float, y: float, d: float, z0: float, z1: float) -> cq.Workplane:
    return cq.Workplane("XY").workplane(offset=z0).center(x, y).circle(d / 2).extrude(z1 - z0)


def ycyl(x: float, z: float, d: float, y0: float, y1: float) -> cq.Workplane:
    plane = cq.Plane(origin=(x, y0, z), xDir=(1, 0, 0), normal=(0, 1, 0))
    return cq.Workplane(plane).circle(d / 2).extrude(y1 - y0)


def rounded_slot_yz(y: Tuple[float, float], z: Tuple[float, float], r: float, x0: float, x1: float) -> cq.Workplane:
    """Rectangle in YZ with corner radius r (wire-EDM slot), through x."""
    plane = cq.Plane(origin=(x0, (y[0] + y[1]) / 2, (z[0] + z[1]) / 2), xDir=(0, 1, 0), normal=(1, 0, 0))
    w = cq.Workplane(plane).rect(y[1] - y[0], z[1] - z[0])
    s = w.extrude(x1 - x0)
    if r > 0:
        s = s.edges("|X").fillet(min(r, (y[1] - y[0]) / 2 - 0.01))
    return s


# --------------------------------------------------------------------------- finger (7075-T6)
def side_profile() -> List[Tuple[float, float]]:
    """Outer y–z profile of the finger (before the EDM slots)."""
    return [
        (P.FLANGE_Y[0], 0.0),
        (P.FLANGE_Y[0], -P.FLANGE_T),
        (P.NECK_BACK_Y, -P.FLANGE_T),       # web hangs from the front part of the flange only, so the
        (P.NECK_BACK_Y, P.NECK_BOTTOM_Z),   # screw/key columns under the M4 holes stay open
        (P.BACK_Y, P.NECK_BOTTOM_Z),
        (P.BACK_Y, P.TIP_CHAMFER_Z),
        (P.TIP_CHAMFER_Y, P.TIP_Z),
        (P.FRONT_Y, P.TIP_Z),
        (P.FRONT_Y, -15.0),
        (P.FLANGE_Y[1], -P.FLANGE_T),
        (P.FLANGE_Y[1], 0.0),
    ]


def front_profile() -> List[Tuple[float, float]]:
    """Outer x–z profile (front view)."""
    x0, x1 = XC - HB, XC + HB
    r = 2.0
    return [
        (P.FLANGE_X[0], 0.0),
        (P.FLANGE_X[0], -P.FLANGE_T),
        (P.WEB_X[0], -P.FLANGE_T - 2.0),
        (x0, P.NECK_TOP_Z),
        (x0, P.TIP_Z + r),
        (x0 + r, P.TIP_Z),
        (x1 - r, P.TIP_Z),
        (x1, P.TIP_Z + r),
        (x1, P.NECK_TOP_Z),
        (P.WEB_X[1], -P.FLANGE_T - 2.0),
        (P.FLANGE_X[1], -P.FLANGE_T),
        (P.FLANGE_X[1], 0.0),
    ]


def edm_cuts() -> cq.Workplane:
    """The wire-EDM profile: slot between the beams and the L-shaped gap around the arm."""
    x0, x1 = XC - HB - 1, XC + HB + 1
    slot = rounded_slot_yz(P.SLOT_Y, (P.BEAM_Z[1], P.BEAM_Z[0]), P.SLOT_R, x0, x1)
    # vertical gap: arm ↔ (front beam + ground block); bottom end rounded by the wire
    vgap = rounded_slot_yz(P.GAP_Y, (P.BEAM_Z[1], P.NECK_BOTTOM_Z), 0.0, x0, x1)
    # keyhole at the bottom of the gap, tangent to the front beam's front face
    kp = cq.Plane(origin=(x0, P.GAP_Y[0] + P.KEYHOLE_R, P.BEAM_Z[1]), xDir=(0, 1, 0), normal=(1, 0, 0))
    vgap = vgap.union(cq.Workplane(kp).circle(P.KEYHOLE_R).extrude(x1 - x0))
    hgap = rounded_slot_yz((P.GAP_Y[0], P.FRONT_Y + 1.0), (P.ARM_TOP_Z, P.NECK_BOTTOM_Z), 0.0, x0, x1)
    return slot.union(vgap).union(hgap)


def make_finger() -> cq.Workplane:
    big = (-40.0, 40.0)
    body = yz_prism(side_profile(), *big).intersect(xz_prism(front_profile(), -20.0, 30.0))
    body = body.cut(edm_cuts())
    # M4 interface: clearance through the 5 mm under the head, Ø8 c'bore from below (stock screws)
    for x in P.M4_X:
        body = body.cut(zcyl(x, P.M4_Y, P.M4_CLEAR_D, -P.M4_UNDER_HEAD - 0.1, 0.1))
        body = body.cut(zcyl(x, P.M4_Y, P.M4_CBORE_D, -P.FLANGE_T - 0.1, -P.M4_UNDER_HEAD))
    # cable channel in the neck back face (under the gauge cover)
    w, d = P.CABLE_CH
    body = body.cut(box((XC - w / 2, XC + w / 2), (P.NECK_BACK_Y - 1, P.NECK_BACK_Y + d), (P.CABLE_CH_Z[1], P.CABLE_CH_Z[0])))
    # M2 tapped holes (tap drill Ø1.6, 5 deep): gauge cover × 2, cable clip × 1
    for z in P.COVER_SCREW_Z:
        for sx in (-1, 1):
            body = body.cut(ycyl(XC + sx * P.COVER_SCREW_DX, z, 1.6, P.NECK_BACK_Y - 0.1, P.NECK_BACK_Y + 5.0))
    body = body.cut(ycyl(XC + P.CLIP_SCREW_DX, sum(P.CLIP_Z) / 2, 1.6, P.NECK_BACK_Y - 0.1, P.NECK_BACK_Y + 5.0))
    return body


# --------------------------------------------------------------------------- pad (TPU 85A)
def make_pad() -> cq.Workplane:
    x = (XC - HB + P.PAD_MARGIN_X, XC + HB - P.PAD_MARGIN_X)
    z = (P.PAD_Z[1], P.PAD_Z[0])
    h, pitch = P.PAD_RIDGE
    base = box(x, (P.FRONT_Y, P.CONTACT_Y - h), z)
    n = int((z[1] - z[0]) / pitch)
    z0 = (z[0] + z[1]) / 2 - (n - 1) * pitch / 2
    for i in range(n):
        zc = z0 + i * pitch
        base = base.union(box(x, (P.CONTACT_Y - h - 0.01, P.CONTACT_Y), (zc - pitch / 4, zc + pitch / 4)))
    return base


# --------------------------------------------------------------------------- strain gauges (visual)
def gauge_centres() -> List[Tuple[float, float]]:
    zt = P.BEAM_Z[0] - P.GAUGE_INSET
    zb = P.BEAM_Z[1] + P.GAUGE_INSET
    return [(XC - P.GAUGE_DX, zt), (XC + P.GAUGE_DX, zt), (XC - P.GAUGE_DX, zb), (XC + P.GAUGE_DX, zb)]


def make_gauges() -> cq.Workplane:
    out = None
    bl, bw = P.GAUGE_BACKING
    gl, gw = P.GAUGE_GRID
    for x, z in gauge_centres():
        g = box((x - bw / 2, x + bw / 2), (P.BACK_Y - 0.05, P.BACK_Y), (z - bl / 2, z + bl / 2))
        g = g.union(box((x - gw / 2, x + gw / 2), (P.BACK_Y - 0.08, P.BACK_Y - 0.04), (z - gl / 2, z + gl / 2)))
        out = g if out is None else out.union(g)
    return out


# --------------------------------------------------------------------------- gauge cover (PETG)
def make_cover() -> cq.Workplane:
    xo = (XC - HB - P.COVER_SIDE_CLEAR - P.COVER_WALL, XC + HB + P.COVER_SIDE_CLEAR + P.COVER_WALL)
    xi = (XC - HB - P.COVER_SIDE_CLEAR, XC + HB + P.COVER_SIDE_CLEAR)
    z = (P.COVER_Z[1], P.COVER_Z[0])
    y0 = P.NECK_BACK_Y - P.COVER_T
    plate = box(xo, (y0, P.NECK_BACK_Y), z)
    walls = box(xo, (P.NECK_BACK_Y - 0.01, P.COVER_SIDE_Y), z).cut(box(xi, (P.NECK_BACK_Y - 0.1, P.COVER_SIDE_Y + 1), (z[0] - 1, z[1] + 1)))
    c = plate.union(walls)
    # bottom lip under the tip chamfer is not needed; cable notch at the top
    w = P.CABLE_CH[0] + 0.4
    c = c.cut(box((XC - w / 2, XC + w / 2), (y0 - 1, P.NECK_BACK_Y + 1), (P.COVER_Z[0] - 4.0, P.COVER_Z[0] + 1)))
    for zz in P.COVER_SCREW_Z:
        for sx in (-1, 1):
            c = c.cut(ycyl(XC + sx * P.COVER_SCREW_DX, zz, 2.3, y0 - 1, P.NECK_BACK_Y + 1))
    return c


def make_clip() -> cq.Workplane:
    """Cable clip on the neck back, just above the cover: holds the 4-core cable in its channel."""
    z = P.CLIP_Z
    x = (XC - 3.5, XC + 7.0)
    y0 = P.NECK_BACK_Y - 1.5
    c = box(x, (y0, P.NECK_BACK_Y), z)
    c = c.cut(ycyl(XC + P.CLIP_SCREW_DX, sum(z) / 2, 2.3, y0 - 1, P.NECK_BACK_Y + 1))
    return c


def make_cable_stub(length: float = 18.0) -> cq.Workplane:
    """First stretch of the 4-core cable (Ø2.8) leaving the channel upward (visual)."""
    y = P.NECK_BACK_Y + P.CABLE_CH[1] - 1.45
    plane = cq.Plane(origin=(XC, y, P.CABLE_CH_Z[1] + 2), xDir=(1, 0, 0), normal=(0, 0, 1))
    return cq.Workplane(plane).circle(1.4).extrude(P.CABLE_CH_Z[0] - P.CABLE_CH_Z[1] - 2 + length)


# --------------------------------------------------------------------------- electronics enclosure (gripper frame)
R_IN = P.GRIPPER_CYL_R + 0.1


def _ring(r0: float, r1: float, a0: float, a1: float, z: Tuple[float, float], n: int = 64) -> cq.Workplane:
    pts = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        pts.append((r1 * math.cos(a), r1 * math.sin(a)))
    for i in range(n, -1, -1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        pts.append((r0 * math.cos(a), r0 * math.sin(a)))
    return cq.Workplane("XY").workplane(offset=z[0]).polyline(pts).close().extrude(z[1] - z[0])


ENC_X_OUT = R_IN + P.ENC_D
ENC_WALL = 1.6
CLAMP_Z = (-34.0, -34.0 + P.CLAMP_W)
TAB_Y = R_IN + P.CLAMP_T + 4.0


def _enc_outer() -> cq.Workplane:
    hw = P.ENC_W / 2
    return box((R_IN - 6.0, ENC_X_OUT), (-hw, hw), P.ENC_Z).cut(zcyl(0, 0, 2 * R_IN, P.ENC_Z[0] - 1, P.ENC_Z[1] + 1))


def make_enclosure_base() -> cq.Workplane:
    hw = P.ENC_W / 2
    outer = _enc_outer()
    inner = box((R_IN + ENC_WALL - 6.0, ENC_X_OUT + 1), (-hw + ENC_WALL, hw - ENC_WALL),
                (P.ENC_Z[0] + ENC_WALL, P.ENC_Z[1] - ENC_WALL)).cut(zcyl(0, 0, 2 * (R_IN + ENC_WALL), P.ENC_Z[0] - 1, P.ENC_Z[1] + 1))
    base = outer.cut(inner)
    # half clamp ring on the +x side with screw tabs at ±y
    ring = _ring(R_IN, R_IN + P.CLAMP_T, -90, 90, CLAMP_Z)
    tabs = box((-1.5, 4.5), (R_IN, TAB_Y + 3.0), CLAMP_Z).union(box((-1.5, 4.5), (-TAB_Y - 3.0, -R_IN), CLAMP_Z))
    tabs = tabs.cut(zcyl(0, 0, 2 * R_IN, CLAMP_Z[0] - 1, CLAMP_Z[1] + 1))
    base = base.union(ring).union(tabs)
    for sy in (-1, 1):
        base = base.cut(xcyl(sy * TAB_Y, sum(CLAMP_Z) / 2, 3.4, -5, 10))
    # cable entries: two finger cables at the bottom, USB-C at the top
    for sy in (-1, 1):
        base = base.cut(zcyl(ENC_X_OUT - 5.0, sy * 9.0, 3.4, P.ENC_Z[0] - 1, P.ENC_Z[0] + ENC_WALL + 1))
    base = base.cut(box((ENC_X_OUT - 9.5, ENC_X_OUT - 0.5), (-5.0, 5.0), (P.ENC_Z[1] - ENC_WALL - 1, P.ENC_Z[1] + 1)))
    # board standoffs (M2 self-tapping into Ø1.8 holes)
    bx = R_IN + ENC_WALL + 1.0
    for sy in (-1, 1):
        for zz in (P.ENC_Z[0] + 5.0, P.ENC_Z[1] - 5.0):
            base = base.union(xcyl(sy * 12.0, zz, 4.0, R_IN - 2.0, bx + 2.0).cut(xcyl(sy * 12.0, zz, 1.8, bx - 3.0, bx + 3.0)))
    return base


def make_enclosure_lid() -> cq.Workplane:
    hw = P.ENC_W / 2
    lid = box((ENC_X_OUT, ENC_X_OUT + 1.6), (-hw, hw), P.ENC_Z)
    lip = box((ENC_X_OUT - 1.5, ENC_X_OUT), (-hw + ENC_WALL + 0.2, hw - ENC_WALL - 0.2),
              (P.ENC_Z[0] + ENC_WALL + 0.2, P.ENC_Z[1] - ENC_WALL - 0.2))
    lip = lip.cut(box((ENC_X_OUT - 2, ENC_X_OUT + 1), (-hw + ENC_WALL + 1.4, hw - ENC_WALL - 1.4),
                      (P.ENC_Z[0] + ENC_WALL + 1.4, P.ENC_Z[1] - ENC_WALL - 1.4)))
    lid = lid.union(lip)
    lid = lid.cut(box((ENC_X_OUT - 2, ENC_X_OUT + 2), (-5.0, 5.0), (P.ENC_Z[1] - ENC_WALL - 1, P.ENC_Z[1] + 1)))
    return lid


def make_clamp() -> cq.Workplane:
    ring = _ring(R_IN, R_IN + P.CLAMP_T, 90, 270, CLAMP_Z)
    tabs = box((-4.5, 1.5), (R_IN, TAB_Y + 3.0), CLAMP_Z).union(box((-4.5, 1.5), (-TAB_Y - 3.0, -R_IN), CLAMP_Z))
    tabs = tabs.cut(zcyl(0, 0, 2 * R_IN, CLAMP_Z[0] - 1, CLAMP_Z[1] + 1))
    c = ring.union(tabs)
    for sy in (-1, 1):
        c = c.cut(xcyl(sy * TAB_Y, sum(CLAMP_Z) / 2, 3.4, -10, 5))
    return c


def xcyl(y: float, z: float, d: float, x0: float, x1: float) -> cq.Workplane:
    plane = cq.Plane(origin=(x0, y, z), xDir=(0, 1, 0), normal=(1, 0, 0))
    return cq.Workplane(plane).circle(d / 2).extrude(x1 - x0)


def make_board() -> cq.Workplane:
    """Protoboard / PCB with the XIAO and the ADC (visual, gripper frame)."""
    bw, bh, bt = P.BOARD
    bx = R_IN + ENC_WALL + 3.0
    zc = sum(P.ENC_Z) / 2
    b = box((bx, bx + bt), (-bw / 2, bw / 2), (zc - bh / 2, zc + bh / 2))
    xiao = box((bx + bt, bx + bt + 3.5), (-8.75, 8.75), (zc + bh / 2 - 21.0, zc + bh / 2))
    adc = box((bx + bt, bx + bt + 2.5), (-12.0, -5.0), (zc - bh / 2 + 2, zc - bh / 2 + 10))
    return b.union(xiao).union(adc)
