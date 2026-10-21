"""Grip triggers on the leader handles.

Backends:
* `HGMTrigger`: the Haptic Grip Module, a series-elastic trigger with its own RP2040
  running a 1 kHz force loop, reached over USB CDC (see docs/protocol/haptic-protocol.md).
* `LegacyTrigger`: the original trigger servo on the leader's Dynamixel bus. It senses
  position only and renders force crudely by changing its current limit.
* `SimHGM`: a physics model of the HGM (lever, spring, servo, operator finger) running
  the same control law as the firmware.
* `NoTrigger`: for arms without a trigger.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

import numpy as np

from . import haptic_protocol as hp

log = logging.getLogger("station.trigger")


@dataclass
class TriggerReading:
    t: float = 0.0
    ok: bool = False
    pos: float = 0.0          # 0 = open … 1 = fully squeezed
    vel: float = 0.0          # 1/s
    force_op: float = 0.0     # operator squeeze force, N (NaN if not sensed)
    force_cmd: float = 0.0    # force the trigger is rendering, N
    lever: float = 0.0        # rad
    servo: float = 0.0        # rad
    servo_ma: float = 0.0
    buttons: int = 0
    mode: int = 0
    status: int = 0

    @property
    def button_a(self) -> bool:
        return bool(self.buttons & 1)

    @property
    def button_b(self) -> bool:
        return bool(self.buttons & 2)


class TriggerBase:
    senses_force = False
    renders_force = False

    def connect(self) -> None: ...
    def latest(self) -> TriggerReading: return TriggerReading()
    def send_setpoint(self, sp: hp.Setpoint) -> None: ...
    def set_param(self, param: hp.Param, value: float, timeout: float = 0.5) -> float: return value
    def get_param(self, param: hp.Param, timeout: float = 0.5) -> float: return float("nan")
    def command(self, cmd: hp.Command, timeout: float = 1.0) -> bool: return True
    def led(self, r: int, g: int, b: int, pattern: int = 0) -> None: ...
    def cue(self, waveform: int, amplitude: int = 200, duration_ms: int = 25) -> None:
        """Vibrotactile cue on the trigger pad (HGM v1.1 LRA). No-op where unsupported."""
    def info(self) -> Dict: return {}
    def close(self) -> None: ...


class NoTrigger(TriggerBase):
    def latest(self) -> TriggerReading:
        return TriggerReading(t=time.monotonic(), ok=True, force_op=float("nan"))


# ----------------------------------------------------------------------------- HGM


class HGMTrigger(TriggerBase):
    senses_force = True
    renders_force = True

    def __init__(self, port: str, on_log: Optional[Callable[[int, str], None]] = None):
        self.port_name = port
        self._ser = None
        self._rx_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._seq = 0
        self._latest = TriggerReading()
        self._info: Optional[hp.Info] = None
        self._pending: Dict[int, "queue.Queue[hp.Ack]"] = {}
        self._decoder = hp.FrameDecoder()
        self._on_log = on_log
        self.rx_count = 0

    def connect(self) -> None:
        import serial  # pyserial

        try:
            self._ser = serial.Serial(self.port_name, 115200, timeout=0.01, write_timeout=0.05)
        except serial.SerialException as e:
            raise RuntimeError(f"cannot open haptic grip module at {self.port_name}: {e}") from e
        self._ser.reset_input_buffer()
        self._stop.clear()
        self._rx_thread = threading.Thread(target=self._rx_loop, name=f"hgm-rx:{self.port_name}", daemon=True)
        self._rx_thread.start()
        self._send(hp.Ping())
        t_end = time.monotonic() + 1.5
        while time.monotonic() < t_end:
            if self._info is not None and self._latest.ok:
                break
            time.sleep(0.02)
        if self._info is None:
            raise RuntimeError(f"no INFO from haptic grip module on {self.port_name} (firmware flashed?)")
        if self._info.proto != hp.PROTO_VERSION:
            raise RuntimeError(f"HGM protocol v{self._info.proto}, station expects v{hp.PROTO_VERSION}")
        log.info("HGM %s fw %s connected on %s", self._info.serial, self._info.fw_version, self.port_name)

    def _send(self, pkt) -> int:
        with self._lock:
            self._seq = (self._seq + 1) & 0xFFFF
            seq = self._seq
            frame = hp.encode(pkt, seq)
            try:
                self._ser.write(frame)
            except Exception as e:  # serial timeout or unplug: warn at most once per 2 s
                now = time.monotonic()
                if now - getattr(self, "_last_warn", 0.0) > 2.0:
                    self._last_warn = now
                    log.warning("HGM write failed: %s", e)
        return seq

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._ser.read(512)
            except Exception as e:
                log.error("HGM read failed: %s", e)
                with self._lock:
                    self._latest.ok = False
                time.sleep(0.2)
                continue
            if not data:
                if time.monotonic() - self._latest.t > 0.05:
                    self._latest.ok = False
                continue
            for fr in self._decoder.feed(data):
                p = fr.packet
                if isinstance(p, hp.Telemetry):
                    self.rx_count += 1
                    self._latest = TriggerReading(
                        t=time.monotonic(), ok=True, pos=p.pos, vel=p.vel, force_op=p.force_op_n,
                        force_cmd=p.force_cmd_n, lever=p.lever_rad, servo=p.servo_rad, servo_ma=p.servo_ma,
                        buttons=p.buttons, mode=p.mode, status=p.status,
                    )
                elif isinstance(p, hp.Ack):
                    q = self._pending.pop(p.req_seq, None)
                    if q is not None:
                        q.put(p)
                elif isinstance(p, hp.Info):
                    self._info = p
                elif isinstance(p, hp.Log):
                    lvl = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR][min(p.level, 3)]
                    log.log(lvl, "[hgm %s] %s", self.port_name, p.text)
                    if self._on_log:
                        self._on_log(p.level, p.text)

    def _request(self, pkt, timeout: float) -> hp.Ack:
        q: "queue.Queue[hp.Ack]" = queue.Queue(maxsize=1)
        with self._lock:
            next_seq = (self._seq + 1) & 0xFFFF
            self._pending[next_seq] = q
        self._send(pkt)
        try:
            ack = q.get(timeout=timeout)
        except queue.Empty:
            self._pending.pop(next_seq, None)
            raise TimeoutError(f"HGM did not acknowledge {type(pkt).__name__}")
        if ack.result != hp.AckResult.OK:
            raise RuntimeError(f"HGM rejected {type(pkt).__name__}: {hp.AckResult(ack.result).name}")
        return ack

    def latest(self) -> TriggerReading:
        return self._latest

    def send_setpoint(self, sp: hp.Setpoint) -> None:
        self._send(sp)

    def set_param(self, param: hp.Param, value: float, timeout: float = 0.5) -> float:
        return self._request(hp.SetParam(int(param), float(value)), timeout).value

    def get_param(self, param: hp.Param, timeout: float = 0.5) -> float:
        return self._request(hp.GetParam(int(param)), timeout).value

    def command(self, cmd: hp.Command, timeout: float = 1.0) -> bool:
        self._request(hp.CommandPacket(int(cmd)), timeout)
        return True

    def led(self, r: int, g: int, b: int, pattern: int = 0) -> None:
        self._send(hp.Led(r, g, b, pattern))

    def cue(self, waveform: int, amplitude: int = 200, duration_ms: int = 25) -> None:
        self._send(hp.CuePacket(int(waveform), int(amplitude), int(duration_ms)))

    def info(self) -> Dict:
        i = self._info
        if i is None:
            return {}
        return {"serial": i.serial, "firmware": i.fw_version, "hw_rev": i.hw_rev, "rx_errors": i.rx_errors,
                "host_rx_errors": self._decoder.errors}

    def close(self) -> None:
        if self._ser is not None:
            try:
                self.send_setpoint(hp.Setpoint(mode=hp.Mode.SPRING))
            except Exception:
                pass
            self._stop.set()
            if self._rx_thread:
                self._rx_thread.join(timeout=1.0)
            self._ser.close()
            self._ser = None


# ---------------------------------------------------------------------- legacy servo


class LegacyTrigger(TriggerBase):
    """Original trigger servo on the leader bus. Position is fed in by the ArmWorker from the
    leader sync-read; rendering sets the servo's goal current (stiffer spring = more grip)."""

    renders_force = True

    def __init__(self, leader, max_render_n: float = 12.0):
        self.leader = leader
        self.max_render_n = max_render_n
        self._latest = TriggerReading(force_op=float("nan"))
        self._prev_pos: Optional[float] = None

    def update_from_leader(self, t: float, raw_trigger_rad: float) -> None:
        if not np.isfinite(raw_trigger_rad):
            self._latest.ok = False
            return
        pos = self.leader.legacy_trigger_pos(raw_trigger_rad)
        vel = 0.0 if self._prev_pos is None else (pos - self._prev_pos) / max(t - self._latest.t, 1e-3)
        self._prev_pos = pos
        self._latest = TriggerReading(t=t, ok=True, pos=pos, vel=vel, force_op=float("nan"),
                                      force_cmd=self._latest.force_cmd, lever=raw_trigger_rad, mode=2)

    def latest(self) -> TriggerReading:
        return self._latest

    def send_setpoint(self, sp: hp.Setpoint) -> None:
        frac = 0.0 if sp.mode == hp.Mode.OFF else min(max(sp.haptic_n / max(self.max_render_n, 1e-6), 0.0), 1.0)
        lo, hi = self.leader.trigger_base_ma, self.leader.trigger_max_ma
        self.leader.set_trigger_current(lo + frac * (hi - lo))
        self._latest.force_cmd = sp.haptic_n


