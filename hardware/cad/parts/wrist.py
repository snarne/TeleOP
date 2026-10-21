"""Simplified leader-arm wrist for the placement render: J6 (roll, axis +X) and J5 (pitch,
axis +Y) XL330-sized servo blocks, the printed yoke between them, and a forearm stub.

These are not printable parts. They only show where the HGM sits on a GELLO-style
3D-printed YAM replica.
"""

import cadquery as cq

from geom import xcyl, ycyl
from params import J6_AXIS_YZ
from parts.mount_adapter import j6_face_x

XL_W, XL_L, XL_D = 20.0, 34.0, 26.0   # XL330: W × L × D (D along the output axis)
AXIS_FROM_END = 10.0


def _box(x0, x1, y0, y1, z0, z1, r=1.2):
    b = cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    return b.edges().fillet(r) if r else b


def make():
    yc, zc = J6_AXIS_YZ
    xf = j6_face_x()
    # J6: horn faces +X at xf, body behind; axis 10 mm from the body's lower end (body extends upward)
    j6 = _box(xf - 3.0 - XL_D, xf - 3.0, yc - XL_W / 2, yc + XL_W / 2, zc - AXIS_FROM_END, zc - AXIS_FROM_END + XL_L)
    j6_horn = xcyl(yc, zc, 16.0, xf - 3.0, xf)
    # J5: pitch axis along Y, sitting behind J6; its horn drives the yoke that carries J6
    x5 = xf - 3.0 - XL_D - 26.0          # J5 axis x
    z5 = zc + 4.0
    j5 = _box(x5 - (XL_L - AXIS_FROM_END), x5 + AXIS_FROM_END, yc - XL_D / 2 - 3.0, yc + XL_D / 2 - 3.0,
              z5 - XL_W / 2, z5 + XL_W / 2)
    j5_horn = ycyl(x5, z5, 16.0, yc + XL_D / 2 - 3.0, yc + XL_D / 2)
    # yoke: side plate on the J5 horn + back plate bolted to J6
    side = _box(x5 - 10.0, xf - 3.0 - XL_D + 4.0, yc + XL_D / 2, yc + XL_D / 2 + 4.0, z5 - 12.0, z5 + 14.0, r=1.0)
    back = _box(xf - 3.0 - XL_D - 4.0, xf - 3.0 - XL_D, yc - XL_W / 2 - 2.0, yc + XL_D / 2 + 4.0,
                zc - AXIS_FROM_END + 2.0, zc - AXIS_FROM_END + XL_L - 2.0, r=1.0)
    forearm = _box(x5 - (XL_L - AXIS_FROM_END) - 90.0, x5 - (XL_L - AXIS_FROM_END) + 2.0, yc - 12.0, yc + 12.0,
                   z5 - 9.0, z5 + 9.0, r=3.0)
    servos = j6.union(j5)
    horns = j6_horn.union(j5_horn)
    printed = side.union(back).union(forearm)
    return servos, horns, printed
