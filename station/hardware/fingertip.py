"""Follower fingertip sensors (FGS): true contact force at each jaw pad, plus a slip band.

The follower's grip force can be *estimated* from the gripper motor's torque (see
teleop/gripper.py), but friction, the lead screw and the jaw compliance all sit between the
motor and the object. With FGS fingertips the haptic feedback is driven by the force that's
actually pressing on the object, and slip shows up as high-frequency energy in the strain
signal before the object visibly moves.

Backends: `FGSDevice` (USB, protocol in docs/protocol/haptic-protocol.md → v1.1),
`SimFingertip` (driven by the simulated follower), `NoFingertip`.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from . import haptic_protocol as hp

log = logging.getLogger("station.fingertip")


@dataclass
class FingertipReading:
    t: float = 0.0
    ok: bool = False
    force_a: float = 0.0     # N, jaw A pad normal force
    force_b: float = 0.0     # N, jaw B
    hf_a: float = 0.0        # N rms in the slip band
    hf_b: float = 0.0
    status: int = 0

    @property
    def force(self) -> float:
        """Grip force = mean of the two pads (equal and opposite in a static two-finger grasp)."""
        return 0.5 * (self.force_a + self.force_b)

    @property
    def hf(self) -> float:
        return max(self.hf_a, self.hf_b)


class FingertipBase:
    present = False

    def connect(self) -> None: ...
    def latest(self) -> FingertipReading: return FingertipReading()
    def tare(self) -> None: ...
    def set_param(self, param: int, value: float) -> float: return value
    def info(self) -> Dict: return {}
    def close(self) -> None: ...


class NoFingertip(FingertipBase):
    pass


class FGSDevice(FingertipBase):
    present = True

    def __init__(self, port: str):
        self.port_name = port
        self._ser = None
        self._latest = FingertipReading()
        self._dec = hp.FrameDecoder()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._seq = 0
        self._acks: Dict[int, "queue.Queue[hp.Ack]"] = {}
        self._info: Optional[hp.Info] = None
        self._thread: Optional[threading.Thread] = None

    def connect(self) -> None:
        import serial

        try:
            self._ser = serial.Serial(self.port_name, 115200, timeout=0.01, write_timeout=0.05)
        except serial.SerialException as e:
            raise RuntimeError(f"cannot open fingertip sensor at {self.port_name}: {e}") from e
        self._stop.clear()
        self._thread = threading.Thread(target=self._rx, name=f"fgs-rx:{self.port_name}", daemon=True)
        self._thread.start()
        self._send(hp.Ping())
        t_end = time.monotonic() + 1.5
        while time.monotonic() < t_end and (self._info is None or not self._latest.ok):
            time.sleep(0.02)
        if self._info is None:
            raise RuntimeError(f"no INFO from fingertip sensor on {self.port_name} (firmware flashed?)")
        if (self._info.hw_rev >> 4) != hp.DeviceKind.FGS:
            raise RuntimeError(f"{self.port_name} is not a fingertip sensor (device kind {self._info.hw_rev >> 4})")

    def _send(self, pkt) -> int:
        with self._lock:
            self._seq = (self._seq + 1) & 0xFFFF
            try:
                self._ser.write(hp.encode(pkt, self._seq))
            except Exception as e:
                now = time.monotonic()
                if now - getattr(self, "_last_warn", 0.0) > 2.0:
                    self._last_warn = now
                    log.warning("FGS write failed: %s", e)
            return self._seq

    def _rx(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._ser.read(512)
            except Exception as e:
                log.error("FGS read failed: %s", e)
                self._latest.ok = False
                time.sleep(0.2)
                continue
            if not data:
                if time.monotonic() - self._latest.t > 0.15:  # SAVE pauses telemetry ~50 ms
                    self._latest.ok = False
                continue
            for fr in self._dec.feed(data):
                p = fr.packet
                if isinstance(p, hp.FingertipTelemetry):
                    self._latest = FingertipReading(time.monotonic(), bool(p.status & hp.FGSStatus.ADC_OK),
                                                    p.force_a_n, p.force_b_n, p.hf_a_n, p.hf_b_n, p.status)
                elif isinstance(p, hp.Info):
                    self._info = p
                elif isinstance(p, hp.Ack):
                    q = self._acks.pop(p.req_seq, None)
                    if q:
                        q.put(p)
                elif isinstance(p, hp.Log):
                    log.info("[fgs %s] %s", self.port_name, p.text)

    def _request(self, pkt, timeout: float = 1.0) -> hp.Ack:
        q: "queue.Queue[hp.Ack]" = queue.Queue(maxsize=1)
        with self._lock:
            self._acks[(self._seq + 1) & 0xFFFF] = q
        self._send(pkt)
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"fingertip sensor did not acknowledge {type(pkt).__name__}")

    def latest(self) -> FingertipReading:
        return self._latest

    def tare(self) -> None:
        self._request(hp.CommandPacket(int(hp.Command.TARE_SEA)))  # command 1 = TARE on the FGS

    def set_param(self, param: int, value: float) -> float:
        return self._request(hp.SetParam(int(param), float(value))).value

    def info(self) -> Dict:
        i = self._info
        return {} if i is None else {"serial": i.serial, "firmware": i.fw_version, "hw_rev": i.hw_rev}

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._ser:
            self._ser.close()


class SimFingertip(FingertipBase):
    """Reads the simulated follower's true object force; adds pad noise, and slip-band energy
    when the object slips (the sim follower decides that from grip force vs. object weight)."""

    present = True

    def __init__(self, follower):
        self.follower = follower
        self._rng = np.random.default_rng(7)

    def connect(self) -> None:
        time.sleep(0.02)

    def latest(self) -> FingertipReading:
        f = float(getattr(self.follower, "contact_force", 0.0)) + self.weight_n
        slip = float(getattr(self.follower, "slip_level", 0.0))
        n = self._rng.normal(0.0, 0.05, 2)
        hf = 0.01 + slip * 0.6 + abs(self._rng.normal(0, 0.005))
        return FingertipReading(time.monotonic(), True, max(0.0, f * 1.02 + n[0]), max(0.0, f * 0.98 + n[1]),
                                hf, hf * 0.9, int(hp.FGSStatus.ADC_OK | hp.FGSStatus.CAL_VALID))

    def info(self) -> Dict:
        return {"serial": "SIM-FGS", "firmware": "sim"}

    def tare(self) -> None:
        pass

    weight_n = 0.0  # calibration wizard: a known weight hanging on a pad (sim only)
