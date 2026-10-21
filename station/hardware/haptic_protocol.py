"""Haptic Grip Module wire protocol v1 (see docs/protocol/haptic-protocol.md).

Pure-Python codec, no I/O. Shared by the real device driver, the simulator, the
firmware test-vector generator and the unit tests.
"""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass
from typing import Iterator, Optional, Union

PROTO_VERSION = 1
MAX_PAYLOAD = 64


# --------------------------------------------------------------------------- enums


class PacketType(enum.IntEnum):
    SETPOINT = 0x01
    SET_PARAM = 0x02
    GET_PARAM = 0x03
    COMMAND = 0x04
    PING = 0x05
    LED = 0x06
    CUE = 0x07              # HGM v1.1: vibrotactile cue on the trigger pad (contact tap, slip buzz, ...)
    TELEMETRY = 0x81
    ACK = 0x82
    LOG = 0x83
    INFO = 0x84
    FINGERTIP = 0x91        # FGS (follower fingertip sensor) telemetry


class Mode(enum.IntEnum):
    OFF = 0
    SPRING = 1
    RENDER = 2
    POSITION = 3


class Param(enum.IntEnum):
    K_THETA = 1
    FINGER_RADIUS = 2
    THETA_OPEN = 3
    THETA_CLOSED = 4
    SEA_ZERO = 5
    KI = 6
    CURRENT_LIMIT_MA = 7
    TELEMETRY_DIV = 8
    SERVO_P_GAIN = 9
    WATCHDOG_MS = 10
    LEVER_DIR = 11
    SERVO_DIR = 12
    PRELOAD_NM = 13


PARAM_DEFAULTS = {
    Param.K_THETA: 3.14,
    Param.FINGER_RADIUS: 0.045,
    Param.THETA_OPEN: 0.0,
    Param.THETA_CLOSED: 0.5236,
    Param.SEA_ZERO: 0.0,
    Param.KI: 0.0,
    Param.CURRENT_LIMIT_MA: 1200.0,
    Param.TELEMETRY_DIV: 2.0,
    Param.SERVO_P_GAIN: 1600.0,
    Param.WATCHDOG_MS: 100.0,
    Param.LEVER_DIR: 1.0,
    Param.SERVO_DIR: 1.0,
    Param.PRELOAD_NM: 0.047,
}


class Command(enum.IntEnum):
    TARE_SEA = 1
    SAVE_PARAMS = 2
    LOAD_DEFAULTS = 3
    REBOOT = 4
    BOOTSEL = 5
    CLEAR_FAULTS = 6
    IDENTIFY = 7


class Status(enum.IntFlag):
    SERVO_OK = 1 << 0
    ENCODER_OK = 1 << 1
    CAL_VALID = 1 << 2
    WATCHDOG = 1 << 3
    SERVO_HW_ERROR = 1 << 4
    OVERFORCE = 1 << 5
    MAGNET_FAULT = 1 << 6
    SERVO_POWER = 1 << 7
    PARAMS_DIRTY = 1 << 8
    LRA_OK = 1 << 9          # HGM v1.1: vibrotactile driver present and calibrated


class Cue(enum.IntEnum):
    TAP = 1        # contact onset: one crisp ~20 ms pulse
    SLIP = 2       # object slipping: short burst while slip persists
    RELEASE = 3    # object released: soft tick
    BUZZ = 4       # generic alert (fault)


class DeviceKind(enum.IntEnum):
    """INFO.hw_rev high nibble identifies the device on the shared protocol."""
    HGM = 0x0
    FGS = 0x1


class FGSStatus(enum.IntFlag):
    ADC_OK = 1 << 0
    CAL_VALID = 1 << 1
    OVERLOAD_A = 1 << 2
    OVERLOAD_B = 1 << 3


class FGSParam(enum.IntEnum):
    SCALE_A = 20      # N per ADC count, jaw A
    SCALE_B = 21
    OFFSET_A = 22     # counts (set by TARE)
    OFFSET_B = 23
    HF_BAND_LO_HZ = 24
    HF_BAND_HI_HZ = 25
    TELEMETRY_HZ = 26


class AckResult(enum.IntEnum):
    OK = 0
    BAD_PARAM = 1
    BAD_VALUE = 2
    FAILED = 3
    UNKNOWN_TYPE = 4


# --------------------------------------------------------------------------- CRC + COBS


def crc16_ccitt_false(data: bytes, crc: int = 0xFFFF) -> int:
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


