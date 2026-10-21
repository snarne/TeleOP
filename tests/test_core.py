"""Unit tests for the parts that must be right: protocol, mapping, force estimation,
coupling modes, calibration math, relay framing, recorder round trip."""

from __future__ import annotations

import json
import math
import os
import queue
import time
from pathlib import Path

import numpy as np
import pytest

from station.config import load_config, make_sim
from station.hardware import haptic_protocol as hp
from station.hardware.leader import LeaderCalibration, SimLeader, map_leader, YAM_LIMITS
from station.teleop.gripper import GripForceEstimator, GripperCoupler, HapticSettings

ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------------- protocol


def test_crc_check_value():
    assert hp.crc16_ccitt_false(b"123456789") == 0x29B1


@pytest.mark.parametrize("n", [0, 1, 2, 253, 254, 255, 256, 600])
def test_cobs_roundtrip(n):
    rng = np.random.default_rng(n)
    for _ in range(30):
        data = bytes(rng.integers(0, 256, n, dtype=np.uint8))
        data = bytes(b if rng.random() > 0.2 else 0 for b in data)
        enc = hp.cobs_encode(data)
        assert 0 not in enc
        assert hp.cobs_decode(enc) == data


def test_frame_roundtrip_and_resync():
    pkts = [hp.Setpoint(hp.Mode.RENDER, 3.5, 1.5, 0.3, 0.02, 12.0, 0.0),
            hp.Telemetry(123, 0.4, -0.1, 2.2, 3.3, 0.2, 0.1, 400, 3, 2, 7, 220),
            hp.Ack(1, 77, 0, 1.25), hp.Info(1, 1, 2, 3, 0, 0, "E6614103E7"), hp.Log(2, "watchdog")]
    stream = b"\x13\x37garbage\x00" + b"".join(hp.encode(p, i) for i, p in enumerate(pkts))
    corrupt = bytearray(hp.encode(pkts[1], 99))
    corrupt[5] ^= 0xFF
    stream += bytes(corrupt) + hp.encode(pkts[0], 100)
    dec = hp.FrameDecoder()
    frames = []
    for i in range(0, len(stream), 7):  # arbitrary chunking, like a USB read
        frames += list(dec.feed(stream[i:i + 7]))
    types = [type(f.packet).__name__ for f in frames]
    assert types == ["Setpoint", "Telemetry", "Ack", "Info", "Log", "Setpoint"]
    assert dec.errors == 2  # leading garbage + corrupted telemetry
    tel = frames[1].packet
    assert tel.button_a and tel.button_b and tel.servo_ma == 400
    assert frames[3].packet.serial == "E6614103E7"


def test_payload_sizes_fit():
    assert len(hp.Setpoint().pack()) == 25
    assert len(hp.Telemetry(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0).pack()) == 36
    assert len(hp.encode(hp.Telemetry(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), 0)) < 64


# ----------------------------------------------------------------------------- leader mapping


def test_leader_mapping_inverts_sim_calibration():
    lead = SimLeader("left")
    cal = LeaderCalibration(SimLeader.FAKE_OFFSETS.copy(), SimLeader.FAKE_SIGNS.copy(), True)
    for q in [np.zeros(6), np.array([0.3, 1.5, 2.9, -1.2, 0.7, 1.9]), np.array([-2.4, 3.5, 0.1, 1.4, -1.4, -2.0])]:
        lead.manual_pose = q
        raw = lead.read().raw[:6]
        assert np.allclose(map_leader(raw, cal), q, atol=1e-9)


def test_leader_mapping_is_continuous_across_wrap():
    cal = LeaderCalibration(np.zeros(6), np.ones(6), True)
    prev = np.array([3.10, 1.0, 1.0, 0, 0, 0])
    raw = np.array([-3.10, 1.0, 1.0, 0, 0, 0])  # encoder wrapped past ±π
    q = map_leader(raw, cal, prev)
    assert q[0] == pytest.approx(2 * math.pi - 3.10)


# ----------------------------------------------------------------------------- grip force


def test_grip_force_estimator_contact_hysteresis():
    est = GripForceEstimator(gain_n_per_nm=68.4, tau_friction_nm=0.12, filter_hz=1000)
    t = 0.0
    f, c = est.update(t, 0.05, 0.0)
    assert not c
    for _ in range(50):
        t += 0.005
        f, c = est.update(t, -0.3, 0.0)   # 0.3 N·m held still → ~20 N
    assert c and 15 < f < 25
    for _ in range(50):
        t += 0.005
        f, c = est.update(t, 0.12, 1.0)   # moving: friction only
    assert not c and f < 1.0


