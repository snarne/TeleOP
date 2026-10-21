"""Generate standalone calibration scripts with this station's ports and paths baked in.

The scripts need no station install, so a technician can calibrate on any machine the
hardware is plugged into (`station calib script leader_left`, or Calibration → Generate
script in the UI). They write the same YAML format the station loads.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict

from station import __version__
from station.config import StationConfig

TEMPLATES = Path(__file__).resolve().parent / "templates"


def _codec_source() -> str:
    src = (Path(__file__).resolve().parent.parent / "hardware" / "haptic_protocol.py").read_text()
    src = re.sub(r'^""".*?"""\n', "", src, count=1, flags=re.S)
    return src.replace("from __future__ import annotations\n", "")


def generate_script(cfg: StationConfig, procedure_id: str, out_dir: Path) -> Dict[str, str]:
    kind, _, target = procedure_id.partition("_")
    subs: Dict[str, str] = {"VERSION": __version__, "DATE": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if kind in ("leader", "trigger", "gripper", "fingertips"):
        if target not in cfg.arms:
            raise KeyError(f"no arm named {target!r}")
        arm = cfg.arms[target]
        subs["SIDE"] = target
    if kind == "leader":
        lc = arm.leader
        subs.update(PORT=repr(lc.port), BAUD=str(lc.baudrate), JOINT_IDS=repr(lc.joint_ids),
                    CHECK_POSE=repr(list(lc.check_pose)), SIGNS=repr(list(lc.joint_signs)),
                    CAN=repr(arm.follower.can_channel), OUTPUT=repr(str(cfg.cal_path(lc.calibration_file))))
    elif kind == "trigger":
        subs.update(PORT=repr(arm.trigger.port), PORT_RAW=arm.trigger.port, CODEC=_codec_source(),
                    OUTPUT=repr(str(cfg.cal_path(arm.trigger.calibration_file))))
    elif kind == "gripper":
        subs.update(CAN=repr(arm.follower.can_channel), CAN_RAW=arm.follower.can_channel,
                    OUTPUT=repr(str(cfg.cal_path(arm.gripper_force.calibration_file))))
    elif kind == "fingertips":
        subs.update(PORT=repr(arm.fingertips.port), PORT_RAW=arm.fingertips.port, CODEC=_codec_source(),
                    OUTPUT=repr(str(cfg.cal_path(arm.fingertips.calibration_file))))
    elif kind == "camera":
        if target not in cfg.cameras:
            raise KeyError(f"no camera named {target!r}")
        c = cfg.cameras[target]
        subs.update(CAMERA=target, DEVICE=repr(c.device), DEVICE_RAW=str(c.device), WIDTH=str(c.width),
                    HEIGHT=str(c.height), FPS=str(c.fps),
                    OUTPUT=repr(str(cfg.cal_path(c.calibration_file or f"calibration/camera_{target}.yaml"))))
    else:
        raise KeyError(f"unknown procedure {procedure_id!r}")
    filename = f"calibrate_{procedure_id}.py"
    subs["FILENAME"] = filename
    text = (TEMPLATES / f"{kind}.py.tmpl").read_text()
    for k, v in subs.items():
        text = text.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if left:
        raise RuntimeError(f"unfilled template fields: {left}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(text)
    path.chmod(0o755)
    return {"filename": filename, "path": str(path), "content": text}
