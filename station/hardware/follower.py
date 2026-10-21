"""Follower arms: I2RT YAM over CAN (via the i2rt SDK) and a simulated twin.

Both expose the same small interface used by the ArmWorker:
  connect(), observe() -> FollowerObs, command(q7), hold(), set_gripper_force_limit(N), close()
where q7 = 6 arm joints (rad) + gripper (normalized: 0 = closed, 1 = open), matching i2rt.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .leader import SimOperator, YAM_LIMITS

log = logging.getLogger("station.follower")


@dataclass
class FollowerObs:
    t: float
    ok: bool
    q: np.ndarray            # (6,)
    dq: np.ndarray           # (6,)
    tau: np.ndarray          # (6,) N·m
    gripper: float           # 0 closed … 1 open
    gripper_vel: float
    gripper_tau: float       # gripper motor effort, N·m
    temps: np.ndarray        # (6,) °C, NaN if unknown
    error: str = ""


class FollowerBase:
    joint_limits = YAM_LIMITS

    def connect(self) -> None: ...
    def observe(self) -> FollowerObs: raise NotImplementedError
    def command(self, q7: np.ndarray) -> None: ...
    def hold(self) -> None: ...
    def float_(self) -> None:
        """Gravity-compensated and backdrivable: the arm can be posed by hand."""
    def set_gripper_force_limit(self, newtons: float) -> None: ...
    def close(self) -> None: ...


class I2RTFollower(FollowerBase):
    def __init__(self, channel: str, arm_type: str = "yam", gripper_type: str = "linear_4310",
                 gripper_limits=None, gravity_comp_factor=None):
        self.channel = channel
        self.arm_type = arm_type
        self.gripper_type = gripper_type
        self.gripper_limits = gripper_limits
        self.gravity_comp_factor = gravity_comp_factor
        self.robot = None

    def connect(self) -> None:
        try:
            from i2rt.robots.get_robot import get_yam_robot
            from i2rt.robots.utils import ArmType, GripperType
        except ImportError as e:
            raise RuntimeError(
                "the i2rt SDK is not installed: git clone https://github.com/i2rt-robotics/i2rt && pip install -e i2rt"
            ) from e
        kwargs = dict(
            channel=self.channel,
            arm_type=ArmType.from_string_name(self.arm_type),
            gripper_type=GripperType.from_string_name(self.gripper_type),
            zero_gravity_mode=True,
        )
        if self.gripper_limits is not None:
            kwargs["gripper_limits_override"] = np.asarray(self.gripper_limits, float)
        if self.gravity_comp_factor is not None:
            kwargs["gravity_comp_factor"] = np.asarray(self.gravity_comp_factor, float)
        self.robot = get_yam_robot(**kwargs)
        if hasattr(self.robot, "temp_record_flag"):
            self.robot.temp_record_flag = True  # include motor temperatures in observations
        info = self.robot.get_robot_info()
        lim = info.get("joint_limits")
        if lim is not None:
            self.joint_limits = np.asarray(lim, float)[:6]
        log.info("YAM follower on %s ready (%s, %s)", self.channel, self.arm_type, self.gripper_type)

    def _alive(self) -> bool:
        """i2rt keeps returning the last joint state after its motor-chain thread dies, so check
        the threads explicitly (a frozen pose must never look healthy)."""
        r = self.robot
        th = getattr(r, "_server_thread", None)
        chain = getattr(r, "motor_chain", None)
        if th is not None and not th.is_alive():
            return False
        if chain is not None and getattr(chain, "running", True) is False:
            return False
        return True

    def observe(self) -> FollowerObs:
        t = time.monotonic()
        if self.robot is None or not self._alive():
            nan6 = np.full(6, np.nan)
            return FollowerObs(t, False, nan6, nan6, nan6, float("nan"), 0.0, 0.0, nan6, "i2rt motor chain stopped")
        try:
            o = self.robot.get_observations()
        except Exception as e:  # motor chain errored
            nan6 = np.full(6, np.nan)
            return FollowerObs(t, False, nan6, nan6, nan6, float("nan"), 0.0, 0.0, nan6, str(e))
        temps = np.asarray(o.get("temp_rotor", np.full(6, np.nan)), float)[:6]
        return FollowerObs(
            t, True, np.asarray(o["joint_pos"], float), np.asarray(o["joint_vel"], float),
            np.asarray(o["joint_eff"], float), float(o["gripper_pos"][0]), float(o["gripper_vel"][0]),
            float(o["gripper_eff"][0]), temps,
        )

    def command(self, q7: np.ndarray) -> None:
        self.robot.command_joint_pos(np.asarray(q7, float))

    def hold(self) -> None:
        self.robot.command_joint_pos(self.robot.get_joint_pos())

    def float_(self) -> None:
        if hasattr(self.robot, "enter_gravity_comp_idle"):
            self.robot.enter_gravity_comp_idle()
        else:  # older i2rt
            self.robot.zero_torque_mode()

    def set_gripper_force_limit(self, newtons: float) -> None:
        """Adjust (or disable with newtons <= 0) i2rt's stall force limiter. Uses i2rt internals."""
        r = self.robot
        try:
            from functools import partial

            r._limit_gripper_force = float(newtons) if newtons > 0 else -1.0
            lim = getattr(r, "_gripper_force_limiter", None)
            if lim is not None and newtons > 0:
                fn = lim.gripper_force_torque_map
                base = fn.func if isinstance(fn, partial) else fn
                kw = dict(fn.keywords) if isinstance(fn, partial) else {}
                kw["gripper_force"] = float(newtons)
                lim.gripper_force_torque_map = partial(base, **kw)
                lim.max_force = float(newtons)
        except Exception as e:  # pragma: no cover - depends on i2rt version
            log.warning("could not adjust i2rt gripper force limit: %s", e)

    def close(self) -> None:
        if self.robot is not None:
            try:
                self.robot.close()
            finally:
                self.robot = None