def test_position_force_coupling_renders_scaled_force():
    cp = GripperCoupler(HapticSettings(feedback_mode="linear", feedback_gain=0.25, max_render_n=12))
    out = cp.step(0.0, trigger_pos=0.5, trigger_force=3.0, grip_x=0.5, grip_force=20.0, contact=False, senses_force=True)
    assert out.gripper_cmd == pytest.approx(0.5)  # free space: position follows the trigger
    assert out.trigger_mode == int(hp.Mode.RENDER) and out.haptic_n == pytest.approx(5.0)
    out = cp.step(0.0, 0.9, 3.0, 0.5, 200.0, False, True)
    assert out.haptic_n == 12.0  # capped


def test_contact_relative_force_law():
    """Past contact, squeeze depth commands grip force (§5.3); opening the trigger past the jaws
    returns to position following; contact sensed with the trigger open never latches."""
    s = HapticSettings(feedback_mode="linear", feedback_gain=0.25, max_grip_n=40.0)
    cp = GripperCoupler(s)
    # contact sensed while the trigger asks for a wide-open gripper → stay in position mode
    out = cp.step(0.0, 0.10, float("nan"), 0.42, 5.0, contact=True, senses_force=False)
    assert not cp.contact_active and out.gripper_cmd == pytest.approx(0.9)
    # operator closes onto the object: trigger maps to 0.55, jaws stopped at 0.56
    t = 0.0
    cp.step(t, 0.45, float("nan"), 0.56, 3.0, contact=True, senses_force=False)
    assert cp.contact_active and cp.regulating
    for _ in range(400):  # contact point = jaw position 0.56 ↔ p_c 0.44; p 0.72 → depth 0.5 → 20 N
        t += 0.005
        out = cp.step(t, 0.72, float("nan"), 0.56, 20.0, True, False)
    assert out.target_force_n == pytest.approx(20.0, abs=0.2)
    assert out.gripper_cmd == pytest.approx(0.56 - 20.0 / cp.k_x)
    assert out.haptic_n == pytest.approx(5.0)
    out = cp.step(t, 0.38, float("nan"), 0.56, 20.0, True, False)  # maps to 0.62 > 0.56 + 0.04
    assert not cp.contact_active
    # object pulled out while squeezing: contact lost for > 200 ms → position following again
    cp.step(t, 0.45, float("nan"), 0.56, 3.0, contact=True, senses_force=False)
    assert cp.contact_active
    for _ in range(50):
        t += 0.005
        cp.step(t, 0.8, float("nan"), 0.50, 0.0, False, False)
    assert not cp.contact_active
    assert out.gripper_cmd == pytest.approx(cp.trigger_to_gripper(0.38))


def test_force_command_mode_enters_and_releases():
    cp = GripperCoupler(HapticSettings(force_input=True, input_gain=4.0, max_grip_n=30, release_n=0.8))
    t = 0.0
    out = cp.step(t, 0.4, 2.0, 0.42, 3.0, contact=True, senses_force=True)
    assert cp.force_mode_active and out.trigger_mode == int(hp.Mode.POSITION) and out.pos_cmd == pytest.approx(0.4)
    for _ in range(200):  # target force slews up to input_gain * F_op = 20 N
        t += 0.005
        out = cp.step(t, 0.4, 5.0, 0.42, 18.0, True, True)
    assert out.target_force_n == pytest.approx(20.0, abs=0.5)
    assert out.gripper_cmd < 0.42  # squeezing past the measured position
    for _ in range(8):  # relax → back to position mode after 150 ms
        t += 0.025
        out = cp.step(t, 0.4, 0.2, 0.42, 18.0, True, True)
    assert not cp.force_mode_active and out.trigger_mode == int(hp.Mode.RENDER)


def test_force_mode_needs_force_sensor():
    cp = GripperCoupler(HapticSettings(force_input=True))
    cp.step(0.0, 0.4, float("nan"), 0.4, 10.0, True, senses_force=False)
    assert not cp.force_mode_active


# ----------------------------------------------------------------------------- sim haptic module


