"""Read raw episodes (telemetry.mcap + cameras/*) back into numpy arrays."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

VECTOR_FIELDS = {"leader_q": 6, "q_cmd": 7, "follower_q": 6, "follower_dq": 6, "follower_tau": 6}
SCALAR_FIELDS = ["gripper", "gripper_vel", "gripper_tau", "trigger_pos", "trigger_force", "trigger_render",
                 "grip_force", "contact", "target_force", "force_mode", "buttons", "fingertip_a", "fingertip_b",
                 "slip_hf", "slip", "cue"]


@dataclass
class ArmTrack:
    t: np.ndarray
    data: Dict[str, np.ndarray]

    def at(self, times: np.ndarray, name: str, nearest: bool = False) -> np.ndarray:
        """Sample a field at `times` (linear interpolation, or nearest neighbour)."""
        y = self.data[name]
        if nearest:
            idx = np.clip(np.searchsorted(self.t, times), 1, len(self.t) - 1)
            left = self.t[idx - 1]
            idx = np.where((times - left) < (self.t[idx] - times), idx - 1, idx)
            return y[idx]
        if y.ndim == 1:
            return np.interp(times, self.t, y)
        return np.stack([np.interp(times, self.t, y[:, j]) for j in range(y.shape[1])], axis=1)


@dataclass
class CameraTrack:
    name: str
    video: Path
    t: np.ndarray  # seconds, monotonic
    index: np.ndarray


@dataclass
class RawEpisode:
    path: Path
    info: Dict
    arms: Dict[str, ArmTrack] = field(default_factory=dict)
    cameras: Dict[str, CameraTrack] = field(default_factory=dict)
    events: List[Dict] = field(default_factory=list)


def _nan(v, n: Optional[int] = None):
    if v is None:
        return np.full(n, np.nan) if n else np.nan
    return v


def load_episode(path: Path, load_telemetry: bool = True) -> RawEpisode:
    path = Path(path)
    with open(path / "episode.json") as f:
        info = json.load(f)
    ep = RawEpisode(path, info)
    for csv_path in sorted((path / "cameras").glob("*.frames.csv")):
        name = csv_path.name[: -len(".frames.csv")]
        idx, ts = [], []
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                idx.append(int(row["frame_index"]))
                ts.append(int(row["t_ns"]) / 1e9)
        ep.cameras[name] = CameraTrack(name, path / "cameras" / f"{name}.mp4", np.array(ts), np.array(idx))
    if load_telemetry and (path / "telemetry.mcap").exists():
        _load_mcap(ep, path / "telemetry.mcap")
    return ep


def _load_mcap(ep: RawEpisode, mcap_path: Path) -> None:
    from mcap.reader import make_reader

    rows: Dict[str, List[Dict]] = {}
    with open(mcap_path, "rb") as f:
        reader = make_reader(f)
        for _schema, channel, message in reader.iter_messages():
            topic = channel.topic
            if topic.endswith("/sample"):
                side = topic.strip("/").split("/")[0]
                rows.setdefault(side, []).append(json.loads(message.data))
            elif topic == "/events":
                ep.events.append(json.loads(message.data))
    for side, rs in rows.items():
        rs.sort(key=lambda r: r["t_mono"])
        t = np.array([r["t_mono"] for r in rs])
        data: Dict[str, np.ndarray] = {}
        for k, n in VECTOR_FIELDS.items():
            data[k] = np.array([_nan(r.get(k), n) for r in rs], dtype=np.float64)
        for k in SCALAR_FIELDS:
            data[k] = np.array([np.nan if r.get(k) is None else float(r.get(k)) for r in rs], dtype=np.float64)
        ep.arms[side] = ArmTrack(t, data)


def grip_stats(ep: RawEpisode) -> Dict:
    """Per-arm summary of how hard the operator gripped during the take (for dataset analysis:
    which objects got which forces). Contact time is from the follower's contact detector."""
    out: Dict = {}
    for side, a in ep.arms.items():
        if len(a.t) < 2:
            continue
        g = np.nan_to_num(a.data["grip_force"])
        c = a.data["contact"] > 0.5
        cmd = a.data["target_force"]
        dt = np.diff(a.t, append=a.t[-1])
        out[side] = {
            "peak_grip_n": round(float(g.max()), 2),
            "mean_contact_grip_n": round(float(g[c].mean()), 2) if c.any() else 0.0,
            "contact_s": round(float(dt[c].sum()), 2),
            "peak_grip_cmd_n": round(float(np.nanmax(cmd)), 2) if np.isfinite(cmd).any() else 0.0,
            "peak_operator_force_n": round(float(np.nanmax(a.data["trigger_force"])), 2)
            if np.isfinite(a.data["trigger_force"]).any() else None,
            "slip_s": round(float(dt[np.nan_to_num(a.data["slip"]) > 0.5].sum()), 2),
            "grip_source": "fingertip" if np.isfinite(a.data["fingertip_a"]).any() else "motor",
        }
    return out


def decimate_series(ep: RawEpisode, max_points: int = 1500) -> Dict:
    """Telemetry for UI plots: time relative to episode start, decimated."""
    out: Dict = {"t": [], "series": {}, "video_offsets": {}}
    if not ep.arms:
        return out
    # t = 0 is the first video frame, so a plot playhead can follow <video>.currentTime directly
    firsts = {n: float(c.t[0]) for n, c in ep.cameras.items() if len(c.t)}
    t0 = min(firsts.values()) if firsts else min(a.t[0] for a in ep.arms.values())
    out["video_offsets"] = {n: round(v - t0, 4) for n, v in firsts.items()}
    ref = next(iter(ep.arms.values()))
    step = max(1, len(ref.t) // max_points)
    grid = ref.t[::step]
    out["t"] = (grid - t0).round(4).tolist()
    for side, a in ep.arms.items():
        for name in ("grip_force", "trigger_pos", "trigger_force", "trigger_render", "gripper"):
            v = a.at(grid, name)
            out["series"][f"{side}.{name}"] = [None if not np.isfinite(x) else round(float(x), 4) for x in v]
        fq = a.at(grid, "follower_q")
        lq = a.at(grid, "leader_q")
        for j in range(6):
            out["series"][f"{side}.follower.q{j}"] = [round(float(x), 4) for x in np.nan_to_num(fq[:, j])]
            out["series"][f"{side}.leader.q{j}"] = [None if not np.isfinite(x) else round(float(x), 4) for x in lq[:, j]]
        err = np.nanmax(np.abs(a.at(grid, "q_cmd")[:, :6] - fq), axis=1) if np.isfinite(a.data["q_cmd"]).any() else np.zeros(len(grid))
        out["series"][f"{side}.tracking_error"] = [round(float(x), 4) for x in np.nan_to_num(err)]
    return out
