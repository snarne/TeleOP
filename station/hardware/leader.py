"""Leader arms: 3D-printed YAM replicas with Dynamixel joints.

`DynamixelLeader` reads the joints, and optionally the original trigger servo, with one
Protocol 2.0 sync-read per control tick. The joints stay torque-off so the arm is light
and backdrivable. `SimLeader` plays a scripted operator for development and tests.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

log = logging.getLogger("station.leader")

TICKS_PER_REV = 4096
RAD_PER_TICK = 2.0 * math.pi / TICKS_PER_REV

# Dynamixel X-series control table (protocol 2.0)
ADDR_OPERATING_MODE = 11
ADDR_CURRENT_LIMIT = 38
ADDR_TORQUE_ENABLE = 64
ADDR_GOAL_CURRENT = 102
ADDR_GOAL_POSITION = 116
ADDR_PRESENT_CURRENT = 126
ADDR_PRESENT_POSITION = 132
ADDR_PRESENT_INPUT_VOLTAGE = 144
ADDR_PRESENT_TEMPERATURE = 146
MODE_CURRENT_BASED_POSITION = 5

DXL_MODELS = {
    1190: "XL330-M077", 1200: "XL330-M288", 1210: "XC330-M181", 1220: "XC330-M288",
    1230: "XC330-T181", 1240: "XC330-T288", 1060: "XL430-W250", 1020: "XM430-W350",
    1030: "XM430-W210", 1070: "XC430-W150", 1080: "XC430-W240",
}


def ticks_to_rad(t: np.ndarray | int) -> np.ndarray:
    return (np.asarray(t, dtype=np.float64) - 2048.0) * RAD_PER_TICK


@dataclass
class LeaderReading:
    t: float
    ok: bool
    raw: np.ndarray  # 7 values: 6 joints (rad) + legacy trigger (rad) or NaN
    error: str = ""


@dataclass
class LeaderCalibration:
    """q_follower = sign * (raw - offset), then unwrapped into the follower's joint range."""

    offsets: np.ndarray = field(default_factory=lambda: np.zeros(6))
    signs: np.ndarray = field(default_factory=lambda: np.ones(6))
    valid: bool = False

    @classmethod
    def from_dict(cls, d: Dict) -> "LeaderCalibration":
        return cls(np.asarray(d["offsets"], float), np.asarray(d["signs"], float), True)

    def to_dict(self) -> Dict:
        return {"offsets": [float(x) for x in self.offsets], "signs": [int(s) for s in self.signs]}


# YAM joint limits (i2rt yam.xml), used to pick the right 2π branch when mapping.
YAM_LIMITS = np.array([
    [-2.61799, 3.14159], [0.0, 3.66519], [0.0, 3.14159],
    [-1.69297, 1.5708], [-1.5708, 1.5708], [-2.0944, 2.0944],
])


def map_leader(raw6: np.ndarray, cal: LeaderCalibration, prev: Optional[np.ndarray] = None,
               limits: np.ndarray = YAM_LIMITS) -> np.ndarray:
    """Map raw leader joint angles into the follower's joint frame.

    The servo's absolute encoder is single-turn, so after a power cycle a joint can read
    2π away from where it read during calibration. With a previous sample available, the
    branch is chosen for continuity. Otherwise it's the branch whose value lies inside the
    joint limits (closest to the center of the range).
    """
    q = cal.signs * (raw6 - cal.offsets)
    out = np.empty_like(q)
    for i, qi in enumerate(q):
        candidates = qi + 2.0 * math.pi * np.array([-2, -1, 0, 1, 2])
        if prev is not None and np.isfinite(prev[i]):
            out[i] = candidates[np.argmin(np.abs(candidates - prev[i]))]
        else:
            lo, hi = limits[i]
            mid = 0.5 * (lo + hi)
            inside = (candidates >= lo - 0.6) & (candidates <= hi + 0.6)
            pool = candidates[inside] if inside.any() else candidates
            out[i] = pool[np.argmin(np.abs(pool - mid))]
    return out


class LeaderBase:
    n_joints = 6
    has_legacy_trigger = False

    def connect(self) -> None: ...
    def read(self) -> LeaderReading: raise NotImplementedError
    def scan(self) -> List[Dict]: return []
    def set_trigger_current(self, milliamps: float) -> None: ...
    def close(self) -> None: ...


