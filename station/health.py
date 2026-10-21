"""`station doctor`: every check returns ok/warn/error with a message and a concrete fix."""

from __future__ import annotations

import glob
import importlib.util
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from station.config import StationConfig


def _check(cid: str, group: str, label: str, status: str, message: str = "", hint: str = "") -> Dict[str, str]:
    return {"id": cid, "group": group, "label": label, "status": status, "message": message, "hint": hint}


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def ftdi_latency(port: str) -> Optional[int]:
    """USB-serial adapters (U2D2 = FTDI) default to 16 ms latency, which caps Dynamixel reads ≈ 60 Hz."""
    try:
        tty = os.path.basename(os.path.realpath(port))
        p = Path(f"/sys/bus/usb-serial/devices/{tty}/latency_timer")
        return int(p.read_text().strip()) if p.exists() else None
    except Exception:
        return None


def can_state(name: str) -> Dict[str, Any]:
    p = Path(f"/sys/class/net/{name}")
    if not p.exists():
        return {"exists": False}
    out: Dict[str, Any] = {"exists": True, "up": False, "bitrate": None}
    try:
        flags = int((p / "flags").read_text().strip(), 16)
        out["up"] = bool(flags & 0x1)
    except Exception:
        pass
    try:
        r = subprocess.run(["ip", "-details", "link", "show", name], capture_output=True, text=True, timeout=2)
        m = re.search(r"bitrate (\d+)", r.stdout)
        out["bitrate"] = int(m.group(1)) if m else None
    except Exception:
        pass
    return out


