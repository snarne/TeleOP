"""Headless renders (VTK/EGL through PyVista) of CadQuery shapes."""

from __future__ import annotations

import os
import tempfile
from typing import Iterable, Optional, Sequence, Tuple

import cadquery as cq
import numpy as np
import pyvista as pv

pv.OFF_SCREEN = True

PALETTE = {
    "housing": "#3a3f47",
    "housing_alt": "#4a515c",
    "lever": "#e8742c",
    "disc": "#2f7dd1",
    "servo": "#1c1c1e",
    "horn": "#6d6d72",
    "spring": "#c9ccd1",
    "steel": "#a9adb3",
    "magnet": "#8f3b3b",
    "pcb": "#1f6e43",
    "pcb_blue": "#2a3f8f",
    "chip": "#111111",
    "cover": "#5b6573",
    "cap": "#e8742c",
    "mount": "#7b8794",
    "wrist": "#d9dde3",
    "switch": "#202020",
}


def to_mesh(shape: cq.Workplane | cq.Shape, tol: float = 0.05, angular: float = 0.2) -> pv.PolyData:
    s = shape.val() if isinstance(shape, cq.Workplane) else shape
    if isinstance(shape, cq.Workplane) and len(shape.vals()) > 1:
        s = cq.Compound.makeCompound([v for v in shape.vals() if isinstance(v, cq.Shape)])
    verts, tris = s.tessellate(tol, angular)
    pts = np.array([(v.x, v.y, v.z) for v in verts], dtype=float)
    faces = np.hstack([np.full((len(tris), 1), 3), np.array(tris, dtype=np.int64)]).ravel()
    mesh = pv.PolyData(pts, faces)
    return mesh.compute_normals(split_vertices=True, feature_angle=35.0, auto_orient_normals=False)


def render(items: Iterable[Tuple[cq.Workplane | cq.Shape, str, float]], path: str,
           camera: Sequence = ("iso",), size=(1600, 1200), title: Optional[str] = None,
           edges: bool = True, bg: str = "white", zoom: float = 1.0,
           annotations: Sequence[Tuple[Sequence[float], str]] = ()) -> None:
    """items: (shape, color, opacity). camera: ("iso",) or (position, focal, viewup)."""
    p = pv.Plotter(off_screen=True, window_size=size, lighting="none")
    p.set_background(bg, top="#e9edf2" if bg == "white" else None)
    # three-point lighting
    p.add_light(pv.Light(position=(250, -350, 400), focal_point=(0, 0, -30), intensity=0.85, light_type="scene light"))
    p.add_light(pv.Light(position=(-300, 200, 150), focal_point=(0, 0, -30), intensity=0.35, light_type="scene light"))
    p.add_light(pv.Light(position=(0, 400, -200), focal_point=(0, 0, -30), intensity=0.25, light_type="scene light"))
    p.add_light(pv.Light(light_type="headlight", intensity=0.25))
    for shape, color, opacity in items:
        m = to_mesh(shape)
        p.add_mesh(m, color=color, opacity=opacity, smooth_shading=True, specular=0.35, specular_power=25,
                   ambient=0.18, diffuse=0.8)
        if edges and opacity > 0.6:
            fe = m.extract_feature_edges(feature_angle=40, boundary_edges=False, non_manifold_edges=False,
                                         manifold_edges=False)
            if fe.n_points:
                p.add_mesh(fe, color="#15171a", line_width=1.2, opacity=0.55)
    for pos, text in annotations:
        p.add_point_labels([pos], [text], font_size=26, point_size=1, shape_opacity=0.85,
                           text_color="#111111", fill_shape=True, shape_color="#ffffff", always_visible=True)
    if camera[0] == "iso":
        p.view_isometric()
    else:
        p.camera_position = camera
    p.camera.zoom(zoom)
    if title:
        p.add_text(title, position="upper_left", font_size=13, color="#222222")
    p.enable_anti_aliasing("ssaa")
    p.screenshot(path)
    p.close()
