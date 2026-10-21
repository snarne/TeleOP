#!/usr/bin/env python3
"""End-to-end test against a running simulated station.

    station serve --sim --port 8011 &
    python tests/e2e_sim.py --url http://localhost:8011

Walks the whole operator workflow through the public API: session → start arms →
calibrate every procedure → teleop → record/save → record/abort → episode review →
handle-button actions → stop. Exits non-zero on the first failed expectation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time

import httpx
import websockets

OK = "\033[32m✔\033[0m"


class E2E:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.c = httpx.Client(base_url=self.url, timeout=60)

    def req(self, method: str, path: str, expect: int = 200, **kw):
        r = self.c.request(method, path, **kw)
        if r.status_code != expect:
            raise AssertionError(f"{method} {path} → {r.status_code}: {r.text[:400]}")
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else r

    def state(self) -> dict:
        async def one():
            ws_url = self.url.replace("http", "ws") + "/ws/state"
            async with websockets.connect(ws_url) as ws:
                return json.loads(await ws.recv())
        return asyncio.run(one())

    def wait_phase(self, phase: str, timeout: float = 30) -> dict:
        t = time.time() + timeout
        while time.time() < t:
            s = self.state()
            if s["phase"] == phase:
                return s
            if s["phase"] == "fault" and phase != "fault":
                raise AssertionError(f"fault: {s['phase_detail']}  steps={s['startup']['steps']}")
            time.sleep(0.3)
        raise AssertionError(f"timed out waiting for phase {phase} (now {s['phase']})")

    def step(self, msg: str) -> None:
        print(f"{OK} {msg}", flush=True)

    def calibrate(self, pid: str, steps: list) -> dict:
        self.req("POST", f"/api/calibration/procedures/{pid}/start")
        for sid, inputs, times in steps:
            for _ in range(times):
                rs = self.req("POST", f"/api/calibration/procedures/{pid}/steps/{sid}", json={"inputs": inputs})
                st = next(x for x in rs["steps"] if x["id"] == sid)
                if st["status"] != "ok":
                    raise AssertionError(f"{pid}/{sid}: {st['message']} ({st['data'].get('hint')})")
        assert rs["can_commit"], f"{pid} not committable: {rs}"
        item = self.req("POST", f"/api/calibration/procedures/{pid}/commit")
        assert item["calibrated"], item
        return item

    def run(self) -> None:
        st = self.req("GET", "/api/station")
        assert st["sim"], "point this test at a --sim station"
        self.step(f"station '{st['name']}' {st['version']}: arms {st['arms']}, cameras {[c['name'] for c in st['cameras']]}")

        # --- organization
        d = self.req("POST", "/api/departments", json={"name": f"QA {int(time.time())}", "color": "#22aa88"})
        u = self.req("POST", "/api/users", json={"name": "Test Operator", "role": "operator", "department_ids": [d["id"]]})
        t = self.req("POST", "/api/tasks", json={"name": "Stack blocks", "description": "Stack the red block on the blue block",
                                                 "department_id": d["id"]})
        self.req("PUT", "/api/session", json={"operator_id": u["id"], "department_id": d["id"], "task_id": t["id"]})
        self.step(f"org: department {d['name']}, operator {u['name']}, task {t['name']}")

        # --- recording requires teleop
        self.req("POST", "/api/recording/start", expect=409)

        # --- start arms
        self.req("POST", "/api/control/start_arms", json={})
        s = self.wait_phase("ready", 40)
        bad = [x for x in s["startup"]["steps"] if x["status"] == "error"]
        assert not bad, bad
        self.step("start arms: " + ", ".join(f"{x['id']}={x['status']}" for x in s["startup"]["steps"]))

        # --- calibration
        for side in st["arms"]:
            item = self.calibrate(f"leader_{side}", [("check", {}, 1), ("pose_a", {}, 1), ("pose_b", {}, 1), ("verify", {}, 1)])
            self.step(f"calibrated leader_{side}: {item['summary']}")
        item = self.calibrate("trigger_left", [("connect", {}, 1), ("tare", {}, 1), ("open", {}, 1), ("closed", {}, 1),
                                               ("stiffness", {"mass_g": 500}, 1)])
        self.step(f"calibrated trigger_left: {item['summary']}")
        item = self.calibrate("gripper_left", [("friction", {}, 1), ("squeeze_1", {}, 1), ("squeeze_2", {}, 1), ("squeeze_3", {}, 1)])
        self.step(f"calibrated gripper_left: {item['summary']}")
        item = self.calibrate("fingertips_left", [("tare", {}, 1), ("pad_a", {"mass_g": 1000}, 1), ("pad_b", {"mass_g": 1000}, 1)])
        self.step(f"calibrated fingertips_left: {item['summary']}")
        item = self.calibrate("camera_overhead", [("board", {"square_mm": 30, "marker_mm": 22}, 1), ("collect", {}, 12), ("solve", {}, 1)])
        self.step(f"calibrated camera_overhead: {item['summary']}")
        script = self.req("POST", "/api/calibration/scripts", json={"procedure_id": "trigger_left"})
        compile(script["content"], script["filename"], "exec")
        for pid in ("leader_left", "gripper_left", "camera_overhead"):
            compile(self.req("POST", "/api/calibration/scripts", json={"procedure_id": pid})["content"], pid, "exec")
        self.step(f"generated standalone scripts compile ({script['filename']}, {len(script['content'])} chars)")

        # --- teleop
        self.req("POST", "/api/control/teleop", json={"enabled": True})
        time.sleep(4.0)
        s = self.state()
        assert s["phase"] == "teleop", s["phase"]
        for side, a in s["arms"].items():
            assert a["state"] == "teleop", (side, a["state"], a["fault"])
            assert a["loop_hz"] > 150, (side, a["loop_hz"])
            assert a["tracking_error_rad"] < 0.25, (side, a["tracking_error_rad"])
        self.step("teleop: " + ", ".join(f"{k} {a['loop_hz']:.0f} Hz, jitter {a['loop_jitter_ms']:.2f} ms, "
                                         f"track {math.degrees(a['tracking_error_rad']):.1f}°" for k, a in s["arms"].items()))

        # --- haptics: over a grasp cycle the follower should see contact and the trigger should render force
        peak = {side: (0.0, 0.0, 0.0) for side in s["arms"]}
        t_end = time.time() + 10
        while time.time() < t_end:
            s = self.state()
            for side, a in s["arms"].items():
                g, r, f = a["grip_force_n"] or 0, a["trigger"]["render_n"] or 0, a["trigger"]["force_n"] or 0
                p = peak[side]
                peak[side] = (max(p[0], g), max(p[1], r), max(p[2], f))
            time.sleep(0.1)
        for side, (g, r, f) in peak.items():
            assert g > 5 and r > 1, (side, peak[side])
        assert all(a["grip_source"] == "fingertip" for a in s["arms"].values()), "sim fingertips should drive feedback"
        self.step("haptics: " + ", ".join(f"{k} peak grip {v[0]:.1f} N → rendered {v[1]:.1f} N, squeeze {v[2]:.1f} N"
                                          for k, v in peak.items()))

        # --- record + save
        rid = self.req("POST", "/api/recording/start")["episode_id"]
        time.sleep(6.0)
        s = self.state()
        assert s["phase"] == "recording" and s["recording"]["active"] and s["recording"]["frames"] > 100, s["recording"]
        ep = self.req("POST", "/api/recording/save", json={"success": True, "notes": "e2e"})
        assert ep["id"] == rid and ep["duration_s"] > 5 and ep["frames"] > 20 * ep["duration_s"], ep
        assert ep["department_name"] == d["name"] and ep["user_name"] == u["name"], ep
        self.step(f"saved episode {ep['id']}: {ep['duration_s']:.1f}s, {ep['frames']} frames, {ep['size_mb']:.1f} MB → {ep['path']}")

        # --- record + abort
        self.req("POST", "/api/recording/start")
        time.sleep(2.0)
        self.req("POST", "/api/recording/abort")
        lst = self.req("GET", f"/api/episodes?department_id={d['id']}")
        assert lst["total"] == 1, lst
        self.step("abort deletes the take (1 episode in department)")

        # --- review
        tel = self.req("GET", f"/api/episodes/{ep['id']}/telemetry?max_points=500")
        assert len(tel["t"]) > 100 and "left.grip_force" in tel["series"], list(tel["series"])[:5]
        v = self.c.get(f"/api/episodes/{ep['id']}/video/overhead")
        assert v.status_code == 200 and v.content[4:8] == b"ftyp", v.status_code
        self.req("PATCH", f"/api/episodes/{ep['id']}", json={"notes": "reviewed", "tags": ["e2e"]})
        snap = self.c.get("/api/cameras/overhead/snapshot.jpg")
        assert snap.content[:2] == b"\xff\xd8"
        self.step(f"review: telemetry {len(tel['t'])} pts, {len(tel['series'])} series; mp4 {len(v.content) / 1e6:.1f} MB")

        # --- named actions (what keys / handle buttons trigger)
        self.req("POST", "/api/control/action", json={"action": "start_recording"})
        time.sleep(1.5)
        self.req("POST", "/api/control/action", json={"action": "mark_failure"})
        ep2 = self.req("POST", "/api/control/action", json={"action": "save"})
        assert ep2["success"] is False, ep2
        self.step("actions: start_recording → mark_failure → save")

        # --- settings
        cur = self.req("GET", "/api/settings")
        cur["haptics"]["left"]["feedback_gain"] = 0.4
        new = self.req("PUT", "/api/settings", json=cur)
        assert new["haptics"]["left"]["feedback_gain"] == 0.4
        cur["keybindings"]["save"] = cur["keybindings"]["abort"]
        self.req("PUT", "/api/settings", json=cur, expect=400)
        self.step("settings: haptic gains update live; duplicate keybindings rejected")

        # --- e-stop and recovery
        self.req("POST", "/api/control/estop")
        s = self.wait_phase("fault", 5)
        self.req("POST", "/api/control/clear_fault")
        self.wait_phase("ready", 5)
        self.step("software e-stop → fault → clear → ready")

        # --- health
        h = self.req("POST", "/api/health/run")
        self.step(f"health: {len(h['checks'])} checks, worst = {h['worst']}")

        # --- stop
        self.req("POST", "/api/control/stop_arms")
        self.wait_phase("idle", 30)
        self.step("stop arms → idle")
        print("\nALL E2E CHECKS PASSED")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8011")
    try:
        E2E(ap.parse_args().url).run()
    except AssertionError as e:
        print(f"\033[31m✘ {e}\033[0m")
        sys.exit(1)
