"""Lock-free shared state between worker processes and the server.

Each worker owns one `SharedBlock` (a flat float64 RawArray with named fields) and is
its only writer. Readers (the server, the UI streamer, simulated cameras) take
consistent snapshots with a seqlock: the writer bumps `seq` to odd before writing and to
even after, and readers retry if `seq` changed or was odd. Control loops never block on
readers.
"""

from __future__ import annotations

import multiprocessing as mp
import time
from typing import Dict, Iterable, List, Sequence, Tuple, Union

import numpy as np

FieldSpec = Sequence[Tuple[str, int]]


class SharedBlock:
    def __init__(self, fields: FieldSpec, ctx: mp.context.BaseContext | None = None, raw=None):
        self.fields: List[Tuple[str, int]] = [("_seq", 1)] + [(n, int(s)) for n, s in fields]
        self._slices: Dict[str, slice] = {}
        off = 0
        for name, size in self.fields:
            self._slices[name] = slice(off, off + size)
            off += size
        self.size = off
        ctx = ctx or mp.get_context()
        self.raw = raw if raw is not None else ctx.RawArray("d", self.size)
        self._np = np.frombuffer(self.raw, dtype=np.float64)

    # pickling support (pass to child processes)
    def __getstate__(self):
        return {"fields": self.fields[1:], "raw": self.raw}

    def __setstate__(self, st):
        self.__init__(st["fields"], raw=st["raw"])

    # ----------------------------------------------------------------- writer

    def write(self, values: Dict[str, Union[float, Iterable[float]]]) -> None:
        a = self._np
        a[0] += 1.0  # odd: write in progress
        for k, v in values.items():
            s = self._slices[k]
            if s.stop - s.start == 1:
                a[s.start] = float(v)  # type: ignore[arg-type]
            else:
                a[s] = v
        a[0] += 1.0  # even: consistent

    # ----------------------------------------------------------------- readers

    def snapshot(self, retries: int = 50) -> np.ndarray:
        a = self._np
        for _ in range(retries):
            s0 = a[0]
            if int(s0) % 2 == 0:
                copy = a.copy()
                if a[0] == s0:
                    return copy
            time.sleep(0)
        return a.copy()  # writer is hammering; a torn read is acceptable for display

    def read(self) -> Dict[str, Union[float, np.ndarray]]:
        snap = self.snapshot()
        out: Dict[str, Union[float, np.ndarray]] = {}
        for name, size in self.fields[1:]:
            s = self._slices[name]
            out[name] = float(snap[s.start]) if size == 1 else snap[s].copy()
        return out

    def get(self, name: str):
        s = self._slices[name]
        return float(self._np[s.start]) if s.stop - s.start == 1 else self._np[s].copy()


# ----------------------------------------------------------------------- layouts

ARM_STATES = ["offline", "connecting", "connected", "syncing", "teleop", "fault"]
TRIGGER_MODES = ["off", "spring", "render", "position"]

ARM_FIELDS: FieldSpec = [
    ("t", 1),
    ("state", 1),            # index into ARM_STATES
    ("loop_hz", 1),
    ("loop_jitter_ms", 1),
    ("tracking_error", 1),
    ("leader_ok", 1),
    ("leader_q", 6),         # follower frame (calibrated)
    ("leader_raw", 7),       # raw radians from the bus (6 joints + legacy trigger)
    ("follower_ok", 1),
    ("follower_q", 6),
    ("follower_dq", 6),
    ("follower_tau", 6),
    ("follower_gripper", 1),
    ("follower_gripper_vel", 1),
    ("follower_gripper_tau", 1),
    ("follower_temps", 6),
    ("trigger_ok", 1),
    ("trigger_pos", 1),
    ("trigger_force", 1),
    ("trigger_render", 1),
    ("trigger_btn_a", 1),
    ("trigger_btn_b", 1),
    ("trigger_mode", 1),
    ("trigger_lever", 1),
    ("trigger_servo", 1),
    ("trigger_status", 1),
    ("grip_force", 1),
    ("contact", 1),
    ("fingertip_ok", 1),
    ("fingertip_a", 1),
    ("fingertip_b", 1),
    ("slip", 1),
    ("q_cmd", 7),            # last command sent to the follower (6 joints + gripper)
]

CAMERA_FIELDS: FieldSpec = [
    ("t", 1),
    ("ok", 1),
    ("fps", 1),
    ("dropped", 1),
    ("width", 1),
    ("height", 1),
    ("recording", 1),
    ("frames_recorded", 1),
    ("preview_seq", 1),
]


class JpegSlot:
    """Single-producer latest-frame JPEG buffer in shared memory (for MJPEG previews)."""

    def __init__(self, capacity: int = 1 << 20, ctx: mp.context.BaseContext | None = None, raw=None, meta=None):
        ctx = ctx or mp.get_context()
        self.capacity = capacity
        self.raw = raw if raw is not None else ctx.RawArray("B", capacity)
        self.meta = meta if meta is not None else ctx.RawArray("q", 3)  # seq, length, t_ns

    def __getstate__(self):
        return {"capacity": self.capacity, "raw": self.raw, "meta": self.meta}

    def __setstate__(self, st):
        self.__init__(st["capacity"], raw=st["raw"], meta=st["meta"])

    def put(self, data: bytes, t_ns: int) -> None:
        n = len(data)
        if n > self.capacity:
            return
        self.meta[0] += 1
        memoryview(self.raw).cast("B")[:n] = data
        self.meta[1] = n
        self.meta[2] = t_ns
        self.meta[0] += 1

    def get(self) -> Tuple[int, bytes]:
        for _ in range(20):
            s0 = self.meta[0]
            if s0 % 2 == 0:
                n = self.meta[1]
                data = bytes(memoryview(self.raw).cast("B")[:n])
                if self.meta[0] == s0:
                    return s0 // 2, data
            time.sleep(0.001)
        return -1, b""