def cobs_encode(data: bytes) -> bytes:
    """Consistent Overhead Byte Stuffing (Cheshire & Baker 1999). Output contains no 0x00."""
    out = bytearray([0])
    code_idx, code = 0, 1
    for i, b in enumerate(data):
        if b:
            out.append(b)
            code += 1
        if not b or code == 0xFF:
            out[code_idx] = code
            code = 1
            code_idx = len(out)
            if not b or i + 1 < len(data):
                out.append(0)
    if code_idx < len(out):  # a final full block needs no trailing code byte
        out[code_idx] = code
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    out = bytearray()
    idx = 0
    n = len(data)
    while idx < n:
        code = data[idx]
        if code == 0:
            raise ValueError("zero byte inside COBS frame")
        idx += 1
        end = idx + code - 1
        if end > n:
            raise ValueError("truncated COBS frame")
        out += data[idx:end]
        idx = end
        if code < 0xFF and idx < n:
            out.append(0)
    return bytes(out)


# --------------------------------------------------------------------------- packets


@dataclass
class Setpoint:
    mode: Mode = Mode.SPRING
    haptic_n: float = 0.0
    spring_n: float = 1.5
    spring_min_n: float = 1.2
    damping: float = 0.02
    max_n: float = 12.0
    pos_cmd: float = 0.0
    TYPE = PacketType.SETPOINT
    FMT = "<B6f"

    def pack(self) -> bytes:
        return struct.pack(
            self.FMT, int(self.mode), self.haptic_n, self.spring_n, self.spring_min_n,
            self.damping, self.max_n, self.pos_cmd,
        )

    @classmethod
    def unpack(cls, body: bytes) -> "Setpoint":
        m, *f = struct.unpack(cls.FMT, body)
        return cls(Mode(m), *f)


@dataclass
class SetParam:
    param: int
    value: float
    TYPE = PacketType.SET_PARAM
    FMT = "<Bf"

    def pack(self) -> bytes:
        return struct.pack(self.FMT, int(self.param), self.value)

    @classmethod
    def unpack(cls, body: bytes) -> "SetParam":
        return cls(*struct.unpack(cls.FMT, body))


@dataclass
class GetParam:
    param: int
    TYPE = PacketType.GET_PARAM
    FMT = "<B"

    def pack(self) -> bytes:
        return struct.pack(self.FMT, int(self.param))

    @classmethod
    def unpack(cls, body: bytes) -> "GetParam":
        return cls(*struct.unpack(cls.FMT, body))


@dataclass
class CommandPacket:
    cmd: int
    TYPE = PacketType.COMMAND
    FMT = "<B"

    def pack(self) -> bytes:
        return struct.pack(self.FMT, int(self.cmd))

    @classmethod
    def unpack(cls, body: bytes) -> "CommandPacket":
        return cls(*struct.unpack(cls.FMT, body))


@dataclass
class Ping:
    TYPE = PacketType.PING

    def pack(self) -> bytes:
        return b""

    @classmethod
    def unpack(cls, body: bytes) -> "Ping":
        return cls()


@dataclass
class Led:
    r: int
    g: int
    b: int
    pattern: int = 0
    TYPE = PacketType.LED
    FMT = "<BBBB"

    def pack(self) -> bytes:
        return struct.pack(self.FMT, self.r, self.g, self.b, self.pattern)

    @classmethod
    def unpack(cls, body: bytes) -> "Led":
        return cls(*struct.unpack(cls.FMT, body))


@dataclass
class Telemetry:
    t_us: int
    pos: float
    vel: float
    force_op_n: float
    force_cmd_n: float
    lever_rad: float
    servo_rad: float
    servo_ma: int
    buttons: int
    mode: int
    status: int
    loop_us_max: int
    TYPE = PacketType.TELEMETRY
    FMT = "<I6fhBBHH"

    def pack(self) -> bytes:
        return struct.pack(
            self.FMT, self.t_us & 0xFFFFFFFF, self.pos, self.vel, self.force_op_n, self.force_cmd_n,
            self.lever_rad, self.servo_rad, int(self.servo_ma), self.buttons, self.mode, self.status,
            min(int(self.loop_us_max), 0xFFFF),
        )

    @classmethod
    def unpack(cls, body: bytes) -> "Telemetry":
        return cls(*struct.unpack(cls.FMT, body))

    @property
    def button_a(self) -> bool:
        return bool(self.buttons & 1)

    @property
    def button_b(self) -> bool:
        return bool(self.buttons & 2)


@dataclass
class Ack:
    req_type: int
    req_seq: int
    result: int
    value: float
    TYPE = PacketType.ACK
    FMT = "<BHBf"

    def pack(self) -> bytes:
        return struct.pack(self.FMT, self.req_type, self.req_seq, self.result, self.value)

    @classmethod
    def unpack(cls, body: bytes) -> "Ack":
        return cls(*struct.unpack(cls.FMT, body))


