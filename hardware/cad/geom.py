"""Small geometry helpers shared by the part modules."""

from __future__ import annotations

import math
from typing import Sequence, Tuple

import cadquery as cq

from params import ALPHA_T, DELTA_MID, R_T, SPRING_Y

Vec3 = Tuple[float, float, float]
Y_AXIS = ((0, 0, 0), (0, 1, 0))


def unit(v: Sequence[float]) -> cq.Vector:
    return cq.Vector(*v).normalized()


def local_box(origin: Vec3, ex: Vec3, ez: Vec3, a: Tuple[float, float], b: Tuple[float, float],
              c: Tuple[float, float]) -> cq.Workplane:
    """Box spanning [a] along ex, [b] along ey = ez × ex, [c] along ez, all in a local frame."""
    exv, ezv = unit(ex), unit(ez)
    plane = cq.Plane(origin=cq.Vector(*origin) + ezv * c[0], xDir=exv, normal=ezv)
    return (
        cq.Workplane(plane)
        .center((a[0] + a[1]) / 2, (b[0] + b[1]) / 2)
        .rect(a[1] - a[0], b[1] - b[0])
        .extrude(c[1] - c[0])
    )


def local_cyl(origin: Vec3, axis: Vec3, d: float, z0: float, z1: float, xdir: Vec3 | None = None) -> cq.Workplane:
    axv = unit(axis)
    if xdir is None:
        xdir = (1, 0, 0) if abs(axv.x) < 0.9 else (0, 1, 0)
    plane = cq.Plane(origin=cq.Vector(*origin) + axv * z0, xDir=cq.Vector(*xdir), normal=axv)
    return cq.Workplane(plane).circle(d / 2).extrude(z1 - z0)


def ycyl(x: float, z: float, d: float, y0: float, y1: float) -> cq.Workplane:
    """Cylinder parallel to +Y through (x, z)."""
    return local_cyl((x, 0, z), (0, 1, 0), d, y0, y1, xdir=(1, 0, 0))


def xcyl(y: float, z: float, d: float, x0: float, x1: float) -> cq.Workplane:
    return local_cyl((0, y, z), (1, 0, 0), d, x0, x1, xdir=(0, 1, 0))


def zcyl(x: float, y: float, d: float, z0: float, z1: float) -> cq.Workplane:
    return local_cyl((x, y, 0), (0, 0, 1), d, z0, z1, xdir=(1, 0, 0))


def xz_prism(points_xz: Sequence[Tuple[float, float]], y0: float, y1: float) -> cq.Workplane:
    """Extrude a closed polygon drawn in the XZ plane along +Y from y0 to y1."""
    # The XZ workplane's normal is -Y, so draw on a custom plane with normal +Y and xDir +X:
    # local (u, v) = (x, -z)... avoid confusion by using an explicit plane: xDir = +X, normal = +Y
    # → yDir = normal × xDir = (0,1,0)×(1,0,0) = (0,0,-1). So local v = -z.
    plane = cq.Plane(origin=(0, y0, 0), xDir=(1, 0, 0), normal=(0, 1, 0))
    pts = [(x, -z) for x, z in points_xz]
    return cq.Workplane(plane).polyline(pts).close().extrude(y1 - y0)


def annular_sector_xz(r0: float, r1: float, a0_deg: float, a1_deg: float, y0: float, y1: float,
                      n: int = 48) -> cq.Workplane:
    pts = []
    for i in range(n + 1):
        a = math.radians(a0_deg + (a1_deg - a0_deg) * i / n)
        pts.append((r1 * math.cos(a), r1 * math.sin(a)))
    if r0 <= 1e-6:
        pts.append((0.0, 0.0))
    else:
        for i in range(n, -1, -1):
            a = math.radians(a0_deg + (a1_deg - a0_deg) * i / n)
            pts.append((r0 * math.cos(a), r0 * math.sin(a)))
    return xz_prism(pts, y0, y1)


def rot_y(wp: cq.Workplane, deg: float) -> cq.Workplane:
    """Right-hand rotation about +Y through the pivot (positive = squeeze direction)."""
    return wp.rotate(*Y_AXIS, deg)


# ---------------------------------------------------------------------------- SEA frames


def spring_frame() -> Tuple[Vec3, Vec3, Vec3]:
    """(origin, ex = radial, ez = spring axis) at the tangent point T, lever frame."""
    a = math.radians(ALPHA_T)
    origin = (R_T * math.cos(a), SPRING_Y, R_T * math.sin(a))
    ex = (math.cos(a), 0.0, math.sin(a))
    ez = (-math.sin(a), 0.0, math.cos(a))
    return origin, ex, ez


def tab_frame() -> Tuple[Vec3, Vec3, Vec3]:
    """Frame of the tab face at delta = 0 (disc frame == lever frame at delta = 0)."""
    b = math.radians(ALPHA_T - DELTA_MID)
    origin = (R_T * math.cos(b), SPRING_Y, R_T * math.sin(b))
    ex = (math.cos(b), 0.0, math.sin(b))
    ez = (-math.sin(b), 0.0, math.cos(b))
    return origin, ex, ez


def s_of_delta(delta_deg: float) -> float:
    """Tab-face centre position along the spring axis (relative to T) at deflection delta."""
    return R_T * math.sin(math.radians(delta_deg - DELTA_MID))
