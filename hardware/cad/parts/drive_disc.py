"""Drive disc: bolts to the XC330 horn and carries the spring tab.

A Ø3 × 8 dowel pressed (and glued) into the disc centre runs in an MR63 bearing in the
lever hub. That keeps the lever and disc coaxial without adding friction to the force path.

The disc is the servo-side half of the series-elastic actuator. Its tab sits in the
lever's window. The tab's rear face bears on the lever backstop (at preload), and its
front face carries a spigot that locates the spring.

Print: flat on the bed, horn face down (no supports). PETG preferred.
"""

import math

import cadquery as cq

from geom import local_box, local_cyl, tab_frame, ycyl, xz_prism
from params import (
    ALPHA_T, DELTA_MID, DISC_ARM_W, DISC_BOSS_Y1, DISC_D, DISC_Y0, DISC_Y1, FIT_PRESS,
    HORN_BOLT_D, HORN_BOLT_N, HORN_BOLT_PCD, HORN_CENTER_SCREW_D, PIN_D, R_T,
    SPIGOT_D, SPIGOT_L, SPRING_Y, TAB_T, TAB_W, TAB_Y0, TAB_Y1,
)


def make() -> cq.Workplane:
    disc = ycyl(0, 0, DISC_D, DISC_Y0, DISC_Y1)
    boss = ycyl(0, 0, 7.0, DISC_Y0, DISC_BOSS_Y1)

    # Arm from the hub out to the tab (in the disc plane)
    b = math.radians(ALPHA_T - DELTA_MID)
    r_end = R_T + TAB_W / 2
    ux, uz = math.cos(b), math.sin(b)          # radial
    px, pz = -math.sin(b), math.cos(b)         # tangential
    hw0, hw1 = DISC_ARM_W / 2 + 1.0, DISC_ARM_W / 2
    pts = [
        (0 + px * hw0, 0 + pz * hw0),
        (r_end * ux + px * hw1, r_end * uz + pz * hw1),
        (r_end * ux - px * (hw1 + TAB_T), r_end * uz - pz * (hw1 + TAB_T)),
        (0 - px * hw0, 0 - pz * hw0),
    ]
    arm = xz_prism(pts, DISC_Y0, DISC_Y1)

    o, ex, ez = tab_frame()
    tab = local_box(o, ex, ez, (-TAB_W / 2, TAB_W / 2), (TAB_Y0 - SPRING_Y, TAB_Y1 - SPRING_Y), (-TAB_T, 0.0))
    tab = tab.edges("|Y").fillet(0.8)
    spigot = local_cyl(o, ez, SPIGOT_D, -0.1, SPIGOT_L)

    part = disc.union(boss).union(arm).union(tab).union(spigot)

    # Press hole for the Ø3 pilot pin; the pin runs in the MR63 bearing in the lever hub
    part = part.cut(ycyl(0, 0, PIN_D - FIT_PRESS, DISC_Y0 + 1.2, DISC_BOSS_Y1 + 0.1))
    # Relief for the horn's centre screw head
    part = part.cut(ycyl(0, 0, HORN_CENTER_SCREW_D, DISC_Y0 - 0.1, DISC_Y0 + 1.2))
    # Horn bolts: M2 × 4 ISO 7380 button heads, counterbored 1.0 mm from the +Y face (1.8 mm seat)
    for i in range(HORN_BOLT_N):
        a = 2 * math.pi * i / HORN_BOLT_N + math.pi / 4
        x, z = HORN_BOLT_PCD / 2 * math.cos(a), HORN_BOLT_PCD / 2 * math.sin(a)
        part = part.cut(ycyl(x, z, HORN_BOLT_D, DISC_Y0 - 0.1, DISC_Y1 + 0.1))
        part = part.cut(ycyl(x, z, 4.2, DISC_Y1 - 1.0, DISC_Y1 + 0.1))   # ISO 7380 M2 button head (1.04 tall)
    return part
