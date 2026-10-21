"""ArmWorker: owns one leader → follower pair and runs its teleop loop at `control_hz`.

The worker runs in its own process, so the web server and video encoding can't add jitter.
It talks to the server through:
  * `cmd_q`    commands in (dicts with a "cmd" key)
  * `evt_q`    events out: startup steps, faults, button presses, replies, log records
  * `sample_q` full-rate samples out, only while recording
  * `state`    a SharedBlock (ipc.ARM_FIELDS) with the latest snapshot, written every tick
"""

from __future__ import annotations

import logging
import logging.handlers
import math
import queue
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import yaml

from station.config import ArmConfig
from station.hardware import haptic_protocol as hp
from station.hardware.follower import FollowerBase, FollowerObs, I2RTFollower, SimFollower
from station.hardware.leader import (DynamixelLeader, LeaderBase, LeaderCalibration, SimLeader, SimOperator,
                                     map_leader)
from station.hardware.trigger import HGMTrigger, LegacyTrigger, NoTrigger, SimHGM, TriggerBase, TriggerReading
from station.ipc import ARM_STATES, SharedBlock
from station.hardware.fingertip import FGSDevice, FingertipBase, FingertipReading, NoFingertip, SimFingertip
from station.teleop.gripper import GripForceEstimator, GripperCoupler, HapticSettings, TouchEvents

CAL_GRIP_LIMIT_N = 40.0     # grip force cap during gripper calibration squeezes
CAL_APPROACH_SPEED = 0.15   # normalized opening per second while closing onto the gauge
# commands that do slow bus I/O inside the loop; refused while teleoperating
BLOCKING_CMDS = {"scan", "trigger_param", "trigger_command", "reload_calibration", "float", "gripper_override",
                 "fingertip_tare"}

LED_BY_PHASE = {
    "idle": (0, 0, 40, 2), "ready": (0, 60, 60, 0), "teleop": (0, 120, 0, 0),
    "recording": (160, 0, 0, 1), "saving": (160, 100, 0, 1), "fault": (200, 0, 0, 1),
}


def min_jerk(s: float) -> float:
    s = min(max(s, 0.0), 1.0)
    return s * s * s * (10 - 15 * s + 6 * s * s)


class ArmFault(RuntimeError):
    pass


