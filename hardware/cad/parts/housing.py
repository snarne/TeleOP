"""Handle housing: head (servo, SEA and encoder) and raked pistol grip (electronics).

The housing is one closed shell, modelled as a whole and then split on the plane
y = SPLIT_Y into two clamshell halves:

* Servo half (y < SPLIT_Y): servo cradle, button-switch cradle, board rails, clearance
  and counterbores for the M2.5 clamshell screws.
* Encoder half (y > SPLIT_Y): the 6700ZZ bearing seat, encoder-cover bosses and heat-set
  inserts for the clamshell screws.

Both halves print split-face down with no supports, apart from small bridges over the
button holes and the lever slot. Use PETG (or PLA+) at 4 perimeters and 30 % gyroid infill.
"""

from __future__ import annotations

import math

import cadquery as cq

from geom import annular_sector_xz, local_cyl, xcyl, ycyl, zcyl, xz_prism
from params import (
    B6700_OD, BEARING_BOSS_Y0, BEARING_LIP_D, BEARING_LIP_T, BLADE_ANGLE_OPEN, BOSS_D,
    BUTTON_A_X, BUTTON_B_X, BUTTON_Y, CAP_STEM_D, D2F_H, D2F_L, D2F_W, FIT_PRESS, GRIP_BOT_Z,
    GRIP_CORNER_R, GRIP_CY, GRIP_DEPTH, GRIP_FRONT_X_TOP, GRIP_RAKE, GRIP_SHELL, GRIP_TOP_Z,
    GRIP_WIDTH, HEAD_FILLET, HEAD_X0, HEAD_X1, HEAD_Y0, HEAD_Y1, HEAD_Z0, HEAD_Z1, INNER_PY_WALL,
    INSERT_D, INSERT_L, LEVER_ARM_W, MOUNT_INSERT_PTS, PROTO_L, PROTO_T, PROTO_W, SERVO_AXIS_FROM_END,
    SERVO_L, SERVO_W, SHELL_SCREWS_XZ, SPLIT_Y, STOP_SLOT_Y0, STOP_SLOT_Y1, TRAVEL, USBC_H, USBC_W,
    WALL, WIRE_CLIP_ANG, WIRE_CLIP_R,
)

COVER_SCREWS_XZ = [(0.0, 14.2), (0.0, -14.2)]
CABLE_EXIT_YZ = (4.0, -12.0)   # clear of the mount inserts and the clamshell bosses
SERVO_CLEAR = 0.2


# ---------------------------------------------------------------------------- grip geometry


def grip_axis():
    """(top centre, bottom centre) of the grip loft."""
    top = (GRIP_FRONT_X_TOP - GRIP_DEPTH / 2, GRIP_CY, GRIP_TOP_Z)
    dz = GRIP_TOP_Z - GRIP_BOT_Z
    bot = (top[0] - dz * math.tan(math.radians(GRIP_RAKE)), GRIP_CY, GRIP_BOT_Z)
    return top, bot


def _grip_solid(inset: float, z_top_extra: float = 0.0, bottom_inset: float = 0.0) -> cq.Workplane:
    top, bot = grip_axis()
    z0 = bot[2] + bottom_inset
    z1 = top[2] + z_top_extra
    t = math.tan(math.radians(GRIP_RAKE))
    x_at = lambda z: top[0] - (top[2] - z) * t  # noqa: E731
    d0, w0 = GRIP_DEPTH - 2 * inset, GRIP_WIDTH - 2 * inset
    d1, w1 = GRIP_DEPTH - 2.0 - 2 * inset, GRIP_WIDTH - 2.0 - 2 * inset  # slight taper toward the bottom
    r0 = max(GRIP_CORNER_R - inset, 1.0)
    r1 = max(GRIP_CORNER_R - 1.0 - inset, 1.0)
    w_top = _rounded_rect_wire(d0, w0, r0, (x_at(z1), GRIP_CY, z1))
    w_bot = _rounded_rect_wire(d1, w1, r1, (x_at(z0), GRIP_CY, z0))
    solid = cq.Solid.makeLoft([w_bot, w_top], True)
    return cq.Workplane("XY").add(solid)


def _rounded_rect_wire(dx: float, dy: float, r: float, at) -> cq.Wire:
    face = cq.Sketch().rect(dx, dy).vertices().fillet(r)._faces.Faces()[0]
    return face.outerWire().translate(cq.Vector(*at))