def test_sim_hgm_renders_force_closed_loop():
    from station.hardware.trigger import SimHGM

    m = SimHGM("left")
    m.manual_squeeze = 6.0
    m.connect()
    try:
        m.send_setpoint(hp.Setpoint(mode=hp.Mode.RENDER, haptic_n=5.0, spring_n=0.0, spring_min_n=0.0, damping=0.0, max_n=12))
        t_end = time.time() + 0.6
        while time.time() < t_end:
            m.send_setpoint(hp.Setpoint(mode=hp.Mode.RENDER, haptic_n=5.0, spring_n=0.0, spring_min_n=0.0, damping=0.0, max_n=12))
            time.sleep(0.01)
        r = m.latest()
        # the finger pushes 6 N against a 5 N wall: the force sensor reads ≈ rendered force while the lever closes
        assert abs(r.force_op - r.force_cmd) < 1.0
        assert r.force_cmd == pytest.approx(5.0, abs=0.3)
        # watchdog: stop sending → falls back to SPRING and flags it
        time.sleep(0.3)
        assert m.latest().mode == int(hp.Mode.SPRING)
        assert m.latest().status & int(hp.Status.WATCHDOG)
    finally:
        m.close()


# ----------------------------------------------------------------------------- calibration math


class _FakeCtx:
    sim = False

    def __init__(self, cfg, tmp):
        self.cfg, self.tmp = cfg, tmp
        self.raw = np.zeros(6)
        self.q = np.zeros(6)

    def arm_request(self, side, cmd, timeout=5.0, **kw):
        if cmd == "read_leader_raw":
            return {"raw": list(self.raw), "std": [0.0] * 6}
        if cmd == "follower_read":
            return {"q": list(self.q)}
        return {}

    def arm_state(self, side):
        return {"follower_ok": True, "leader_raw": list(self.raw) + [0.0], "follower_q": list(self.q)}

    def arm_connected(self, side):
        return True

    def cal_file(self, item):
        return self.tmp / f"{item}.yaml"

    def scratch_dir(self, item):
        return self.tmp

    def config(self):
        return self.cfg

    def camera_capture(self, name, path):
        return path


def test_leader_procedure_recovers_offsets_and_signs(tmp_path):
    from station.calibration.procedures import LeaderProcedure

    cfg = load_config(ROOT / "config" / "station.sim.yaml")
    ctx = _FakeCtx(cfg, tmp_path)
    true_off = np.array([0.4, -1.1, 2.0, 0.3, -0.7, 1.2])
    true_sign = np.array([1, -1, 1, -1, 1, 1])
    proc = LeaderProcedure(ctx, "left")
    proc.start()

    def pose(q):
        ctx.q = np.asarray(q, float)
        ctx.raw = (true_sign * ctx.q + true_off + math.pi) % (2 * math.pi) - math.pi

    assert proc.run_step("check")["steps"][0]["status"] == "ok"
    pose([0.1, 0.8, 1.2, -0.2, 0.3, 0.5]); proc.run_step("pose_a")
    pose([-0.6, 1.7, 0.4, 0.4, -0.5, -0.4]); rs = proc.run_step("pose_b")
    assert rs["can_commit"], rs
    pose([0.7, 1.3, 1.5, 0.1, 0.0, 1.1]); rs = proc.run_step("verify")
    assert rs["steps"][3]["status"] == "ok", rs["steps"][3]
    r = proc.result
    assert r["signs"] == true_sign.tolist()
    assert np.allclose(np.angle(np.exp(1j * (np.array(r["offsets"]) - true_off))), 0, atol=1e-6)
    assert r["flipped_vs_config"] == [2, 4]
    out = proc.commit("tester")
    assert Path(out["path"]).exists()


def test_leader_procedure_rejects_small_motion(tmp_path):
    from station.calibration.procedures import LeaderProcedure

    cfg = load_config(ROOT / "config" / "station.sim.yaml")
    ctx = _FakeCtx(cfg, tmp_path)
    proc = LeaderProcedure(ctx, "left")
    proc.start()
    ctx.q = np.zeros(6); ctx.raw = np.zeros(6); proc.run_step("pose_a")
    ctx.q = np.array([0.5, 0.5, 0.5, 0.5, 0.5, 0.05]); ctx.raw = ctx.q.copy()
    rs = proc.run_step("pose_b")
    assert rs["steps"][2]["status"] == "error" and "6" in rs["steps"][2]["message"]


# ----------------------------------------------------------------------------- relays