class ArmWorker:
    def __init__(self, side: str, cfg: ArmConfig, cal_dir: str, control_hz: float, state: SharedBlock,
                 cmd_q, evt_q, sample_q, haptics: Dict[str, Any], log_to_queue: bool = True):
        self.side = side
        self.cfg = cfg
        self.cal_dir = Path(cal_dir)
        self.hz = control_hz
        self.dt = 1.0 / control_hz
        self.state = state
        self.cmd_q, self.evt_q, self.sample_q = cmd_q, evt_q, sample_q
        self.log_to_queue = log_to_queue
        self.coupler = GripperCoupler(HapticSettings.from_dict(haptics or {}))
        self._clamp_grip_setting()
        gf = cfg.gripper_force
        self.estimator = GripForceEstimator(gf.gain_n_per_nm, gf.tau_friction_nm, gf.contact_on_n,
                                            gf.contact_off_n, gf.still_speed, gf.filter_hz)
        self.fingertips: FingertipBase = NoFingertip()
        self.touch = TouchEvents()
        self._ft = FingertipReading()
        self._jaw_pos, self._jaw_t, self._jaw_speed = 1.0, 0.0, 0.0  # gripper opening rate (1/s), gates slip
        self.ft_gain = (1.0, 1.0)  # per-pad calibration gains (Calibration → fingertip sensors)
        self._ft_contact = False
        self._last_cue = 0
        self.leader: Optional[LeaderBase] = None
        self.trigger: TriggerBase = NoTrigger()
        self.follower: Optional[FollowerBase] = None
        self.cal = LeaderCalibration()
        self.mode = "connecting"
        self.recording = False
        self.running = True
        self.prev_q: Optional[np.ndarray] = None
        self.q_cmd: Optional[np.ndarray] = None
        self.engage: Optional[Dict[str, Any]] = None
        self.move: Optional[Dict[str, Any]] = None
        self.gripper_override: Optional[Dict[str, Any]] = None
        self.trigger_override: Optional[hp.Setpoint] = None
        self.track_err_since: Optional[float] = None
        self.leader_stale_since: Optional[float] = None
        self.prev_buttons = 0
        self.fault_msg = ""
        self.samplers: list = []
        self.follower_bad_since: Optional[float] = None
        self.trigger_bad_since: Optional[float] = None
        self.last_trig_pos = 0.0  # multi-tick measurements requested by calibration (never block the loop)
        self.log = logging.getLogger(f"station.arm.{side}")

    # ------------------------------------------------------------------ plumbing

    def emit(self, **evt: Any) -> None:
        evt.setdefault("side", self.side)
        try:
            self.evt_q.put_nowait(evt)
        except queue.Full:
            pass

    def step(self, sid: str, status: str, message: str = "", t0: Optional[float] = None) -> None:
        self.emit(type="step", id=f"{sid}_{self.side}", status=status, message=message,
                  duration_s=(time.monotonic() - t0) if t0 else 0.0)

    def _setup_logging(self) -> None:
        if not self.log_to_queue:
            return
        root = logging.getLogger()
        root.handlers[:] = [_EvtQueueHandler(self.evt_q, self.side)]
        root.setLevel(logging.INFO)

    # ------------------------------------------------------------------ device setup

    def _build(self) -> None:
        c = self.cfg
        operator = SimOperator(self.side)
        if c.leader.backend == "sim":
            self.leader = SimLeader(self.side, operator)
        else:
            legacy_id = c.trigger.legacy_id if c.trigger.backend == "dynamixel_legacy" else None
            self.leader = DynamixelLeader(c.leader.port, c.leader.baudrate, c.leader.joint_ids, legacy_id,
                                          c.trigger.legacy_open_ticks, c.trigger.legacy_closed_ticks,
                                          c.trigger.legacy_base_current_ma, c.trigger.legacy_max_current_ma)
        tb = c.trigger.backend
        if tb == "sim":
            self.trigger = SimHGM(self.side, operator)
        elif tb == "hgm":
            self.trigger = HGMTrigger(c.trigger.port)
        elif tb == "dynamixel_legacy":
            self.trigger = LegacyTrigger(self.leader, self.coupler.settings.max_render_n)
        else:
            self.trigger = NoTrigger()
        if c.follower.backend == "sim":
            self.follower = SimFollower(self.side, operator)
        else:
            f = c.follower
            self.follower = I2RTFollower(f.can_channel, f.arm_type, f.gripper_type, f.gripper_limits,
                                         f.gravity_comp_factor)
        fb = c.fingertips.backend
        if fb == "sim":
            self.fingertips = SimFingertip(self.follower)
        elif fb == "fgs":
            self.fingertips = FGSDevice(c.fingertips.port)

    def _connect(self) -> None:
        t0 = time.monotonic()
        self.step("leader", "running", "opening Dynamixel bus")
        try:
            self.leader.connect()
            self.step("leader", "ok", "all joint servos answered", t0)
        except Exception as e:
            self.step("leader", "error", str(e), t0)
            raise ArmFault(f"leader: {e}")

        t0 = time.monotonic()
        self.step("trigger", "running", "connecting trigger")
        try:
            self.trigger.connect()
            info = self.trigger.info()
            msg = f"{type(self.trigger).__name__} {info.get('serial', '')} fw {info.get('firmware', '-')}".strip()
            self.step("trigger", "ok", msg, t0)
            self._load_trigger_calibration()
        except Exception as e:
            self.step("trigger", "warn", f"{e}: continuing without haptics", t0)
            self.trigger = NoTrigger()

        t0 = time.monotonic()
        self.step("follower", "running", "initializing YAM (the gripper will auto-calibrate)")
        try:
            self.follower.connect()
            self._apply_grip_limit()
            self.step("follower", "ok", "motors enabled, gravity compensation on", t0)
        except Exception as e:
            self.step("follower", "error", str(e), t0)
            raise ArmFault(f"follower: {e}")

        if self.fingertips.present:
            t0 = time.monotonic()
            self.step("fingertips", "running", "connecting fingertip sensors")
            try:
                self.fingertips.connect()
                serial = self.fingertips.info().get('serial', '')
                # Zero the pads while nothing is between the jaws (strain gauges drift with temperature).
                try:
                    jaws_open = self.follower.observe().gripper > 0.5
                except Exception:
                    jaws_open = False
                if jaws_open:
                    self.fingertips.tare()
                    self.step("fingertips", "ok", f"true contact force at the jaws, zeroed ({serial})", t0)
                else:
                    self.step("fingertips", "warn", f"connected ({serial}) but not zeroed: the jaws are closed. "
                              "Open them and run Calibrate → Follower fingertip sensors → Zero", t0)
            except Exception as e:
                self.step("fingertips", "warn", f"{e}: grip force falls back to the motor-torque estimate", t0)
                self.fingertips = NoFingertip()

        t0 = time.monotonic()
        self.load_calibration()
        if self.cal.valid:
            self.step("calibration", "ok", f"loaded {self._cal_file().name}", t0)
        else:
            self.step("calibration", "warn", "leader not calibrated: run Calibration → leader arm", t0)

    def _cal_file(self) -> Path:
        return self.cal_dir / Path(self.cfg.leader.calibration_file).name

    def load_calibration(self) -> None:
        p = self._cal_file()
        if p.exists():
            with open(p) as f:
                d = yaml.safe_load(f) or {}
            try:
                self.cal = LeaderCalibration.from_dict(d)
            except Exception as e:
                self.log.error("bad leader calibration %s: %s", p, e)
                self.cal = LeaderCalibration()
        else:
            self.cal = LeaderCalibration(np.zeros(6), np.asarray(self.cfg.leader.joint_signs, float), False)
        gp = self.cal_dir / Path(self.cfg.gripper_force.calibration_file).name
        if gp.exists():
            with open(gp) as f:
                g = yaml.safe_load(f) or {}
            self.estimator.gain_n_per_nm = float(g.get("gain_n_per_nm", self.estimator.gain_n_per_nm))
            self.estimator.tau_friction_nm = float(g.get("tau_friction_nm", self.estimator.tau_friction_nm))
            self.estimator.tau_offset_nm = max(0.0, float(g.get("tau_offset_nm", self.estimator.tau_offset_nm)))
        fp = self.cal_dir / Path(self.cfg.fingertips.calibration_file).name
        if fp.exists():
            with open(fp) as f:
                d = yaml.safe_load(f) or {}
            self.ft_gain = (float(d.get("gain_a", 1.0)), float(d.get("gain_b", 1.0)))
        self.prev_q = None

    def _load_trigger_calibration(self) -> None:
        p = self.cal_dir / Path(self.cfg.trigger.calibration_file).name
        if not p.exists() or not isinstance(self.trigger, (HGMTrigger, SimHGM)):
            return
        with open(p) as f:
            d = yaml.safe_load(f) or {}
        for name, value in (d.get("params") or {}).items():
            try:
                self.trigger.set_param(hp.Param[name.upper()], float(value))
            except Exception as e:
                self.log.warning("trigger param %s: %s", name, e)

    # ------------------------------------------------------------------ main loop

    def run(self) -> None:
        self._setup_logging()
        try:
            self._build()
            self._connect()
        except Exception as e:
            self._set_fault(str(e))
            self._write_state(None, TriggerReading(), 0.0, 0.0, 0.0)
            self._drain_until_stop()
            self._close_devices()
            return
        self.mode = "connected"
        self.emit(type="connected")
        try:
            self._loop()
        except Exception as e:  # never die silently
            self.log.error("arm loop crashed: %s\n%s", e, traceback.format_exc())
            self._set_fault(f"loop crashed: {e}")
            self._safe_stop()
            self._drain_until_stop()
        finally:
            self._close_devices()

    def _loop(self) -> None:
        period = self.dt
        nxt = time.perf_counter()
        last = nxt
        win_t0, win_n, hz = nxt, 0, self.hz
        jit_ema = 0.0
        while self.running:
            self._handle_commands()
            now_p = time.perf_counter()
            dtm = now_p - last
            last = now_p
            jit_ema += 0.02 * (abs(dtm - period) * 1000 - jit_ema)
            win_n += 1
            if now_p - win_t0 >= 0.5:  # rate over a window (robust to single long ticks)
                hz = win_n / (now_p - win_t0)
                win_t0, win_n = now_p, 0
            self._tick(time.monotonic(), hz, jit_ema)
            if win_n == 0 and self._parent_dead():
                self._park_and_exit()
                return
            nxt += period
            delay = nxt - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -period:  # overran a whole period: skip, never burst to catch up
                nxt = time.perf_counter()

    def _tick(self, t: float, hz: float, jitter: float) -> None:
        lr = self.leader.read()
        if isinstance(self.trigger, LegacyTrigger):
            self.trigger.update_from_leader(lr.t, lr.raw[6])
        tr = self.trigger.latest()
        fo = self.follower.observe()

        q_leader = None
        if lr.ok:
            q_leader = map_leader(lr.raw[:6], self.cal, self.prev_q, self.follower.joint_limits)
            self.prev_q = q_leader
            self.leader_stale_since = None
        elif self.leader_stale_since is None:
            self.leader_stale_since = t

        grip_force, contact = self.estimator.update(t, fo.gripper_tau, fo.gripper_vel) if fo.ok else (0.0, False)
        ft = self.fingertips.latest() if self.fingertips.present else FingertipReading()
        if ft.ok and self.ft_gain != (1.0, 1.0):
            ft = FingertipReading(ft.t, ft.ok, ft.force_a * self.ft_gain[0], ft.force_b * self.ft_gain[1],
                                  ft.hf_a * self.ft_gain[0], ft.hf_b * self.ft_gain[1], ft.status)
        if ft.ok:
            # true contact force at the pads drives everything (feedback, contact, force regulation)
            grip_force = ft.force
            fc = self.cfg.fingertips
            if not self._ft_contact and grip_force > fc.contact_on_n:
                self._ft_contact = True
            elif self._ft_contact and grip_force < fc.contact_off_n:
                self._ft_contact = False
            contact = self._ft_contact
        self._ft = ft

        # buttons → server
        if tr.ok and tr.buttons != self.prev_buttons:
            for bit, name in ((1, "a"), (2, "b")):
                if (tr.buttons & bit) and not (self.prev_buttons & bit):
                    self.emit(type="button", button=name)
            self.prev_buttons = tr.buttons

        if fo.ok:
            self.follower_bad_since = None
        elif self.mode != "fault":
            if self.mode in ("teleop", "syncing") or self.move is not None or self.gripper_override is not None:
                self._set_fault(f"follower stopped responding: {fo.error or 'motor chain stopped'}")
                self._safe_stop()
            elif self.follower_bad_since is None:
                self.follower_bad_since = t
            elif t - self.follower_bad_since > 0.5:
                self._set_fault(f"follower stopped responding: {fo.error or 'motor chain stopped'}")

        # A lost trigger must not open the gripper: hold the last position, fault after 250 ms.
        if tr.ok:
            self.trigger_bad_since = None
            self.last_trig_pos = tr.pos
        elif self.trigger_bad_since is None:
            self.trigger_bad_since = t
        elif self.mode in ("teleop", "syncing") and t - self.trigger_bad_since > 0.25:
            self._set_fault("trigger stopped responding (USB unplugged?): gripper held")
            self._safe_stop()
        trig_pos = self.last_trig_pos
        trig_force = tr.force_op if (tr.ok and self.trigger.senses_force) else float("nan")
        was_regulating = self.coupler.regulating
        gc = self.coupler.step(t, trig_pos, trig_force, fo.gripper, grip_force, contact, self.trigger.senses_force)
        if self.coupler.regulating != was_regulating and self.mode in ("teleop", "syncing"):
            self._apply_grip_limit()  # i2rt's limiter would fight our force regulation
        releasing = trig_pos < self.coupler._p_contact - 0.02 if self.coupler.contact_active else trig_pos < 0.1
        dt_j = t - self._jaw_t if self._jaw_t else 0.0
        if dt_j > 0:
            self._jaw_speed += min(1.0, dt_j / 0.03) * (abs(fo.gripper - self._jaw_pos) / dt_j - self._jaw_speed)
        self._jaw_pos, self._jaw_t = fo.gripper, t
        cue, amp = self.touch.update(t, contact, grip_force, ft.hf, ft.ok, releasing, self.coupler.settings,
                                     jaw_speed=self._jaw_speed)
        self._last_cue = 0
        if cue is not None and self.mode in ("teleop", "syncing"):
            self.trigger.cue(int(cue), amp, 20 if cue != hp.Cue.SLIP else 40)
            self._last_cue = int(cue)

        # ---------------------------------------------------- follower command
        if self.mode in ("teleop", "syncing") and fo.ok:
            if q_leader is None:
                if self.leader_stale_since is not None and t - self.leader_stale_since > 0.25:
                    self._set_fault(f"leader bus stopped responding ({lr.error})")
                    self._safe_stop()
            else:
                target = np.concatenate([q_leader, [gc.gripper_cmd]])
                if self.mode == "syncing" and self.engage is not None:
                    e = self.engage
                    s = min_jerk((t - e["t0"]) / e["T"])
                    target = e["q0"] + s * (target - e["q0"])
                    if s >= 1.0:
                        self.mode = "teleop"
                        self.engage = None
                        self.log.info("teleop engaged")
                        self.emit(type="teleop", enabled=True)
                self._command(target, fo, t)
        elif self.move is not None and fo.ok:
            m = self.move
            s = min_jerk((t - m["t0"]) / m["T"])
            self._command(m["q0"] + s * (m["q1"] - m["q0"]), fo, t, check_tracking=False)
            if s >= 1.0:
                self.move = None
                self.emit(type="move_done")
        elif self.gripper_override is not None and fo.ok:
            go = self.gripper_override
            x = go.get("x")
            if go.get("force") is not None:
                # Close at a slow, fixed speed until contact, then regulate the force. The approach
                # setpoint stops the moment contact is seen, so the impact force stays small.
                f_t = float(np.clip(go["force"], 0.0, CAL_GRIP_LIMIT_N))
                if go.setdefault("phase", "approach") == "approach":
                    sp = go.setdefault("x_sp", fo.gripper)
                    if grip_force > min(0.5 * f_t, 3.0) or sp <= 0.0:
                        go["phase"] = "regulate"
                    else:
                        go["x_sp"] = max(0.0, sp - CAL_APPROACH_SPEED * self.dt)
                    x = go["x_sp"]
                if go["phase"] == "regulate":
                    x = fo.gripper - f_t / self.coupler.k_x
            q = np.concatenate([fo.q if self.q_cmd is None else self.q_cmd[:6], [float(np.clip(x, 0, 1))]])
            self._command(q, fo, t, check_tracking=False, rate_limit=False)

        # ---------------------------------------------------- trigger setpoint
        if self.trigger_override is not None:
            self.trigger.send_setpoint(self.trigger_override)
        else:
            s = self.coupler.settings
            active = self.mode in ("teleop", "syncing")
            mode = gc.trigger_mode if active else (int(hp.Mode.SPRING) if self.mode != "fault" else int(hp.Mode.SPRING))
            haptic, spring_n = (gc.haptic_n if active else 0.0), s.spring_n
            if active and self.coupler.contact_active:
                # In contact, the felt force is the grip force alone: drop the return-spring slope and
                # count the (unavoidable) mechanical preload as part of the rendered grip force.
                spring_n = 0.0
                haptic = max(gc.haptic_n - s.spring_min_n, 0.0)
            self.trigger.send_setpoint(hp.Setpoint(
                mode=hp.Mode(mode), haptic_n=haptic, spring_n=spring_n,
                spring_min_n=s.spring_min_n, damping=s.damping, max_n=s.max_render_n, pos_cmd=gc.pos_cmd,
            ))

        tracking = 0.0
        if self.q_cmd is not None and fo.ok:
            tracking = float(np.max(np.abs(self.q_cmd[:6] - fo.q)))
        self._write_state(lr, tr, hz, jitter, tracking, q_leader, fo, grip_force, contact)

        if self.recording:
            self._push_sample(t, q_leader, fo, tr, grip_force, contact, gc)
        if self.samplers:
            self._run_samplers(lr, fo, tr)

    def _run_samplers(self, lr, fo: FollowerObs, tr: TriggerReading) -> None:
        done = []
        for sm in self.samplers:
            k = sm["kind"]
            if k == "leader_raw" and lr.ok:
                sm["acc"].append(lr.raw[:6].copy())
            elif k == "follower_q" and fo.ok:
                sm["acc"].append(fo.q.copy())
            elif k == "trigger" and tr.ok:
                sm["acc"].append([tr.lever, tr.servo, tr.pos, tr.force_op if np.isfinite(tr.force_op) else 0.0])
            elif k == "fingertip" and self._ft.ok:
                sm["acc"].append([self._ft.force_a, self._ft.force_b])
            elif k == "gripper" and fo.ok:
                sm["acc"].append([fo.gripper, fo.gripper_vel, fo.gripper_tau])
            sm["ticks"] += 1
            if len(sm["acc"]) >= sm["n"] or sm["ticks"] > sm["n"] * 4 + 50:
                done.append(sm)
        for sm in done:
            self.samplers.remove(sm)
            msg, a = sm["msg"], np.array(sm["acc"], dtype=float)
            if len(a) == 0:
                self.emit(type="reply", req=msg.get("req"), ok=False, error=f"no valid {sm['kind']} readings")
                continue
            k = sm["kind"]
            if k == "leader_raw":
                self._reply(msg, raw=a.mean(axis=0).tolist(), std=a.std(axis=0).tolist())
            elif k == "follower_q":
                self._reply(msg, q=a.mean(axis=0).tolist())
            elif k == "trigger":
                self._reply(msg, lever=float(a[:, 0].mean()), servo=float(a[:, 1].mean()), pos=float(a[:, 2].mean()),
                            force=float(a[:, 3].mean()), deflection=float((a[:, 0] - a[:, 1]).mean()),
                            senses_force=self.trigger.senses_force, kind=type(self.trigger).__name__)
            elif k == "fingertip":
                self._reply(msg, a=float(a[:, 0].mean()), b=float(a[:, 1].mean()),
                            std_a=float(a[:, 0].std()), std_b=float(a[:, 1].std()))
            elif k == "gripper":
                self._reply(msg, x=float(a[:, 0].mean()), vel=float(a[:, 1].mean()), tau=float(a[:, 2].mean()),
                            tau_abs=float(np.abs(a[:, 2]).mean()), tau_std=float(a[:, 2].std()))

    def _sample(self, msg: Dict[str, Any], kind: str, n: int) -> None:
        self.samplers.append({"kind": kind, "n": max(1, n), "acc": [], "ticks": 0, "msg": msg})

    def _command(self, target: np.ndarray, fo: FollowerObs, t: float, check_tracking: bool = True,
                 rate_limit: bool = True) -> None:
        lim = self.follower.joint_limits
        target = target.copy()
        target[:6] = np.clip(target[:6], lim[:, 0], lim[:, 1])
        target[6] = float(np.clip(target[6], 0.0, 1.0))
        if self.q_cmd is None:
            self.q_cmd = np.concatenate([fo.q, [fo.gripper]])
        if rate_limit:
            vmax = self.cfg.follower.max_joint_speed * self.dt
            step = np.clip(target[:6] - self.q_cmd[:6], -vmax, vmax)
            self.q_cmd[:6] = self.q_cmd[:6] + step
        else:
            self.q_cmd[:6] = target[:6]
        self.q_cmd[6] = target[6]
        self.follower.command(self.q_cmd)
        if check_tracking:
            err = float(np.max(np.abs(self.q_cmd[:6] - fo.q)))
            if err > self.cfg.follower.max_tracking_error:
                if self.track_err_since is None:
                    self.track_err_since = t
                elif t - self.track_err_since > 0.3:
                    j = int(np.argmax(np.abs(self.q_cmd[:6] - fo.q))) + 1
                    self._set_fault(f"follower can't keep up: joint {j} is {math.degrees(err):.0f}° behind "
                                    "(collision, joint limit, or motor error)")
                    self._safe_stop()
            else:
                self.track_err_since = None

    # ------------------------------------------------------------------ state + samples

    def _write_state(self, lr, tr: TriggerReading, hz: float, jitter: float, tracking: float,
                     q_leader=None, fo: Optional[FollowerObs] = None, grip_force: float = 0.0,
                     contact: bool = False) -> None:
        nan6 = np.full(6, np.nan)
        vals: Dict[str, Any] = {
            "t": time.monotonic(), "state": ARM_STATES.index(self.mode), "loop_hz": hz,
            "loop_jitter_ms": jitter, "tracking_error": tracking,
            "leader_ok": 1.0 if (lr is not None and lr.ok) else 0.0,
            "leader_q": q_leader if q_leader is not None else nan6,
            "leader_raw": lr.raw if lr is not None else np.full(7, np.nan),
            "trigger_ok": 1.0 if tr.ok else 0.0, "trigger_pos": tr.pos, "trigger_force": tr.force_op,
            "trigger_render": tr.force_cmd, "trigger_btn_a": float(tr.button_a), "trigger_btn_b": float(tr.button_b),
            "trigger_mode": tr.mode, "trigger_lever": tr.lever, "trigger_servo": tr.servo,
            "trigger_status": tr.status, "grip_force": grip_force, "contact": float(contact),
            "fingertip_ok": float(getattr(self, "_ft", FingertipReading()).ok),
            "fingertip_a": getattr(self, "_ft", FingertipReading()).force_a,
            "fingertip_b": getattr(self, "_ft", FingertipReading()).force_b,
            "slip": float(self.touch.slip),
            "q_cmd": self.q_cmd if self.q_cmd is not None else np.full(7, np.nan),
        }
        if fo is not None:
            vals.update({
                "follower_ok": float(fo.ok), "follower_q": fo.q, "follower_dq": fo.dq, "follower_tau": fo.tau,
                "follower_gripper": fo.gripper, "follower_gripper_vel": fo.gripper_vel,
                "follower_gripper_tau": fo.gripper_tau, "follower_temps": fo.temps,
            })
        else:
            vals["follower_ok"] = 0.0
        self.state.write(vals)

    def _push_sample(self, t, q_leader, fo: FollowerObs, tr: TriggerReading, grip_force, contact, gc) -> None:
        s = {
            "t": t,
            "leader_q": None if q_leader is None else q_leader.tolist(),
            "q_cmd": None if self.q_cmd is None else self.q_cmd.tolist(),
            "follower_q": fo.q.tolist(), "follower_dq": fo.dq.tolist(), "follower_tau": fo.tau.tolist(),
            "gripper": fo.gripper, "gripper_vel": fo.gripper_vel, "gripper_tau": fo.gripper_tau,
            "trigger_pos": tr.pos, "trigger_force": tr.force_op if self.trigger.senses_force else None,
            "trigger_render": tr.force_cmd, "grip_force": grip_force, "contact": bool(contact),
            "grip_source": "fingertip" if self._ft.ok else "motor",
            "fingertip_a": self._ft.force_a if self._ft.ok else None,
            "fingertip_b": self._ft.force_b if self._ft.ok else None,
            "slip_hf": self._ft.hf if self._ft.ok else None,
            "slip": bool(self.touch.slip), "cue": self._last_cue,
            "target_force": None if not math.isfinite(gc.target_force_n) else gc.target_force_n,
            "force_mode": bool(self.coupler.force_mode_active), "buttons": tr.buttons, "mode": self.mode,
        }
        try:
            self.sample_q.put_nowait((self.side, s))
        except queue.Full:
            pass

    # ------------------------------------------------------------------ commands

    def _handle_commands(self) -> None:
        for _ in range(20):
            try:
                msg = self.cmd_q.get_nowait()
            except queue.Empty:
                return
            try:
                self._dispatch(msg)
            except Exception as e:
                self.log.error("command %s failed: %s", msg.get("cmd"), e)
                if "req" in msg:
                    self.emit(type="reply", req=msg["req"], ok=False, error=str(e))

    def _reply(self, msg: Dict, **data: Any) -> None:
        if "req" in msg:
            self.emit(type="reply", req=msg["req"], ok=True, data=data)

    def _dispatch(self, msg: Dict[str, Any]) -> None:
        c = msg["cmd"]
        if c in BLOCKING_CMDS and self.mode in ("teleop", "syncing"):
            raise ArmFault(f"'{c}' would pause the control loop: disengage teleop first")
        fo = self.follower.observe()
        if c == "teleop":
            if msg.get("enabled"):
                if self.mode == "fault":
                    raise ArmFault(f"clear the fault first: {self.fault_msg}")
                if not self.cal.valid:
                    self.log.warning("teleop with an uncalibrated leader: follower motion may not match")
                lr = self.leader.read()
                if not lr.ok:
                    raise ArmFault("leader not readable")
                ql = map_leader(lr.raw[:6], self.cal, self.prev_q, self.follower.joint_limits)
                q0 = np.concatenate([fo.q, [fo.gripper]])
                dist = float(np.max(np.abs(ql - fo.q)))
                T = max(1.0, dist / max(self.cfg.follower.engage_speed, 0.05))
                self.engage = {"t0": time.monotonic(), "T": T, "q0": q0}
                self.q_cmd = q0.copy()
                self.move = None
                self.gripper_override = None   # calibration leftovers never survive into teleop
                self.trigger_override = None
                self.samplers.clear()
                self._apply_grip_limit()
                self.mode = "syncing"
                self.log.info("engaging: follower eases onto leader over %.1fs (max Δ %.0f°)", T, math.degrees(dist))
            else:
                self._disengage()
                self.emit(type="teleop", enabled=False)
            self._reply(msg)
        elif c == "record":
            self.recording = bool(msg["on"])
            self._reply(msg)
        elif c == "settings":
            self.coupler.settings = HapticSettings.from_dict(msg.get("haptics", {}))
            self._clamp_grip_setting()
            if isinstance(self.trigger, LegacyTrigger):
                self.trigger.max_render_n = self.coupler.settings.max_render_n
            self._apply_grip_limit()
            self._reply(msg)
        elif c in ("home", "move_to"):
            self._disengage()
            q1 = np.asarray(msg.get("q", list(self.cfg.follower.rest_pose) + [1.0]), float)
            if len(q1) == 6:
                q1 = np.concatenate([q1, [fo.gripper]])
            q0 = np.concatenate([fo.q, [fo.gripper]])
            T = max(1.5, float(np.max(np.abs(q1[:6] - q0[:6]))) / 0.5)
            self.move = {"t0": time.monotonic(), "T": T, "q0": q0, "q1": q1}
            self.q_cmd = q0.copy()
            self._reply(msg, duration_s=T)
        elif c == "estop":
            self._set_fault(msg.get("reason", "software e-stop"))
            self._safe_stop()
            self._reply(msg)
        elif c == "clear_fault":
            if self.mode == "fault":
                self.mode = "connected"
                self.fault_msg = ""
                self.q_cmd = None
                self.track_err_since = None
                self.leader_stale_since = None
                try:
                    self.trigger.command(hp.Command.CLEAR_FAULTS, timeout=0.2)
                except Exception as e:
                    self.log.warning("trigger clear_faults: %s", e)
            self._reply(msg)
        elif c == "reload_calibration":
            self.load_calibration()
            self._load_trigger_calibration()
            self._reply(msg, valid=self.cal.valid)
        elif c == "float":
            self._disengage()
            self.move = None
            self.gripper_override = None
            self.q_cmd = None
            self.follower.float_()
            self._reply(msg)
        elif c == "sim_follower_pose":
            if isinstance(self.follower, SimFollower):
                self.follower.command(np.asarray(msg["q"], float))
            self._reply(msg)
        elif c == "sim_object":
            if isinstance(self.follower, SimFollower):
                self.follower.force_object = bool(msg.get("on"))
            self._reply(msg)
        elif c == "follower_read":
            self._sample(msg, "follower_q", int(msg.get("n", 20)))
        elif c == "scan":
            self._reply(msg, found=self.leader.scan())
        elif c == "led":
            r, g, b, pat = LED_BY_PHASE.get(msg.get("phase", ""), (20, 20, 20, 0))
            self.trigger.led(r, g, b, pat)
        elif c == "sim_pose":
            if isinstance(self.leader, SimLeader):
                q = msg.get("q")
                self.leader.manual_pose = None if q is None else np.asarray(q, float)
            self._reply(msg)
        elif c == "sim_squeeze":
            if isinstance(self.trigger, SimHGM):
                self.trigger.manual_squeeze = msg.get("n")
            self._reply(msg)
        elif c == "read_leader_raw":
            self._sample(msg, "leader_raw", int(msg.get("n", 20)))
        elif c == "trigger_override":
            sp = msg.get("setpoint")
            self.trigger_override = None if sp is None else hp.Setpoint(
                mode=hp.Mode(sp.get("mode", 1)), haptic_n=sp.get("haptic_n", 0.0), spring_n=sp.get("spring_n", 0.0),
                spring_min_n=sp.get("spring_min_n", 0.0), damping=sp.get("damping", 0.0),
                max_n=sp.get("max_n", 12.0), pos_cmd=sp.get("pos_cmd", 0.0))
            self._reply(msg)
        elif c == "trigger_param":
            v = self.trigger.set_param(hp.Param(msg["param"]), float(msg["value"]))
            self._reply(msg, value=v)
        elif c == "trigger_command":
            self.trigger.command(hp.Command(msg["command"]))
            self._reply(msg)
        elif c == "trigger_read":
            self._sample(msg, "trigger", int(msg.get("n", 50)))
        elif c == "gripper_override":
            self._disengage()
            g = msg.get("override")
            self.gripper_override = g
            if g:
                self.follower.set_gripper_force_limit(CAL_GRIP_LIMIT_N)  # calibration squeezes stay capped
            else:
                self._apply_grip_limit()
            self._reply(msg)
        elif c == "fingertip_read":
            if not self.fingertips.present:
                raise ArmFault("no fingertip sensors on this arm (arms.<side>.fingertips.backend)")
            self._sample(msg, "fingertip", int(msg.get("n", 100)))
        elif c == "sim_ft_weight":
            if isinstance(self.fingertips, SimFingertip):
                self.fingertips.weight_n = float(msg.get("n") or 0.0)
            self._reply(msg)
        elif c == "fingertip_tare":
            self.fingertips.tare()
            self._reply(msg)
        elif c == "gripper_read":
            self._sample(msg, "gripper", int(msg.get("n", 100)))
        elif c == "stop":
            self._disengage()
            self.running = False
            self._reply(msg)
        else:
            raise ValueError(f"unknown command {c!r}")

    def _clamp_grip_setting(self) -> None:
        full = self.cfg.follower.max_grip_force_n
        st = self.coupler.settings
        st.max_grip_n = float(min(max(st.max_grip_n, 1.0), full))

    def _reset_coupling(self) -> None:
        self.coupler.contact_active = False
        self.coupler.force_mode_active = False

    def _disengage(self) -> None:
        if self.mode in ("teleop", "syncing"):
            self._reset_coupling()
            self.mode = "connected"
            self._apply_grip_limit()
            self.engage = None
            self.follower.hold()
            self.q_cmd = None
            self.log.info("teleop disengaged: follower holding pose")

    def _set_fault(self, message: str) -> None:
        if self.mode != "fault":
            self.log.error("FAULT: %s", message)
            self.emit(type="fault", message=message)
        self.mode = "fault"
        self.fault_msg = message

    def _apply_grip_limit(self) -> None:
        """i2rt's stall limiter caps grip force. It is only disabled while force-command mode can
        actually engage (it would otherwise fight our force regulation); everything else stays capped."""
        st = self.coupler.settings
        regulating = self.coupler.regulating and self.mode in ("teleop", "syncing")
        try:
            self.follower.set_gripper_force_limit(-1 if regulating else st.max_grip_n)
        except Exception as e:
            self.log.warning("grip limit: %s", e)

    def _safe_stop(self) -> None:
        self.engage = None
        self.move = None
        self.q_cmd = None  # never resume from a stale command
        self.trigger_override = None
        self.samplers.clear()
        self._reset_coupling()
        self.gripper_override = None
        self._apply_grip_limit()
        try:
            self.follower.hold()
        except Exception:
            pass
        try:
            self.trigger.send_setpoint(hp.Setpoint(mode=hp.Mode.SPRING))
        except Exception:
            pass

    def _parent_dead(self) -> bool:
        """True if the station server died (a worker must never outlive it holding hardware)."""
        if not self.log_to_queue:  # thread mode: the parent is us
            return False
        import multiprocessing as mp

        parent = mp.parent_process()
        return parent is not None and not parent.is_alive()

    def _park_and_exit(self) -> None:
        self.log.error("station server is gone: parking the follower and releasing hardware")
        self._disengage()
        try:
            fo = self.follower.observe()
            q1 = np.concatenate([np.asarray(self.cfg.follower.rest_pose, float), [fo.gripper]])
            q0 = np.concatenate([fo.q, [fo.gripper]])
            T = max(1.5, float(np.max(np.abs(q1[:6] - q0[:6]))) / 0.5)
            t0 = time.monotonic()
            while time.monotonic() - t0 < T + 0.3:
                s_ = min_jerk((time.monotonic() - t0) / T)
                self.follower.command(q0 + s_ * (q1 - q0))
                self.trigger.send_setpoint(hp.Setpoint(mode=hp.Mode.SPRING))
                time.sleep(self.dt)
        except Exception as e:
            self.log.error("parking failed: %s", e)
        self.running = False

    def _drain_until_stop(self) -> None:
        while self.running:
            if self._parent_dead():
                self.running = False
                break
            try:
                msg = self.cmd_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if msg.get("cmd") == "stop":
                self.running = False
            if "req" in msg:
                ok = msg.get("cmd") == "stop"
                self.emit(type="reply", req=msg["req"], ok=ok,
                          error=None if ok else f"arm {self.side} is in fault: {self.fault_msg}")

    def _close_devices(self) -> None:
        for dev in (self.fingertips, self.trigger, self.follower, self.leader):
            try:
                if dev is not None:
                    dev.close()
            except Exception as e:
                self.log.warning("close %s: %s", type(dev).__name__, e)
        self.mode = "offline"
        try:
            self.state.write({"state": ARM_STATES.index("offline"), "t": time.monotonic()})
        except Exception:
            pass
        self.emit(type="stopped")


class _EvtQueueHandler(logging.Handler):
    def __init__(self, q, side: str):
        super().__init__()
        self.q = q
        self.side = side

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put_nowait({"type": "log", "side": self.side, "level": record.levelname,
                               "source": f"arm.{self.side}" if record.name.startswith("station") else record.name,
                               "message": record.getMessage(), "ts": record.created})
        except Exception:
            pass


def run_arm_worker(*args, **kwargs) -> None:
    """Process entry point."""
    ArmWorker(*args, **kwargs).run()
