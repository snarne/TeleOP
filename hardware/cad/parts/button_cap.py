"""Thumb-button cap: an oblong plunger through the top wall with a retaining flange inside.
It presses an Omron D2F-01 micro switch held in the cradle below.

Print: flange down, two caps per handle (A and B). TPU 95A gives a soft feel; PETG works too.
"""

import cadquery as cq

from params import BUTTON_Y, D2F_H, HEAD_Z1, SERVO_W, WALL

PAD_X, PAD_Y = 4.5, 8.5        # through the 5 × 9 hole
FLANGE_X, FLANGE_Y, FLANGE_T = 7.5, 11.5, 1.0
PROUD = 1.8                    # how far the cap stands above the top surface


def z_flange_bottom() -> float:
    switch_top = SERVO_W / 2 + 0.2 + D2F_H
    return switch_top + 0.1


def make(x: float) -> cq.Workplane:
    z0 = z_flange_bottom()
    flange = (cq.Workplane("XY", origin=(x, BUTTON_Y, z0)).rect(FLANGE_X, FLANGE_Y).extrude(FLANGE_T)
              .edges("|Z").fillet(1.5))
    top = HEAD_Z1 + PROUD
    pad = (cq.Workplane("XY", origin=(x, BUTTON_Y, z0 + FLANGE_T)).rect(PAD_X, PAD_Y)
           .extrude(top - z0 - FLANGE_T).edges("|Z").fillet(2.0))
    pad = pad.faces(">Z").edges().fillet(1.2)
    return flange.union(pad)


def wall_inner_z() -> float:
    return HEAD_Z1 - WALL
