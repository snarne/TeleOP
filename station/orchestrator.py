"""Orchestrator: the station's brain in the server process.

Owns the phase state machine, spawns and supervises arm/camera workers, routes their
events, runs startup/power/recording/calibration flows, and builds the state snapshot
the UI streams. All public methods are thread-safe and either fast or explicitly
backgrounded, so HTTP handlers can call them directly.
"""

from __future__ import annotations

import json
import logging
import math
import multiprocessing as mp
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import psutil
from sqlmodel import select

from station import __version__
from station.calibration.procedures import CalError, Procedure, build_procedures
from station.cameras.worker import run_camera_worker
from station.config import SIDES, StationConfig
from station.db import CalibrationRecord, Database, Department, Episode, Task, User, slugify
from station.health import can_state, run_checks
from station.hardware.power import PowerManager
from station.ipc import ARM_FIELDS, ARM_STATES, CAMERA_FIELDS, TRIGGER_MODES, JpegSlot, SharedBlock
from station.logbus import LogBus, LogBusHandler
from station.recording.recorder import Recorder, git_version
from station.teleop.arm_worker import run_arm_worker

log = logging.getLogger("station.orchestrator")
_console = logging.getLogger("station.worker")

PHASES = ["off", "idle", "starting", "ready", "teleop", "recording", "saving", "stopping", "fault"]

DEFAULT_HAPTICS = {"enabled": True, "feedback_gain": 0.25, "max_render_n": 12.0, "spring_n": 1.5, "spring_min_n": 1.2,
                   "damping": 0.02, "force_input": False, "input_gain": 4.0, "max_grip_n": 50.0, "force_curve": 1.0,
                   "feedback_mode": "perceptual", "feedback_exponent": 0.6, "cues_enabled": True, "cue_strength": 0.8}
# Hard bounds on operator-editable haptic settings (validated on every settings update).
# Hard bounds on operator-editable haptic settings. max_grip_n is bounded per arm by the
# follower's max_grip_force_n (the gripper's full force), not here.
HAPTIC_LIMITS = {"feedback_gain": (0.0, 1.0), "max_render_n": (0.0, 15.0), "spring_n": (0.0, 5.0),
                 "spring_min_n": (0.0, 3.0), "damping": (0.0, 0.2), "input_gain": (0.5, 10.0),
                 "force_curve": (0.3, 3.0), "feedback_exponent": (0.2, 1.5), "cue_strength": (0.0, 1.0)}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "keybindings": {"start_recording": "KeyR", "save": "KeyS", "abort": "KeyX", "teleop_toggle": "KeyT",
                    "estop": "Escape", "mark_success": "KeyY", "mark_failure": "KeyN"},
    "handle_buttons": {"left_a": "save", "left_b": "abort", "right_a": "start_recording", "right_b": "teleop_toggle"},
    "haptics": {"left": dict(DEFAULT_HAPTICS), "right": dict(DEFAULT_HAPTICS)},
    "recording": {"auto_export": False, "countdown_s": 0, "max_duration_s": 600, "confirm_abort_after_s": 10},
}


class StationError(RuntimeError):
    def __init__(self, detail: str, hint: str = "", status: int = 409):
        super().__init__(detail)
        self.detail, self.hint, self.status = detail, hint, status


def _f(x: Any) -> Any:
    """JSON-safe float(s): NaN/inf → None."""
    if isinstance(x, np.ndarray):
        return [_f(v) for v in x.tolist()]
    if isinstance(x, (list, tuple)):
        return [_f(v) for v in x]
    if isinstance(x, float):
        return round(x, 5) if math.isfinite(x) else None
    return x