def test_lcus_frame():
    from station.hardware.power import LcusRelay

    class FakeSerial:
        def __init__(self):
            self.out = b""

        def write(self, b):
            self.out += b

    r = LcusRelay.__new__(LcusRelay)
    r.ser, r.state = FakeSerial(), {}
    r.set(0, True)
    r.set(1, False)
    assert r.ser.out == bytes([0xA0, 1, 1, 0xA2, 0xA0, 2, 0, 0xA2])


# ----------------------------------------------------------------------------- config + scripts


def test_configs_load_and_sim_switch():
    hw = load_config(ROOT / "config" / "station.yaml")
    assert hw.enabled_arms() == ["left", "right"] and len(hw.cameras) == 3
    make_sim(hw)
    assert all(a.follower.backend == "sim" and a.leader.backend == "sim" for a in hw.arms.values())


@pytest.mark.parametrize("pid", ["leader_left", "trigger_right", "gripper_left", "camera_overhead", "fingertips_left"])
def test_generated_scripts_compile(tmp_path, pid):
    from station.calibration.generator import generate_script

    cfg = load_config(ROOT / "config" / "station.yaml")
    r = generate_script(cfg, pid, tmp_path)
    compile(r["content"], r["filename"], "exec")
    assert "CHANGE_ME" in r["content"] or pid.startswith(("gripper", "trigger", "fingertips"))


# ----------------------------------------------------------------------------- recorder


def test_recorder_roundtrip(tmp_path):
    from station.recording.raw_episode import load_episode
    from station.recording.recorder import Recorder

    q: "queue.Queue" = queue.Queue()
    rec = Recorder(tmp_path, q)
    a = rec.start({"operator": {"id": 1, "name": "A"}})
    t0 = time.monotonic()
    for i in range(50):
        q.put(("left", {"t": t0 + i * 0.005, "leader_q": [0.1] * 6, "q_cmd": [0.1] * 7, "follower_q": [0.1 * i] * 6,
                        "follower_dq": [0.0] * 6, "follower_tau": [0.0] * 6, "gripper": 0.5, "gripper_vel": 0.0,
                        "gripper_tau": float("nan"), "trigger_pos": 0.2, "trigger_force": None, "trigger_render": 1.0,
                        "grip_force": 3.0, "contact": False, "target_force": None, "force_mode": False,
                        "buttons": 0, "mode": "teleop"}))
    time.sleep(0.3)
    res = rec.finish(True, tmp_path / "out" / "ep1")
    ep = load_episode(res["path"])
    arm = ep.arms["left"]
    assert len(arm.t) == 50
    assert arm.at(np.array([t0 + 0.0025]), "follower_q")[0, 0] == pytest.approx(0.05)
    assert np.isnan(arm.data["trigger_force"]).all()
    info = json.loads((res["path"] / "episode.json").read_text())
    assert info["operator"]["name"] == "A" and info["samples"]["left"] == 50
    assert not (tmp_path / "recordings" / ".staging" / a["id"]).exists()


def test_recorder_abort_deletes(tmp_path):
    from station.recording.recorder import Recorder

    rec = Recorder(tmp_path, queue.Queue())
    a = rec.start({})
    staging = a["staging"]
    assert staging.exists()
    rec.finish(False)
    assert not staging.exists()


def test_export_action_carries_operator_grip_force(tmp_path):
    """The operator's chosen grip force is part of the training action, and episodes get a grip summary."""
    from station.recording.lerobot_export import build_features, episode_arrays
    from station.recording.raw_episode import grip_stats, load_episode
    from station.recording.recorder import Recorder

    q: "queue.Queue" = queue.Queue()
    rec = Recorder(tmp_path, q)
    rec.start({})
    t0 = time.monotonic()
    for i in range(200):
        in_contact = 80 <= i < 160
        q.put(("left", {"t": t0 + i * 0.005, "leader_q": [0.0] * 6, "q_cmd": [0.0] * 6 + [0.4], "follower_q": [0.0] * 6,
                        "follower_dq": [0.0] * 6, "follower_tau": [0.0] * 6, "gripper": 0.4, "gripper_vel": 0.0,
                        "gripper_tau": 0.3 if in_contact else 0.0, "trigger_pos": 0.8 if in_contact else 0.2,
                        "trigger_force": 6.0 if in_contact else 1.0, "trigger_render": 5.0, "grip_force": 21.0 if in_contact else 0.0,
                        "contact": in_contact, "target_force": 22.0 if in_contact else None, "force_mode": False,
                        "buttons": 0, "mode": "teleop"}))
    time.sleep(0.3)
    ep = load_episode(rec.finish(True, tmp_path / "ep")["path"])
    feats = build_features(["left"], {})
    assert feats["action"]["shape"] == (8,) and feats["action"]["names"][-1] == "left_grip_force_cmd_n"
    grid = ep.arms["left"].t[0] + np.arange(0, 0.99, 1 / 30)
    act = episode_arrays(ep, ["left"], grid)["action"]
    assert act.shape == (len(grid), 8)
    assert act[:, 7].max() == pytest.approx(22.0) and act[0, 7] == 0.0  # 0 in free space, operator's force in contact
    st = grip_stats(ep)["left"]
    assert st["peak_grip_n"] == pytest.approx(21.0) and st["contact_s"] == pytest.approx(0.4, abs=0.02)
    assert st["peak_grip_cmd_n"] == pytest.approx(22.0) and st["peak_operator_force_n"] == pytest.approx(6.0)


