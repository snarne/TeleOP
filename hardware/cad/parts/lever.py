"""Trigger lever: hub, spring pocket, finger arm and blade.

* Hub: a Ø10 shaft runs in a 6700ZZ bearing in the +Y housing wall. A diametric magnet
  in the shaft end is read by the AS5600. An MR63 in the inner face takes the drive-disc
  pilot pin.
* Pocket: a U-channel (open toward −Y for assembly) holds the compression spring between
  the floor spigot and the drive-disc tab. The window that the tab sweeps is cut as the
  exact swept envelope of the tab over 0 … DELTA_MAX, so the backstop (delta = 0) and the
  overload rim (delta = DELTA_MAX) are both defined by the geometry.
* Blade: the finger pad sits at r_f = 45 mm.

Print: lying on its −Y face (the pocket opening faces the bed, so the bridge is the only
overhang, a 10 mm bridge). PETG preferred for stiffness and creep resistance.
"""

import math

import cadquery as cq

from geom import (annular_sector_xz, local_box, local_cyl, rot_y, s_of_delta, spring_frame,
                  tab_frame, xz_prism, ycyl)
from params import (
    B6700_ID, B6700_W, BLADE_ANGLE_OPEN, BLADE_R_IN, BLADE_R_OUT, BLADE_T, BLADE_Y0,
    BEARING_LIP_T, BEARING_BOSS_Y0, DELTA_MAX, LRA_D, LRA_T, LRA_TAPE, LRA_Y, SKIN_T, BLADE_BOSS_H,
    WIRE_GROOVE_W, WIRE_GROOVE_D, R_FINGER, FIT_PRESS, HEAD_Y1, HUB_SHOULDER_D,
    LEVER_ARM_W, LEVER_HUB_D, LEVER_Y0, LEVER_Y1, MAGNET_D, MAGNET_T, MR63_OD, MR63_W,
    POCKET_HALF_W, POCKET_Y0, POCKET_Y1, BRIDGE_Y0, SPIGOT_D, SPIGOT_L, SPRING_BORE_D,
    SPRING_L_INSTALLED, SPRING_Y, TAB_T, TAB_W, WINDOW_CLEAR, BACKSTOP_T,
)

POCKET_INNER_W = 6.4     # radial extent of the pocket block toward the pivot
END_WALL = 2.0


def spring_seat_s() -> float:
    """Spring seat (floor) position along the spring axis, relative to T."""
    return s_of_delta(0.0) + SPRING_L_INSTALLED


def tab_keepout() -> cq.Workplane:
    """Swept envelope of the tab + spigot over the deflection range, plus side clearance."""
    o, ex, ez = tab_frame()
    y0, y1 = POCKET_Y0 - 0.6 - SPRING_Y, BRIDGE_Y0 - SPRING_Y
    c = WINDOW_CLEAR
    shape = None
    n = 14
    for i in range(n + 1):
        d = DELTA_MAX * i / n
        tab = local_box(o, ex, ez, (-TAB_W / 2 - c, TAB_W / 2 + c), (y0, y1), (-TAB_T, 0.0))
        sp = local_cyl(o, ez, SPIGOT_D + 2 * c, -0.1, SPIGOT_L + 0.3)
        piece = rot_y(tab.union(sp), -d)   # disc rotates CCW relative to the lever
        shape = piece if shape is None else shape.union(piece)
    return shape