class Orchestrator:
    def __init__(self, cfg: StationConfig):
        self.cfg = cfg
        self.sim = cfg.station.sim
        self.data_root = cfg.data_root
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.cal_dir = self.data_root / "calibration"
        self.cal_dir.mkdir(parents=True, exist_ok=True)
        self.logbus = LogBus()
        self._install_logging()
        self.db = Database(self.data_root / "station.db")
        self.db.seed_if_empty()
        self.ctx = mp.get_context("spawn")
        self.use_processes = cfg.runtime.workers == "process"
        self.lock = threading.RLock()
        self.phase = "idle"
        self.phase_detail = ""
        self.startup_steps: List[Dict[str, Any]] = []
        # macOS caps multiprocessing queue sizes at SEM_VALUE_MAX (32767); stay below it everywhere.
        # 30000 samples ≈ 75 s of both arms at 200 Hz, far more than the recorder ever lags.
        self.evt_q = self.ctx.Queue(maxsize=20000) if self.use_processes else queue.Queue(maxsize=20000)
        self.sample_q = self.ctx.Queue(maxsize=30000) if self.use_processes else queue.Queue(maxsize=30000)
        self.arm_blocks = {s: SharedBlock(ARM_FIELDS, self.ctx) for s in cfg.enabled_arms()}
        self.cam_blocks = {n: SharedBlock(CAMERA_FIELDS, self.ctx) for n in cfg.cameras}
        self.jpegs = {n: JpegSlot(ctx=self.ctx) for n in cfg.cameras}
        self.arm_procs: Dict[str, Any] = {}
        self.arm_cmd: Dict[str, Any] = {}
        self.arm_connected: Dict[str, bool] = {s: False for s in cfg.enabled_arms()}
        self.arm_fault: Dict[str, Optional[str]] = {s: None for s in cfg.enabled_arms()}
        self.cam_procs: Dict[str, Any] = {}
        self.cam_cmd: Dict[str, Any] = {}
        self._pending: Dict[str, Dict[str, Any]] = {}
        self.power = PowerManager(cfg.power)
        self.recorder = Recorder(self.data_root, self.sample_q, cfg.recording.telemetry_compression)
        self.logbus.listeners.append(lambda l: self.recorder.log_line(l["ts"], l.get("level", "INFO"),
                                                                       l.get("source", ""), l.get("message", "")))
        self.procedures: Dict[str, Procedure] = build_procedures(_CalCtx(self))
        self.active_cal: Optional[Procedure] = None
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.health_cache: Optional[Dict[str, Any]] = None
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        rev = git_version(Path(__file__).resolve().parent.parent)
        self.version = __version__ if rev == "unknown" else f"{__version__}+{rev}"
        self._rec_meta_pending: Optional[Dict[str, Any]] = None
        self._estop_latched = False
        self._last_estop_ok: Optional[bool] = None
        self._stopping: set = set()
        self._deferred: "queue.Queue" = queue.Queue()   # blocking work triggered by events (never on the pump)
        self._export_q: "queue.Queue" = queue.Queue()   # exports run one at a time (they may share a dataset)
        self._fault_epoch = 0                             # bumped by clear_fault; stale fault events are ignored

    # =================================================================== lifecycle

    def _install_logging(self) -> None:
        root = logging.getLogger()
        if not any(isinstance(h, LogBusHandler) for h in root.handlers):
            root.addHandler(LogBusHandler(self.logbus))
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)

    def start(self) -> None:
        log.info("station '%s' starting (%s, workers=%s, %s)", self.cfg.station.name, self.version,
                 self.cfg.runtime.workers, "SIMULATION" if self.sim else "hardware")
        self.power.connect()
        from station.input_devices import InputDevices

        self.inputs = InputDevices(self.cfg.inputs, lambda a, src: self.do_action(a, source=src))
        self.inputs.start()
        for name in self.cfg.cameras:
            self._spawn_camera(name)
        for target, name in ((self._event_pump, "evt-pump"), (self._supervisor, "supervisor"),
                             (self._deferred_worker, "deferred"), (self._export_worker, "exports")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        self.phase = "idle"

    def shutdown(self) -> None:
        log.info("station shutting down")
        try:
            if self.recorder.is_active:
                self.recorder.finish(keep=False)
        except Exception:
            pass
        for side in list(self.arm_procs):
            self._stop_arm_worker(side, home=True)
        for name, q in self.cam_cmd.items():
            q.put({"cmd": "stop"})
        for p in self.cam_procs.values():
            if hasattr(p, "join"):
                p.join(timeout=3)
            if hasattr(p, "terminate") and p.is_alive():
                p.terminate()
        self._stop.set()
        self.power.close()

    # =================================================================== workers

    def _launch(self, target, args, kwargs, name: str):
        if self.use_processes:
            p = self.ctx.Process(target=target, args=args, kwargs=kwargs, name=name, daemon=True)
        else:
            kwargs = dict(kwargs, log_to_queue=False)
            p = threading.Thread(target=target, args=args, kwargs=kwargs, name=name, daemon=True)
        p.start()
        return p

    def _queue(self):
        return self.ctx.Queue() if self.use_processes else queue.Queue()

    def _spawn_camera(self, name: str) -> None:
        q = self._queue()
        self.cam_cmd[name] = q
        self.cam_procs[name] = self._launch(
            run_camera_worker,
            (name, self.cfg.cameras[name], self.cfg.recording, self.cam_blocks[name], self.jpegs[name], q,
             self.evt_q, self.arm_blocks), {}, f"camera-{name}")

    def _spawn_arm(self, side: str) -> None:
        q = self._queue()
        self.arm_cmd[side] = q
        self.arm_connected[side] = False
        self.arm_fault[side] = None
        haptics = self.settings()["haptics"].get(side, DEFAULT_HAPTICS)
        self.arm_procs[side] = self._launch(
            run_arm_worker,
            (side, self.cfg.arms[side], str(self.cal_dir), self.cfg.runtime.control_hz, self.arm_blocks[side], q,
             self.evt_q, self.sample_q, haptics), {}, f"arm-{side}")

    def _stop_arm_worker(self, side: str, home: bool = True) -> None:
        p = self.arm_procs.get(side)
        if p is None:
            return
        self._stopping.add(side)
        try:
            if home and self.arm_connected.get(side):
                r = self.arm_request(side, "home", timeout=3.0)
                time.sleep(min(float(r.get("duration_s", 2.0)) + 0.3, 8.0))
            self.arm_request(side, "stop", timeout=5.0)
        except Exception as e:
            log.warning("arm %s did not stop cleanly: %s", side, e)
        p.join(timeout=5)
        if self.use_processes and p.is_alive():
            log.warning("terminating arm %s worker", side)
            p.terminate()
        self.arm_procs.pop(side, None)
        self.arm_cmd.pop(side, None)
        self.arm_connected[side] = False
        self._stopping.discard(side)

    def arm_alive(self, side: str) -> bool:
        p = self.arm_procs.get(side)
        return p is not None and p.is_alive()

    # =================================================================== request/reply

    def _request(self, _queue, _timeout: float, **msg: Any) -> Dict[str, Any]:
        req = uuid.uuid4().hex[:10]
        ev = threading.Event()
        slot: Dict[str, Any] = {"event": ev}
        self._pending[req] = slot
        timeout = _timeout
        _queue.put(dict(msg, req=req))
        if not ev.wait(timeout):
            self._pending.pop(req, None)
            raise StationError(f"no reply to '{msg.get('cmd')}' within {timeout:.0f}s", "check the logs for this device")
        r = slot["reply"]
        if not r.get("ok"):
            raise StationError(r.get("error") or "request failed")
        return r.get("data") or {}

    def arm_request(self, side: str, cmd: str, timeout: float = 5.0, **kw: Any) -> Dict[str, Any]:
        q = self.arm_cmd.get(side)
        if q is None or not self.arm_alive(side):
            raise StationError(f"{side} arm is not started", "press Start Arms")
        return self._request(q, timeout, cmd=cmd, **kw)

    def camera_request(self, name: str, cmd: str, timeout: float = 5.0, **kw: Any) -> Dict[str, Any]:
        if name not in self.cam_cmd:
            raise StationError(f"unknown camera {name!r}", status=404)
        return self._request(self.cam_cmd[name], timeout, cmd=cmd, **kw)

    def _broadcast_arms(self, cmd: str, **kw: Any) -> None:
        for side, q in list(self.arm_cmd.items()):
            if self.arm_alive(side):
                q.put(dict(cmd=cmd, **kw))

    # =================================================================== event pump

    def _event_pump(self) -> None:
        while not self._stop.is_set():
            try:
                e = self.evt_q.get(timeout=0.2)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                break
            try:
                self._on_event(e)
            except Exception as ex:  # pragma: no cover
                log.error("event handling failed for %s: %s", e.get("type"), ex)

    def _defer(self, fn, *args: Any) -> None:
        self._deferred.put((fn, args))

    def _deferred_worker(self) -> None:
        while not self._stop.is_set():
            try:
                fn, args = self._deferred.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                fn(*args)
            except Exception as ex:
                log.error("deferred %s failed: %s", getattr(fn, "__name__", fn), ex)

    def _on_event(self, e: Dict[str, Any]) -> None:
        # Runs on the event-pump thread, the only thread that delivers worker replies.
        # Never block here: anything that waits on a worker goes through _defer().
        t = e.get("type")
        if t == "log":
            self.logbus.publish({"ts": e.get("ts"), "level": e.get("level", "INFO"), "source": e.get("source", ""),
                                 "message": e.get("message", "")})
            # mirror worker logs to the server console (marked so LogBusHandler doesn't publish them twice)
            lvl = getattr(logging, str(e.get("level", "INFO")), logging.INFO)
            _console.log(lvl, "[%s] %s", e.get("source", ""), e.get("message", ""), extra={"from_worker": True})
        elif t == "reply":
            slot = self._pending.pop(e.get("req") or "", None)
            if slot is not None:
                slot["reply"] = e
                slot["event"].set()
        elif t == "step":
            self._set_step(e["id"], e["status"], e.get("message", ""), e.get("duration_s"))
        elif t == "connected":
            self.arm_connected[e["side"]] = True
        elif t == "stopped":
            self.arm_connected[e["side"]] = False
        elif t == "fault":
            side = e.get("side")
            self.arm_fault[side] = e.get("message")
            reason = f"{side} arm: {e.get('message')}"
            if self.phase != "fault":  # cheap and immediate; the slow part (saving a take) is deferred
                self.phase, self.phase_detail = "fault", reason
            self._defer(self._enter_fault, reason, self._fault_epoch)
        elif t == "button":
            self._defer(self._on_button, e["side"], e["button"])
        if t in ("fault", "button", "teleop"):
            self.recorder.event(t, {k: v for k, v in e.items() if k != "type"})

    def _on_button(self, side: str, button: str) -> None:
        action = self.settings()["handle_buttons"].get(f"{side}_{button}")
        log.info("handle button %s/%s → %s", side, button, action or "unbound")
        if not action:
            return
        try:
            self.do_action(action, source=f"handle:{side}_{button}")
        except StationError as ex:
            log.warning("button action %s failed: %s", action, ex.detail)

    def do_action(self, action: str, source: str = "") -> Dict[str, Any]:
        """Named actions shared by keyboard bindings, handle buttons and foot pedals."""
        if action == "start_recording":
            return self.start_recording()
        if action == "save":
            return self.save_recording()
        if action == "abort":
            return self.abort_recording()
        if action == "toggle_recording":
            return self.save_recording() if self.recorder.is_active else self.start_recording()
        if action == "teleop_toggle":
            return self.set_teleop(self.phase not in ("teleop", "recording"))
        if action == "mark_success":
            self._rec_meta_pending = dict(self._rec_meta_pending or {}, success=True)
            return {"ok": True}
        if action == "mark_failure":
            self._rec_meta_pending = dict(self._rec_meta_pending or {}, success=False)
            return {"ok": True}
        if action == "estop":
            return self.estop()
        raise StationError(f"unknown action {action!r}", status=400)

    # =================================================================== supervisor

    def _supervisor(self) -> None:
        last_power = 0.0
        last_led_phase = None
        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_power > 0.5:
                last_power = now
                try:
                    self.power.refresh()
                except Exception:
                    pass
                ok = self.power.estop_ok()
                if ok is False and self._last_estop_ok is not False:
                    log.error("E-STOP pressed: arm power is cut in hardware")
                    self._estop_latched = True
                    self._broadcast_arms("estop", reason="hardware e-stop")
                    self._defer(self._enter_fault, "E-stop pressed", None)
                elif ok is True and self._last_estop_ok is False:
                    log.info("e-stop released: power-cycle the arms (Start Arms) to continue")
                self._last_estop_ok = ok
            # workers that died unexpectedly
            for side, p in list(self.arm_procs.items()):
                if not p.is_alive() and self.arm_connected.get(side) and side not in self._stopping:
                    self.arm_connected[side] = False
                    self._defer(self._enter_fault, f"{side} arm worker exited unexpectedly", None)
            for name, p in list(self.cam_procs.items()):
                if not p.is_alive() and not self._stop.is_set():
                    log.error("camera %s worker died: restarting", name)
                    self._spawn_camera(name)
            # recording duration cap
            if self.recorder.is_active:
                cap = self.settings()["recording"].get("max_duration_s", 600)
                if cap and time.monotonic() - self.recorder.active["t0_mono"] > cap:
                    log.warning("recording reached max duration (%ss): saving automatically", cap)
                    self._defer(self._autosave)
            if self.phase != last_led_phase:
                last_led_phase = self.phase
                self._broadcast_arms("led", phase=self.phase)
            time.sleep(0.1)

    def _autosave(self) -> None:
        try:
            if self.recorder.is_active:
                self.save_recording()
        except Exception as e:
            log.error("auto-save failed: %s", e)

    def _enter_fault(self, reason: str, epoch: Optional[int] = None) -> None:
        """Stop everything, then save any take in progress (tagged 'fault').

        A fault on one arm stops *every* arm: a lone follower must never keep teleoperating
        while the station reports a fault."""
        if epoch is not None and epoch != self._fault_epoch:
            return  # fault event from before the last clear_fault
        self._broadcast_arms("estop", reason=f"station fault: {reason}")
        if self.phase != "fault":
            self.phase, self.phase_detail = "fault", reason
        with self.lock:
            if self.recorder.is_active:
                try:
                    self._finish_recording(keep=True, success=False, notes=f"auto-saved on fault: {reason}",
                                           tags=["fault"])
                except Exception as e:
                    log.error("could not save recording on fault: %s", e)
            self.phase = "fault"
            self.phase_detail = reason

    # =================================================================== steps

    def _set_step(self, sid: str, status: str, message: str = "", duration: Optional[float] = None) -> None:
        with self.lock:
            for s in self.startup_steps:
                if s["id"] == sid:
                    s.update(status=status, message=message)
                    if duration is not None:
                        s["duration_s"] = round(duration, 2)
                    return
            self.startup_steps.append({"id": sid, "label": sid, "status": status, "message": message,
                                       "duration_s": round(duration or 0, 2)})

    def _plan_steps(self, sides: List[str]) -> None:
        steps = [("power", "Power on arms")]
        for side in sides:
            steps += [(f"can_{side}", f"{side.title()} CAN bus"), (f"leader_{side}", f"{side.title()} leader arm"),
                      (f"trigger_{side}", f"{side.title()} trigger"), (f"follower_{side}", f"{side.title()} follower YAM"),
                      *([(f"fingertips_{side}", f"{side.title()} fingertip sensors")]
                        if self.cfg.arms[side].fingertips.backend != "none" else []),
                      (f"calibration_{side}", f"{side.title()} calibration")]
        steps += [("cameras", "Cameras streaming"), ("pose_check", "Leader/follower pose check")]
        self.startup_steps = [{"id": i, "label": l, "status": "pending", "message": "", "duration_s": 0.0} for i, l in steps]

    # =================================================================== control: power

    def set_power(self, channel: str, on: bool) -> Dict[str, Any]:
        if on and self.power.estop_ok() is False:
            raise StationError("E-stop is pressed", "release the e-stop first")
        if not on:
            running = [s for s in self._arms_on_channel(channel) if self.arm_alive(s)]
            if running:
                raise StationError(f"{', '.join(running)} arm running", "Stop Arms first, or use Power cycle (parks the arm)")
        try:
            self.power.set(channel, on)
        except (RuntimeError, KeyError) as e:
            raise StationError(str(e), "check power.* in the station config")
        return self.power.snapshot()

    def _arm_channels(self) -> Dict[str, str]:
        return {s: self.cfg.arms[s].power_channel for s in self.cfg.enabled_arms() if self.cfg.arms[s].power_channel}

    def _arms_on_channel(self, channel: str) -> List[str]:
        """Arms whose follower or leader is fed by this relay channel ('all' = every arm)."""
        out = []
        for s in self.cfg.enabled_arms():
            a = self.cfg.arms[s]
            if channel == "all" or channel in (a.power_channel, a.leader_power_channel):
                out.append(s)
        return out

    def power_cycle(self, channel: str, off_s: float = 3.0) -> Dict[str, Any]:
        if self.recorder.is_active:
            raise StationError("recording in progress", "save or abort the recording first")
        if self.phase in ("starting", "stopping", "saving"):
            raise StationError(f"wait: the station is {self.phase}")
        if not self.power.available or self.power.driver is None:
            raise StationError("no relay board configured", "see docs/hardware/electronics.md → Power control")

        def run():
            affected = self._arms_on_channel(channel)
            was_running = [s for s in affected if self.arm_alive(s)]
            log.info("power cycle %s (arms: %s)", channel, affected or "none")
            for s in was_running:
                self._stop_arm_worker(s, home=True)
            try:
                self.power.set(channel, False)
                time.sleep(max(off_s, 1.0))
                self.power.set(channel, True)
                time.sleep(self.cfg.power.boot_wait_s)
            except Exception as e:
                log.error("power cycle failed: %s", e)
                return
            if was_running:
                try:
                    self.start_arms(was_running, background=False)
                except StationError as e:
                    log.error("restart after power cycle failed: %s", e.detail)
            log.info("power cycle %s complete", channel)

        threading.Thread(target=run, name="power-cycle", daemon=True).start()
        return {"started": True}

    # =================================================================== control: arms

    def start_arms(self, arms: Optional[List[str]] = None, background: bool = True) -> Dict[str, Any]:
        sides = [s for s in (arms or self.cfg.enabled_arms()) if s in self.cfg.enabled_arms()]
        with self.lock:
            if self.phase in ("starting", "stopping", "teleop", "recording", "saving"):
                raise StationError(f"can't start arms while {self.phase}",
                                   "disengage teleop first" if self.phase == "teleop" else "")
            if self.phase == "fault" and self._estop_latched and self.power.estop_ok() is False:
                raise StationError("E-stop is pressed", "release the e-stop first")
            self.phase = "starting"
            self.phase_detail = ""
            self._estop_latched = False
            self._plan_steps(sides)
        if background:
            threading.Thread(target=self._start_arms, args=(sides,), name="start-arms", daemon=True).start()
        else:
            self._start_arms(sides)
        return {"steps": self.startup_steps}

    def _start_arms(self, sides: List[str]) -> None:
        t0 = time.monotonic()
        try:
            # 1 · power
            if self.power.driver is not None:
                if self.power.estop_ok() is False:
                    self._set_step("power", "error", "E-stop is pressed: release it", 0)
                    raise StationError("E-stop pressed")
                off = [c.id for c in self.cfg.power.channels if self.power.is_on(c.id) is not True]
                if off:
                    for cid in off:
                        self.power.set(cid, True)
                    self._set_step("power", "running", f"powered {', '.join(off)}; waiting for boot")
                    time.sleep(self.cfg.power.boot_wait_s)
                self._set_step("power", "ok", "all channels on", time.monotonic() - t0)
            else:
                self._set_step("power", "skipped", "no relay board: make sure the arms are switched on")
            # 2 · CAN
            for side in sides:
                f = self.cfg.arms[side].follower
                t1 = time.monotonic()
                if f.backend == "sim":
                    self._set_step(f"can_{side}", "ok", "simulated")
                    continue
                cs = can_state(f.can_channel)
                if cs["exists"] and not cs["up"]:
                    self._can_up(f.can_channel)
                    cs = can_state(f.can_channel)
                if not cs["exists"]:
                    self._set_step(f"can_{side}", "error", f"{f.can_channel} missing: CANable unplugged or udev name wrong",
                                   time.monotonic() - t1)
                elif not cs["up"]:
                    self._set_step(f"can_{side}", "error", f"{f.can_channel} is down (needs sudo: see Hardware → Reset CAN)",
                                   time.monotonic() - t1)
                else:
                    self._set_step(f"can_{side}", "ok", f"{f.can_channel} up", time.monotonic() - t1)
            # 3 · workers (leader, trigger, follower, calibration steps are reported by the workers)
            for side in sides:
                if self.arm_alive(side):
                    self._stop_arm_worker(side, home=False)
                self._spawn_arm(side)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                done = all(self.arm_connected.get(s) or self.arm_fault.get(s) or not self.arm_alive(s) for s in sides)
                if done:
                    break
                time.sleep(0.05)
            failed = [s for s in sides if not self.arm_connected.get(s)]
            for s in failed:
                for k in ("leader", "trigger", "follower", "calibration"):
                    st = next((x for x in self.startup_steps if x["id"] == f"{k}_{s}"), None)
                    if st and st["status"] in ("pending", "running"):
                        self._set_step(f"{k}_{s}", "skipped" if st["status"] == "pending" else "error",
                                       "" if st["status"] == "pending" else "timed out")
            # 4 · cameras
            time.sleep(0.3)
            cams = self.camera_snapshot()
            bad = [n for n, c in cams.items() if not c["ok"]]
            slow = [n for n, c in cams.items() if c["ok"] and (c["fps"] or 0) < 25]
            if bad:
                self._set_step("cameras", "warn", f"not streaming: {', '.join(bad)}")
            elif slow:
                self._set_step("cameras", "warn", f"low frame rate: {', '.join(slow)}")
            else:
                self._set_step("cameras", "ok", f"{len(cams)} cameras at ≥25 fps")
            # 5 · pose check
            time.sleep(0.2)
            msgs, worst = [], 0.0
            for s in sides:
                if not self.arm_connected.get(s):
                    continue
                st = self.arm_blocks[s].read()
                d = np.abs(np.asarray(st["leader_q"]) - np.asarray(st["follower_q"]))
                if np.all(np.isfinite(d)):
                    worst = max(worst, float(d.max()))
                    msgs.append(f"{s} max Δ {math.degrees(d.max()):.0f}°")
            if msgs:
                self._set_step("pose_check", "warn" if worst > 0.6 else "ok",
                               "; ".join(msgs) + (" · engaging will slowly move the follower" if worst > 0.6 else ""))
            else:
                self._set_step("pose_check", "skipped")
            with self.lock:
                if failed:
                    self.phase = "fault"
                    self.phase_detail = f"{', '.join(failed)} arm failed to start: see the checklist"
                else:
                    self.phase = "ready"
                    log.info("arms ready in %.1fs", time.monotonic() - t0)
        except StationError as e:
            with self.lock:
                self.phase, self.phase_detail = "fault", e.detail
        except Exception as e:
            log.exception("start arms failed")
            with self.lock:
                self.phase, self.phase_detail = "fault", str(e)

    def _can_up(self, name: str) -> bool:
        cmd = ["sudo", "-n", "ip", "link", "set", name, "up", "type", "can", "bitrate", "1000000"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            log.warning("could not bring up %s: %s", name, r.stderr.strip() or r.stdout.strip())
            return False
        log.info("brought up %s at 1 Mbit/s", name)
        return True

    def reset_can(self) -> Dict[str, Any]:
        out = {}
        for side in self.cfg.enabled_arms():
            f = self.cfg.arms[side].follower
            if f.backend != "i2rt":
                out[f.can_channel] = "simulated"
                continue
            subprocess.run(["sudo", "-n", "ip", "link", "set", f.can_channel, "down"], capture_output=True)
            out[f.can_channel] = "up" if self._can_up(f.can_channel) else "failed (configure passwordless sudo for ip: see scripts/setup_ubuntu.sh)"
        return out

    def stop_arms(self) -> Dict[str, Any]:
        if self.recorder.is_active:
            self.abort_recording()
        with self.lock:
            self.phase = "stopping"

        def run():
            for side in list(self.arm_procs):
                self._stop_arm_worker(side, home=True)
            with self.lock:
                self.phase = "idle"
                self.phase_detail = ""
            log.info("arms stopped")

        threading.Thread(target=run, name="stop-arms", daemon=True).start()
        return {"stopping": True}

    def reconnect_arm(self, side: str) -> Dict[str, Any]:
        if side not in self.cfg.enabled_arms():
            raise StationError(f"unknown arm {side!r}", status=404)
        if self.recorder.is_active:
            raise StationError("recording in progress")
        if self.phase in ("teleop", "starting", "stopping"):
            raise StationError(f"can't reconnect while {self.phase}", "disengage teleop first")
        self._stop_arm_worker(side, home=True)
        return self.start_arms([side])

    def set_teleop(self, enabled: bool) -> Dict[str, Any]:
        with self.lock:
            connected = [s for s in self.cfg.enabled_arms() if self.arm_connected.get(s)]
            if enabled:
                if self.phase not in ("ready", "teleop"):
                    raise StationError(f"can't engage teleop while {self.phase}",
                                       "Start Arms first" if self.phase in ("idle", "off") else "clear the fault first")
                if not connected:
                    raise StationError("no arms connected", "press Start Arms")
                if self.active_cal is not None:
                    raise StationError(f"calibration '{self.active_cal.id}' is open",
                                       "finish or cancel it first (Calibration page)")
            else:
                if self.recorder.is_active:
                    raise StationError("recording in progress", "save or abort before disengaging")
        errors, engaged = [], []
        for s in connected:
            try:
                self.arm_request(s, "teleop", enabled=enabled)
                engaged.append(s)
            except StationError as e:
                errors.append(f"{s}: {e.detail}")
        if errors:
            if enabled:  # all-or-nothing: never leave one arm teleoperating alone
                for s in engaged:
                    try:
                        self.arm_request(s, "teleop", enabled=False)
                    except StationError:
                        self._broadcast_arms("estop", reason="teleop rollback failed")
            raise StationError("; ".join(errors))
        with self.lock:
            if enabled:
                self.phase = "teleop"
            elif self.phase == "teleop":
                self.phase = "ready"
        return {"phase": self.phase}

    def home(self) -> Dict[str, Any]:
        if self.phase in ("teleop", "recording"):
            raise StationError("disengage teleop first")
        for s in self.cfg.enabled_arms():
            if self.arm_connected.get(s):
                self.arm_request(s, "home")
        return {"ok": True}

    @staticmethod
    def _parallel(calls) -> List[Any]:
        """Run blocking requests concurrently; raise the first StationError after all finish."""
        results: List[Any] = [None] * len(calls)
        errors: List[StationError] = []

        def run(i, fn, args, kw):
            try:
                results[i] = fn(*args, **kw)
            except StationError as e:
                errors.append(e)
            except Exception as e:
                errors.append(StationError(str(e)))

        ts = [threading.Thread(target=run, args=(i, *c), daemon=True) for i, c in enumerate(calls)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        if errors:
            raise errors[0]
        return results

    def _all_arms(self, cmd: str, timeout: float = 2.0, **kw: Any) -> None:
        """Send to every running arm and wait for each reply (so their events are processed first)."""
        threads = []
        for side in list(self.arm_cmd):
            if self.arm_alive(side):
                def one(s=side):
                    try:
                        self.arm_request(s, cmd, timeout=timeout, **kw)
                    except StationError as e:
                        log.warning("%s %s: %s", s, cmd, e.detail)
                threads.append(threading.Thread(target=one, daemon=True))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout + 0.5)

    def estop(self) -> Dict[str, Any]:
        log.error("SOFTWARE E-STOP")
        self._broadcast_arms("estop", reason="software e-stop")   # arms first, before any bookkeeping
        self.phase, self.phase_detail = "fault", "software e-stop"
        self._all_arms("estop", reason="software e-stop")         # wait for acknowledgements
        self._enter_fault("software e-stop")
        return {"phase": self.phase}

    def clear_fault(self) -> Dict[str, Any]:
        if self.power.estop_ok() is False:
            raise StationError("E-stop is still pressed", "release the e-stop")
        self._all_arms("clear_fault")
        time.sleep(0.05)
        self._fault_epoch += 1
        with self.lock:
            for s in self.arm_fault:
                self.arm_fault[s] = None
            connected = any(self.arm_connected.get(s) and self.arm_alive(s) for s in self.cfg.enabled_arms())
            self.phase = "ready" if connected and not self._estop_latched else "idle"
            self.phase_detail = ""
        return {"phase": self.phase}

    # =================================================================== settings & session

    def settings(self) -> Dict[str, Any]:
        saved = self.db.get_kv("settings", {}) or {}
        out = json.loads(json.dumps(DEFAULT_SETTINGS))
        for side in self.cfg.enabled_arms():  # default: a full squeeze uses the gripper's full force
            out["haptics"].setdefault(side, dict(DEFAULT_HAPTICS))["max_grip_n"] = \
                self.cfg.arms[side].follower.max_grip_force_n
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                for kk, vv in v.items():
                    if isinstance(vv, dict) and isinstance(out[k].get(kk), dict):
                        out[k][kk].update(vv)
                    else:
                        out[k][kk] = vv
            else:
                out[k] = v
        return out

    def update_settings(self, new: Dict[str, Any]) -> Dict[str, Any]:
        merged = self.settings()
        for k, v in new.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                for kk, vv in v.items():
                    if isinstance(vv, dict) and isinstance(merged[k].get(kk), dict):
                        merged[k][kk].update(vv)
                    else:
                        merged[k][kk] = vv
            else:
                merged[k] = v
        for side, h in merged["haptics"].items():
            for key, (lo, hi) in HAPTIC_LIMITS.items():
                if key in h:
                    try:
                        v = float(h[key])
                    except (TypeError, ValueError):
                        raise StationError(f"haptics.{side}.{key} must be a number", status=400)
                    if not lo <= v <= hi:
                        raise StationError(f"haptics.{side}.{key} = {v:g} is outside the safe range {lo:g}–{hi:g}",
                                           status=400)
            if side in self.cfg.arms and "max_grip_n" in h:
                full = self.cfg.arms[side].follower.max_grip_force_n
                if not 1.0 <= float(h["max_grip_n"]) <= full:
                    raise StationError(f"haptics.{side}.max_grip_n must be 1–{full:g} N (the gripper's full force, "
                                       f"arms.{side}.follower.max_grip_force_n)", status=400)
        kb = merged["keybindings"]
        dup = {c for c in kb.values() if c and list(kb.values()).count(c) > 1}
        if dup:
            raise StationError(f"key {', '.join(dup)} is bound to more than one action", status=400)
        self.db.set_kv("settings", merged)
        for side in self.cfg.enabled_arms():
            if self.arm_alive(side):
                self.arm_cmd[side].put({"cmd": "settings", "haptics": merged["haptics"].get(side, DEFAULT_HAPTICS)})
        log.info("settings updated")
        return merged

    def session(self) -> Dict[str, Any]:
        return self.db.get_kv("session", {"operator_id": None, "department_id": None, "task_id": None})

    def set_session(self, s: Dict[str, Any]) -> Dict[str, Any]:
        cur = self.session()
        cur.update({k: s.get(k) for k in ("operator_id", "department_id", "task_id") if k in s})
        self.db.set_kv("session", cur)
        return cur

    # =================================================================== recording

    def _session_entities(self):
        s = self.session()
        with self.db.session() as db:
            user = db.get(User, s.get("operator_id")) if s.get("operator_id") else None
            dept = db.get(Department, s.get("department_id")) if s.get("department_id") else None
            task = db.get(Task, s.get("task_id")) if s.get("task_id") else None
        return user, dept, task

    def start_recording(self) -> Dict[str, Any]:
        with self.lock:
            if self.recorder.is_active:
                raise StationError("already recording")
            if self.phase != "teleop":
                raise StationError(f"can't record while {self.phase}", "engage teleop first (the follower must be live)")
            syncing = [s for s in self.cfg.enabled_arms() if self.arm_snapshot(s)["state"] == "syncing"]
            if syncing:
                raise StationError(f"{', '.join(syncing)} follower still easing onto the leader", "wait a moment, then record")
            user, dept, task = self._session_entities()
            missing = [n for n, v in (("operator", user), ("department", dept), ("task", task)) if v is None]
            if missing:
                raise StationError(f"choose the {', '.join(missing)} first", "use the selectors in the top bar")
            free = shutil.disk_usage(self.data_root).free / 1e9
            if free < 2:
                raise StationError(f"only {free:.1f} GB free", "free disk space before recording")
            meta = {
                "station": self.cfg.station.name, "software_version": self.version, "sim": self.sim,
                "operator": {"id": user.id, "name": user.name},
                "department": {"id": dept.id, "name": dept.name},
                "task": {"id": task.id, "name": task.name, "description": task.description or task.name},
                "arms": {s: {"arm_type": self.cfg.arms[s].follower.arm_type,
                             "gripper_type": self.cfg.arms[s].follower.gripper_type,
                             "trigger": self.cfg.arms[s].trigger.backend} for s in self.cfg.enabled_arms()},
                "control_hz": self.cfg.runtime.control_hz,
                "settings": {"haptics": self.settings()["haptics"]},
                "calibration": self._calibration_snapshot(),
            }
            a = self.recorder.start(meta)
            self._rec_meta_pending = {}
            started = list(self.cfg.cameras)
            try:
                self._parallel([(self.camera_request, (n, "record"), {"timeout": 8,
                                 "path": str(a["staging"] / "cameras" / f"{n}.mp4")}) for n in started] +
                               [(self.arm_request, (s, "record"), {"on": True})
                                for s in self.cfg.enabled_arms() if self.arm_connected.get(s)])
                a["t0_mono"] = time.monotonic()
            except StationError as e:
                for name in started:
                    try:
                        self.camera_request(name, "stop_record", timeout=5)
                    except Exception:
                        pass
                self._broadcast_arms("record", on=False)
                self.recorder.finish(keep=False)
                raise StationError(f"recording failed to start: {e.detail}", "check the camera tiles and logs")
            self.phase = "recording"
            log.info("recording %s started: %s / %s / %s", a["id"], dept.name, user.name, task.name)
            return {"episode_id": a["id"]}

    def save_recording(self, success: Optional[bool] = None, notes: str = "") -> Dict[str, Any]:
        with self.lock:
            if not self.recorder.is_active:
                raise StationError("not recording")
            pend = self._rec_meta_pending or {}
            if success is None:
                success = pend.get("success")
            return self._finish_recording(True, success, notes)

    def abort_recording(self) -> Dict[str, Any]:
        with self.lock:
            if not self.recorder.is_active:
                raise StationError("not recording")
            self._finish_recording(False)
            log.info("recording aborted and deleted")
            return {"deleted": True}

    def _finish_recording(self, keep: bool, success: Optional[bool] = None, notes: str = "",
                          tags: Optional[List[str]] = None) -> Dict[str, Any]:
        prev_phase = self.phase
        t_stop = time.monotonic()
        self.phase = "saving"
        self._broadcast_arms("record", on=False)
        cams: Dict[str, Any] = {}
        names = list(self.cfg.cameras)
        replies: Dict[str, Any] = {}

        def stop_one(n):
            try:
                replies[n] = self.camera_request(n, "stop_record", timeout=15)
            except Exception as e:
                replies[n] = e

        ts = [threading.Thread(target=stop_one, args=(n,), daemon=True) for n in names]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        for name in names:
            try:
                r = replies.get(name)
                if isinstance(r, Exception) or r is None:
                    raise r or RuntimeError("no reply")
                blk = self.cam_blocks[name].read()
                cams[name] = {"frames": r.get("frames", 0), "width": int(blk["width"]), "height": int(blk["height"]),
                              "fps_nominal": self.cfg.cameras[name].fps, "fps_measured": round(blk["fps"], 2),
                              "dropped_total": int(blk["dropped"]), "file": f"cameras/{name}.mp4",
                              "label": self.cfg.cameras[name].label}
            except Exception as e:
                log.error("camera %s stop failed: %s", name, e)
        a = self.recorder.active
        meta = a["meta"]  # who/what was selected when the take *started* (the session may have changed since)
        op, dept, task = meta["operator"], meta["department"], meta["task"]
        started: datetime = a["started_at"]
        final = (self.data_root / "recordings" / slugify(dept["name"]) / slugify(op["name"]) /
                 f"{started.astimezone().strftime('%Y-%m-%d_%H-%M-%S')}_{slugify(task['name'])}")
        res = self.recorder.finish(keep, final, {"cameras": cams, "success": success, "notes": notes,
                                                  "tags": tags or []}, t_stop=t_stop)
        if self.phase != "fault" and prev_phase != "fault":  # a fault raised while saving wins
            self.phase = "teleop" if prev_phase in ("recording", "saving") else prev_phase
        elif prev_phase == "fault":
            self.phase = "fault"
        if not keep or res is None:
            return {"deleted": True}
        frames = max([c["frames"] for c in cams.values()] or [0])
        ep = Episode(id=res["id"], user_id=op["id"], department_id=dept["id"],
                     task_id=task["id"], started_at=started, duration_s=round(res["duration_s"], 2),
                     frames=frames, cameras_json=json.dumps(list(cams)), size_mb=round(res["size_mb"], 2),
                     success=success, notes=notes, tags_json=json.dumps(tags or []), path=str(res["path"]),
                     station=self.cfg.station.name)
        with self.db.lock, self.db.session() as s:
            s.add(ep)
            s.commit()
        try:  # grip-force summary in episode.json (which object got how much force)
            from station.recording.raw_episode import grip_stats, load_episode

            p = Path(res["path"]) / "episode.json"
            info = json.loads(p.read_text())
            info["grip_stats"] = grip_stats(load_episode(Path(res["path"])))
            p.write_text(json.dumps(info, indent=2, default=str))
        except Exception as e:
            log.warning("grip stats for %s failed: %s", res["id"], e)
        log.info("saved episode %s (%.1fs, %.0f MB) → %s", res["id"], res["duration_s"], res["size_mb"], res["path"])
        if self.settings()["recording"].get("auto_export"):
            try:
                self.create_export([ep.id], f"{dept['name']}-{task['name']}")
            except Exception as e:
                log.error("auto-export failed to start: %s", e)
        return self.episode_dict(ep)

    def _calibration_snapshot(self) -> Dict[str, Any]:
        import yaml

        out = {}
        for p in sorted(self.cal_dir.glob("*.yaml")):
            if p.name.endswith(".prev.yaml"):
                continue
            try:
                out[p.stem] = yaml.safe_load(p.read_text())
            except Exception:
                pass
        return out

    # =================================================================== episodes

    def episode_dict(self, ep: Episode) -> Dict[str, Any]:
        with self.db.session() as s:
            u = s.get(User, ep.user_id) if ep.user_id else None
            d = s.get(Department, ep.department_id) if ep.department_id else None
            t = s.get(Task, ep.task_id) if ep.task_id else None
        return {"id": ep.id, "user_id": ep.user_id, "user_name": u.name if u else None,
                "department_id": ep.department_id, "department_name": d.name if d else None,
                "task_id": ep.task_id, "task_name": t.name if t else None,
                "started_at": ep.started_at.replace(tzinfo=ep.started_at.tzinfo or timezone.utc).isoformat(),
                "duration_s": ep.duration_s, "frames": ep.frames, "cameras": json.loads(ep.cameras_json),
                "size_mb": ep.size_mb, "success": ep.success, "notes": ep.notes, "tags": json.loads(ep.tags_json),
                "path": ep.path, "status": ep.status if os.path.isdir(ep.path) else "missing",
                "grip_stats": _read_grip_stats(ep.path)}

    # =================================================================== exports

    def create_export(self, episode_ids: List[str], name: str, fps: Optional[int] = None) -> Dict[str, Any]:
        if not episode_ids:
            raise StationError("select at least one episode", status=400)
        with self.db.session() as s:
            eps = [s.get(Episode, i) for i in episode_ids]
        missing = [i for i, e in zip(episode_ids, eps) if e is None or not os.path.isdir(e.path)]
        if missing:
            raise StationError(f"episodes not found on disk: {missing}", status=404)
        slug = slugify(name)
        root = self.data_root / self.cfg.export.root / slug
        repo_id = f"{slugify(self.cfg.station.name)}/{slug}"
        job = {"id": uuid.uuid4().hex[:10], "kind": "lerobot_export", "status": "queued", "progress": 0.0,
               "message": f"{len(eps)} episodes → {root}", "result": None, "created_at": time.time()}
        self.jobs[job["id"]] = job
        py = self.cfg.export.python or sys.executable
        cmd = [py, "-m", "station.recording.lerobot_export", "--root", str(root), "--repo-id", repo_id,
               "--fps", str(fps or self.cfg.export.fps), "--codec", self.cfg.export.video_codec] + [e.path for e in eps]

        def run():
            job["status"] = "running"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent) + os.pathsep + env.get("PYTHONPATH", "")
            try:
                # stderr is merged into stdout so a chatty child can never block on a full pipe
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
            except FileNotFoundError as e:
                job.update(status="error", message=f"cannot run exporter: {e}")
                return
            other: List[str] = []
            for line in proc.stdout:
                try:
                    m = json.loads(line)
                    if not isinstance(m, dict):
                        raise ValueError
                except ValueError:
                    other.append(line.rstrip())
                    del other[:-200]
                    continue
                job["progress"] = float(m.get("progress", job["progress"]))
                if m.get("stage") == "error":
                    job.update(status="error", message=m.get("error", "export failed"))
                elif m.get("stage") == "done":
                    job.update(status="done", progress=1.0, result=m.get("result"), message=f"dataset at {root}")
                elif m.get("stage") == "frames":
                    job["message"] = f"episode {m['episode'] + 1}/{len(eps)} · frame {m['frames_done']}/{m['frames']}"
            proc.wait()
            err = "\n".join(other)
            if job["status"] == "running":
                tail = err.strip().splitlines()[-1] if err.strip() else f"exit code {proc.returncode}"
                if "No module named 'lerobot'" in err:
                    tail = "lerobot is not installed (pip install lerobot, or set export.python)"
                job.update(status="error", message=tail)
            if job["status"] == "done":
                with self.db.lock, self.db.session() as s:
                    for i in episode_ids:
                        e = s.get(Episode, i)
                        if e:
                            e.status = "exported"
                            s.add(e)
                    s.commit()
                log.info("export %s finished: %s", job["id"], root)
            else:
                log.error("export %s failed: %s", job["id"], job["message"])

        self._export_q.put(run)  # one export at a time: two exports may append to the same dataset
        return job

    def _export_worker(self) -> None:
        while not self._stop.is_set():
            try:
                run = self._export_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                run()
            except Exception as e:
                log.error("export crashed: %s", e)

    # =================================================================== calibration (CalContext)

    def arm_state(self, side: str) -> Dict[str, Any]:
        st = self.arm_blocks[side].read()
        out = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in st.items()}
        out["follower_ok"] = bool(st["follower_ok"]) and self.arm_connected.get(side, False)
        return out

    def arm_connected_(self, side: str) -> bool:
        return bool(self.arm_connected.get(side)) and self.arm_alive(side)

    def camera_capture(self, name: str, path: Path) -> Path:
        self.camera_request(name, "capture_frame", timeout=5, path=str(path))
        return path

    def cal_file(self, item_id: str) -> Path:
        kind, target = item_id.split("_", 1)
        if kind == "leader":
            return self.cal_dir / Path(self.cfg.arms[target].leader.calibration_file).name
        if kind == "trigger":
            return self.cal_dir / Path(self.cfg.arms[target].trigger.calibration_file).name
        if kind == "gripper":
            return self.cal_dir / Path(self.cfg.arms[target].gripper_force.calibration_file).name
        if kind == "fingertips":
            return self.cal_dir / Path(self.cfg.arms[target].fingertips.calibration_file).name
        if kind == "camera":
            f = self.cfg.cameras[target].calibration_file or f"calibration/camera_{target}.yaml"
            return self.cal_dir / Path(f).name
        raise KeyError(item_id)

    def scratch_dir(self, item_id: str) -> Path:
        d = self.data_root / "calibration" / ".work" / item_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def config(self) -> StationConfig:
        return self.cfg

    def calibration_items(self) -> List[Dict[str, Any]]:
        import yaml

        items = []
        for pid, p in self.procedures.items():
            f = self.cal_file(pid)
            meta: Dict[str, Any] = {}
            if f.exists():
                try:
                    meta = (yaml.safe_load(f.read_text()) or {}).get("_meta", {})
                except Exception:
                    pass
            label = {"leader": "leader arm", "trigger": "haptic trigger", "gripper": "gripper force",
                     "fingertips": "fingertip sensors"}.get(p.kind)
            nice = f"{p.target.title()} {label}" if label else f"{self.cfg.cameras[p.target].label or p.target} camera"
            items.append({"id": pid, "label": nice, "kind": p.kind, "target": p.target, "calibrated": f.exists(),
                          "updated_at": meta.get("created_at"), "updated_by": meta.get("by"),
                          "summary": meta.get("summary", ""),
                          "requires_arm": p.kind in ("trigger", "gripper", "fingertips"),
                          "active": self.active_cal is p})
        return items

    def cal_procedure(self, pid: str) -> Procedure:
        p = self.procedures.get(pid)
        if p is None:
            raise StationError(f"unknown procedure {pid!r}", status=404)
        return p

    def cal_start(self, pid: str) -> Dict[str, Any]:
        p = self.cal_procedure(pid)
        if self.phase in ("teleop", "recording", "saving"):
            raise StationError("disengage teleop before calibrating")
        if p.kind in ("leader", "trigger", "gripper", "fingertips") and not self.arm_connected_(p.target):
            raise StationError(f"{p.target} arm is not started", "press Start Arms (calibration reads through the arm)")
        if self.active_cal and self.active_cal is not p:
            self.active_cal.on_end()
        self.active_cal = p
        try:
            return p.start()
        except StationError:
            raise
        except CalError as e:
            raise StationError(str(e), e.hint)
        except Exception as e:
            raise StationError(f"calibration start failed: {e}")

    def cal_step(self, pid: str, sid: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        p = self.cal_procedure(pid)
        if self.active_cal is not p:
            raise StationError("start this procedure first")
        try:
            return p.run_step(sid, inputs)
        except CalError as e:
            raise StationError(str(e), e.hint, status=404 if "unknown step" in str(e) else 409)
        except StationError as e:
            p.status[sid] = {"id": sid, "status": "error", "message": e.detail, "data": {"hint": e.hint}}
            return p.run_state()

    def cal_commit(self, pid: str) -> Dict[str, Any]:
        p = self.cal_procedure(pid)
        user, _, _ = self._session_entities()
        try:
            r = p.commit(user.name if user else None)
        except CalError as e:
            raise StationError(str(e), e.hint)
        with self.db.lock, self.db.session() as s:
            s.add(CalibrationRecord(item_id=pid, user_id=user.id if user else None, summary=r["summary"],
                                    path=r["path"], data_json=json.dumps(r["data"], default=float)))
            s.commit()
        self.active_cal = None
        log.info("calibration %s saved: %s", pid, r["summary"])
        return next(i for i in self.calibration_items() if i["id"] == pid)

    def cal_cancel(self, pid: str) -> Dict[str, Any]:
        p = self.cal_procedure(pid)
        try:
            p.on_end()
        finally:
            if self.active_cal is p:
                self.active_cal = None
        return {}

    # =================================================================== snapshots

    def camera_snapshot(self) -> Dict[str, Dict[str, Any]]:
        out = {}
        now = time.monotonic()
        for name, b in self.cam_blocks.items():
            st = b.read()
            fresh = (now - st["t"]) < 1.0
            out[name] = {"ok": bool(st["ok"]) and fresh, "fps": round(st["fps"], 2) if fresh else 0.0,
                         "dropped": int(st["dropped"]), "width": int(st["width"]), "height": int(st["height"]),
                         "recording": bool(st["recording"]), "label": self.cfg.cameras[name].label or name}
        return out

    def arm_snapshot(self, side: str) -> Dict[str, Any]:
        st = self.arm_blocks[side].read()
        alive = self.arm_alive(side)
        state = ARM_STATES[int(st["state"])] if alive and st["t"] > 0 else "offline"
        tm = int(st["trigger_mode"])
        return {
            "state": state, "fault": self.arm_fault.get(side),
            "loop_hz": _f(st["loop_hz"]) if alive else 0.0, "loop_jitter_ms": _f(st["loop_jitter_ms"]),
            "tracking_error_rad": _f(st["tracking_error"]),
            "leader": {"ok": bool(st["leader_ok"]) and alive, "q": _f(st["leader_q"])},
            "follower": {"ok": bool(st["follower_ok"]) and alive, "q": _f(st["follower_q"]), "dq": _f(st["follower_dq"]),
                         "tau": _f(st["follower_tau"]), "gripper": _f(st["follower_gripper"]),
                         "gripper_tau": _f(st["follower_gripper_tau"]), "temps_c": _f(st["follower_temps"])},
            "trigger": {"ok": bool(st["trigger_ok"]) and alive, "pos": _f(st["trigger_pos"]),
                        "force_n": _f(st["trigger_force"]), "render_n": _f(st["trigger_render"]),
                        "buttons": [bool(st["trigger_btn_a"]), bool(st["trigger_btn_b"])],
                        "mode": TRIGGER_MODES[tm] if 0 <= tm < len(TRIGGER_MODES) else "off"},
            "grip_force_n": _f(st["grip_force"]), "contact": bool(st["contact"]),
            "slip": bool(st["slip"]),
            "grip_source": "fingertip" if st["fingertip_ok"] > 0.5 else "motor",
            "fingertips": {"ok": bool(st["fingertip_ok"]) and alive, "a_n": _f(st["fingertip_a"]),
                           "b_n": _f(st["fingertip_b"])},
        }

    def snapshot(self) -> Dict[str, Any]:
        rec = {"active": False, "episode_id": None, "elapsed_s": 0.0, "frames": 0, "size_mb": 0.0}
        a = self.recorder.active
        if a:
            frames = 0
            for b in self.cam_blocks.values():
                frames = max(frames, int(b.get("frames_recorded")))
            size = 0.0
            try:
                size = sum(f.stat().st_size for f in Path(a["staging"]).rglob("*") if f.is_file()) / 1e6
            except Exception:
                pass
            rec = {"active": True, "episode_id": a["id"], "elapsed_s": round(time.monotonic() - a["t0_mono"], 2),
                   "frames": frames, "size_mb": round(size, 1)}
        cal = {"active": None, "step": None, "live": {}}
        if self.active_cal is not None:
            try:
                live = self.active_cal.live()
            except Exception as e:
                live = {"error": str(e)}
            cal = {"active": self.active_cal.id, "step": self.active_cal.step_index, "live": _jsonable(live)}
        du = shutil.disk_usage(self.data_root)
        return {
            "t": round(time.monotonic(), 3), "phase": self.phase, "phase_detail": self.phase_detail, "sim": self.sim,
            "session": self.session(), "startup": {"steps": self.startup_steps},
            "arms": {s: self.arm_snapshot(s) for s in self.cfg.enabled_arms()},
            "cameras": self.camera_snapshot(), "recording": rec,
            "power": {k: v for k, v in self.power.snapshot().items()}, "calibration": cal,
            "system": {"cpu_pct": psutil.cpu_percent(interval=None), "mem_pct": psutil.virtual_memory().percent,
                       "disk_free_gb": round(du.free / 1e9, 1), "disk_total_gb": round(du.total / 1e9, 1)},
        }

    def health(self, rerun: bool = False) -> Dict[str, Any]:
        if rerun or self.health_cache is None or time.time() - self._health_t > 30:
            self.health_cache = run_checks(self.cfg, self.snapshot)
            self._health_t = time.time()
        return self.health_cache

    _health_t = 0.0


def _read_grip_stats(path: str) -> Dict[str, Any]:
    try:
        return json.loads((Path(path) / "episode.json").read_text()).get("grip_stats") or {}
    except Exception:
        return {}


class _CalCtx:
    """The narrow interface calibration procedures get (see calibration.procedures.CalContext)."""

    def __init__(self, o: "Orchestrator"):
        self._o = o
        self.sim = o.sim

    def arm_request(self, side: str, cmd: str, timeout: float = 8.0, **kw: Any) -> Dict[str, Any]:
        return self._o.arm_request(side, cmd, timeout=timeout, **kw)

    def arm_state(self, side: str) -> Dict[str, Any]:
        return self._o.arm_state(side)

    def arm_connected(self, side: str) -> bool:
        return self._o.arm_connected_(side)

    def camera_capture(self, name: str, path: Path) -> Path:
        return self._o.camera_capture(name, path)

    def cal_file(self, item_id: str) -> Path:
        return self._o.cal_file(item_id)

    def scratch_dir(self, item_id: str) -> Path:
        return self._o.scratch_dir(item_id)

    def config(self) -> StationConfig:
        return self._o.cfg


def _jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return round(v, 5) if math.isfinite(v) else None
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.ndarray):
        return _jsonable(x.tolist())
    return x