# ---------------------------------------------------------------------------- simulation


class SimFollower(FollowerBase):
    """YAM twin: joints track commands with a 2nd-order response and velocity limits; the
    gripper is a PD servo that closes on a compliant object when the operator script has one
    between the fingers. Effort follows the same model the real force estimator assumes."""

    GRIP_KX = 68.4 * 20.0 * 6.57      # N per normalized unit = G * kp * raw_range
    OBJ_WIDTH = 0.42                  # normalized opening at first contact
    OBJ_STIFFNESS = 2500.0            # N per normalized unit of squeeze
    HOLD_FORCE = 6.0                  # grip needed to hold the lifted sim object without slipping

    def __init__(self, side: str, operator: Optional[SimOperator] = None, rate_hz: float = 250.0):
        self.side = side
        self.operator = operator or SimOperator(side)
        self.dt = 1.0 / rate_hz
        self.q = np.array([0.0, 0.05, 0.05, 0.0, 0.0, 0.0])
        self.dq = np.zeros(6)
        self.cmd = np.concatenate([self.q, [1.0]])
        self.grip = 1.0
        self.grip_v = 0.0
        self.grip_tau = 0.0
        self.force_limit = 50.0
        self.force_object = False         # calibration: pretend a gauge sits between the fingers
        self.contact_force = 0.0          # true object force (what fingertip sensors would read)
        self.slip_level = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.temps = np.array([34.0, 36.0, 35.0, 33.0, 32.0, 32.0])

    def connect(self) -> None:
        time.sleep(0.1)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"sim-yam:{self.side}", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        wn, zeta, vmax = 2 * math.pi * 6.0, 0.9, 4.0
        nxt = time.monotonic()
        while not self._stop.is_set():
            nxt += self.dt
            t = time.monotonic()
            with self._lock:
                cmd = self.cmd.copy()
            acc = wn * wn * (cmd[:6] - self.q) - 2 * zeta * wn * self.dq
            self.dq = np.clip(self.dq + acc * self.dt, -vmax, vmax)
            self.q = self.q + self.dq * self.dt
            self._grip_step(t, float(cmd[6]))
            self.temps += (0.002 * np.abs(self.dq) - (self.temps - 33.0) * 0.0005) * self.dt * 50
            d = nxt - time.monotonic()
            if d > 0:
                time.sleep(d)
            else:
                nxt = time.monotonic()

    def _grip_step(self, t: float, x_cmd: float) -> None:
        x = self.grip
        obj = self.force_object or self.operator.object_present(t)
        # PD toward command, velocity-limited like the real linear gripper (~0.1 m/s stroke)
        v_des = np.clip((x_cmd - x) * 25.0, -2.5, 2.5)
        x_next = x + v_des * self.dt
        f_obj = 0.0
        if obj and x_next < self.OBJ_WIDTH:
            # equilibrium between the gripper PD spring and the object's stiffness
            kx, ko = self.GRIP_KX, self.OBJ_STIFFNESS
            x_eq = (kx * x_cmd + ko * self.OBJ_WIDTH) / (kx + ko) if x_cmd < self.OBJ_WIDTH else self.OBJ_WIDTH
            x_next = max(x_next, x_eq)
            f_obj = ko * max(self.OBJ_WIDTH - x_next, 0.0)
            if self.force_limit > 0 and f_obj > self.force_limit:
                f_obj = self.force_limit
                x_next = self.OBJ_WIDTH - f_obj / ko
        # Slip: while the object is lifted it needs HOLD_FORCE of grip (friction × weight); a
        # lighter grip lets it slide, which the fingertip sensors see as slip-band energy.
        u = self.operator._u(t)
        lifting = obj and 0.45 < u < 0.72 and x_next < self.OBJ_WIDTH
        self.slip_level = float(np.clip((self.HOLD_FORCE - f_obj) / self.HOLD_FORCE, 0.0, 1.0)) if lifting and f_obj > 0 else 0.0
        self.contact_force = f_obj
        self.grip_v = (x_next - x) / self.dt
        self.grip = float(np.clip(x_next, 0.0, 1.0))
        friction = 0.10 * np.tanh(self.grip_v * 20.0)
        accel_term = 0.02 * v_des
        self.grip_tau = -(f_obj / 68.4) - friction - accel_term + np.random.normal(0, 0.004)

    def observe(self) -> FollowerObs:
        tau = 0.8 * np.sin(self.q) * np.array([0.1, 1.0, 0.6, 0.2, 0.05, 0.02]) + np.random.normal(0, 0.01, 6)
        return FollowerObs(time.monotonic(), True, self.q.copy(), self.dq.copy(), tau, self.grip,
                           self.grip_v, self.grip_tau, self.temps.copy())

    def command(self, q7: np.ndarray) -> None:
        q7 = np.asarray(q7, float)
        with self._lock:
            self.cmd = np.concatenate([np.clip(q7[:6], YAM_LIMITS[:, 0] - 0.15, YAM_LIMITS[:, 1]),
                                       [float(np.clip(q7[6], 0, 1))]])

    def hold(self) -> None:
        self.command(np.concatenate([self.q, [self.grip]]))

    def float_(self) -> None:
        self.hold()  # the sim arm has no gravity: holding in place is equivalent

    def set_gripper_force_limit(self, newtons: float) -> None:
        self.force_limit = float(newtons)

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