class DynamixelLeader(LeaderBase):
    def __init__(self, port: str, baudrate: int, joint_ids: List[int], trigger_id: Optional[int] = None,
                 trigger_open_ticks: int = 2048, trigger_closed_ticks: int = 2700,
                 trigger_base_ma: int = 40, trigger_max_ma: int = 300):
        self.port_name = port
        self.baudrate = baudrate
        self.joint_ids = list(joint_ids)
        self.trigger_id = trigger_id
        self.has_legacy_trigger = trigger_id is not None
        self.trigger_open_ticks = trigger_open_ticks
        self.trigger_closed_ticks = trigger_closed_ticks
        self.trigger_base_ma = trigger_base_ma
        self.trigger_max_ma = trigger_max_ma
        self._port = None
        self._ph = None
        self._gsr = None
        self._ids: List[int] = []
        self._last_current = None

    def connect(self) -> None:
        try:
            from dynamixel_sdk import COMM_SUCCESS, GroupSyncRead, PacketHandler, PortHandler
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("dynamixel_sdk is not installed (pip install dynamixel-sdk)") from e
        self._COMM_SUCCESS = COMM_SUCCESS
        port = PortHandler(self.port_name)
        if not port.openPort():
            raise RuntimeError(f"cannot open {self.port_name} (is the U2D2 plugged in? user in 'dialout'?)")
        if not port.setBaudRate(self.baudrate):
            raise RuntimeError(f"cannot set baudrate {self.baudrate} on {self.port_name}")
        self._port, self._ph = port, PacketHandler(2.0)
        self._ids = self.joint_ids + ([self.trigger_id] if self.trigger_id is not None else [])
        missing = [i for i in self._ids if self._ping(i) is None]
        if missing:
            raise RuntimeError(f"Dynamixel IDs {missing} did not answer on {self.port_name} @ {self.baudrate} bps")
        for i in self.joint_ids:  # joints are passive: keep the leader light to move
            self._ph.write1ByteTxRx(self._port, i, ADDR_TORQUE_ENABLE, 0)
        if self.trigger_id is not None:
            self._setup_legacy_trigger()
        self._gsr = GroupSyncRead(self._port, self._ph, ADDR_PRESENT_POSITION, 4)
        for i in self._ids:
            self._gsr.addParam(i)
        log.info("leader connected on %s: ids=%s", self.port_name, self._ids)

    def _setup_legacy_trigger(self) -> None:
        tid = self.trigger_id
        ph, port = self._ph, self._port
        ph.write1ByteTxRx(port, tid, ADDR_TORQUE_ENABLE, 0)
        ph.write1ByteTxRx(port, tid, ADDR_OPERATING_MODE, MODE_CURRENT_BASED_POSITION)
        ph.write4ByteTxRx(port, tid, ADDR_GOAL_POSITION, int(self.trigger_open_ticks))
        ph.write2ByteTxRx(port, tid, ADDR_GOAL_CURRENT, int(self.trigger_base_ma))
        ph.write1ByteTxRx(port, tid, ADDR_TORQUE_ENABLE, 1)

    def _ping(self, dxl_id: int) -> Optional[int]:
        model, res, _err = self._ph.ping(self._port, dxl_id)
        return model if res == self._COMM_SUCCESS else None

    def read(self) -> LeaderReading:
        t = time.monotonic()
        res = self._gsr.txRxPacket()
        if res != self._COMM_SUCCESS:
            return LeaderReading(t, False, np.full(7, np.nan), self._ph.getTxRxResult(res))
        vals = []
        for i in self._ids:
            if not self._gsr.isAvailable(i, ADDR_PRESENT_POSITION, 4):
                return LeaderReading(t, False, np.full(7, np.nan), f"id {i} missing from sync read")
            v = self._gsr.getData(i, ADDR_PRESENT_POSITION, 4)
            vals.append(v - (1 << 32) if v & 0x80000000 else v)
        raw = np.full(7, np.nan)
        raw[: len(self.joint_ids)] = ticks_to_rad(np.array(vals[: len(self.joint_ids)]))
        if self.trigger_id is not None:
            raw[6] = ticks_to_rad(vals[-1])
        return LeaderReading(t, True, raw)

    def legacy_trigger_pos(self, raw_trigger_rad: float) -> float:
        o = ticks_to_rad(self.trigger_open_ticks)
        c = ticks_to_rad(self.trigger_closed_ticks)
        return float(np.clip((raw_trigger_rad - o) / (c - o), 0.0, 1.0)) if c != o else 0.0

    def set_trigger_current(self, milliamps: float) -> None:
        """Legacy haptics: the trigger servo's current limit sets how hard it pushes back toward open."""
        if self.trigger_id is None:
            return
        ma = int(np.clip(milliamps, self.trigger_base_ma, self.trigger_max_ma))
        if ma != self._last_current:
            self._ph.write2ByteTxOnly(self._port, self.trigger_id, ADDR_GOAL_CURRENT, ma)
            self._last_current = ma

    def scan(self) -> List[Dict]:
        found = []
        for i in range(0, 32):
            model = self._ping(i)
            if model is not None:
                fw, _, _ = self._ph.read1ByteTxRx(self._port, i, 6)
                found.append({"id": i, "model": DXL_MODELS.get(model, f"model {model}"), "firmware": int(fw)})
        return found

    def close(self) -> None:
        if self._port is not None:
            try:
                if self.trigger_id is not None:
                    self._ph.write1ByteTxRx(self._port, self.trigger_id, ADDR_TORQUE_ENABLE, 0)
            finally:
                self._port.closePort()
                self._port = None


