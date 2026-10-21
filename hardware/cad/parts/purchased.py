"""Simplified models of purchased parts, used for fit checks, renders and mass budget.

Masses (g) come from the datasheets or measured typical values.
"""

import math

import cadquery as cq

from geom import local_cyl, s_of_delta, spring_frame, ycyl, zcyl
from params import (
    AS5600_AIR_GAP, AS5600_BOARD, AS5600_BOARD_T, B6700_ID, B6700_OD, B6700_W, BEARING_BOSS_Y0,
    BEARING_LIP_T, D2F_H, D2F_L, D2F_W, HEAD_Y1, HORN_D, HORN_T, LEVER_Y0, MAGNET_D, MAGNET_T,
    MR63_ID, MR63_OD, MR63_W, PIN_D, PIN_L, DISC_Y0, SERVO_AXIS_FROM_END, SERVO_D, SERVO_L,
    SERVO_W, SPRING_L0, SPRING_OD, SPRING_PRELOAD, SPRING_WIRE, SPRING_N_TOTAL,
    PROTO_L, PROTO_T, PROTO_W, XIAO_L, XIAO_T, XIAO_W, USBC_W, USBC_H,
)

MASS_G = {
    "XC330-M288-T servo + horn": 23.0 + 1.0,
    "6700ZZ bearing": 2.3,
    "MR63ZZ bearing": 0.3,
    "Ø3×8 dowel pin": 0.45,
    "Magnet Ø6×2.5 N52": 0.53,
    "Compression spring": 0.35,
    "AS5600 breakout": 1.8,
    "Seeed XIAO RP2040": 3.0,
    "Protoboard + 74LVC2G241 + passives": 6.0,
    "2× Omron D2F-01": 2 * 0.5,
    "Screws, inserts (M2/M2.5)": 6.0,
    "Wiring (USB pigtail in grip, JST leads)": 5.0,
    "v1.1: LRA Ø8 × 3.2 + tape": 0.9,
    "v1.1: DRV2605L + passives on the protoboard": 0.4,
    "v1.1: LRA leads (2 × 30 AWG, 0.25 m)": 0.6,
}


def servo_body() -> cq.Workplane:
    x0 = -SERVO_AXIS_FROM_END
    body = (cq.Workplane("XY").box(SERVO_L, SERVO_D, SERVO_W)
            .translate((x0 + SERVO_L / 2, -SERVO_D / 2, 0)).edges("|Y").fillet(1.5))
    # moulded bump around the output, connector blocks at the front end
    body = body.union(ycyl(0, 0, 13.0, -0.6, 0.0).translate((0, 0, 0)))
    for z in (-5.5, 5.5):
        body = body.union(cq.Workplane("XY").box(4.0, 7.5, 6.0).translate((x0 + SERVO_L + 1.0, -13.0, z)))
    return body


def servo_horn() -> cq.Workplane:
    horn = ycyl(0, 0, HORN_D, 0.0, HORN_T)
    for i in range(4):
        a = math.pi / 4 + i * math.pi / 2
        horn = horn.cut(ycyl(5.5 * math.cos(a), 5.5 * math.sin(a), 1.8, -0.1, HORN_T + 0.1))
    return horn.cut(ycyl(0, 0, 3.0, HORN_T - 1.0, HORN_T + 0.1))


def ring(od: float, id_: float, y0: float, w: float) -> cq.Workplane:
    return ycyl(0, 0, od, y0, y0 + w).cut(ycyl(0, 0, id_, y0 - 0.1, y0 + w + 0.1))


def bearing_6700() -> cq.Workplane:
    y0 = BEARING_BOSS_Y0 + BEARING_LIP_T
    return ring(B6700_OD, B6700_ID, y0, B6700_W).cut(ring(13.4, 11.6, y0 - 0.1, 0.4)).cut(
        ring(13.4, 11.6, y0 + B6700_W - 0.3, 0.4))


def bearing_mr63() -> cq.Workplane:
    return ring(MR63_OD, MR63_ID, LEVER_Y0, MR63_W)