def test_force_curve_gives_finer_light_grips():
    lin = GripperCoupler(HapticSettings(max_grip_n=50.0, force_curve=1.0))
    cur = GripperCoupler(HapticSettings(max_grip_n=50.0, force_curve=2.0))
    for cp in (lin, cur):
        cp.step(0.0, 0.5, float("nan"), 0.5, 3.0, contact=True, senses_force=False)
        t = 0.0
        for _ in range(400):
            t += 0.005
            out = cp.step(t, 0.75, float("nan"), 0.5, 10.0, True, False)
        cp.result = out.target_force_n
        for _ in range(400):
            t += 0.005
            out = cp.step(t, 1.0, float("nan"), 0.5, 10.0, True, False)
        cp.full = out.target_force_n
    assert lin.result == pytest.approx(25.0, abs=0.5) and cur.result == pytest.approx(12.5, abs=0.5)
    assert lin.full == pytest.approx(50.0, abs=0.5) and cur.full == pytest.approx(50.0, abs=0.5)  # full squeeze = full force


def test_perceptual_feedback_spans_full_grip_range():
    """Light holds are clearly felt, heavier grips feel heavier, and full force maps to max feel."""
    from station.teleop.gripper import felt_force

    s = HapticSettings(max_render_n=12.0, max_grip_n=50.0, feedback_exponent=0.6)
    felt = [felt_force(s, f) for f in (0.0, 2.0, 5.0, 10.0, 25.0, 50.0, 80.0)]
    assert felt[0] == 0.0 and felt[-2] == pytest.approx(12.0) and felt[-1] == pytest.approx(12.0)
    assert all(b > a for a, b in zip(felt[:-1], felt[1:-1]))  # monotonic up to full force
    assert felt[1] > 1.5  # a 2 N hold is felt (linear 0.25 would give 0.5 N)
    lin = HapticSettings(feedback_mode="linear", feedback_gain=0.25, max_render_n=12.0)
    assert felt_force(lin, 2.0) == pytest.approx(0.5)


def test_touch_events_tap_slip_release():
    from station.hardware.haptic_protocol import Cue
    from station.teleop.gripper import TouchEvents

    s = HapticSettings()
    te = TouchEvents()
    assert te.update(0.0, False, 0.0, 0.0, True, False, s)[0] is None
    assert te.update(0.005, True, 3.0, 0.01, True, False, s)[0] == Cue.TAP
    assert te.update(0.010, True, 3.0, 0.01, True, False, s)[0] is None
    cue, _ = te.update(0.10, True, 3.0, 0.5, True, False, s)  # slip-band energy at the pads
    assert cue == Cue.SLIP and te.slip
    assert te.update(0.12, True, 3.0, 0.5, True, False, s)[0] is None  # rate-limited
    assert te.update(0.30, False, 0.0, 0.0, True, False, s)[0] == Cue.RELEASE
    # without fingertip sensors: a sudden grip-force drop while not releasing = slip
    te2 = TouchEvents()
    te2.update(0.0, True, 10.0, 0.0, False, False, s)
    for i in range(1, 6):
        te2.update(i * 0.005, True, 10.0, 0.0, False, False, s)
    cue, _ = te2.update(0.035, True, 5.0, 0.0, False, False, s)
    assert te2.slip and cue == Cue.SLIP
