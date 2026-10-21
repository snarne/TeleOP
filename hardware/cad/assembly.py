"""HGM assembly: places every part for a lever angle phi and spring deflection delta."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import cadquery as cq

import params as P
from geom import rot_y
from parts import button_cap, drive_disc, encoder_cover, housing, lever, mount_adapter, purchased, wrist


@dataclass
class Part:
    name: str
    shape: cq.Workplane
    color: str
    group: str            # "printed" | "purchased" | "context"
    moving: str = "fixed"  # "fixed" | "lever" | "disc"
    material: Optional[str] = None
    explode: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    print_rot: Tuple[Tuple[float, float, float], float] = ((1, 0, 0), 0.0)  # axis, deg → print orientation
    note: str = ""


@lru_cache(maxsize=1)
def _static_shapes() -> Dict[str, cq.Workplane]:
    servo_half, enc_half = housing.make()
    return {
        "housing_servo_half": servo_half,
        "housing_encoder_half": enc_half,
        "lever": lever.make(),
        "blade": lever.make_blade(),
        "blade_skin": lever.make_skin(),
        "lra": lever.make_lra(),
        "drive_disc": drive_disc.make(),
        "encoder_cover": encoder_cover.make(),
        "button_cap_a": button_cap.make(P.BUTTON_A_X),
        "button_cap_b": button_cap.make(P.BUTTON_B_X),
        "mount_adapter": mount_adapter.make(),
        "servo": purchased.servo_body(),
        "servo_horn": purchased.servo_horn(),
        "bearing_6700": purchased.bearing_6700(),
        "bearing_mr63": purchased.bearing_mr63(),
        "pin": purchased.pin(),
        "magnet": purchased.magnet(),
        "as5600": purchased.as5600_board(),
        "switch_a": purchased.d2f_switch(P.BUTTON_A_X, P.BUTTON_Y, P.SERVO_W / 2 + 0.2),
        "switch_b": purchased.d2f_switch(P.BUTTON_B_X, P.BUTTON_Y, P.SERVO_W / 2 + 0.2),
        "electronics": purchased.protoboard_with_xiao(*housing.board_frame()[:3]),
    }


@lru_cache(maxsize=8)
def _spring(compression: float) -> cq.Workplane:
    return purchased.spring(compression)


def parts(phi: float = 0.0, delta: float = 0.0, with_wrist: bool = False) -> List[Part]:
    s = _static_shapes()
    L = lambda w: rot_y(w, phi)            # noqa: E731  lever-frame → world
    D = lambda w: rot_y(w, phi - delta)    # noqa: E731  disc-frame → world
    comp = P.spring_compression_mm(delta)
    out = [
        Part("housing_servo_half", s["housing_servo_half"], "housing", "printed", material="PETG",
             explode=(0, -38, 0), print_rot=((1, 0, 0), -90.0), note="split face down"),
        Part("housing_encoder_half", s["housing_encoder_half"], "housing_alt", "printed", material="PETG",
             explode=(0, 48, 0), print_rot=((1, 0, 0), 90.0), note="split face down"),
        Part("lever", L(s["lever"]), "lever", "printed", "lever", material="PETG", explode=(0, 26, 0),
             print_rot=((1, 0, 0), 90.0), note="−Y face (pocket opening) down"),
        Part("blade", L(s["blade"]), "lever", "printed", "lever", material="PETG", explode=(18, 26, -30),
             print_rot=((1, 0, 0), 90.0), note="−Y face down"),
        Part("blade_skin", L(s["blade_skin"]), "cap", "printed", "lever", material="TPU 95A", explode=(30, 26, -18),
             print_rot=((1, 0, 0), 90.0), note="−Y edge down (thin shell; print slowly)"),
        Part("lra", L(s["lra"]), "magnet", "purchased", "lever", explode=(26, 26, -22)),
        Part("drive_disc", D(s["drive_disc"]), "disc", "printed", "disc", material="PETG", explode=(0, 12, 0),
             print_rot=((1, 0, 0), 90.0), note="horn face down"),
        Part("encoder_cover", s["encoder_cover"], "cover", "printed", material="PETG", explode=(0, 75, 0),
             print_rot=((1, 0, 0), -90.0), note="floor down, open side up"),
        Part("button_cap_a", s["button_cap_a"], "cap", "printed", material="TPU 95A", explode=(0, 0, 22),
             note="flange down"),
        Part("button_cap_b", s["button_cap_b"], "cap", "printed", material="TPU 95A", explode=(0, 0, 22),
             note="flange down"),
        Part("mount_adapter", s["mount_adapter"], "mount", "printed", material="PETG", explode=(-30, 0, 0),
             print_rot=((0, 1, 0), 90.0), note="flange face down"),
        Part("servo_xc330", s["servo"], "servo", "purchased", explode=(0, -20, 0)),
        Part("servo_horn", D(s["servo_horn"]), "horn", "purchased", "disc", explode=(0, -8, 0)),
        Part("bearing_6700zz", s["bearing_6700"], "steel", "purchased", explode=(0, 62, 0)),
        Part("bearing_mr63zz", L(s["bearing_mr63"]), "steel", "purchased", "lever", explode=(0, 20, 0)),
        Part("pin_3x8", D(s["pin"]), "steel", "purchased", "disc", explode=(0, 16, 0)),
        Part("magnet_6x2.5", L(s["magnet"]), "magnet", "purchased", "lever", explode=(0, 66, 0)),
        Part("spring", L(_spring(round(comp, 3))), "spring", "purchased", "lever", explode=(0, 20, 0)),
        Part("as5600_board", s["as5600"], "pcb_blue", "purchased", explode=(0, 70, 0)),
        Part("switch_a", s["switch_a"], "switch", "purchased", explode=(0, 0, 12)),
        Part("switch_b", s["switch_b"], "switch", "purchased", explode=(0, 0, 12)),
        Part("electronics", s["electronics"], "pcb", "purchased", explode=(0, -30, -10)),
    ]
    if with_wrist:
        servos, horns, printed = wrist.make()
        out += [Part("wrist_servos", servos, "servo", "context", explode=(-60, 0, 0)),
                Part("wrist_horns", horns, "horn", "context", explode=(-60, 0, 0)),
                Part("wrist_links", printed, "wrist", "context", explode=(-60, 0, 0))]
    return out


def exploded(parts_list: List[Part], k: float = 1.0) -> List[Part]:
    res = []
    for p in parts_list:
        dx, dy, dz = (k * v for v in p.explode)
        res.append(Part(p.name, p.shape.translate((dx, dy, dz)), p.color, p.group, p.moving, p.material,
                        p.explode, p.print_rot, p.note))
    return res