def run_checks(cfg: StationConfig, runtime: Optional[Callable[[], Dict[str, Any]]] = None) -> Dict[str, Any]:
    checks: List[Dict[str, str]] = []
    add = checks.append
    sim = cfg.station.sim

    # ------------------------------------------------------------------ system
    root = cfg.data_root
    try:
        root.mkdir(parents=True, exist_ok=True)
        test = root / ".write_test"
        test.write_text("ok")
        test.unlink()
        du = shutil.disk_usage(root)
        free_gb = du.free / 1e9
        st = "ok" if free_gb > 20 else ("warn" if free_gb > 2 else "error")
        add(_check("disk", "system", "Data drive", st, f"{root} · {free_gb:.0f} GB free",
                   "" if st == "ok" else "free up space or point station.data_root at a bigger drive (≈ 1 GB per 10 min of recording)"))
    except Exception as e:
        add(_check("disk", "system", "Data drive", "error", f"{root}: {e}", "fix permissions or change station.data_root"))

    gov = glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor")
    if gov and not sim:
        g = Path(gov[0]).read_text().strip()
        add(_check("cpu_governor", "system", "CPU governor", "ok" if g == "performance" else "warn", g,
                   "" if g == "performance" else "lower jitter: sudo cpupower frequency-set -g performance"))

    for mod, label, needed, hint in [
        ("dynamixel_sdk", "Dynamixel SDK", any(a.leader.backend == "dynamixel" for a in cfg.arms.values()),
         "pip install dynamixel-sdk"),
        ("i2rt", "I2RT SDK", any(a.follower.backend == "i2rt" for a in cfg.arms.values()),
         "git clone https://github.com/i2rt-robotics/i2rt && pip install -e i2rt"),
        ("av", "PyAV (video encoding)", True, "pip install av"),
        ("mcap", "MCAP (telemetry)", True, "pip install mcap zstandard"),
        ("lerobot", "LeRobot (dataset export)", False, "pip install lerobot (or set export.python to a venv that has it)"),
    ]:
        ok = _has(mod)
        if needed or ok or mod == "lerobot":
            st = "ok" if ok else ("error" if needed else "warn")
            add(_check(f"dep_{mod}", "software", label, st, "installed" if ok else "not installed", "" if ok else hint))
    if _has("av"):
        try:
            import av

            av.codec.Codec(cfg.recording.video_codec, "w")
            add(_check("codec", "software", f"Encoder {cfg.recording.video_codec}", "ok", "available"))
        except Exception:
            add(_check("codec", "software", f"Encoder {cfg.recording.video_codec}", "warn", "not available (mpeg4 fallback)",
                       "install an FFmpeg build with libx264, or set recording.video_codec"))

    # ------------------------------------------------------------------ arms
    for side in cfg.enabled_arms():
        a = cfg.arms[side]
        g = f"{side} arm"
        if a.leader.backend == "sim":
            add(_check(f"leader_port_{side}", g, "Leader U2D2", "ok", "simulated"))
        else:
            port = a.leader.port
            if "CHANGE_ME" in port:
                add(_check(f"leader_port_{side}", g, "Leader U2D2", "error", "port not configured",
                           f"set arms.{side}.leader.port to the /dev/serial/by-id/… path of this arm's U2D2"))
            elif not os.path.exists(port):
                add(_check(f"leader_port_{side}", g, "Leader U2D2", "error", f"{port} not found",
                           "plug in the U2D2; ls /dev/serial/by-id/ to find its path"))
            else:
                rw = os.access(port, os.R_OK | os.W_OK)
                add(_check(f"leader_port_{side}", g, "Leader U2D2", "ok" if rw else "error", port,
                           "" if rw else "sudo usermod -aG dialout $USER, then log out and in"))
                lat = ftdi_latency(port)
                if lat is not None:
                    add(_check(f"leader_latency_{side}", g, "USB latency timer", "ok" if lat <= 2 else "warn", f"{lat} ms",
                               "" if lat <= 2 else "install scripts/udev/99-teleop-station.rules (sets 1 ms); caps the loop at ≈60 Hz otherwise"))
        tb = a.trigger.backend
        if tb == "hgm":
            ok = os.path.exists(a.trigger.port)
            add(_check(f"trigger_port_{side}", g, "Haptic grip module", "ok" if ok else "error", a.trigger.port,
                       "" if ok else "plug in the module's USB-C; install the udev rule so it appears as /dev/hgm_<side>"))
        elif tb == "dynamixel_legacy":
            add(_check(f"trigger_port_{side}", g, "Trigger", "warn", "legacy Dynamixel trigger (no force sensing)",
                       "build the Haptic Grip Module (docs/hardware/haptic-trigger.md) for real grip-force feedback"))
        if a.fingertips.backend == "fgs":
            ok = os.path.exists(a.fingertips.port)
            add(_check(f"fgs_port_{side}", g, "Fingertip sensors", "ok" if ok else "error", a.fingertips.port,
                       "" if ok else "plug in the fingertip sensor USB; udev rule for /dev/fgs_<side>"))
        if a.follower.backend == "i2rt":
            cs = can_state(a.follower.can_channel)
            if not cs["exists"]:
                add(_check(f"can_{side}", g, f"CAN {a.follower.can_channel}", "error", "interface missing",
                           "plug in the CANable; set persistent names: scripts/udev/README.md"))
            elif not cs["up"]:
                add(_check(f"can_{side}", g, f"CAN {a.follower.can_channel}", "error", "interface down",
                           f"sudo ip link set {a.follower.can_channel} up type can bitrate 1000000 (or Hardware → Reset CAN)"))
            else:
                br = cs.get("bitrate")
                st = "ok" if br in (None, 1000000) else "error"
                add(_check(f"can_{side}", g, f"CAN {a.follower.can_channel}", st, f"up · {br or '?'} bit/s",
                           "" if st == "ok" else "the YAM bus runs at 1 Mbit/s"))
        else:
            add(_check(f"can_{side}", g, "Follower", "ok", "simulated"))
        cal = cfg.cal_path(a.leader.calibration_file)
        add(_check(f"cal_leader_{side}", g, "Leader calibration", "ok" if cal.exists() else "warn",
                   cal.name if cal.exists() else "missing",
                   "" if cal.exists() else "Calibration → Leader arm (takes 2 minutes)"))

    # ------------------------------------------------------------------ cameras
    for name, c in cfg.cameras.items():
        g = "cameras"
        if c.backend == "sim":
            add(_check(f"cam_dev_{name}", g, c.label or name, "ok", "simulated"))
        elif c.backend == "opencv":
            if "CHANGE_ME" in c.device:
                add(_check(f"cam_dev_{name}", g, c.label or name, "error", "device not configured",
                           "set cameras.<name>.device to a /dev/v4l/by-id/…-video-index0 path (ls /dev/v4l/by-id/)"))
            elif not os.path.exists(c.device) and not str(c.device).isdigit():
                add(_check(f"cam_dev_{name}", g, c.label or name, "error", f"{c.device} not found",
                           "check the USB cable/hub; many webcams need their own USB controller at 30 fps"))
            else:
                add(_check(f"cam_dev_{name}", g, c.label or name, "ok", str(c.device)))
        else:
            ok = _has("pyrealsense2")
            add(_check(f"cam_dev_{name}", g, c.label or name, "ok" if ok else "error", "RealSense",
                       "" if ok else "pip install pyrealsense2"))

    # ------------------------------------------------------------------ power
    p = cfg.power
    if p.backend == "none":
        add(_check("power", "power", "Relay board", "warn", "not configured",
                   "arms can't be power-cycled from the UI: see docs/hardware/electronics.md"))
    elif p.backend in ("numato", "lcus"):
        ok = os.path.exists(p.port)
        add(_check("power", "power", "Relay board", "ok" if ok else "error", p.port, "" if ok else "plug in the relay board USB"))

    # ------------------------------------------------------------------ live runtime
    if runtime:
        rt = runtime()
        for side, a in (rt.get("arms") or {}).items():
            if a.get("state") in ("teleop", "syncing", "connected"):
                hz = a.get("loop_hz") or 0
                st = "ok" if hz > 0.9 * cfg.runtime.control_hz else "warn"
                add(_check(f"loop_{side}", f"{side} arm", "Control loop", st,
                           f"{hz:.0f} Hz · jitter {a.get('loop_jitter_ms', 0):.2f} ms",
                           "" if st == "ok" else "check the USB latency timer and CPU load"))
                temps = [t for t in (a.get("follower", {}).get("temps_c") or []) if t is not None]
                if temps:
                    mx = max(temps)
                    st = "ok" if mx < 60 else ("warn" if mx < 75 else "error")
                    add(_check(f"temp_{side}", f"{side} arm", "Motor temperature", st, f"max {mx:.0f} °C",
                               "" if st == "ok" else "let the arm rest; avoid holding heavy loads at full extension"))
        for name, c in (rt.get("cameras") or {}).items():
            if c.get("ok"):
                fps = c.get("fps") or 0
                st = "ok" if fps > 25 else "warn"
                add(_check(f"cam_fps_{name}", "cameras", f"{name} frame rate", st, f"{fps:.1f} fps · {c.get('dropped', 0)} dropped",
                           "" if st == "ok" else "lower resolution, use MJPG, or move the camera to another USB controller"))
        pw = rt.get("power") or {}
        if pw.get("available"):
            e = pw.get("estop_ok")
            add(_check("estop", "power", "E-stop", "ok" if e else ("error" if e is False else "unknown"),
                       {True: "released", False: "PRESSED", None: "not wired"}[e], "" if e else "twist to release the e-stop"))

    order = {"error": 0, "warn": 1, "unknown": 2, "ok": 3}
    return {"checks": checks, "ran_at": datetime.now(timezone.utc).isoformat(),
            "worst": min((c["status"] for c in checks), key=lambda s: order[s]) if checks else "ok"}
