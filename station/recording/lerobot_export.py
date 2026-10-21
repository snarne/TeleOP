"""Export raw episodes to a LeRobot dataset (format v3.0, written by the `lerobot` library).

Each episode is resampled onto a uniform `fps` grid spanning the interval that every
stream covers. Cameras use the nearest frame by capture timestamp (the worst skew is
reported); arm signals are linearly interpolated, and booleans use the nearest sample.

Features (dimensions shown for two arms; single-arm stations get half):
  observation.state           (14)  follower joints 1-6 + gripper, left then right
  action                      (16)  leader joints 1-6 (calibrated) + gripper position command
                                    + grip-force command (N; 0 in free space), the operator's chosen force
  observation.velocity        (14)  follower joint + gripper velocities
  observation.effort          (14)  follower joint torques + gripper motor torque
  observation.grip_force      (2)   grip force, N (fingertip sensors when fitted, else motor-torque estimate)
  observation.fingertip_force (4)   per-pad normal force, N       } only when every episode has
  observation.slip            (4)   slip-band RMS (N), slipping   } fingertip sensors
  observation.haptics         (6)   trigger position, operator squeeze force (N), rendered force (N)
  observation.images.<camera> video

Run it as a module, so the heavy torch/lerobot import stays out of the station server:
  python -m station.recording.lerobot_export --root DIR --repo-id ORG/NAME EPISODE_DIR...
Progress goes to stdout as JSON lines.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np

from station.recording.raw_episode import RawEpisode, load_episode

JOINTS = [f"joint_{i}" for i in range(1, 7)]


def _progress(**kw) -> None:
    print(json.dumps(kw), flush=True)


def build_features(sides: List[str], cameras: Dict[str, tuple], fingertips: bool = False) -> Dict:
    def names(suffix: List[str]) -> List[str]:
        return [f"{s}_{n}" for s in sides for n in suffix]

    feats = {
        "observation.state": {"dtype": "float32", "shape": (7 * len(sides),), "names": names(JOINTS + ["gripper"])},
        "action": {"dtype": "float32", "shape": (8 * len(sides),),
                   "names": names(JOINTS + ["gripper", "grip_force_cmd_n"])},
        "observation.velocity": {"dtype": "float32", "shape": (7 * len(sides),), "names": names(JOINTS + ["gripper"])},
        "observation.effort": {"dtype": "float32", "shape": (7 * len(sides),), "names": names(JOINTS + ["gripper"])},
        "observation.grip_force": {"dtype": "float32", "shape": (len(sides),), "names": names(["grip_force_n"])},
        "observation.haptics": {"dtype": "float32", "shape": (3 * len(sides),),
                                "names": names(["trigger_pos", "operator_force_n", "render_force_n"])},
    }
    if fingertips:
        feats["observation.fingertip_force"] = {"dtype": "float32", "shape": (2 * len(sides),),
                                                "names": names(["pad_a_n", "pad_b_n"])}
        feats["observation.slip"] = {"dtype": "float32", "shape": (2 * len(sides),),
                                     "names": names(["slip_band_n", "slipping"])}
    for cam, (h, w) in cameras.items():
        feats[f"observation.images.{cam}"] = {"dtype": "video", "shape": (h, w, 3),
                                              "names": ["height", "width", "channels"]}
    return feats


def episode_grid(ep: RawEpisode, fps: int) -> np.ndarray:
    starts = [a.t[0] for a in ep.arms.values()] + [c.t[0] for c in ep.cameras.values() if len(c.t)]
    ends = [a.t[-1] for a in ep.arms.values()] + [c.t[-1] for c in ep.cameras.values() if len(c.t)]
    t0, t1 = max(starts), min(ends)
    n = int(np.floor((t1 - t0) * fps)) + 1
    if n < 2:
        raise ValueError(f"{ep.path.name}: streams overlap for only {t1 - t0:.2f}s")
    return t0 + np.arange(n) / fps


def frame_sequence(cam, grid: np.ndarray):
    """Yield (rgb_frame, skew_s) for each grid time, decoding the video sequentially."""
    import av

    t = cam.t
    idx = np.clip(np.searchsorted(t, grid), 1, len(t) - 1)
    idx = np.where(np.abs(grid - t[idx - 1]) <= np.abs(t[idx] - grid), idx - 1, idx)
    skews = np.abs(t[idx] - grid)
    container = av.open(str(cam.video))
    stream = container.streams.video[0]
    decoded = container.decode(stream)
    cur_i, cur = -1, None
    for k, want in enumerate(idx):
        while cur_i < want:
            try:
                cur = next(decoded).to_ndarray(format="rgb24")
                cur_i += 1
            except StopIteration:
                break
        yield cur, float(skews[k])
    container.close()


def has_fingertips(ep: RawEpisode, sides: List[str]) -> bool:
    return all(s in ep.arms and np.isfinite(ep.arms[s].data["fingertip_a"]).any() for s in sides)


def episode_arrays(ep: RawEpisode, sides: List[str], grid: np.ndarray, fingertips: bool = False) -> Dict[str, np.ndarray]:
    st, act, vel, eff, gf, hap, ftf, slp = [], [], [], [], [], [], [], []
    for s in sides:
        a = ep.arms[s]
        fq = a.at(grid, "follower_q")
        lq = a.at(grid, "leader_q")
        lq = np.where(np.isfinite(lq), lq, fq)  # leader dropouts: fall back to follower (rare)
        qcmd = a.at(grid, "q_cmd")
        grip_cmd = np.where(np.isfinite(qcmd[:, 6]), qcmd[:, 6], a.at(grid, "gripper"))
        st.append(np.column_stack([fq, a.at(grid, "gripper")]))
        f_cmd = a.at(grid, "target_force", nearest=True)
        f_cmd = np.where(np.isfinite(f_cmd), f_cmd, 0.0)  # free space: position control, no force command
        act.append(np.column_stack([lq, grip_cmd, f_cmd]))
        vel.append(np.column_stack([a.at(grid, "follower_dq"), a.at(grid, "gripper_vel")]))
        eff.append(np.column_stack([a.at(grid, "follower_tau"), a.at(grid, "gripper_tau")]))
        gf.append(a.at(grid, "grip_force")[:, None])
        hap.append(np.column_stack([a.at(grid, "trigger_pos"), np.nan_to_num(a.at(grid, "trigger_force")),
                                    a.at(grid, "trigger_render")]))
        if fingertips:
            ftf.append(np.column_stack([a.at(grid, "fingertip_a"), a.at(grid, "fingertip_b")]))
            slp.append(np.column_stack([a.at(grid, "slip_hf"), a.at(grid, "slip", nearest=True)]))
    f32 = lambda xs: np.nan_to_num(np.concatenate(xs, axis=1)).astype(np.float32)  # noqa: E731
    out = {"observation.state": f32(st), "action": f32(act), "observation.velocity": f32(vel),
           "observation.effort": f32(eff), "observation.grip_force": f32(gf), "observation.haptics": f32(hap)}
    if fingertips:
        out["observation.fingertip_force"] = f32(ftf)
        out["observation.slip"] = f32(slp)
    return out


def _create_kwargs(fn, codec: str) -> Dict:
    params = inspect.signature(fn).parameters
    kw: Dict = {}
    if "rgb_encoder" in params and codec:
        try:
            from lerobot.configs.video import RGBEncoderConfig

            kw["rgb_encoder"] = RGBEncoderConfig(vcodec=codec)
        except Exception:
            pass
    return kw


def export(episode_dirs: List[Path], root: Path, repo_id: str, fps: int = 30, codec: str = "h264",
           robot_type: str = "i2rt_yam_bimanual") -> Dict:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    episodes = [load_episode(p) for p in episode_dirs]
    sides = sorted({s for ep in episodes for s in ep.arms}, key=lambda s: ["left", "right"].index(s))
    cams: Dict[str, tuple] = {}
    for ep in episodes:
        for name, cam in ep.cameras.items():
            meta = ep.info.get("cameras", {}).get(name, {})
            cams.setdefault(name, (int(meta.get("height", 480)), int(meta.get("width", 640))))
    for ep in episodes:
        missing = [s for s in sides if s not in ep.arms] + [c for c in cams if c not in ep.cameras]
        if missing:
            raise ValueError(f"episode {ep.path.name} is missing streams {missing}; export it separately")
    fingertips = all(has_fingertips(ep, sides) for ep in episodes)
    features = build_features(sides, cams, fingertips)

    if (root / "meta" / "info.json").exists():
        ds = LeRobotDataset.resume(repo_id, root=root, **_create_kwargs(LeRobotDataset.resume, codec))
    else:
        ds = LeRobotDataset.create(repo_id, fps=fps, features=features, root=root, robot_type=robot_type,
                                   use_videos=True, **_create_kwargs(LeRobotDataset.create, codec))
    total = sum(1 for _ in episodes)
    report = []
    for e_i, ep in enumerate(episodes):
        grid = episode_grid(ep, fps)
        arrays = episode_arrays(ep, sides, grid, fingertips)
        task = ep.info.get("task", {}).get("description") or ep.info.get("task", {}).get("name") or "teleoperation"
        gens = {name: frame_sequence(cam, grid) for name, cam in ep.cameras.items()}
        max_skew = 0.0
        for k in range(len(grid)):
            frame = {key: arr[k] for key, arr in arrays.items()}
            for name, g in gens.items():
                img, skew = next(g)
                max_skew = max(max_skew, skew)
                frame[f"observation.images.{name}"] = img
            frame["task"] = task
            ds.add_frame(frame)
            if k % 60 == 0:
                _progress(stage="frames", episode=e_i, frames_done=k, frames=len(grid),
                          progress=(e_i + k / len(grid)) / total * 0.9)
        ds.save_episode()
        report.append({"episode": ep.info.get("id"), "frames": len(grid), "max_camera_skew_ms": round(max_skew * 1e3, 2),
                       "duration_s": round(float(grid[-1] - grid[0]), 3)})
        _progress(stage="episode_saved", episode=e_i, progress=(e_i + 1) / total * 0.9, detail=report[-1])
    ds.finalize()
    # sidecar: which raw episode (and who recorded it) each dataset episode came from
    side = root / "meta" / "teleop_station_episodes.jsonl"
    with open(side, "a") as f:
        for ep, r in zip(episodes, report):
            f.write(json.dumps({"raw_episode": ep.info.get("id"), "path": str(ep.path),
                                "operator": ep.info.get("operator"), "department": ep.info.get("department"),
                                "task": ep.info.get("task"), "started_at": ep.info.get("started_at"),
                                "success": ep.info.get("success"), **r}) + "\n")
    result = {"root": str(root), "repo_id": repo_id, "episodes": report}
    _progress(stage="done", progress=1.0, result=result)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--codec", default="h264")
    ap.add_argument("episodes", nargs="+", type=Path)
    a = ap.parse_args(argv)
    try:
        export(a.episodes, a.root, a.repo_id, a.fps, a.codec)
    except Exception as e:
        _progress(stage="error", error=f"{type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
