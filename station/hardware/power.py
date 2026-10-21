"""Relay boards that switch arm power, plus e-stop sensing.

Wiring (docs/hardware/electronics.md): each follower's 24 V supply passes through a DC
power relay or SSR. Its control input is driven by a relay-board channel *in series with*
the e-stop's NC contact, so the e-stop always cuts power regardless of software. The
e-stop's auxiliary contact goes to a relay-board GPIO so the station can see it.

Drivers:
* `numato`: Numato Lab USB relay modules (ASCII: "relay on 0", "gpio read 0")
* `lcus`: common CH340 "LCUS" USB relay boards (4-byte binary frames)
* `modbus_tcp`: Ethernet relay boards speaking Modbus TCP (e.g. Waveshare Modbus POE ETH Relay)
* `sim`: in-memory, for --sim
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from typing import Dict, List, Optional

from station.config import PowerConfig

log = logging.getLogger("station.power")


class RelayDriver:
    def set(self, relay: int, on: bool) -> None: raise NotImplementedError
    def get(self, relay: int) -> Optional[bool]: return None
    def read_input(self, index: int) -> Optional[int]: return None
    def close(self) -> None: ...


class NumatoRelay(RelayDriver):
    def __init__(self, port: str):
        import serial

        self.ser = serial.Serial(port, 19200, timeout=0.3)
        self.lock = threading.Lock()

    @staticmethod
    def _idx(i: int) -> str:
        return str(i) if i < 10 else chr(ord("A") + i - 10)

    def _cmd(self, s: str) -> str:
        with self.lock:
            self.ser.reset_input_buffer()
            self.ser.write((s + "\r").encode())
            time.sleep(0.02)
            resp = self.ser.read(64).decode(errors="ignore")
        # Response echoes the command; the value is on the following line.
        lines = [ln.strip() for ln in resp.replace("\n\r", "\n").split("\n") if ln.strip() and ">" not in ln]
        return lines[-1] if lines else ""

    def set(self, relay: int, on: bool) -> None:
        self._cmd(f"relay {'on' if on else 'off'} {self._idx(relay)}")

    def get(self, relay: int) -> Optional[bool]:
        r = self._cmd(f"relay read {self._idx(relay)}")
        return {"on": True, "off": False}.get(r.lower())

    def read_input(self, index: int) -> Optional[int]:
        r = self._cmd(f"gpio read {self._idx(index)}")
        return int(r) if r in ("0", "1") else None

    def close(self) -> None:
        self.ser.close()


class LcusRelay(RelayDriver):
    def __init__(self, port: str):
        import serial

        self.ser = serial.Serial(port, 9600, timeout=0.2)
        self.state: Dict[int, bool] = {}

    def set(self, relay: int, on: bool) -> None:
        ch = relay + 1
        frame = bytes([0xA0, ch, 1 if on else 0])
        self.ser.write(frame + bytes([sum(frame) & 0xFF]))
        self.state[relay] = on

    def get(self, relay: int) -> Optional[bool]:
        return self.state.get(relay)  # these boards can't report state

    def close(self) -> None:
        self.ser.close()


class ModbusTcpRelay(RelayDriver):
    def __init__(self, host: str, port: int = 502, unit: int = 1):
        self.addr = (host, port)
        self.unit = unit
        self.tid = 0
        self.lock = threading.Lock()

    def _xfer(self, pdu: bytes) -> bytes:
        with self.lock:
            self.tid = (self.tid + 1) & 0xFFFF
            mbap = struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, self.unit)
            with socket.create_connection(self.addr, timeout=1.0) as s:
                s.sendall(mbap + pdu)
                head = s.recv(7)
                if len(head) < 7:
                    raise IOError("short Modbus response")
                length = struct.unpack(">H", head[4:6])[0]
                body = s.recv(length - 1)
        if body and body[0] & 0x80:
            raise IOError(f"Modbus exception code {body[1]}")
        return body

    def set(self, relay: int, on: bool) -> None:
        self._xfer(struct.pack(">BHH", 0x05, relay, 0xFF00 if on else 0x0000))

    def get(self, relay: int) -> Optional[bool]:
        body = self._xfer(struct.pack(">BHH", 0x01, relay, 1))
        return bool(body[2] & 1)

    def read_input(self, index: int) -> Optional[int]:
        body = self._xfer(struct.pack(">BHH", 0x02, index, 1))
        return int(body[2] & 1)


class SimRelay(RelayDriver):
    def __init__(self):
        self.state: Dict[int, bool] = {}
        self.estop_pressed = False

    def set(self, relay: int, on: bool) -> None:
        self.state[relay] = on

    def get(self, relay: int) -> Optional[bool]:
        return self.state.get(relay, False)

    def read_input(self, index: int) -> Optional[int]:
        return 1 if self.estop_pressed else 0  # wired as in electronics.md: released = low


class PowerManager:
    def __init__(self, cfg: PowerConfig):
        self.cfg = cfg
        self.driver: Optional[RelayDriver] = None
        self.error = ""
        self._cache: Dict[str, Optional[bool]] = {c.id: None for c in cfg.channels}
        self._estop_ok: Optional[bool] = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.cfg.backend != "none" and bool(self.cfg.channels)

    def connect(self) -> None:
        if not self.available:
            return
        try:
            b = self.cfg.backend
            if b == "numato":
                self.driver = NumatoRelay(self.cfg.port)
            elif b == "lcus":
                self.driver = LcusRelay(self.cfg.port)
            elif b == "modbus_tcp":
                self.driver = ModbusTcpRelay(self.cfg.host, self.cfg.tcp_port, self.cfg.unit_id)
            elif b == "sim":
                self.driver = SimRelay()
            self.error = ""
            self.refresh()
        except Exception as e:
            self.error = f"relay board ({self.cfg.backend}) unavailable: {e}"
            log.error(self.error)
            self.driver = None

    def channel(self, cid: str):
        for c in self.cfg.channels:
            if c.id == cid:
                return c
        raise KeyError(f"unknown power channel {cid!r}")

    def set(self, cid: str, on: bool) -> None:
        if self.driver is None:
            raise RuntimeError(self.error or "no relay board configured (power.backend: none)")
        ids = [c.id for c in self.cfg.channels] if cid == "all" else [cid]
        with self._lock:
            for i in ids:
                self.driver.set(self.channel(i).relay, on)
                self._cache[i] = on
                log.info("power %s → %s", i, "ON" if on else "OFF")
                time.sleep(0.05)  # stagger inrush

    def refresh(self) -> None:
        if self.driver is None:
            return
        with self._lock:
            for c in self.cfg.channels:
                try:
                    v = self.driver.get(c.relay)
                    if v is not None:
                        self._cache[c.id] = v
                except Exception as e:
                    log.warning("relay read failed: %s", e)
            if self.cfg.estop_input is not None:
                try:
                    lvl = self.driver.read_input(self.cfg.estop_input)
                    self._estop_ok = None if lvl is None else (lvl == self.cfg.estop_ok_level)
                except Exception as e:
                    log.warning("e-stop input read failed: %s", e)

    def is_on(self, cid: str) -> Optional[bool]:
        return self._cache.get(cid)

    def estop_ok(self) -> Optional[bool]:
        return self._estop_ok

    def snapshot(self) -> Dict:
        return {
            "available": self.driver is not None,
            "error": self.error,
            "estop_ok": self._estop_ok,
            "channels": [{"id": c.id, "label": c.label, "on": self._cache.get(c.id)} for c in self.cfg.channels],
        }

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