# ---------------------------------------------------------------------- simulation


@dataclass
class SimHGMParams:
    k_theta: float = 3.144         # N·m/rad (spring pack, see docs/hardware/haptic-trigger.md)
    finger_radius: float = 0.045   # m
    theta_open: float = 0.0
    theta_closed: float = math.radians(30)
    sea_zero: float = 0.0
    ki: float = 0.0
    servo_tau_s: float = 0.004     # servo position-loop time constant
    servo_max_nm: float = 0.9
    lever_inertia: float = 3.0e-5  # kg·m² incl. finger
    lever_damping: float = 2.0e-3
    current_limit_ma: float = 1200.0
    watchdog_ms: float = 100.0
    params: Dict[int, float] = field(default_factory=dict)


class SimHGM(TriggerBase):
    """Physics model of the series-elastic trigger + a scripted operator finger.

    Mirrors the firmware: 1 kHz control law, modes, watchdog. Used by `--sim` and the
    tests, and handy for tuning gains without hardware.
    """

    senses_force = True
    renders_force = True

    def __init__(self, side: str, operator=None, rate_hz: float = 1000.0):
        from .leader import SimOperator

        self.side = side
        self.operator = operator or SimOperator(side)
        self.p = SimHGMParams()
        self.p.params = {int(k): float(v) for k, v in hp.PARAM_DEFAULTS.items()}
        self.dt = 1.0 / rate_hz
        self._lock = threading.Lock()
        self._sp = hp.Setpoint(mode=hp.Mode.SPRING)
        self._sp_t = time.monotonic()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.th_l = self.p.theta_open
        self.w_l = 0.0
        self.th_s = self.p.theta_open
        self._int = 0.0
        self._p_prev = 0.0
        self._v_filt = 0.0
        self.status = int(hp.Status.SERVO_OK | hp.Status.ENCODER_OK | hp.Status.CAL_VALID | hp.Status.SERVO_POWER)
        self._latest = TriggerReading()
        self.manual_squeeze: Optional[float] = None  # wizard override: finger force in N (None = scripted)
        self.cues: list = []  # (t, waveform, amplitude) of recent vibrotactile cues
        self.buttons = 0

    # ------------------------------------------------------------------ device API

    def connect(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"sim-hgm:{self.side}", daemon=True)
        self._thread.start()
        time.sleep(0.02)

    def latest(self) -> TriggerReading:
        return self._latest

    def send_setpoint(self, sp: hp.Setpoint) -> None:
        with self._lock:
            self._sp = sp
            self._sp_t = time.monotonic()

    def set_param(self, param: hp.Param, value: float, timeout: float = 0.5) -> float:
        self.p.params[int(param)] = float(value)
        attr = {hp.Param.K_THETA: "k_theta", hp.Param.FINGER_RADIUS: "finger_radius",
                hp.Param.THETA_OPEN: "theta_open", hp.Param.THETA_CLOSED: "theta_closed",
                hp.Param.SEA_ZERO: "sea_zero", hp.Param.KI: "ki"}.get(hp.Param(param))
        # The simulated mechanism keeps its true geometry; only the controller's beliefs change.
        if attr in ("k_theta", "finger_radius", "theta_open", "theta_closed"):
            pass
        elif attr:
            setattr(self.p, attr, float(value))
        return float(value)

    def get_param(self, param: hp.Param, timeout: float = 0.5) -> float:
        return self.p.params.get(int(param), float("nan"))

    def command(self, cmd: hp.Command, timeout: float = 1.0) -> bool:
        if cmd == hp.Command.TARE_SEA:
            self.p.sea_zero = self.th_l - self.th_s
            self.p.params[int(hp.Param.SEA_ZERO)] = self.p.sea_zero
        elif cmd == hp.Command.CLEAR_FAULTS:
            self.status &= ~int(hp.Status.WATCHDOG | hp.Status.OVERFORCE)
        return True

    def info(self) -> Dict:
        return {"serial": f"SIM-{self.side.upper()}", "firmware": "sim", "hw_rev": 0, "rx_errors": 0}

    def cue(self, waveform: int, amplitude: int = 200, duration_ms: int = 25) -> None:
        self.cues.append((time.monotonic(), int(waveform), int(amplitude)))
        del self.cues[:-50]

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    # ------------------------------------------------------------------ physics + control

    def _run(self) -> None:
        nxt = time.monotonic()
        tick = 0
        while not self._stop.is_set():
            nxt += self.dt
            self._step(time.monotonic(), tick)
            tick += 1
            delay = nxt - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.05:
                nxt = time.monotonic()

    def _finger_force(self, t: float, p: float) -> float:
        if self.manual_squeeze is not None:
            return self.manual_squeeze
        intent = self.operator.squeeze_intent(t)
        effort = self.operator.squeeze_effort(t)
        return float(np.clip(60.0 * (intent - p) + effort, 0.0, 35.0))

    def _step(self, t: float, tick: int) -> None:
        P = self.p
        prm = P.params
        # --- true mechanism (simulated truth uses the real geometry)
        th_o, th_c = P.theta_open, P.theta_closed
        r_true = 0.045
        k_true = 3.144
        p_true = (self.th_l - th_o) / (th_c - th_o)
        f_finger = self._finger_force(t, p_true)
        tau_spring = k_true * (self.th_l - self.th_s)  # positive = spring resisting closing
        tau = f_finger * r_true - tau_spring - P.lever_damping * self.w_l
        self.w_l += tau / P.lever_inertia * self.dt
        self.th_l += self.w_l * self.dt
        if self.th_l < th_o:
            self.th_l, self.w_l = th_o, max(0.0, self.w_l)
        if self.th_l > th_c:
            self.th_l, self.w_l = th_c, min(0.0, self.w_l)

        # --- firmware control law (uses calibrated parameters)
        k = prm[int(hp.Param.K_THETA)]
        r = prm[int(hp.Param.FINGER_RADIUS)]
        c_open = prm[int(hp.Param.THETA_OPEN)]
        c_closed = prm[int(hp.Param.THETA_CLOSED)]
        lever_meas = self.th_l + np.random.normal(0, 0.0004)
        servo_meas = self.th_s + np.random.normal(0, 0.0004)
        p = float(np.clip((lever_meas - c_open) / max(c_closed - c_open, 1e-6), -0.05, 1.05))
        v_raw = (p - self._p_prev) / self.dt
        self._p_prev = p
        self._v_filt += (v_raw - self._v_filt) * (1 - math.exp(-self.dt * 2 * math.pi * 30))
        f_op = k * (lever_meas - servo_meas - P.sea_zero) / r

        with self._lock:
            sp = self._sp
            sp_age = time.monotonic() - self._sp_t
        mode = sp.mode
        if mode == hp.Mode.RENDER and sp_age * 1000 > prm[int(hp.Param.WATCHDOG_MS)]:
            mode = hp.Mode.SPRING
            self.status |= int(hp.Status.WATCHDOG)
        haptic = sp.haptic_n if mode == hp.Mode.RENDER else 0.0

        if mode == hp.Mode.OFF:
            f_des = 0.0
            th_cmd = self.th_s  # limp: servo stays where it is (approximation of torque-off)
            self.th_s += (self.th_l - self.th_s) * 0.02  # backdriven
        elif mode == hp.Mode.POSITION:
            th_cmd = c_open + float(np.clip(sp.pos_cmd, 0, 1)) * (c_closed - c_open)
            f_des = f_op
        else:
            f_des = sp.spring_min_n + sp.spring_n * max(p, 0.0) + haptic + sp.damping * self._v_filt
            f_des = float(np.clip(f_des, 0.0, sp.max_n))
            self._int += (f_des - f_op) * self.dt * P.ki
            self._int = float(np.clip(self._int, -0.1, 0.1))
            th_cmd = lever_meas - f_des * r / k - P.sea_zero - self._int
            th_cmd = float(np.clip(th_cmd, c_open - 0.35, c_closed + 0.1))

        if mode != hp.Mode.OFF:
            # servo: first-order position loop with torque saturation
            th_next = self.th_s + (th_cmd - self.th_s) * (1 - math.exp(-self.dt / P.servo_tau_s))
            if abs(k_true * (self.th_l - th_next)) > P.servo_max_nm:
                th_next = self.th_l - math.copysign(P.servo_max_nm / k_true, self.th_l - th_next)
            self.th_s = th_next

        if f_op > 40.0:
            self.status |= int(hp.Status.OVERFORCE)

        if tick % 2 == 0:
            self._latest = TriggerReading(
                t=time.monotonic(), ok=True, pos=float(np.clip(p, 0, 1)), vel=self._v_filt, force_op=f_op,
                force_cmd=f_des, lever=lever_meas, servo=servo_meas,
                servo_ma=abs(k_true * (self.th_l - self.th_s)) / 0.93 * 1800.0,
                buttons=self.buttons, mode=int(mode), status=self.status,
            )