def _head_solid(inset: float, py_inset: float | None = None) -> cq.Workplane:
    py = inset if py_inset is None else py_inset
    x0, x1 = HEAD_X0 + inset, HEAD_X1 - inset
    y0, y1 = HEAD_Y0 + inset, HEAD_Y1 - py
    z0, z1 = HEAD_Z0 + inset, HEAD_Z1 - inset
    box = cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    r = max(HEAD_FILLET - inset, 0.8)
    return box.edges().fillet(r)


# ---------------------------------------------------------------------------- the shell


def make_shell() -> cq.Workplane:
    outer = _head_solid(0.0).union(_grip_solid(0.0))
    inner = _head_solid(WALL, py_inset=HEAD_Y1 - INNER_PY_WALL).union(
        _grip_solid(GRIP_SHELL, z_top_extra=-1.8, bottom_inset=2.4))
    shell = outer.cut(inner)

    # ---------------- internal features (added before the holes are cut)
    feats = []
    # bearing boss on the +Y wall
    feats.append(ycyl(0, 0, B6700_OD + 6.0, BEARING_BOSS_Y0, INNER_PY_WALL + 0.5))
    # encoder-cover screw bosses
    for x, z in COVER_SCREWS_XZ:
        feats.append(ycyl(x, z, 6.6, BEARING_BOSS_Y0 + 1.0, INNER_PY_WALL + 0.5))
    # mount insert bosses on the back wall
    for y, z in MOUNT_INSERT_PTS:
        feats.append(xcyl(y, z, BOSS_D, HEAD_X0 + WALL - 0.5, HEAD_X0 + WALL + INSERT_L + 1.0))
    # clamshell screw bosses (span the cavity in Y)
    for x, z in shell_screws():
        y0, y1 = _cavity_y_extent(x, z)
        feats.append(ycyl(x, z, BOSS_D, y0 - 0.5, y1 + 0.5))
    # servo cradle: bottom posts, rear rib, front rib (servo half only, y < SPLIT_Y)
    sx0 = -SERVO_AXIS_FROM_END
    sx1 = sx0 + SERVO_L
    zb = -SERVO_W / 2 - SERVO_CLEAR
    for xa, xb in ((-6.0, 0.0), (13.0, 19.0)):
        feats.append(_box(xa, xb, -22.0, -8.0, HEAD_Z0 + WALL - 0.5, zb))
    feats.append(_box(HEAD_X0 + WALL - 0.5, sx0 - SERVO_CLEAR, -24.0, -6.0, -8.0, 8.0))
    for ya, yb in ((-25.0, -19.0), (-7.0, -3.2)):   # front ribs, clear of the servo connectors
        feats.append(_box(sx1 + SERVO_CLEAR, HEAD_X1 - WALL + 0.5, ya, yb, -6.5, 6.5))
    # button-switch cradle: block between servo top and top wall with downward pockets
    zt = SERVO_W / 2 + SERVO_CLEAR
    cradle = _box(-9.5, 14.5, BUTTON_Y - D2F_L / 2 - 1.8, BUTTON_Y + D2F_L / 2 + 1.8, zt, HEAD_Z1 - WALL + 0.5)
    for bx in (BUTTON_A_X, BUTTON_B_X):
        cradle = cradle.cut(_box(bx - D2F_W / 2 - 0.15, bx + D2F_W / 2 + 0.15, BUTTON_Y - D2F_L / 2 - 0.15,
                                 BUTTON_Y + D2F_L / 2 + 0.15, zt - 0.1, zt + D2F_H - 0.9 + 0.05))
        cradle = cradle.cut(_box(bx - 4.0, bx + 4.0, BUTTON_Y - 6.0, BUTTON_Y + 6.0, zt + D2F_H - 0.9,
                                 HEAD_Z1))  # room for the cap flange
    cradle = cradle.cut(_box(-9.6, 14.6, BUTTON_Y - 1.5, BUTTON_Y + 1.5, zt - 0.1, zt + 2.0))  # wire channel
    feats.append(cradle)
    # protoboard rails in the grip (servo half)
    feats += _board_rails()
    # v1.1: strain-relief post for the LRA leads, near the pivot (encoder half, outside the lever sweep)
    feats.append(wire_clip())
    for f in feats:
        shell = shell.union(f)
    # keep features from protruding outside the skin
    shell = shell.intersect(outer)

    # ---------------- holes and openings
    # 6700 seat (inserted from outside against the inner lip) and lip bore
    y_seat0 = BEARING_BOSS_Y0 + BEARING_LIP_T
    shell = shell.cut(ycyl(0, 0, B6700_OD + FIT_PRESS, y_seat0, HEAD_Y1 + 0.1))
    shell = shell.cut(ycyl(0, 0, BEARING_LIP_D, BEARING_BOSS_Y0 - 0.1, y_seat0 + 0.01))
    # encoder-cover inserts (M2 heat-set, Ø3.2 × 3.5)
    for x, z in COVER_SCREWS_XZ:
        shell = shell.cut(ycyl(x, z, 3.2, HEAD_Y1 - 3.8, HEAD_Y1 + 0.1))
    # mount inserts (M2.5) in the back wall
    for y, z in MOUNT_INSERT_PTS:
        shell = shell.cut(xcyl(y, z, INSERT_D, HEAD_X0 - 0.1, HEAD_X0 + INSERT_L))
    # cable exit for the 5 V lead from the leader J6 port
    shell = shell.cut(xcyl(CABLE_EXIT_YZ[0], CABLE_EXIT_YZ[1], 5.0, HEAD_X0 - 0.1, HEAD_X0 + WALL + 2))
    # lever slot + travel stops in the head floor
    shell = shell.cut(stop_slot())
    # button holes (oblong) in the top wall
    for bx in (BUTTON_A_X, BUTTON_B_X):
        shell = shell.cut(_box(bx - 2.5, bx + 2.5, BUTTON_Y - 4.5, BUTTON_Y + 4.5, HEAD_Z1 - WALL - 0.5,
                               HEAD_Z1 + 0.5).edges("|Z").fillet(2.0))
    # USB-C opening at the grip bottom
    shell = shell.cut(usb_cutout())
    return shell


