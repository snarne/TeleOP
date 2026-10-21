# Data format

The station keeps two layers of data: **raw episodes**, which are the source of truth,
lossless and at native rates, and **LeRobot datasets**, which are derived from them and
ready for training.

## Raw episodes

```
<data_root>/recordings/
  <department>/<operator>/<YYYY-MM-DD_HH-MM-SS>_<task>/
    episode.json
    telemetry.mcap
    cameras/
      left_wrist.mp4   left_wrist.frames.csv
      overhead.mp4     overhead.frames.csv
      right_wrist.mp4  right_wrist.frames.csv
  .staging/<id>/      takes in progress (renamed into place on Save, deleted on Abort)
  .crashed/<id>/      takes interrupted by a crash, kept for inspection
  .trash/<dir>/       episodes deleted from the UI (recoverable until you empty it)
```

### `episode.json`

| Field | Meaning |
|---|---|
| `id`, `format` | 12-hex episode ID, `teleop-station/raw-v1` |
| `operator`, `department`, `task` | `{id, name}` (task also has `description`, used as the LeRobot task string) |
| `started_at`, `duration_s`, `t0_mono` | wall-clock start (ISO 8601), duration, and start on the shared monotonic clock |
| `success`, `notes`, `tags` | operator labels (editable later in Episodes) |
| `cameras.<name>` | `frames`, `width`, `height`, `fps_nominal`, `fps_measured`, `dropped_total` |
| `arms.<side>` | `arm_type`, `gripper_type`, `trigger` backend |
| `settings.haptics` | gains in effect during the take |
| `calibration` | snapshot of every calibration file at record time |
| `samples` | number of telemetry samples per arm |
| `grip_stats.<side>` | `peak_grip_n`, `mean_contact_grip_n`, `contact_s`, `peak_grip_cmd_n`, `peak_operator_force_n`: how hard this object was gripped |
| `events` | `recording_started`, button presses, faults, `recording_saved`, each with `t_mono` |
| `software_version`, `station`, `sim` | provenance |

### `telemetry.mcap`

An [MCAP](https://mcap.dev) file with zstd-compressed JSON messages. Open it directly in
[Foxglove](https://foxglove.dev) to plot any signal or scrub the timeline.

| Topic | Rate | Content |
|---|---|---|
| `/left/sample`, `/right/sample` | control rate (200 Hz) | `t_mono`, `leader_q[6]`, `q_cmd[7]`, `follower_q[6]`, `follower_dq[6]`, `follower_tau[6]`, `gripper`, `gripper_vel`, `gripper_tau`, `trigger_pos`, `trigger_force`, `trigger_render`, `grip_force`, `grip_source` (`fingertip`/`motor`), `fingertip_a`, `fingertip_b`, `slip_hf`, `slip`, `cue` (1 tap, 2 slip, 3 release), `contact`, `target_force`, `force_mode`, `buttons`, `mode` |
| `/events` | sparse | `{t_mono, kind, data}` |
| `/log` | sparse | `foxglove.Log`: every log line from every process during the take |

Units are radians, rad/s, N·m and newtons. Gripper and trigger positions are normalized
(gripper 0 = closed, 1 = open; trigger 0 = released, 1 = squeezed). `t_mono` is
`CLOCK_MONOTONIC` seconds, the same clock as the camera timestamps. MCAP log times are
wall-clock (monotonic + a fixed offset), so Foxglove shows real dates.

### Cameras

`<name>.mp4` is H.264, yuv420p, written at the camera's nominal rate with sequential
PTS. `<name>.frames.csv` gives the real capture time of every frame:
`frame_index, t_ns` (`CLOCK_MONOTONIC`, minus the configured `latency_ms`). Always align
using these timestamps, not the PTS. Dropped frames show up as gaps in `t_ns`.

## LeRobot export

**Episodes → select → Export to LeRobot** (or `station export --name NAME DIR…`) writes a
dataset in **LeRobot format v3.0** using the `lerobot` library itself, under
`<data_root>/datasets/<name>/`. Exporting again under the same name appends episodes.

Resampling: each episode is put on a uniform `fps` grid (30 Hz by default) over the
interval every stream covers. Arm signals are linearly interpolated. Each camera uses its
nearest frame by timestamp, and the worst skew is reported per episode
(`max_camera_skew_ms`, stored in `meta/teleop_station_episodes.jsonl`).

| Feature | Shape (2 arms) | Content |
|---|---|---|
| `observation.state` | 14 | follower `[left j1..j6, left gripper, right j1..j6, right gripper]` |
| `action` | 16 | per arm: leader joints (calibrated, follower frame), gripper position command, **grip-force command (N)**: the force the operator chose by squeezing, 0 in free space |
| `observation.velocity` | 14 | follower joint and gripper velocities |
| `observation.effort` | 14 | follower joint torques and gripper motor torque |
| `observation.grip_force` | 2 | estimated grip force, N |
| `observation.haptics` | 6 | per arm: trigger position, operator squeeze force (N), rendered force (N) |
| `observation.fingertip_force` | 4 | per arm: pad A, pad B normal force (N), only when every exported episode has fingertip sensors |
| `observation.slip` | 4 | per arm: slip-band RMS (N), slipping flag, same condition |
| `observation.images.left_wrist` / `overhead` / `right_wrist` | 480×640×3 | video |

`meta/teleop_station_episodes.jsonl` maps every dataset episode back to its raw episode,
operator, department, task, success flag and sync statistics.

```python
from lerobot.datasets.lerobot_dataset import LeRobotDataset
ds = LeRobotDataset("teleop-station-1/pick-and-place", root="~/teleop_data/datasets/pick-and-place")
frame = ds[0]   # dict of tensors, images CHW float
```