def pin() -> cq.Workplane:
    return ycyl(0, 0, PIN_D, DISC_Y0 + 1.2, DISC_Y0 + 1.2 + PIN_L)


def magnet() -> cq.Workplane:
    m = ycyl(0, 0, MAGNET_D, HEAD_Y1 - MAGNET_T, HEAD_Y1)
    # show the diametric magnetisation as a two-tone split (N half)
    return m


def spring(compression_mm: float) -> cq.Workplane:
    """Helical compression spring between the tab face and the pocket floor (lever frame)."""
    o, ex, ez = spring_frame()
    s0 = s_of_delta(0.0)
    length = SPRING_L0 - SPRING_PRELOAD - (compression_mm - SPRING_PRELOAD)
    s_seat = s0 + SPRING_L0 - SPRING_PRELOAD
    start = s_seat - length
    r = (SPRING_OD - SPRING_WIRE) / 2
    pitch = length / (SPRING_N_TOTAL - 1)
    helix = cq.Wire.makeHelix(pitch, length - SPRING_WIRE, r)
    plane = cq.Plane(origin=cq.Vector(*o) + cq.Vector(*ez) * (start + SPRING_WIRE / 2), xDir=cq.Vector(*ex),
                     normal=cq.Vector(*ez))
    helix = helix.transformShape(plane.rG)
    p0 = helix.startPoint()
    t0 = helix.tangentAt(0)
    prof = cq.Wire.makeCircle(SPRING_WIRE / 2, p0, t0)
    solid = cq.Solid.sweep(prof, [], helix, isFrenet=True)
    return cq.Workplane("XY").add(solid)


def as5600_board() -> cq.Workplane:
    yb = HEAD_Y1 + AS5600_AIR_GAP + 1.5   # chip height 1.5 mm
    b = cq.Workplane("XY").box(AS5600_BOARD, AS5600_BOARD_T, AS5600_BOARD).translate(
        (0, yb + AS5600_BOARD_T / 2, 0))
    chip = cq.Workplane("XY").box(4.9, 1.5, 3.9).translate((0, yb - 0.75, 0))
    return b.union(chip)


def as5600_chip_y() -> float:
    return HEAD_Y1 + AS5600_AIR_GAP


def d2f_switch(x: float, y: float, z_bottom: float) -> cq.Workplane:
    body = cq.Workplane("XY").box(D2F_W, D2F_L, D2F_H - 0.9).translate((x, y, z_bottom + (D2F_H - 0.9) / 2))
    act = zcyl(x, y + 1.5, 1.6, z_bottom + D2F_H - 0.9, z_bottom + D2F_H)
    return body.union(act)


def protoboard_with_xiao(origin, xdir, normal) -> cq.Workplane:
    """Protoboard lying in a plane; board long axis = xdir, components on +normal side."""
    pl = cq.Plane(origin=cq.Vector(*origin), xDir=cq.Vector(*xdir), normal=cq.Vector(*normal))
    wp = cq.Workplane(pl)
    board = wp.rect(PROTO_L, PROTO_W).extrude(PROTO_T)
    # XIAO at the board end (x = -PROTO_L/2 side), USB-C overhanging the board edge
    xc = -PROTO_L / 2 + XIAO_L / 2 + 0.5
    xiao = cq.Workplane(pl).center(xc, 0).rect(XIAO_L, XIAO_W).extrude(XIAO_T + 2.5).translate(
        cq.Vector(*normal) * (PROTO_T + 2.5))
    usb = cq.Workplane(pl).center(-PROTO_L / 2 - 0.5, 0).rect(7.5, USBC_W - 0.8).extrude(USBC_H - 0.7).translate(
        cq.Vector(*normal) * (PROTO_T + 2.5 + XIAO_T))
    ic = cq.Workplane(pl).center(PROTO_L / 2 - 10, 4).rect(3.0, 3.0).extrude(1.0).translate(
        cq.Vector(*normal) * PROTO_T)
    cap = cq.Workplane(pl).center(PROTO_L / 2 - 6, -6).circle(3.15).extrude(7.0).translate(
        cq.Vector(*normal) * PROTO_T)
    return board.union(xiao).union(usb).union(ic).union(cap)