@dataclass
class Log:
    level: int
    text: str
    TYPE = PacketType.LOG

    def pack(self) -> bytes:
        return bytes([self.level]) + self.text.encode("utf-8")[: MAX_PAYLOAD - 7]

    @classmethod
    def unpack(cls, body: bytes) -> "Log":
        return cls(body[0], body[1:].decode("utf-8", errors="replace"))


@dataclass
class Info:
    proto: int
    fw_major: int
    fw_minor: int
    fw_patch: int
    hw_rev: int
    rx_errors: int
    serial: str
    TYPE = PacketType.INFO
    FMT = "<HBBBBH16s"

    def pack(self) -> bytes:
        return struct.pack(
            self.FMT, self.proto, self.fw_major, self.fw_minor, self.fw_patch, self.hw_rev,
            self.rx_errors, self.serial.encode("ascii")[:16].ljust(16, b"\0"),
        )

    @classmethod
    def unpack(cls, body: bytes) -> "Info":
        p, a, b, c, hw, rx, s = struct.unpack(cls.FMT, body)
        return cls(p, a, b, c, hw, rx, s.rstrip(b"\0").decode("ascii", errors="replace"))

    @property
    def fw_version(self) -> str:
        return f"{self.fw_major}.{self.fw_minor}.{self.fw_patch}"


@dataclass
class CuePacket:
    waveform: int
    amplitude: int = 200      # 0..255
    duration_ms: int = 25
    TYPE = PacketType.CUE
    FMT = "<BBH"

    def pack(self) -> bytes:
        return struct.pack(self.FMT, int(self.waveform), max(0, min(255, int(self.amplitude))),
                           max(0, min(0xFFFF, int(self.duration_ms))))

    @classmethod
    def unpack(cls, body: bytes) -> "CuePacket":
        return cls(*struct.unpack(cls.FMT, body))


@dataclass
class FingertipTelemetry:
    """FGS → host at telemetry_hz (default 500). Forces are normal (grip) forces on each jaw pad.
    hf_* is the RMS of the strain signal in the slip band (default 60–400 Hz), in newtons."""
    t_us: int
    force_a_n: float
    force_b_n: float
    hf_a_n: float
    hf_b_n: float
    status: int
    loop_us_max: int
    TYPE = PacketType.FINGERTIP
    FMT = "<I4fHH"

    def pack(self) -> bytes:
        return struct.pack(self.FMT, self.t_us & 0xFFFFFFFF, self.force_a_n, self.force_b_n, self.hf_a_n,
                           self.hf_b_n, int(self.status), min(int(self.loop_us_max), 0xFFFF))

    @classmethod
    def unpack(cls, body: bytes) -> "FingertipTelemetry":
        return cls(*struct.unpack(cls.FMT, body))


Packet = Union[Setpoint, SetParam, GetParam, CommandPacket, Ping, Led, Telemetry, Ack, Log, Info]

_BY_TYPE = {
    cls.TYPE: cls
    for cls in (Setpoint, SetParam, GetParam, CommandPacket, Ping, Led, CuePacket, Telemetry, Ack, Log, Info,
                FingertipTelemetry)
}


def encode(packet: Packet, seq: int) -> bytes:
    """Return the full on-wire frame (COBS + trailing 0x00)."""
    body = packet.pack()
    head = struct.pack("<BBH", int(packet.TYPE), 0, seq & 0xFFFF)
    payload = head + body
    payload += struct.pack("<H", crc16_ccitt_false(payload))
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too long ({len(payload)} > {MAX_PAYLOAD})")
    return cobs_encode(payload) + b"\x00"


@dataclass
class Frame:
    type: int
    seq: int
    packet: Optional[Packet]


def decode_payload(payload: bytes) -> Frame:
    if len(payload) < 6:
        raise ValueError("payload too short")
    crc_rx = struct.unpack_from("<H", payload, len(payload) - 2)[0]
    if crc16_ccitt_false(payload[:-2]) != crc_rx:
        raise ValueError("crc mismatch")
    ptype, _flags, seq = struct.unpack_from("<BBH", payload, 0)
    body = payload[4:-2]
    cls = _BY_TYPE.get(ptype)
    pkt = cls.unpack(body) if cls is not None else None
    return Frame(ptype, seq, pkt)


class FrameDecoder:
    """Incremental stream decoder: feed bytes, iterate complete frames."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.errors = 0

    def feed(self, data: bytes) -> Iterator[Frame]:
        self._buf += data
        while True:
            try:
                i = self._buf.index(0)
            except ValueError:
                if len(self._buf) > 4 * MAX_PAYLOAD:  # garbage without delimiter
                    self._buf.clear()
                    self.errors += 1
                return
            raw = bytes(self._buf[:i])
            del self._buf[: i + 1]
            if not raw:
                continue
            try:
                yield decode_payload(cobs_decode(raw))
            except (ValueError, struct.error):
                self.errors += 1