def make() -> cq.Workplane:
    o, ex, ez = spring_frame()
    s_seat = spring_seat_s()
    s_back = s_of_delta(0.0) - TAB_T - BACKSTOP_T

    # ---- pocket block (spring frame), then carve the window, bore and slot
    block = local_box(o, ex, ez, (-POCKET_INNER_W, POCKET_HALF_W),
                      (POCKET_Y0 - SPRING_Y, POCKET_Y1 - SPRING_Y), (s_back, s_seat + END_WALL))
    block = block.edges("|Y").fillet(1.5)
    # thicken the outer side wall alongside the tab window (keeps it >= 1.8 mm)
    o_t, ex_t, ez_t = tab_frame()
    side = local_box(o_t, ex_t, ez_t, (POCKET_HALF_W - 1.0, TAB_W / 2 + WINDOW_CLEAR + 1.8),
                     (POCKET_Y0 - SPRING_Y, POCKET_Y1 - SPRING_Y), (-TAB_T - BACKSTOP_T, 5.0))
    block = block.union(side.edges("|Y").fillet(1.0))

    # ---- web plate joining the hub to the pocket (lever plate thickness)
    web = annular_sector_xz(0.0, 17.0, -24.0, 52.0, LEVER_Y0, LEVER_Y1)
    hub = ycyl(0, 0, LEVER_HUB_D, LEVER_Y0, LEVER_Y1)

    # ---- finger arm and blade
    a = math.radians(BLADE_ANGLE_OPEN)
    ux, uz = math.cos(a), math.sin(a)
    px, pz = -math.sin(a), math.cos(a)
    w0, w1 = LEVER_ARM_W / 2, LEVER_ARM_W / 2 - 0.5
    r0, r1 = 4.0, BLADE_R_IN + 5.0
    arm = xz_prism([
        (r0 * ux + px * w0, r0 * uz + pz * w0),
        (r1 * ux + px * w1, r1 * uz + pz * w1),
        (r1 * ux - px * w1, r1 * uz - pz * w1),
        (r0 * ux - px * w0, r0 * uz - pz * w0),
    ], LEVER_Y0, LEVER_Y1)

    # ---- hub shoulder and shaft through the 6700ZZ
    shoulder = ycyl(0, 0, HUB_SHOULDER_D, LEVER_Y1 - 0.5, BEARING_BOSS_Y0 + BEARING_LIP_T)
    shaft = ycyl(0, 0, B6700_ID - 0.02, BEARING_BOSS_Y0 + BEARING_LIP_T, HEAD_Y1)

    lever = block.union(web).union(hub).union(arm).union(shoulder).union(shaft)

    # ---- cut the window (swept tab), the spring bore and the assembly slot
    lever = lever.cut(tab_keepout())
    bore = local_cyl(o, ez, SPRING_BORE_D, s_of_delta(0.0) - 1.0, s_seat)
    slot = local_box(o, ex, ez, (-SPRING_BORE_D / 2, SPRING_BORE_D / 2),
                     (POCKET_Y0 - SPRING_Y - 1.0, 0.0), (s_of_delta(0.0), s_seat))
    lever = lever.cut(bore).cut(slot)
    # Floor spigot that captures the far end of the spring
    lever = lever.union(local_cyl(o, ez, SPIGOT_D, s_seat - SPIGOT_L, s_seat + 0.1))

    # ---- bearing pocket (MR63) for the pilot pin, magnet pocket in the shaft end
    lever = lever.cut(ycyl(0, 0, MR63_OD + FIT_PRESS, LEVER_Y0 - 0.1, LEVER_Y0 + MR63_W))
    lever = lever.cut(ycyl(0, 0, 3.6, LEVER_Y0 + MR63_W - 0.1, LEVER_Y1 + 0.5))
    lever = lever.cut(ycyl(0, 0, MAGNET_D + 0.1, HEAD_Y1 - MAGNET_T - 0.1, HEAD_Y1 + 0.1))
    # ---- v1.1: groove on the arm's +Y face for the LRA leads, from the blade socket to the hub
    lever = lever.cut(arm_wire_groove())
    # ---- two M2 heat-set inserts (Ø3.2 × 3.5) for the blade, entered from +Y
    for r in BLADE_SCREW_R:
        lever = lever.cut(ycyl(r * ux, r * uz, 3.2, LEVER_Y1 - 3.6, LEVER_Y1 + 0.1))
    return lever


BLADE_SCREW_R = (BLADE_R_IN + 1.5,)
GROOVE_R = 30.0


def blade_axes():
    """Unit vectors of the blade at the open stop: u = radial, p = tangential (finger side)."""
    a = math.radians(BLADE_ANGLE_OPEN)
    return (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))


def pad_face_offset() -> float:
    """Tangential offset of the scalloped finger face at r = R_FINGER (from the blade centreline)."""
    return BLADE_T / 2 - 1.2


def arm_wire_groove() -> cq.Workplane:
    (ux, uz), (px, pz) = blade_axes()
    r0, r1 = 8.5, BLADE_R_IN - 2.5
    w = WIRE_GROOVE_W / 2
    return xz_prism([(r0 * ux + px * w, r0 * uz + pz * w), (r1 * ux + px * w, r1 * uz + pz * w),
                     (r1 * ux - px * w, r1 * uz - pz * w), (r0 * ux - px * w, r0 * uz - pz * w)],
                    LEVER_Y1 - WIRE_GROOVE_D, LEVER_Y1 + 0.1)


def lra_pocket_axis():
    """(origin at the finger face on the pad centre, axis pointing into the blade)."""
    (ux, uz), (px, pz) = blade_axes()
    o = (R_FINGER * ux + px * pad_face_offset(), LRA_Y, R_FINGER * uz + pz * pad_face_offset())
    return o, (-px, 0.0, -pz)


def make_lra() -> cq.Workplane:
    o, ax = lra_pocket_axis()
    return local_cyl(o, ax, LRA_D, 0.0, LRA_T)


def make_skin() -> cq.Workplane:
    """TPU 95A skin bonded into the finger scallop; the LRA face touches its underside."""
    (ux, uz), (px, pz) = blade_axes()
    rm = R_FINGER
    gcx = rm * ux + px * (BLADE_T / 2 + GROOVE_R - 1.2)
    gcz = rm * uz + pz * (BLADE_T / 2 + GROOVE_R - 1.2)
    shell = ycyl(gcx, gcz, 2 * GROOVE_R, BLADE_Y0, LEVER_Y1 + 2.0).cut(
        ycyl(gcx, gcz, 2 * (GROOVE_R - SKIN_T), BLADE_Y0 - 1, LEVER_Y1 + 3))
    zone = annular_sector_xz(BLADE_R_IN + 7.7, BLADE_R_OUT - 0.3, BLADE_ANGLE_OPEN - 25, BLADE_ANGLE_OPEN + 25,
                             BLADE_Y0 + 0.3, LEVER_Y1 + 1.7)
    return shell.intersect(zone)