def _box(x0, x1, y0, y1, z0, z1) -> cq.Workplane:
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))


def shell_screws():
    """Head screws from params plus two grip screws placed clear of the electronics board."""
    top, bot = grip_axis()
    t = math.tan(math.radians(GRIP_RAKE))
    pts = list(SHELL_SCREWS_XZ)
    z_up = -40.0
    pts.append((top[0] - (top[2] - z_up) * t, z_up))          # above the board, on the grip axis
    z_lo = GRIP_BOT_Z + 2.4 + 4.0
    cx = top[0] - (top[2] - z_lo) * t
    pts.append((cx - 6.0 * math.cos(math.radians(GRIP_RAKE)), z_lo + 6.0 * math.sin(math.radians(GRIP_RAKE))))
    return pts


def _cavity_y_extent(x: float, z: float):
    if z > GRIP_TOP_Z + 2:      # head
        return HEAD_Y0 + WALL, INNER_PY_WALL
    return GRIP_CY - GRIP_WIDTH / 2 + GRIP_SHELL, GRIP_CY + GRIP_WIDTH / 2 - GRIP_SHELL


def wire_clip() -> cq.Workplane:
    a = math.radians(WIRE_CLIP_ANG)
    x, z = WIRE_CLIP_R * math.cos(a), WIRE_CLIP_R * math.sin(a)
    post = ycyl(x, z, 4.5, 13.6, INNER_PY_WALL + 0.5)
    # slot across the post tip that holds the two leads (glue or a cable tie)
    slot = cq.Workplane("XY").box(1.3, 3.0, 6.0).translate((x, 14.9, z)).rotate((x, 0, z), (x, 1, z),
                                                                               -WIRE_CLIP_ANG)
    return post.cut(slot)


def stop_slot() -> cq.Workplane:
    """Sector cut in the head floor for the lever arm. Its ends are the open and closed stops."""
    # The arm edge sits at half-width w at radius r; the sector boundary at the floor radius
    # is offset by atan(w / r) so the arm edge lands on it at phi = 0 and phi = TRAVEL.
    r_in = abs(HEAD_Z0) - WALL                      # inner floor surface (horizontal)
    w = LEVER_ARM_W / 2 - 0.1                       # arm half-width where it crosses the floor
    a_open_c = BLADE_ANGLE_OPEN
    a_closed_c = BLADE_ANGLE_OPEN - TRAVEL
    r_o = r_in / abs(math.sin(math.radians(a_open_c)))
    r_c = r_in / abs(math.sin(math.radians(a_closed_c)))
    a_open = a_open_c + math.degrees(math.asin(w / r_o))
    a_closed = a_closed_c - math.degrees(math.asin(w / r_c))
    return annular_sector_xz(abs(HEAD_Z0) - WALL - 2.0, 80.0, a_closed, a_open, STOP_SLOT_Y0, STOP_SLOT_Y1)


