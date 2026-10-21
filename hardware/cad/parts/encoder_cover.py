"""Encoder cover: holds the AS5600 breakout chip-down over the lever magnet and clamps
the 6700ZZ outer race.

The cup's inner rim presses the bearing outer race against the housing lip, so the bearing
is retained without glue. The board drops into a pocket and is held by two M2 screws, or a
dab of hot glue if your breakout has no holes. The air gap is set by the pocket depth
(AS5600_AIR_GAP).

Print: open side up, no supports.
"""

import cadquery as cq

from geom import ycyl
from params import (AS5600_AIR_GAP, AS5600_BOARD, AS5600_BOARD_T, B6700_OD, COVER_T, HEAD_Y1)

COVER_HALF = 13.3
EAR_Z = 14.2
FLOOR = 2.0


def make() -> cq.Workplane:
    y0 = HEAD_Y1
    y1 = HEAD_Y1 + COVER_T
    body = (cq.Workplane("XZ", origin=(0, y0, 0)).rect(2 * COVER_HALF, 2 * COVER_HALF).extrude(-COVER_T)
            .edges("|Y").fillet(1.8))
    for z in (EAR_Z, -EAR_Z):
        body = body.union(ycyl(0, z, 6.0, y0, y0 + 3.0))
        body = body.union(cq.Workplane("XY").box(6.0, 3.0, abs(z) - COVER_HALF + 3.0).translate(
            (0, y0 + 1.5, (z / abs(z)) * (COVER_HALF + (abs(z) - COVER_HALF + 3.0) / 2 - 3.0))))
    # board pocket: board back face rests on the cup floor
    chip_y = HEAD_Y1 + AS5600_AIR_GAP
    board_y0 = chip_y + 1.5
    floor_y = board_y0 + AS5600_BOARD_T
    pocket = cq.Workplane("XY").box(AS5600_BOARD + 0.4, floor_y - y0 + 0.1, AS5600_BOARD + 0.4).translate(
        (0, (y0 - 0.1 + floor_y) / 2, 0))
    body = body.cut(pocket)
    # make sure the floor is at least FLOOR thick
    assert y1 - floor_y >= FLOOR - 1e-6, f"cover floor too thin: {y1 - floor_y:.2f}"
    # bearing clamp ring: touches the outer race only
    body = body.union(ycyl(0, 0, B6700_OD + 1.6, y0, y0 + 1.6).cut(ycyl(0, 0, 12.4, y0 - 0.1, y0 + 1.7)))
    # wire exit and screw holes
    body = body.cut(cq.Workplane("XY").box(8.0, 2.4, 6.0).translate((COVER_HALF - 1.0, floor_y - 1.2, 0)))
    for z in (EAR_Z, -EAR_Z):
        body = body.cut(ycyl(0, z, 2.3, y0 - 0.1, y1 + 0.1))
        body = body.cut(ycyl(0, z, 4.2, y0 + 2.0, y1 + 0.1))
    return body