def make_blade() -> cq.Workplane:
    """Finger blade: a separate, swappable part that clamps over the end of the lever arm."""
    a = math.radians(BLADE_ANGLE_OPEN)
    ux, uz = math.cos(a), math.sin(a)
    px, pz = -math.sin(a), math.cos(a)
    half = math.degrees(math.atan2(BLADE_T / 2, (BLADE_R_IN + BLADE_R_OUT) / 2))
    blade = annular_sector_xz(BLADE_R_IN - 3.0, BLADE_R_OUT, BLADE_ANGLE_OPEN - half - 7.0,
                              BLADE_ANGLE_OPEN + half + 7.0, BLADE_Y0, LEVER_Y1 + 2.0)
    # slim the pad back to BLADE_T outside the arm socket
    keep = annular_sector_xz(BLADE_R_IN, BLADE_R_OUT, BLADE_ANGLE_OPEN - half, BLADE_ANGLE_OPEN + half,
                             BLADE_Y0, LEVER_Y1 + 2.0)
    socket_body = annular_sector_xz(BLADE_R_IN - 3.0, BLADE_R_IN + 7.0, BLADE_ANGLE_OPEN - half - 7.0,
                                    BLADE_ANGLE_OPEN + half + 7.0, LEVER_Y0 - 2.0, LEVER_Y1 + 2.0)
    blade = blade.intersect(keep.union(socket_body))
    # finger groove: a shallow concave scallop on the finger (CCW) face
    groove_r = 30.0
    rm = (BLADE_R_IN + BLADE_R_OUT) / 2
    gcx = rm * ux + px * (BLADE_T / 2 + groove_r - 1.2)
    gcz = rm * uz + pz * (BLADE_T / 2 + groove_r - 1.2)
    groove = ycyl(gcx, gcz, 2 * groove_r, BLADE_Y0 - 1, LEVER_Y1 + 3)
    # only the finger zone (outside the arm socket) gets the scallop
    groove = groove.intersect(annular_sector_xz(BLADE_R_IN + 7.5, BLADE_R_OUT + 5, BLADE_ANGLE_OPEN - 30,
                                                BLADE_ANGLE_OPEN + 30, BLADE_Y0 - 2, LEVER_Y1 + 4))
    blade = blade.cut(groove)
    # ---- v1.1: LRA pocket behind the pad centre, with a boss on the back face so the wall stays ≥ 2 mm
    o, ax = lra_pocket_axis()
    depth = LRA_T + LRA_TAPE
    back = BLADE_T / 2  # back face offset from the centreline
    boss_len = BLADE_BOSS_H
    blade = blade.union(local_cyl(o, ax, LRA_D + 4.0, pad_face_offset() + back - 0.2,
                                  pad_face_offset() + back + boss_len))
    blade = blade.cut(local_cyl(o, ax, LRA_D + 0.3, -1.0, depth))
    # lead exit: a Ø1.6 hole from the pocket floor along +Y to the top face, then a groove to the socket
    (ux, uz), (px, pz) = blade_axes()
    hx = R_FINGER * ux - px * 0.6
    hz = R_FINGER * uz - pz * 0.6
    blade = blade.cut(ycyl(hx, hz, 1.6, LRA_Y, LEVER_Y1 + 2.5))
    w = WIRE_GROOVE_W / 2
    r0, r1 = BLADE_R_IN - 3.5, R_FINGER + 0.8
    blade = blade.cut(xz_prism([(r0 * ux + px * w - px * 0.6, r0 * uz + pz * w - pz * 0.6),
                                (r1 * ux + px * w - px * 0.6, r1 * uz + pz * w - pz * 0.6),
                                (r1 * ux - px * w - px * 0.6, r1 * uz - pz * w - pz * 0.6),
                                (r0 * ux - px * w - px * 0.6, r0 * uz - pz * w - pz * 0.6)],
                               LEVER_Y1 + 2.0 - WIRE_GROOVE_D, LEVER_Y1 + 2.5))
    # socket for the lever arm end (+0.15 clearance) and the clamp screw
    w = LEVER_ARM_W / 2 - 0.5 + 0.15
    r0, r1 = BLADE_R_IN - 3.5, BLADE_R_IN + 5.2
    socket = xz_prism([
        (r0 * ux + px * w, r0 * uz + pz * w), (r1 * ux + px * w, r1 * uz + pz * w),
        (r1 * ux - px * w, r1 * uz - pz * w), (r0 * ux - px * w, r0 * uz - pz * w)],
        LEVER_Y0 - 0.15, LEVER_Y1 + 0.15)
    blade = blade.cut(socket)
    for r in BLADE_SCREW_R:
        blade = blade.cut(ycyl(r * ux, r * uz, 2.3, LEVER_Y1, LEVER_Y1 + 3))   # M2 × 6 low-head screw
    try:
        blade = blade.edges("|Y").fillet(0.8)
    except Exception:
        pass
    return blade
