"""In-process integration test: the full API over a simulated station (thread workers)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from station.api import create_app
from station.config import load_config
from station.orchestrator import Orchestrator

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    cfg = load_config(ROOT / "config" / "station.sim.yaml")
    cfg.station.data_root = str(tmp_path_factory.mktemp("station"))
    cfg.runtime.workers = "thread"
    orch = Orchestrator(cfg)
    orch.start()
    with TestClient(create_app(orch)) as c:
        yield c
    orch.shutdown()


def wait(c, phase, timeout=30):
    t = time.time() + timeout
    while time.time() < t:
        with c.websocket_connect("/ws/state") as ws:
            s = ws.receive_json()
        if s["phase"] == phase:
            return s
        assert s["phase"] != "fault", s["phase_detail"]
        time.sleep(0.2)
    raise AssertionError(f"phase {phase} not reached: {s['phase']}")


def test_operator_flow(client):
    c = client
    assert c.get("/api/station").json()["sim"]
    users, depts, tasks = c.get("/api/users").json(), c.get("/api/departments").json(), c.get("/api/tasks").json()
    assert users and depts and tasks  # seeded on first run
    c.put("/api/session", json={"operator_id": users[0]["id"], "department_id": depts[0]["id"], "task_id": tasks[0]["id"]})
    r = c.post("/api/recording/start")
    assert r.status_code == 409 and r.json()["hint"]

    c.post("/api/control/start_arms", json={})
    s = wait(c, "ready")
    assert {x["status"] for x in s["startup"]["steps"]} <= {"ok", "warn", "skipped"}

    assert c.post("/api/control/teleop", json={"enabled": True}).status_code == 200
    r = c.post("/api/recording/start")  # follower still easing onto the (uncalibrated) leader
    assert r.status_code == 409 and "easing" in r.json()["detail"]
    t_end = time.time() + 12
    while time.time() < t_end:
        with c.websocket_connect("/ws/state") as ws:
            s = ws.receive_json()
        if all(a["state"] == "teleop" for a in s["arms"].values()):
            break
        time.sleep(0.3)
    assert all(a["state"] == "teleop" for a in s["arms"].values())

    eid = c.post("/api/recording/start").json()["episode_id"]
    time.sleep(2.5)
    ep = c.post("/api/recording/save", json={"success": True, "notes": "ci"}).json()
    assert ep["id"] == eid and ep["frames"] > 30 and Path(ep["path"]).is_dir()
    assert (Path(ep["path"]) / "telemetry.mcap").stat().st_size > 1000
    for cam in ("left_wrist", "overhead", "right_wrist"):
        assert (Path(ep["path"]) / "cameras" / f"{cam}.mp4").exists()

    lst = c.get("/api/episodes").json()
    assert lst["total"] >= 1
    tel = c.get(f"/api/episodes/{eid}/telemetry").json()
    assert len(tel["t"]) > 50

    with c.websocket_connect("/ws/logs") as ws:
        line = ws.receive_json()
        assert {"ts", "level", "source", "message"} <= set(line)

    c.post("/api/control/teleop", json={"enabled": False})
    c.post("/api/control/stop_arms")
    wait(c, "idle")


def _state(c):
    with c.websocket_connect("/ws/state") as ws:
        return ws.receive_json()


def _engage(c):
    c.post("/api/control/start_arms", json={})
    wait(c, "ready")
    assert c.post("/api/control/teleop", json={"enabled": True}).status_code == 200
    t_end = time.time() + 15
    while time.time() < t_end:
        if all(a["state"] == "teleop" for a in _state(c)["arms"].values()):
            return
        time.sleep(0.3)
    raise AssertionError("arms did not reach teleop")


def test_review_regressions(client):
    """Regressions for the safety review: handle buttons don't deadlock the event pump, a fault
    on one arm stops every arm and saves the take quickly, and nothing re-faults after a clear."""
    c = client
    orch = c.app.state.orch
    _engage(c)

    # handle button bound to teleop_toggle (default right_b) must act within ~1 s
    orch.evt_q.put({"type": "button", "side": "right", "button": "b"})
    t_end = time.time() + 3
    while time.time() < t_end and _state(c)["phase"] != "ready":
        time.sleep(0.1)
    assert _state(c)["phase"] == "ready"
    assert all(a["state"] == "connected" for a in _state(c)["arms"].values())

    # re-engage, record, then fault ONE arm: both arms must stop and the take must be saved fast
    assert c.post("/api/control/teleop", json={"enabled": True}).status_code == 200
    t_end = time.time() + 15
    while time.time() < t_end and not all(a["state"] == "teleop" for a in _state(c)["arms"].values()):
        time.sleep(0.3)
    eid = c.post("/api/recording/start").json()["episode_id"]
    time.sleep(1.0)
    t0 = time.time()
    orch.arm_cmd["left"].put({"cmd": "estop", "reason": "injected test fault"})
    while time.time() - t0 < 5 and _state(c)["recording"]["active"]:
        time.sleep(0.1)
    s = _state(c)
    assert time.time() - t0 < 5, "fault took too long to stop the recording"
    assert s["phase"] == "fault"
    assert all(a["state"] == "fault" for a in s["arms"].values()), {k: a["state"] for k, a in s["arms"].items()}
    ep = c.get(f"/api/episodes/{eid}").json()
    assert "fault" in ep["tags"] and ep["cameras"], ep

    # clear → ready, and stays ready (no late fault events)
    assert c.post("/api/control/clear_fault").status_code == 200
    time.sleep(1.0)
    assert _state(c)["phase"] == "ready"

    # teleop refused while a calibration is open
    assert c.post("/api/calibration/procedures/gripper_left/start").status_code == 200
    r = c.post("/api/control/teleop", json={"enabled": True})
    assert r.status_code == 409 and "calibration" in r.json()["detail"]
    c.post("/api/calibration/procedures/gripper_left/cancel")

    # out-of-range haptics rejected
    cur = c.get("/api/settings").json()
    cur["haptics"]["left"]["max_render_n"] = 50
    assert c.put("/api/settings", json=cur).status_code == 400
    assert c.post("/api/control/teleop", json={"enabled": False}).status_code == 200