# ------------------------------------------------------------------------- simulation


class SimOperator:
    """A scripted operator shared by the simulated leader and the simulated trigger.

    It runs a pick-and-place cycle so every subsystem sees realistic signals: arm
    motion, approach, squeeze (with an object between the follower's fingers),
    lift, and release. Each arm is phase-shifted.
    """

    PERIOD = 9.0

    def __init__(self, side: str):
        self.side = side
        self.phase = 0.0 if side == "left" else 0.37
        self.t0 = time.monotonic()
        self.sign = 1.0 if side == "left" else -1.0

    def _u(self, t: float) -> float:
        return (((t - self.t0) / self.PERIOD) + self.phase) % 1.0

    def joints(self, t: float) -> np.ndarray:
        u = self._u(t)
        w = 2 * math.pi
        base = np.array([0.0, 1.05, 0.95, -0.25, 0.0, 0.0])
        lift = 0.35 * _smooth_bump(u, 0.45, 0.8)
        reach = 0.25 * math.sin(w * u)
        q = base + np.array([
            self.sign * (0.35 * math.sin(w * u + 0.4)),
            0.25 * math.sin(w * u) + lift,
            0.30 * math.sin(w * u + 1.2) - lift * 0.8 + reach * 0.3,
            0.30 * math.sin(2 * w * u),
            0.25 * math.sin(w * u + 2.0),
            0.6 * math.sin(w * u + 0.8),
        ])
        return q + 0.004 * np.sin(np.arange(6) * 7.0 + t * 13.0)  # hand tremor

    # The scripted operator grips each object differently, like a person would: a firm grasp, a
    # medium one, and a too-light one that lets the object slip (exercises the slip cue).
    FIRMNESS = (1.0, 0.5, 0.1)

    def _firmness(self, t: float) -> float:
        k = int(((t - self.t0) / self.PERIOD) + self.phase)
        return self.FIRMNESS[k % len(self.FIRMNESS)]

    def squeeze_intent(self, t: float) -> float:
        """Desired trigger position 0..1 (operator intent)."""
        u = self._u(t)
        p_contact = 0.58  # trigger position where the sim jaws meet the object
        peak = p_contact + 0.02 + self._firmness(t) * (1.0 - p_contact - 0.02)
        return 0.15 + (peak - 0.15) * _smooth_bump(u, 0.3, 0.75, ramp=0.06)

    def squeeze_effort(self, t: float) -> float:
        """How hard the operator presses beyond contact (N)."""
        u = self._u(t)
        return 6.0 * self._firmness(t) * _smooth_bump(u, 0.33, 0.72, ramp=0.08)

    def object_present(self, t: float) -> bool:
        u = self._u(t)
        return 0.25 < u < 0.8


def _smooth_bump(u: float, a: float, b: float, ramp: float = 0.08) -> float:
    def s(x: float) -> float:
        x = min(max(x, 0.0), 1.0)
        return x * x * (3 - 2 * x)
    return s((u - a) / ramp) * (1.0 - s((u - (b - ramp)) / ramp))


class SimLeader(LeaderBase):
    """Simulated leader: raw readings = calibrated pose mapped back through a fake calibration."""

    FAKE_OFFSETS = np.array([0.31, -1.20, 2.05, -0.44, 0.92, -2.61])
    FAKE_SIGNS = np.array([1, -1, 1, -1, 1, 1], dtype=float)

    def __init__(self, side: str, operator: Optional[SimOperator] = None):
        self.side = side
        self.operator = operator or SimOperator(side)
        self.connected = False
        self.manual_pose: Optional[np.ndarray] = None  # calibration wizard drives the sim here

    def connect(self) -> None:
        time.sleep(0.05)
        self.connected = True

    def true_pose(self, t: float) -> np.ndarray:
        return self.manual_pose.copy() if self.manual_pose is not None else self.operator.joints(t)

    def read(self) -> LeaderReading:
        t = time.monotonic()
        q = self.true_pose(t)
        raw6 = q / self.FAKE_SIGNS + self.FAKE_OFFSETS
        raw6 = (raw6 + math.pi) % (2 * math.pi) - math.pi  # single-turn encoder wrap
        raw = np.full(7, np.nan)
        raw[:6] = raw6
        return LeaderReading(t, True, raw)

    def scan(self) -> List[Dict]:
        return [{"id": i, "model": "XL330-M288 (sim)", "firmware": 52} for i in range(1, 7)]
