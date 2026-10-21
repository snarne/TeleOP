"""The Python haptic codec must match the shared vectors that the firmware is also tested against."""

import json
import math
import os

import pytest

from station.hardware import haptic_protocol as hp

VEC = json.load(open(os.path.join(os.path.dirname(__file__), "vectors", "haptic_protocol.json")))

BUILDERS = {
    hp.PacketType.SETPOINT: lambda f: hp.Setpoint(hp.Mode(f["mode"]), f["haptic_n"], f["spring_n"], f["spring_min_n"],
                                                  f["damping"], f["max_n"], f["pos_cmd"]),
    hp.PacketType.SET_PARAM: lambda f: hp.SetParam(f["param"], f["value"]),
    hp.PacketType.COMMAND: lambda f: hp.CommandPacket(f["cmd"]),
    hp.PacketType.PING: lambda f: hp.Ping(),
    hp.PacketType.LED: lambda f: hp.Led(f["r"], f["g"], f["b"], f["pattern"]),
    hp.PacketType.TELEMETRY: lambda f: hp.Telemetry(**f),
    hp.PacketType.ACK: lambda f: hp.Ack(**f),
    hp.PacketType.INFO: lambda f: hp.Info(**f),
    hp.PacketType.CUE: lambda f: hp.CuePacket(**f),
    hp.PacketType.FINGERTIP: lambda f: hp.FingertipTelemetry(**f),
}


def test_protocol_version():
    assert VEC["proto"] == hp.PROTO_VERSION


@pytest.mark.parametrize("case", VEC["crc"], ids=lambda c: f"len{len(c['data']) // 2}")
def test_crc(case):
    assert hp.crc16_ccitt_false(bytes.fromhex(case["data"])) == case["crc"]


def _cobs_id(c):
    return f"raw{len(c['raw']) // 2}"


@pytest.mark.parametrize("case", VEC["cobs"], ids=_cobs_id)
def test_cobs(case):
    raw, enc = bytes.fromhex(case["raw"]), bytes.fromhex(case["encoded"])
    assert hp.cobs_decode(enc) == raw
    assert hp.cobs_encode(raw) == enc


@pytest.mark.parametrize("case", VEC["packets"], ids=lambda c: c["name"])
def test_packet(case):
    ptype = hp.PacketType(case["type"])
    pkt = BUILDERS[ptype](case["fields"])
    assert pkt.pack().hex() == case["body"]
    frame = hp.encode(pkt, case["seq"])
    assert frame.hex() == case["frame"]
    # round trip through the stream decoder with junk in front
    dec = hp.FrameDecoder()
    frames = list(dec.feed(b"\x13\x37\x00" + bytes.fromhex(case["frame"])))
    assert len(frames) == 1
    fr = frames[0]
    assert fr.type == case["type"] and fr.seq == case["seq"]
    for k, v in case["fields"].items():
        got = getattr(fr.packet, k)
        if isinstance(v, float):
            assert math.isclose(got, v, rel_tol=1e-6, abs_tol=1e-6), k
        else:
            assert got == v, k


def test_v11_packets_present():
    names = {c["name"] for c in VEC["packets"]}
    assert {"cue_tap", "cue_slip", "cue_release", "cue_buzz_default_duration", "fingertip", "info_fgs",
            "telemetry_lra_ok"} <= names


def test_fgs_device_kind_in_info():
    case = next(c for c in VEC["packets"] if c["name"] == "info_fgs")
    assert case["fields"]["hw_rev"] >> 4 == hp.DeviceKind.FGS


def test_lra_ok_bit():
    case = next(c for c in VEC["packets"] if c["name"] == "telemetry_lra_ok")
    assert case["fields"]["status"] & hp.Status.LRA_OK
