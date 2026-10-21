"""Calibration procedures, each a list of steps rendered by one generic wizard in the UI
(and by `station calib run` in a terminal).

| Procedure          | Measures                                              | Stored in                      |
|--------------------|-------------------------------------------------------|--------------------------------|
| leader_<side>      | per-joint offset + sign mapping leader → follower     | calibration/leader_<side>.yaml |
| trigger_<side>     | lever travel, SEA zero, spring stiffness k_θ          | calibration/trigger_<side>.yaml (+ module flash) |
| gripper_<side>     | follower grip force = G · (|τ| − τ₀), friction        | calibration/gripper_<side>.yaml |
| camera_<name>      | intrinsics K, distortion (ChArUco), reprojection RMS  | calibration/camera_<name>.yaml |
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

import numpy as np
import yaml

from station.hardware import haptic_protocol as hp


class CalError(RuntimeError):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


@dataclass
class StepDef:
    id: str
    title: str
    instruction: str
    action: str = "capture"  # capture | auto | confirm | input
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    image: Optional[str] = None
    optional: bool = False
    repeatable: bool = False


class CalContext(Protocol):
    sim: bool

    def arm_request(self, side: str, cmd: str, timeout: float = 5.0, **kw: Any) -> Dict[str, Any]: ...
    def arm_state(self, side: str) -> Dict[str, Any]: ...
    def arm_connected(self, side: str) -> bool: ...
    def camera_capture(self, name: str, path: Path) -> Path: ...
    def cal_file(self, item_id: str) -> Path: ...
    def scratch_dir(self, item_id: str) -> Path: ...
    def config(self) -> Any: ...


def wrap(a):
    return (np.asarray(a) + math.pi) % (2 * math.pi) - math.pi


class Procedure:
    kind = ""
    title = ""
    description = ""

    def __init__(self, ctx: CalContext, target: str):
        self.ctx = ctx
        self.target = target
        self.id = f"{self.kind}_{target}"
        self.status: Dict[str, Dict[str, Any]] = {}
        self.result: Optional[Dict[str, Any]] = None
        self.step_index = 0

    # ------------------------------------------------------------------ to override
    def steps(self) -> List[StepDef]: raise NotImplementedError
    def run(self, step_id: str, inputs: Dict[str, Any]) -> Dict[str, Any]: raise NotImplementedError
    def live(self) -> Dict[str, Any]: return {}
    def summary(self) -> str: return ""
    def apply(self) -> None: """Push the committed result to live hardware (optional)."""
    def on_start(self) -> None: ...
    def on_end(self) -> None: ...

    # ------------------------------------------------------------------ framework
    def describe(self) -> Dict[str, Any]:
        return {"id": self.id, "title": f"{self.target.replace('_', ' ').title()} {self.title[0].lower()}{self.title[1:]}"
                if self.kind != "camera" else f"{self.title} · {self.target.replace('_', ' ')}", "kind": self.kind, "target": self.target,
                "description": self.description, "steps": [asdict(s) for s in self.steps()]}

    def start(self) -> Dict[str, Any]:
        self.status = {s.id: {"id": s.id, "status": "pending", "message": "", "data": {}} for s in self.steps()}
        self.result = None
        self.step_index = 0
        self.on_start()
        return self.run_state()

    def run_step(self, step_id: str, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ids = [s.id for s in self.steps()]
        if step_id not in ids:
            raise CalError(f"unknown step {step_id!r}")
        try:
            data = self.run(step_id, inputs or {}) or {}
            self.status[step_id] = {"id": step_id, "status": "ok", "message": data.pop("message", "done"), "data": data}
            i = ids.index(step_id)
            step = self.steps()[i]
            if not step.repeatable or data.get("advance", False):
                self.step_index = max(self.step_index, i + 1)
        except CalError as e:
            self.status[step_id] = {"id": step_id, "status": "error", "message": str(e), "data": {"hint": e.hint}}
        return self.run_state()

    def can_commit(self) -> bool:
        return self.result is not None

    def run_state(self) -> Dict[str, Any]:
        return {"procedure_id": self.id, "step_index": self.step_index,
                "steps": [self.status[s.id] for s in self.steps()], "result": self.result,
                "can_commit": self.can_commit()}

    def commit(self, user: Optional[str]) -> Dict[str, Any]:
        if not self.can_commit():
            raise CalError("procedure not finished", "complete all steps first")
        path = self.ctx.cal_file(self.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = dict(self.result)
        doc["_meta"] = {"item": self.id, "created_at": datetime.now(timezone.utc).isoformat(), "by": user or "",
                        "summary": self.summary(), "station": self.ctx.config().station.name}
        if path.exists():  # keep one backup of the previous calibration
            path.replace(path.with_suffix(".prev.yaml"))
        with open(path, "w") as f:
            yaml.safe_dump(doc, f, sort_keys=False)
        self.apply()
        self.on_end()
        return {"path": str(path), "summary": self.summary(), "data": self.result}


# =============================================================================== leader


class LeaderProcedure(Procedure):
    kind = "leader"
    title = "Leader arm joint mapping"
    description = ("Maps every leader joint onto the matching follower joint: offset and direction. With the "
                   "follower connected, you pose both arms by hand to look the same, twice. Otherwise you use "
                   "the zero pose and a known check pose.")

    def __init__(self, ctx: CalContext, target: str):
        super().__init__(ctx, target)
        self.caps: Dict[str, Dict[str, np.ndarray]] = {}
        self.match_mode = True

    def steps(self) -> List[StepDef]:
        side = self.target
        if self.match_mode:
            a = (f"Pose BOTH {side} arms the same way: the follower is floating (gravity-compensated), so "
                 "move it by hand. Pick any comfortable pose with the elbow bent. Hold still, then Capture.")
            b = ("Now change EVERY joint by at least 20° on both arms, keeping them matched (for example, "
                 "rotate the base, raise the shoulder, bend the elbow, tilt and roll the wrist). Hold still, "
                 "then Capture.")
            v = "Optional check: a third matched pose. The wizard reports the residual error per joint."
        else:
            a = "Follower not connected. Put the leader in the ZERO pose (all joints at 0°, see the picture). Capture."
            b = "Put the leader in the CHECK pose: shoulder 60°, elbow 60°, other joints 0°. Capture."
            v = "Optional: any pose you can measure. Skip if unsure."
        return [
            StepDef("check", "Check the leader bus", "Reads all six joint encoders.", "auto"),
            StepDef("pose_a", "Pose A", a, "capture"),
            StepDef("pose_b", "Pose B", b, "capture"),
            StepDef("verify", "Verify", v, "capture", optional=True),
        ]

    def on_start(self) -> None:
        side = self.target
        self.match_mode = self.ctx.arm_connected(side) and self.ctx.arm_state(side).get("follower_ok", False)
        self.status = {s.id: {"id": s.id, "status": "pending", "message": "", "data": {}} for s in self.steps()}
        if self.match_mode:
            self.ctx.arm_request(side, "float")

    def on_end(self) -> None:
        if self.ctx.sim:
            self.ctx.arm_request(self.target, "sim_pose", q=None)

    def _sim_pose(self, step_id: str) -> Optional[np.ndarray]:
        poses = {"pose_a": [0.2, 0.9, 1.1, -0.3, 0.25, 0.4], "pose_b": [-0.5, 1.6, 0.5, 0.35, -0.4, -0.6],
                 "verify": [0.6, 1.2, 1.4, 0.0, 0.1, 1.0]}
        if not self.match_mode:
            poses["pose_a"] = [0.0] * 6
            poses["pose_b"] = list(self.ctx.config().arms[self.target].leader.check_pose)
        return np.array(poses[step_id]) if step_id in poses else None

    def _capture(self, step_id: str) -> Dict[str, np.ndarray]:
        side = self.target
        if self.ctx.sim:
            q = self._sim_pose(step_id)
            self.ctx.arm_request(side, "sim_pose", q=q.tolist())
            if self.match_mode:
                self.ctx.arm_request(side, "sim_follower_pose", q=list(q) + [1.0])
            time.sleep(0.8)
        r = self.ctx.arm_request(side, "read_leader_raw", n=30)
        if max(r["std"]) > 0.01:
            raise CalError("the leader moved during capture", "hold it still and capture again")
        cap = {"raw": np.array(r["raw"])}
        if self.match_mode:
            cap["q"] = np.array(self.ctx.arm_request(side, "follower_read", n=30)["q"])
        else:
            cfg = self.ctx.config().arms[side].leader
            cap["q"] = np.zeros(6) if step_id == "pose_a" else np.array(cfg.check_pose)
        return cap

    def run(self, step_id: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        side = self.target
        if step_id == "check":
            r = self.ctx.arm_request(side, "read_leader_raw", n=10)
            bad = [i + 1 for i, v in enumerate(r["raw"]) if not np.isfinite(v)]
            if bad:
                raise CalError(f"joints {bad} not reading", "check the daisy-chain cable and servo IDs (Hardware → Scan)")
            mode = "matching the follower" if self.match_mode else "known poses (follower offline)"
            return {"message": f"6/6 joints reading · method: {mode}"}
        cap = self._capture(step_id)
        self.caps[step_id] = cap
        if step_id == "pose_b" or (step_id == "verify" and "pose_b" in self.caps):
            self._solve()
        msg = "captured"
        if step_id == "verify" and self.result:
            res = self._residual(cap)
            self.result["verify_residual_deg"] = [round(math.degrees(x), 2) for x in res]
            if np.max(np.abs(res)) > math.radians(4):
                j = int(np.argmax(np.abs(res))) + 1
                raise CalError(f"joint {j} is off by {math.degrees(np.max(np.abs(res))):.1f}°",
                               "re-capture poses A and B more carefully (match the arms closely)")
            msg = f"max residual {math.degrees(np.max(np.abs(res))):.1f}°"
        elif self.result and step_id == "pose_b":
            msg = self.summary()
        return {"message": msg, "raw_deg": [round(math.degrees(x), 1) for x in cap["raw"]]}

    def _solve(self) -> None:
        a, b = self.caps.get("pose_a"), self.caps.get("pose_b")
        if a is None or b is None:
            return
        dr = wrap(b["raw"] - a["raw"])
        dq = b["q"] - a["q"]
        cfg_signs = np.array(self.ctx.config().arms[self.target].leader.joint_signs, float)
        small = [i for i in range(6) if abs(dq[i]) < math.radians(15) or abs(dr[i]) < math.radians(5)]
        if small and self.match_mode:
            self.result = None
            raise CalError(f"joints {[i + 1 for i in small]} moved less than 15° between poses A and B",
                           "re-capture pose B with every joint clearly rotated")
        signs = np.sign(dr * dq)
        # known-pose method: joints the check pose doesn't move keep the configured direction
        for i in small:
            signs[i] = cfg_signs[i]
        signs[signs == 0] = 1.0
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(np.abs(dq) > 1e-3, np.abs(dr) / np.abs(dq), 1.0)
        flipped = [i + 1 for i in range(6) if signs[i] != cfg_signs[i]]
        offsets = []
        for i in range(6):
            o_a = a["raw"][i] - signs[i] * a["q"][i]
            o_b = b["raw"][i] - signs[i] * b["q"][i]
            o = math.atan2((math.sin(o_a) + math.sin(o_b)) / 2, (math.cos(o_a) + math.cos(o_b)) / 2)
            offsets.append(o)
        self.result = {"offsets": [float(x) for x in offsets], "signs": [int(s) for s in signs],
                       "ratio": [round(float(x), 3) for x in ratio], "flipped_vs_config": flipped,
                       "method": "match_follower" if self.match_mode else "known_poses",
                       "captures": {k: {"raw": v["raw"].tolist(), "q": v["q"].tolist()} for k, v in self.caps.items()}}
        res_a = self._residual(a)
        res_b = self._residual(b)
        self.result["residual_deg"] = [round(math.degrees(max(abs(x), abs(y))), 2) for x, y in zip(res_a, res_b)]
        bad_ratio = [i + 1 for i in range(6) if not 0.85 < ratio[i] < 1.15]
        if bad_ratio:
            self.result["warning"] = (f"joints {bad_ratio} moved by a different amount on leader vs follower; "
                                      "check for a slipping horn or a 2π wrap")

    def _residual(self, cap) -> np.ndarray:
        s = np.array(self.result["signs"])
        o = np.array(self.result["offsets"])
        return wrap(s * (cap["raw"] - o) - cap["q"])

    def live(self) -> Dict[str, Any]:
        st = self.ctx.arm_state(self.target)
        raw = np.array(st.get("leader_raw", [np.nan] * 7)[:6], float)
        out: Dict[str, Any] = {"leader_raw_joints_deg": _degs(raw)}
        if self.match_mode:
            out["follower_joints_deg"] = _degs(st.get("follower_q", [np.nan] * 6))
        if self.result:
            s, o = np.array(self.result["signs"]), np.array(self.result["offsets"])
            out["mapped_joints_deg"] = _degs(wrap(s * (raw - o)))
        return out

    def summary(self) -> str:
        if not self.result:
            return ""
        r = self.result
        fl = f", corrected signs on joints {r['flipped_vs_config']}" if r.get("flipped_vs_config") else ""
        return f"max residual {max(r['residual_deg']):.1f}°{fl}"

    def apply(self) -> None:
        self.ctx.arm_request(self.target, "reload_calibration")


def _degs(xs) -> List[Optional[float]]:
    return [round(math.degrees(float(x)), 1) if np.isfinite(x) else None for x in np.asarray(xs, float)]


def _deg(x) -> str:
    try:
        return f"{math.degrees(float(x)):.1f}" if np.isfinite(x) else "-"
    except Exception:
        return "-"


# =============================================================================== trigger


class TriggerProcedure(Procedure):
    kind = "trigger"
    title = "Haptic trigger"
    description = ("Measures the trigger's travel, zeroes the series-elastic force sensor and measures the "
                   "spring stiffness with a known weight, then stores the results in the module's flash.")

    def __init__(self, ctx: CalContext, target: str):
        super().__init__(ctx, target)
        self.m: Dict[str, float] = {}
        self.kind_name = ""

    def steps(self) -> List[StepDef]:
        return [
            StepDef("connect", "Connect", "Checks the trigger module and firmware.", "auto"),
            StepDef("tare", "Zero the force sensor",
                    "Take your hand OFF the handle. The trigger moves to mid-travel and holds while the sensor zeroes.",
                    "auto"),
            StepDef("open", "Released position", "Leave the trigger fully released. Capture.", "capture"),
            StepDef("closed", "Squeezed position", "Squeeze the trigger all the way and hold. Capture.", "capture"),
            StepDef("stiffness", "Spring stiffness",
                    "The trigger holds at mid-travel. Hang a known weight from the hole in the finger pad (a 500 g "
                    "water bottle works) or press the pad with a kitchen scale. Enter the mass and Capture.",
                    "input", inputs=[{"key": "mass_g", "label": "Mass (g)", "type": "number", "default": 500}]),
        ]

    def _override(self, **sp) -> None:
        self.ctx.arm_request(self.target, "trigger_override", setpoint=sp or None)

    def on_end(self) -> None:
        try:
            self._override()
            if self.ctx.sim:
                self.ctx.arm_request(self.target, "sim_squeeze", n=None)
        except Exception:
            pass

    def run(self, step_id: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        side = self.target
        if not self.ctx.arm_connected(side):
            raise CalError("arm not started", "press Start Arms first (the trigger is read through the arm worker)")
        if step_id == "connect":
            r = self.ctx.arm_request(side, "trigger_read", n=10)
            self.kind_name = r["kind"]
            if r["kind"] == "NoTrigger":
                raise CalError("no trigger connected", "check trigger.backend/port in config and the USB cable")
            if r["kind"] == "LegacyTrigger":
                return {"message": "legacy Dynamixel trigger: only open/closed travel is calibrated"}
            return {"message": f"{r['kind']} ok"}
        legacy = self.kind_name == "LegacyTrigger"
        if step_id == "tare":
            if legacy:
                return {"message": "skipped (legacy trigger has no force sensor)"}
            self._override(mode=int(hp.Mode.POSITION), pos_cmd=0.5)
            if self.ctx.sim:
                self.ctx.arm_request(side, "sim_squeeze", n=0.0)
            time.sleep(0.6)
            self.ctx.arm_request(side, "trigger_command", command=int(hp.Command.TARE_SEA))
            time.sleep(0.1)
            r = self.ctx.arm_request(side, "trigger_read", n=50)
            self.m["sea_zero"] = r["deflection"]
            return {"message": f"zeroed (deflection {math.degrees(r['deflection']):.2f}°)"}
        if step_id in ("open", "closed"):
            self._override(mode=int(hp.Mode.SPRING), spring_min_n=0.4, spring_n=0.0, max_n=2.0)
            if self.ctx.sim:
                self.ctx.arm_request(side, "sim_squeeze", n=0.0 if step_id == "open" else 18.0)
                time.sleep(0.6)
            r = self.ctx.arm_request(side, "trigger_read", n=50)
            self.m[f"theta_{step_id}"] = r["lever"]
            if step_id == "closed":
                travel = math.degrees(self.m["theta_closed"] - self.m.get("theta_open", 0.0))
                if abs(travel) < 10:
                    raise CalError(f"only {travel:.1f}° of travel measured", "squeeze all the way and hold during capture")
                if legacy:
                    self._finish_legacy()
                return {"message": f"travel {travel:.1f}°"}
            return {"message": f"lever {math.degrees(r['lever']):.1f}°"}
        if step_id == "stiffness":
            if legacy:
                return {"message": "skipped"}
            mass = float(inputs.get("mass_g") or 500.0)
            f = mass / 1000.0 * 9.81
            self._override(mode=int(hp.Mode.POSITION), pos_cmd=0.5)
            if self.ctx.sim:
                self.ctx.arm_request(side, "sim_squeeze", n=f)
            time.sleep(0.8)
            r = self.ctx.arm_request(side, "trigger_read", n=80)
            defl = r["deflection"] - self.m.get("sea_zero", 0.0)
            if abs(defl) < math.radians(0.5):
                raise CalError("the spring barely deflected", "use a heavier weight (≥ 400 g) or check the spring pack")
            r_f = 0.045
            k = abs(f * r_f / defl)
            if not 0.5 < k < 20:
                raise CalError(f"implausible stiffness {k:.2f} N·m/rad", "check the weight is hanging from the finger pad")
            self.m["k_theta"] = k
            self.result = {
                "backend": "hgm",
                "params": {"k_theta": round(k, 4), "finger_radius": r_f,
                           "theta_open": round(self.m["theta_open"], 5), "theta_closed": round(self.m["theta_closed"], 5),
                           "sea_zero": round(self.m.get("sea_zero", 0.0), 5)},
                "test": {"mass_g": mass, "force_n": round(f, 3), "deflection_deg": round(math.degrees(defl), 3)},
            }
            return {"message": f"k_θ = {k:.2f} N·m/rad ({math.degrees(f * r_f / k):.1f}° per {f:.1f} N)"}
        raise CalError(f"unknown step {step_id}")

    def _finish_legacy(self) -> None:
        to_ticks = lambda r: int(round(r / (2 * math.pi / 4096) + 2048))  # noqa: E731
        self.result = {"backend": "dynamixel_legacy",
                       "legacy_open_ticks": to_ticks(self.m["theta_open"]),
                       "legacy_closed_ticks": to_ticks(self.m["theta_closed"])}

    def can_commit(self) -> bool:
        return self.result is not None

    def apply(self) -> None:
        side = self.target
        if self.result.get("backend") == "hgm":
            for name, value in self.result["params"].items():
                self.ctx.arm_request(side, "trigger_param", param=int(hp.Param[name.upper()]), value=float(value))
            try:
                self.ctx.arm_request(side, "trigger_command", command=int(hp.Command.SAVE_PARAMS))
            except Exception:
                pass
        self.ctx.arm_request(side, "reload_calibration")

    def live(self) -> Dict[str, Any]:
        st = self.ctx.arm_state(self.target)
        f = lambda k: round(float(np.nan_to_num(st.get(k, 0.0))), 3)  # noqa: E731
        return {"trigger_position": f("trigger_pos"), "squeeze_force_n": f("trigger_force"),
                "rendered_force_n": f("trigger_render"), "lever_deg": _deg(st.get("trigger_lever", np.nan)),
                "servo_deg": _deg(st.get("trigger_servo", np.nan))}

    def summary(self) -> str:
        if not self.result:
            return ""
        if self.result.get("backend") == "hgm":
            p = self.result["params"]
            return f"k_θ {p['k_theta']:.2f} N·m/rad, travel {math.degrees(p['theta_closed'] - p['theta_open']):.1f}°"
        return f"ticks {self.result['legacy_open_ticks']}→{self.result['legacy_closed_ticks']}"


# =============================================================================== gripper


class GripperProcedure(Procedure):
    kind = "gripper"
    title = "Follower grip force"
    description = ("Calibrates the grip-force estimate F = G·(|τ| − τ₀) that drives the haptic feedback. You "
                   "need a force gauge, or a luggage scale and a strap, placed between the fingers.")
    LEVELS = [8.0, 18.0, 30.0]

    def __init__(self, ctx: CalContext, target: str):
        super().__init__(ctx, target)
        self.tau_friction = None
        self.points: List[Dict[str, float]] = []

    def steps(self) -> List[StepDef]:
        s = [StepDef("friction", "Free-air friction",
                     "Clear the area between the fingers. The gripper opens and closes a few times to measure friction.",
                     "auto")]
        for i, lvl in enumerate(self.LEVELS):
            s.append(StepDef(f"squeeze_{i + 1}", f"Squeeze {i + 1}/{len(self.LEVELS)}",
                             f"Put the gauge between the fingers. The gripper squeezes (target ≈ {lvl:.0f} N). Read the "
                             "gauge and enter the value.", "input",
                             inputs=[{"key": "measured_n", "label": "Gauge reading (N)", "type": "number"}]))
        return s

    def on_end(self) -> None:
        try:
            self.ctx.arm_request(self.target, "gripper_override", override=None)
            if self.ctx.sim:
                self.ctx.arm_request(self.target, "sim_object", on=False)
        except Exception:
            pass

    def run(self, step_id: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        side = self.target
        if not self.ctx.arm_connected(side):
            raise CalError("arm not started", "press Start Arms first")
        if self.ctx.sim:
            self.ctx.arm_request(side, "sim_object", on=step_id != "friction")
        if step_id == "friction":
            taus = []
            for x in (0.15, 0.95, 0.15, 0.95):
                self.ctx.arm_request(side, "gripper_override", override={"x": x})
                time.sleep(0.15)
                r = self.ctx.arm_request(side, "gripper_read", n=40)
                taus.append(r["tau_abs"])
                time.sleep(0.6)
            self.tau_friction = float(np.median(taus))
            return {"message": f"friction ≈ {self.tau_friction:.3f} N·m while moving"}
        i = int(step_id.split("_")[1]) - 1
        lvl = self.LEVELS[i]
        # Close *under force control* (creep until contact, then regulate). Never position-close
        # onto the gauge: that would squeeze with whatever torque the PD error asks for.
        self.ctx.arm_request(side, "gripper_override", override={"force": lvl})
        t_end = time.time() + 8.0  # closing from open takes a few seconds at calibration speed
        while time.time() < t_end and float(np.nan_to_num(self.ctx.arm_state(side).get("grip_force", 0.0))) < 0.6 * lvl:
            time.sleep(0.05)
        time.sleep(0.6)  # settle
        r = self.ctx.arm_request(side, "gripper_read", n=100)
        measured = inputs.get("measured_n")
        if self.ctx.sim and measured in (None, ""):
            measured = max(0.0, (r["tau_abs"] - 0.0) * 68.4 * float(np.random.normal(1.0, 0.03)))
        if measured in (None, ""):
            raise CalError("enter the gauge reading", "type the value in newtons, then Capture again")
        self.points.append({"tau_abs": r["tau_abs"], "measured_n": float(measured)})
        self.ctx.arm_request(side, "gripper_override", override={"x": 0.9})
        msg = f"|τ| = {r['tau_abs']:.3f} N·m ↔ {float(measured):.1f} N"
        if len(self.points) >= 2:
            self._fit()
            msg += f" · fit G = {self.result['gain_n_per_nm']:.1f} N/N·m"
        return {"message": msg}

    def _fit(self) -> None:
        tau = np.array([p["tau_abs"] for p in self.points])
        f = np.array([p["measured_n"] for p in self.points])
        A = np.column_stack([tau, np.ones_like(tau)])
        (g, c), *_ = np.linalg.lstsq(A, f, rcond=None)
        tau0 = -c / g if g else 0.0
        pred = A @ np.array([g, c])
        ss_res = float(np.sum((f - pred) ** 2))
        ss_tot = float(np.sum((f - f.mean()) ** 2)) or 1.0
        self.result = {"gain_n_per_nm": float(g), "tau_offset_nm": float(tau0),
                       "tau_friction_nm": float(self.tau_friction if self.tau_friction is not None else 0.12),
                       "r2": round(1 - ss_res / ss_tot, 4), "points": self.points}

    def can_commit(self) -> bool:
        return self.result is not None and len(self.points) >= 2

    def apply(self) -> None:
        self.ctx.arm_request(self.target, "reload_calibration")

    def live(self) -> Dict[str, Any]:
        st = self.ctx.arm_state(self.target)
        f = lambda k: round(float(np.nan_to_num(st.get(k, 0.0))), 4)  # noqa: E731
        return {"gripper_opening": f("follower_gripper"), "estimated_grip_force_n": f("grip_force"),
                "gripper_torque_nm": f("follower_gripper_tau"), "points_collected": len(self.points)}

    def summary(self) -> str:
        if not self.result:
            return ""
        return f"G {self.result['gain_n_per_nm']:.1f} N/N·m, R² {self.result['r2']:.3f}"


# =============================================================================== camera


class CameraProcedure(Procedure):
    kind = "camera"
    title = "Camera intrinsics"
    description = ("Calibrates focal length, principal point and lens distortion from 12 or more views of a "
                   "printed ChArUco board. Download the board at /api/calibration/charuco.png and print it at 100% scale.")
    MIN_VIEWS = 12

    def __init__(self, ctx: CalContext, target: str):
        super().__init__(ctx, target)
        self.square_mm = 30.0
        self.marker_mm = 22.0
        self.views: List[Dict[str, Any]] = []
        self.size = None

    def steps(self) -> List[StepDef]:
        return [
            StepDef("board", "Board", "Print the ChArUco board (5×7 squares) and measure one square with a ruler.",
                    "input", inputs=[{"key": "square_mm", "label": "Square size (mm)", "type": "number", "default": 30},
                                     {"key": "marker_mm", "label": "Marker size (mm)", "type": "number", "default": 22}]),
            StepDef("collect", "Collect views",
                    f"Hold the board in view and Capture at least {self.MIN_VIEWS} times: vary distance, tilt (±45°), "
                    "and position (cover the corners of the image).", "capture", repeatable=True),
            StepDef("solve", "Solve", "Computes the intrinsics and the reprojection error.", "auto"),
        ]

    def run(self, step_id: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        from station.calibration import charuco

        if step_id == "board":
            self.square_mm = float(inputs.get("square_mm") or 30)
            self.marker_mm = float(inputs.get("marker_mm") or 22)
            if self.marker_mm >= self.square_mm:
                raise CalError("the marker must be smaller than the square")
            return {"message": f"{self.square_mm:.0f} mm squares"}
        if step_id == "collect":
            d = self.ctx.scratch_dir(self.id)
            path = d / f"view_{len(self.views):03d}.png"
            if self.ctx.sim:
                charuco.render_synthetic_view(path, len(self.views), self.square_mm, self.marker_mm)
            else:
                self.ctx.camera_capture(self.target, path)
            det = charuco.detect(path, self.square_mm, self.marker_mm)
            if det["n"] < 8:
                raise CalError(f"only {det['n']} board corners found", "move closer, improve the lighting, avoid glare")
            self.size = det["size"]
            self.views.append({"path": str(path), "n": det["n"]})
            n = len(self.views)
            more = max(0, self.MIN_VIEWS - n)
            return {"message": f"{n} views ({det['n']} corners)" + (f" · {more} more needed" if more else " · ready"),
                    "advance": n >= self.MIN_VIEWS, "views": n}
        if step_id == "solve":
            if len(self.views) < self.MIN_VIEWS:
                raise CalError(f"need {self.MIN_VIEWS} views, have {len(self.views)}", "go back to Collect views")
            res = charuco.calibrate([Path(v["path"]) for v in self.views], self.square_mm, self.marker_mm)
            if res["rms"] > 1.0:
                raise CalError(f"reprojection error {res['rms']:.2f} px is too high",
                               "recapture with sharper images and more varied angles")
            self.result = {"camera": self.target, **res,
                           "board": {"squares_x": charuco.SQUARES_X, "squares_y": charuco.SQUARES_Y,
                                     "square_mm": self.square_mm, "marker_mm": self.marker_mm,
                                     "dictionary": charuco.DICT_NAME}}
            return {"message": f"RMS {res['rms']:.3f} px · fx {res['camera_matrix'][0][0]:.1f}"}
        raise CalError(f"unknown step {step_id}")

    def summary(self) -> str:
        return f"RMS {self.result['rms']:.3f} px over {self.result['views']} views" if self.result else ""


# =============================================================================== fingertips


class FingertipProcedure(Procedure):
    kind = "fingertips"
    title = "Follower fingertip sensors"
    description = ("Zeroes both jaw pads and calibrates each one against a known weight, so the force you "
                   "feel is the true contact force at the object.")

    def __init__(self, ctx: CalContext, target: str):
        super().__init__(ctx, target)
        self.m: Dict[str, float] = {}

    def steps(self) -> List[StepDef]:
        w = [{"key": "mass_g", "label": "Mass (g)", "type": "number", "default": 1000}]
        return [
            StepDef("tare", "Zero", "Open the gripper and make sure nothing touches either pad. Capture.", "auto"),
            StepDef("pad_a", "Pad A", "Lay the gripper on its side with pad A facing up (or hang the weight from it "
                    "with a strap). Put a known weight of 0.5–2 kg on pad A only. Enter the mass and Capture.",
                    "input", inputs=w),
            StepDef("pad_b", "Pad B", "Same for pad B: weight on pad B only. Enter the mass and Capture.",
                    "input", inputs=w),
        ]

    def on_end(self) -> None:
        if self.ctx.sim:
            try:
                self.ctx.arm_request(self.target, "sim_ft_weight", n=0.0)
            except Exception:
                pass

    def run(self, step_id: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        side = self.target
        if not self.ctx.arm_connected(side):
            raise CalError("arm not started", "press Start Arms first")
        if step_id == "tare":
            self.ctx.arm_request(side, "fingertip_tare", timeout=3.0)
            time.sleep(0.3)
            r = self.ctx.arm_request(side, "fingertip_read", n=100)
            if max(abs(r["a"]), abs(r["b"])) > 0.3:
                raise CalError(f"pads read {r['a']:.2f} / {r['b']:.2f} N after zeroing", "make sure nothing touches the pads")
            self.m["noise_a"], self.m["noise_b"] = r["std_a"], r["std_b"]
            return {"message": f"zeroed · noise {r['std_a'] * 1000:.0f} / {r['std_b'] * 1000:.0f} mN rms"}
        pad = step_id[-1]
        mass = float(inputs.get("mass_g") or 1000.0)
        f_true = mass / 1000.0 * 9.81
        if self.ctx.sim:
            self.ctx.arm_request(side, "sim_ft_weight", n=f_true * float(np.random.normal(0.97, 0.01)))
            time.sleep(0.3)
        r = self.ctx.arm_request(side, "fingertip_read", n=150)
        if self.ctx.sim:
            self.ctx.arm_request(side, "sim_ft_weight", n=0.0)
        measured = r[pad]
        if measured < 0.2 * f_true:
            raise CalError(f"pad {pad.upper()} reads only {measured:.2f} N for a {f_true:.2f} N weight",
                           "check the weight rests on that pad only and the cable is connected")
        self.m[f"gain_{pad}"] = f_true / measured
        if "gain_a" in self.m and "gain_b" in self.m:
            self.result = {"gain_a": round(self.m["gain_a"], 5), "gain_b": round(self.m["gain_b"], 5),
                           "noise_n": [round(self.m.get("noise_a", 0.0), 4), round(self.m.get("noise_b", 0.0), 4)]}
        return {"message": f"pad {pad.upper()}: {measured:.2f} N measured for {f_true:.2f} N → gain {f_true / measured:.3f}"}

    def apply(self) -> None:
        self.ctx.arm_request(self.target, "reload_calibration")

    def live(self) -> Dict[str, Any]:
        st = self.ctx.arm_state(self.target)
        f = lambda k: round(float(np.nan_to_num(st.get(k, 0.0))), 3)  # noqa: E731
        return {"pad_a_force_n": f("fingertip_a"), "pad_b_force_n": f("fingertip_b")}

    def summary(self) -> str:
        return f"gains {self.result['gain_a']:.3f} / {self.result['gain_b']:.3f}" if self.result else ""


def build_procedures(ctx: CalContext) -> Dict[str, Procedure]:
    cfg = ctx.config()
    procs: Dict[str, Procedure] = {}
    for side in cfg.enabled_arms():
        for cls in (LeaderProcedure, TriggerProcedure, GripperProcedure):
            p = cls(ctx, side)
            procs[p.id] = p
        if cfg.arms[side].fingertips.backend != "none":
            p = FingertipProcedure(ctx, side)
            procs[p.id] = p
    for name in cfg.cameras:
        p = CameraProcedure(ctx, name)
        procs[p.id] = p
    return procs


PROCEDURE_LABELS = {"leader": "{side} leader arm", "trigger": "{side} haptic trigger",
                    "gripper": "{side} gripper force", "camera": "{name} camera"}
