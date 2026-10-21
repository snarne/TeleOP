"""Episode recorder.

Raw episode layout (one directory per episode):

    recordings/<department>/<user>/<YYYY-MM-DD_HH-MM-SS>_<task>/
      episode.json            metadata: who/what/when, calibration and settings snapshot, stats
      telemetry.mcap          all arm samples at the control rate, events, logs
                              (zstd-compressed JSON; opens directly in Foxglove)
      cameras/<name>.mp4      H.264, constant frame rate as captured
      cameras/<name>.frames.csv  frame_index, t_ns (CLOCK_MONOTONIC) per frame

Recording goes to `recordings/.staging/<uuid>/`. Save renames that directory into place
atomically, and abort deletes it, so a crash never leaves a half-written episode looking
like a real one.
"""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("station.recorder")

ARM_SAMPLE_SCHEMA = {
    "type": "object",
    "title": "ArmSample",
    "properties": {
        "t_mono": {"type": "number"},
        "leader_q": {"type": ["array", "null"], "items": {"type": "number"}},
        "q_cmd": {"type": ["array", "null"], "items": {"type": "number"}},
        "follower_q": {"type": "array", "items": {"type": "number"}},
        "follower_dq": {"type": "array", "items": {"type": "number"}},
        "follower_tau": {"type": "array", "items": {"type": "number"}},
        "gripper": {"type": "number"}, "gripper_vel": {"type": "number"}, "gripper_tau": {"type": "number"},
        "trigger_pos": {"type": "number"}, "trigger_force": {"type": ["number", "null"]},
        "trigger_render": {"type": "number"}, "grip_force": {"type": "number"}, "contact": {"type": "boolean"},
        "target_force": {"type": ["number", "null"]}, "force_mode": {"type": "boolean"},
        "buttons": {"type": "integer"}, "mode": {"type": "string"},
        "grip_source": {"type": "string"}, "fingertip_a": {"type": ["number", "null"]},
        "fingertip_b": {"type": ["number", "null"]}, "slip_hf": {"type": ["number", "null"]},
        "slip": {"type": "boolean"}, "cue": {"type": "integer"},
    },
}
EVENT_SCHEMA = {"type": "object", "title": "Event",
                "properties": {"t_mono": {"type": "number"}, "kind": {"type": "string"}, "data": {"type": "object"}}}
# Foxglove's well-known log schema, so logs show up in the Log panel.
FOXGLOVE_LOG_SCHEMA = {
    "type": "object", "title": "foxglove.Log",
    "properties": {
        "timestamp": {"type": "object", "properties": {"sec": {"type": "integer"}, "nsec": {"type": "integer"}}},
        "level": {"type": "integer"}, "message": {"type": "string"}, "name": {"type": "string"},
        "file": {"type": "string"}, "line": {"type": "integer"},
    },
}
_FOX_LEVEL = {"DEBUG": 1, "INFO": 2, "WARNING": 3, "ERROR": 4, "CRITICAL": 5}


def _clean(v: Any) -> Any:
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, list):
        return [_clean(x) for x in v]
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    return v


