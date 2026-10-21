"""Mount adapter: joins the HGM back face to the leader arm's J6 output horn.

Both bolt patterns are parametric. Measure your J6 horn like this:
  1. Count the tapped holes (J6_HORN_BOLT_N).
  2. With calipers, measure across two opposite holes, outer edge to outer edge (A) and
     inner edge to inner edge (B). Then J6_HORN_BOLT_PCD = (A + B) / 2.
  3. Set J6_HORN_RELIEF_D to clear the horn's raised centre boss or centre screw head.
  4. If the holes aren't on one circle, edit `horn_holes()` below.

Assembly order: (1) screw the adapter hub to the J6 horn with M2 × 6 from the housing
side, (2) screw the housing to the adapter flange with 4 × M2.5 × 8 from the J6 side.
The 5 V lead from J6's free JST-EH port passes through the cable hole.

Print: flange face down, no supports. PETG.
"""

import math

import cadquery as cq

from geom import xcyl
from params import (HEAD_X0, J6_AXIS_YZ, J6_HORN_BOLT_D, J6_HORN_BOLT_N, J6_HORN_BOLT_PCD,
                    J6_HORN_RELIEF_D, MOUNT_INSERT_PTS, MOUNT_STANDOFF, MOUNT_T)

FLANGE_Y = (-22.0, 16.0)
FLANGE_Z = (-19.0, 24.5)
HUB_D = 26.0
CABLE_YZ = (4.0, -12.0)


def horn_holes():
    y0, z0 = J6_AXIS_YZ
    for i in range(J6_HORN_BOLT_N):
        a = 2 * math.pi * i / J6_HORN_BOLT_N + math.pi / 4
        yield y0 + J6_HORN_BOLT_PCD / 2 * math.cos(a), z0 + J6_HORN_BOLT_PCD / 2 * math.sin(a)


def j6_face_x() -> float:
    return HEAD_X0 - MOUNT_T - MOUNT_STANDOFF


def make() -> cq.Workplane:
    x1 = HEAD_X0
    x0 = HEAD_X0 - MOUNT_T
    flange = (cq.Workplane("YZ", origin=(x0, 0, 0))
              .center((FLANGE_Y[0] + FLANGE_Y[1]) / 2, (FLANGE_Z[0] + FLANGE_Z[1]) / 2)
              .rect(FLANGE_Y[1] - FLANGE_Y[0], FLANGE_Z[1] - FLANGE_Z[0]).extrude(MOUNT_T)
              .edges("|X").fillet(4.0))
    hub = xcyl(J6_AXIS_YZ[0], J6_AXIS_YZ[1], HUB_D, j6_face_x(), x0 + 0.1)
    part = flange.union(hub)
    # lightening + stiffening: a shallow pocket on the J6 side of the flange around the hub
    # housing screws: counterbored from the J6 side
    for y, z in MOUNT_INSERT_PTS:
        part = part.cut(xcyl(y, z, 2.8, x0 - 0.1, x1 + 0.1))
        part = part.cut(xcyl(y, z, 5.0, x0 - 0.1, x0 + 2.4))
    # J6 horn bolts, counterbored from the housing side
    for y, z in horn_holes():
        part = part.cut(xcyl(y, z, J6_HORN_BOLT_D, j6_face_x() - 0.1, x1 + 0.1))
        part = part.cut(xcyl(y, z, 4.0, x1 - 3.0, x1 + 0.1))
    part = part.cut(xcyl(J6_AXIS_YZ[0], J6_AXIS_YZ[1], J6_HORN_RELIEF_D, j6_face_x() - 0.1, j6_face_x() + 1.5))
    # cable hole
    part = part.cut(xcyl(CABLE_YZ[0], CABLE_YZ[1], 5.0, x0 - 0.1, x1 + 0.1))
    return part