def board_frame():
    """Placement of the protoboard in the grip: origin, long axis (down the grip), normal (+Y)."""
    top, bot = grip_axis()
    ax = (bot[0] - top[0], 0.0, bot[2] - top[2])
    n = math.hypot(ax[0], ax[2])
    ax = (ax[0] / n, 0.0, ax[2] / n)
    length = math.hypot(bot[0] - top[0], bot[2] - top[2])
    # board centred along the grip, its bottom end 5 mm above the inner bottom
    c = 2.4 + 9.0 + PROTO_L / 2
    origin = (bot[0] - ax[0] * c, -12.4, bot[2] - ax[2] * c)
    # board local x points DOWN the grip so the XIAO (at local -x end) sits ... flip: use -ax
    xdir = (-ax[0], 0.0, -ax[2])
    return origin, xdir, (0.0, 1.0, 0.0), length


def _board_rails():
    origin, xdir, normal, _ = board_frame()
    rails = []
    # two pairs of slotted clips gripping the long edges of the board
    for side in (-1, 1):
        for along in (-PROTO_L / 2 + 8, PROTO_L / 2 - 8):
            # edge position: perpendicular to xdir within the XZ plane
            px, pz = -xdir[2], xdir[0]
            cx = origin[0] + xdir[0] * along + px * side * (PROTO_W / 2 + 0.6)
            cz = origin[2] + xdir[2] * along + pz * side * (PROTO_W / 2 + 0.6)
            y_wall = GRIP_CY - GRIP_WIDTH / 2 + GRIP_SHELL - 0.5
            clip = _box(cx - 3.0, cx + 3.0, y_wall, origin[1] + PROTO_T + 1.2, cz - 2.2, cz + 2.2)
            clip = clip.cut(_box(cx - 3.5, cx + 3.5, origin[1] - 0.1, origin[1] + PROTO_T + 0.15, cz - 3, cz + 3)
                            .translate((-px * side * 1.4, 0, -pz * side * 1.4)))
            rails.append(clip)
    return rails


def usb_cutout() -> cq.Workplane:
    origin, xdir, normal, _ = board_frame()
    end = (origin[0] - xdir[0] * (PROTO_L / 2 + 0.5), origin[2] - xdir[2] * (PROTO_L / 2 + 0.5))
    y = origin[1] + PROTO_T + 2.5 + 1.2 + (USBC_H - 0.7) / 2
    axis = (-xdir[0], 0.0, -xdir[2])
    pl = cq.Plane(origin=(end[0], y, end[1]), xDir=(0, 1, 0), normal=axis)
    return (cq.Workplane(pl).sketch().rect(USBC_H + 1.0, USBC_W + 1.0).vertices().fillet(1.4).finalize()
            .extrude(12.0)).translate(
        cq.Vector(*axis) * -2.0)


# ---------------------------------------------------------------------------- halves


def split(shell: cq.Workplane):
    big = 400.0
    neg = _box(-big, big, -big, SPLIT_Y, -big, big)
    pos = _box(-big, big, SPLIT_Y, big, -big, big)
    servo_half = shell.intersect(neg)
    enc_half = shell.intersect(pos)
    for x, z in shell_screws():
        y0, _ = _cavity_y_extent(x, z)
        outer_y = HEAD_Y0 if z > GRIP_TOP_Z + 2 else GRIP_CY - GRIP_WIDTH / 2
        # servo half: Ø2.8 clearance through, Ø5 counterbore to 11 mm from the split
        servo_half = servo_half.cut(ycyl(x, z, 2.8, outer_y - 1, SPLIT_Y + 0.1))
        servo_half = servo_half.cut(ycyl(x, z, 5.0, outer_y - 1, SPLIT_Y - 11.0))
        # encoder half: M2.5 heat-set insert
        enc_half = enc_half.cut(ycyl(x, z, INSERT_D, SPLIT_Y - 0.1, SPLIT_Y + INSERT_L))
    return servo_half, enc_half


def make():
    return split(make_shell())
