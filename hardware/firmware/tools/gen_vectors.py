#!/usr/bin/env python3
"""Generate shared protocol test vectors from the Python reference codec.

    python hardware/firmware/tools/gen_vectors.py   → tests/vectors/haptic_protocol.json

The C++ native tests (hardware/firmware/haptic_grip/test/native) and the pytest suite
(tests/test_haptic_vectors.py) both check their codec against this file, so the station
and the firmware cannot drift apart silently.
"""

import json
import os
import random
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)

from station.hardware import haptic_protocol as hp  # noqa: E402


def hexs(b: bytes) -> str:
    return b.hex()


def cobs_reference(data: bytes) -> bytes:
    """Canonical COBS (Cheshire & Baker 1999), written independently of the station codec
    so that the COBS vectors also check that codec's edge cases."""
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


def main() -> None:
    rnd = random.Random(1234)
    vec = {"proto": hp.PROTO_VERSION, "crc": [], "cobs": [], "packets": []}

    for s in [b"", b"123456789", b"\x00", b"\xff" * 8, bytes(range(64))]:
        vec["crc"].append({"data": hexs(s), "crc": hp.crc16_ccitt_false(s)})

    cobs_inputs = [b"", b"\x00", b"\x00\x00", b"\x11\x22\x00\x33", b"\x11\x00", bytes(range(1, 255)),
                   bytes(range(1, 256)), bytes([0]) + bytes(range(1, 255)), bytes(range(1, 255)) + b"\x00"]
    for _ in range(6):
        n = rnd.randint(1, 80)
        cobs_inputs.append(bytes(rnd.choice([0, rnd.randint(1, 255)]) for _ in range(n)))
    for raw in cobs_inputs:
        vec["cobs"].append({"raw": hexs(raw), "encoded": hexs(cobs_reference(raw))})

    def add(name, pkt, seq, fields):
        frame = hp.encode(pkt, seq)
        vec["packets"].append({"name": name, "type": int(pkt.TYPE), "seq": seq, "fields": fields,
                               "body": hexs(pkt.pack()), "frame": hexs(frame)})

    add("setpoint_default", hp.Setpoint(), 0, {"mode": 1, "haptic_n": 0.0, "spring_n": 1.5, "spring_min_n": 1.2,
                                               "damping": 0.02, "max_n": 12.0, "pos_cmd": 0.0})
    sp = hp.Setpoint(hp.Mode.RENDER, 7.25, 1.5, 1.2, 0.02, 12.0, 0.0)
    add("setpoint_render", sp, 513, {"mode": 2, "haptic_n": 7.25, "spring_n": 1.5, "spring_min_n": 1.2,
                                     "damping": 0.02, "max_n": 12.0, "pos_cmd": 0.0})
    add("setpoint_position", hp.Setpoint(hp.Mode.POSITION, 0, 0, 0, 0, 5.0, 0.5), 65535,
        {"mode": 3, "haptic_n": 0.0, "spring_n": 0.0, "spring_min_n": 0.0, "damping": 0.0, "max_n": 5.0, "pos_cmd": 0.5})
    add("set_param_k_theta", hp.SetParam(1, 3.144), 7, {"param": 1, "value": 3.144})
    add("set_param_preload", hp.SetParam(13, 0.0472), 8, {"param": 13, "value": 0.0472})
    add("command_tare", hp.CommandPacket(1), 9, {"cmd": 1})
    add("led_cyan_pulse", hp.Led(0, 160, 255, 2), 10, {"r": 0, "g": 160, "b": 255, "pattern": 2})
    add("ping", hp.Ping(), 11, {})
    tl = hp.Telemetry(123456789, 0.4375, -1.5, 6.25, 6.5, 0.2291, 0.1102, -812, 3, 2, 0x0087, 412)
    add("telemetry", tl, 40000, {"t_us": 123456789, "pos": 0.4375, "vel": -1.5, "force_op_n": 6.25,
                                 "force_cmd_n": 6.5, "lever_rad": 0.2291, "servo_rad": 0.1102, "servo_ma": -812,
                                 "buttons": 3, "mode": 2, "status": 0x0087, "loop_us_max": 412})
    add("ack", hp.Ack(2, 7, 0, 3.144), 41, {"req_type": 2, "req_seq": 7, "result": 0, "value": 3.144})
    add("info", hp.Info(1, 1, 0, 0, 1, 3, "E6614103E7452D2F"), 1,
        {"proto": 1, "fw_major": 1, "fw_minor": 0, "fw_patch": 0, "hw_rev": 1, "rx_errors": 3,
         "serial": "E6614103E7452D2F"})

    # ---- v1.1: cues (HGM) and fingertip telemetry (FGS)
    for name, cue, seq in (("cue_tap", hp.CuePacket(hp.Cue.TAP, 220, 20), 12),
                           ("cue_slip", hp.CuePacket(hp.Cue.SLIP, 180, 60), 13),
                           ("cue_release", hp.CuePacket(hp.Cue.RELEASE, 120, 12), 14),
                           ("cue_buzz_default_duration", hp.CuePacket(hp.Cue.BUZZ, 255, 0), 15)):
        add(name, cue, seq, {"waveform": int(cue.waveform), "amplitude": cue.amplitude,
                             "duration_ms": cue.duration_ms})
    st = int(hp.Status.SERVO_OK | hp.Status.ENCODER_OK | hp.Status.CAL_VALID | hp.Status.SERVO_POWER
             | hp.Status.LRA_OK)
    tl2 = hp.Telemetry(424242, 0.75, 0.25, 9.5, 9.75, 0.3927, 0.2412, 1105, 0, 2, st, 377)
    add("telemetry_lra_ok", tl2, 7, {"t_us": 424242, "pos": 0.75, "vel": 0.25, "force_op_n": 9.5,
                                     "force_cmd_n": 9.75, "lever_rad": 0.3927, "servo_rad": 0.2412, "servo_ma": 1105,
                                     "buttons": 0, "mode": 2, "status": st, "loop_us_max": 377})
    fst = int(hp.FGSStatus.ADC_OK | hp.FGSStatus.CAL_VALID | hp.FGSStatus.OVERLOAD_B)
    ft = hp.FingertipTelemetry(987654321, 12.5, -0.375, 0.0625, 1.75, fst, 128)
    add("fingertip", ft, 300, {"t_us": 987654321, "force_a_n": 12.5, "force_b_n": -0.375, "hf_a_n": 0.0625,
                               "hf_b_n": 1.75, "status": fst, "loop_us_max": 128})
    add("fingertip_zero", hp.FingertipTelemetry(0, 0.0, 0.0, 0.0, 0.0, 0, 0), 0,
        {"t_us": 0, "force_a_n": 0.0, "force_b_n": 0.0, "hf_a_n": 0.0, "hf_b_n": 0.0, "status": 0, "loop_us_max": 0})
    add("info_fgs", hp.Info(1, 1, 0, 0, (int(hp.DeviceKind.FGS) << 4) | 1, 0, "E66138935F2B6A27"), 2,
        {"proto": 1, "fw_major": 1, "fw_minor": 0, "fw_patch": 0, "hw_rev": 0x11, "rx_errors": 0,
         "serial": "E66138935F2B6A27"})
    add("set_param_fgs_scale_a", hp.SetParam(int(hp.FGSParam.SCALE_A), 2.4e-6), 3,
        {"param": int(hp.FGSParam.SCALE_A), "value": 2.4e-6})
    add("set_param_fgs_band_hi", hp.SetParam(int(hp.FGSParam.HF_BAND_HI_HZ), 400.0), 4,
        {"param": int(hp.FGSParam.HF_BAND_HI_HZ), "value": 400.0})
    add("command_fgs_tare", hp.CommandPacket(1), 5, {"cmd": 1})

    out = os.path.join(ROOT, "tests", "vectors", "haptic_protocol.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(vec, f, indent=1)
    print(f"wrote {out}: {len(vec['packets'])} packets, {len(vec['cobs'])} cobs, {len(vec['crc'])} crc")


if __name__ == "__main__":
    main()