class TelemetryWriter:
    def __init__(self, path: Path, compression: str = "zstd"):
        from mcap.writer import CompressionType, Writer

        comp = {"zstd": CompressionType.ZSTD, "lz4": CompressionType.LZ4}.get(compression, CompressionType.NONE)
        self.f = open(path, "wb")
        try:
            self.w = Writer(self.f, compression=comp)
        except Exception:  # compression library missing
            self.w = Writer(self.f, compression=CompressionType.NONE)
        self.w.start(profile="", library="teleop-station")
        self.schemas = {
            "arm": self.w.register_schema("ArmSample", "jsonschema", json.dumps(ARM_SAMPLE_SCHEMA).encode()),
            "event": self.w.register_schema("Event", "jsonschema", json.dumps(EVENT_SCHEMA).encode()),
            "log": self.w.register_schema("foxglove.Log", "jsonschema", json.dumps(FOXGLOVE_LOG_SCHEMA).encode()),
        }
        self.channels: Dict[str, int] = {}
        # monotonic → epoch offset so Foxglove shows wall-clock time
        self.epoch_offset_ns = time.time_ns() - time.monotonic_ns()
        self.counts: Dict[str, int] = {}
        self.lock = threading.Lock()

    def _chan(self, topic: str, schema: str) -> int:
        if topic not in self.channels:
            self.channels[topic] = self.w.register_channel(topic, "json", self.schemas[schema])
        return self.channels[topic]

    def write(self, topic: str, schema: str, t_mono: float, payload: Dict[str, Any]) -> None:
        ns = int(t_mono * 1e9) + self.epoch_offset_ns
        data = json.dumps(_clean(payload), separators=(",", ":")).encode()
        with self.lock:
            self.w.add_message(self._chan(topic, schema), log_time=ns, publish_time=ns, data=data)
            self.counts[topic] = self.counts.get(topic, 0) + 1

    def log(self, ts_epoch: float, level: str, name: str, message: str) -> None:
        ns = int(ts_epoch * 1e9)
        payload = {"timestamp": {"sec": ns // 1_000_000_000, "nsec": ns % 1_000_000_000},
                   "level": _FOX_LEVEL.get(level, 2), "message": message, "name": name, "file": "", "line": 0}
        with self.lock:
            self.w.add_message(self._chan("/log", "log"), log_time=ns, publish_time=ns,
                               data=json.dumps(payload).encode())

    def close(self) -> None:
        with self.lock:
            self.w.finish()
            self.f.close()


def git_version(base: Path) -> str:
    try:
        return subprocess.run(["git", "describe", "--always", "--dirty", "--tags"], cwd=base, capture_output=True,
                              text=True, timeout=2).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


class Recorder:
    """Coordinates cameras + arms into one episode. Used only by the Orchestrator."""

    def __init__(self, data_root: Path, sample_q, compression: str = "zstd"):
        self.root = data_root / "recordings"
        self.staging_root = self.root / ".staging"
        self.sample_q = sample_q
        self.compression = compression
        self.active: Optional[Dict[str, Any]] = None
        self.telemetry: Optional[TelemetryWriter] = None
        self._drain_thread: Optional[threading.Thread] = None
        self._stop_drain = threading.Event()
        self.samples: Dict[str, int] = {}
        self._lock = threading.Lock()
        self.cleanup_stale_staging()

    def cleanup_stale_staging(self) -> None:
        """Staging dirs left by a crash are moved to recordings/.crashed for inspection."""
        if not self.staging_root.exists():
            return
        for d in self.staging_root.iterdir():
            dest = self.root / ".crashed" / d.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(d), str(dest))
                log.warning("found an unfinished recording from a previous run; moved it to %s", dest)
            except Exception as e:
                log.error("could not move stale staging dir %s: %s", d, e)

    @property
    def is_active(self) -> bool:
        return self.active is not None

    def start(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        if self.active:
            raise RuntimeError("already recording")
        eid = uuid.uuid4().hex[:12]
        staging = self.staging_root / eid
        (staging / "cameras").mkdir(parents=True, exist_ok=True)
        self.telemetry = TelemetryWriter(staging / "telemetry.mcap", self.compression)
        self.samples = {}
        # drop samples queued before the start
        try:
            while True:
                self.sample_q.get_nowait()
        except queue.Empty:
            pass
        self.active = {
            "id": eid, "staging": staging, "t0_mono": time.monotonic(),
            "started_at": datetime.now(timezone.utc), "meta": meta, "events": [],
        }
        self._stop_drain.clear()
        self._drain_thread = threading.Thread(target=self._drain, name="recorder-drain", daemon=True)
        self._drain_thread.start()
        self.event("recording_started", {"episode_id": eid})
        return self.active

    def _drain(self) -> None:
        while not self._stop_drain.is_set() or not self.sample_q.empty():
            try:
                side, s = self.sample_q.get(timeout=0.05)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                break
            tel = self.telemetry
            if tel is None:
                continue
            t = s.pop("t")
            s["t_mono"] = t
            try:
                tel.write(f"/{side}/sample", "arm", t, s)
                self.samples[side] = self.samples.get(side, 0) + 1
            except Exception as e:  # pragma: no cover
                log.error("telemetry write failed: %s", e)

    def event(self, kind: str, data: Optional[Dict[str, Any]] = None) -> None:
        if self.active and self.telemetry:
            t = time.monotonic()
            self.active["events"].append({"t_mono": t, "kind": kind, "data": data or {}})
            self.telemetry.write("/events", "event", t, {"t_mono": t, "kind": kind, "data": data or {}})

    def log_line(self, ts: float, level: str, source: str, message: str) -> None:
        if self.active and self.telemetry:
            try:
                self.telemetry.log(ts, level, source, message)
            except Exception:
                pass

    def finish(self, keep: bool, final_dir: Optional[Path] = None, extra: Optional[Dict[str, Any]] = None,
               t_stop: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Stop writing. keep=True → write episode.json and move into place; else delete."""
        if not self.active:
            raise RuntimeError("not recording")
        a = self.active
        self.event("recording_saved" if keep else "recording_aborted")
        time.sleep(0.05)  # let in-flight samples land
        self._stop_drain.set()
        if self._drain_thread:
            self._drain_thread.join(timeout=3.0)
        tel = self.telemetry
        self.telemetry = None
        self.active = None
        if tel:
            tel.close()
        staging: Path = a["staging"]
        if not keep:
            shutil.rmtree(staging, ignore_errors=True)
            return None
        duration = (t_stop or time.monotonic()) - a["t0_mono"]
        info = dict(a["meta"])
        info.update(extra or {})
        info.update({
            "id": a["id"], "format": "teleop-station/raw-v1",
            "started_at": a["started_at"].isoformat(), "duration_s": round(duration, 3),
            "t0_mono": a["t0_mono"], "samples": self.samples,
            "events": a["events"],
        })
        with open(staging / "episode.json", "w") as f:
            json.dump(_clean(info), f, indent=2, default=str)
        assert final_dir is not None
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        if final_dir.exists():
            final_dir = final_dir.with_name(final_dir.name + "_" + a["id"][:4])
        os.replace(staging, final_dir)
        size = sum(p.stat().st_size for p in final_dir.rglob("*") if p.is_file()) / 1e6
        return {"id": a["id"], "path": final_dir, "duration_s": duration, "size_mb": size, "info": info}
