# Architecture

Teleop Station is the software and hardware stack for a **bimanual leader → follower
teleoperation cell** built on I2RT YAM follower arms, 3D-printed Dynamixel leader arms
with **haptic grip triggers**, and three 30 Hz cameras (left wrist, right wrist, overhead).
It covers the whole loop: who is operating, starting and calibrating the hardware,
teleoperating with grip-force feedback, recording synchronized episodes, and exporting
training-ready LeRobot datasets.

```
                    ┌─────────────────────────── Station PC (Ubuntu) ───────────────────────────┐
 Operator hands     │                                                                            │
 ┌────────────┐ USB │  ┌──────────────┐   200 Hz   ┌──────────────────┐   CAN 1 Mbit/s  ┌───────┴─────┐
 │ Leader arm │─────┼─▶│ LeaderBus    │──────────▶ │  ArmWorker (L)   │───────────────▶ │ YAM follower│
 │ (Dynamixel)│ U2D2│  │ (dxl sync rd)│            │  mapping, safety │◀─────────────── │  + linear   │
 └────────────┘     │  └──────────────┘            │  gripper hybrid  │  q, dq, τ, grip │  4310 grip  │
 ┌────────────┐ USB │  ┌──────────────┐   500 Hz   │  force control   │                 └─────────────┘
 │ Haptic     │◀────┼─▶│ HapticTrigger│◀──────────▶│  haptic render   │
 │ trigger    │ CDC │  │ (COBS proto) │  F_op/F_fb └────────┬─────────┘
 └────────────┘     │  └──────────────┘                     │ samples (all rates)
                    │          … same for the right arm …   ▼
 ┌────────────┐ UVC │  ┌──────────────┐  frames   ┌──────────────────┐   ┌───────────────────────┐
 │ 3× cameras │─────┼─▶│ CameraWorker │──────────▶│    Recorder      │──▶│ recordings/<dept>/<user>│
 └────────────┘     │  │ capture+H.264│ +ts       │ staging→commit   │   │  /<timestamp>/ (raw)   │
                    │  └──────────────┘           └────────┬─────────┘   └──────────┬────────────┘
 ┌────────────┐ USB │  ┌──────────────┐                    │                       ▼ export job
 │ Relay board│◀────┼──│ PowerManager │      ┌─────────────┴──────────┐   ┌───────────────────────┐
 │ + E-stop   │     │  └──────────────┘      │ Orchestrator (state    │   │ LeRobot v3 dataset    │
 └────────────┘     │                        │ machine, health, cal.) │   │ (parquet + mp4)       │
                    │                        └─────────────┬──────────┘   └───────────────────────┘
                    │                          FastAPI REST + WebSocket + MJPEG
                    └──────────────────────────────────────┼─────────────────────────────────────┘
                                                           ▼
                                                   Web UI (browser)
```

## Design principles

1. **Every hardware device has a simulated twin.** `--sim` runs the entire station —
   arms, triggers, cameras, relays — on a laptop. The UI, recorder, exporter and
   calibration wizards are developed and tested against the sims; the same code paths run
   on hardware.
2. **Hard real-time stays out of the web server.** Each arm's control loop runs in its
   own process (`ArmWorker`) and each camera in its own process (`CameraWorker`), so web
   traffic, video encoding and the Python GIL can't add jitter to teleoperation. The
   force-control inner loop runs on the trigger's microcontroller at 1 kHz.
3. **Raw first, datasets derived.** Episodes are recorded at native sensor rates into a
   crash-tolerant raw format (MCAP telemetry + per-camera MP4 with frame timestamps).
   LeRobot datasets are *exports* built from selected raw episodes, so a bad export can
   always be regenerated and nothing is lost to resampling.
4. **Safe by default.** Motor timeouts stay on; a trigger whose host goes silent falls
   back to a passive spring; leaving teleop slow-moves rather than jumps; power-cycling
   parks the follower first; every fault is surfaced with a remediation hint.
5. **Everything observable.** Loop rates, jitter, tracking error, temperatures and every
   log line are streamed to the UI and stored with each episode for debugging.

## Processes and threads

| Unit | Kind | Rate | Owns |
|---|---|---|---|
| `station serve` main | process | — | FastAPI, Orchestrator, DB, Recorder, PowerManager |
| `ArmWorker[left/right]` | process | 200 Hz | Leader Dynamixel bus, haptic trigger serial, follower YAM (i2rt) |
| `CameraWorker[name]` | process | 30 Hz | One camera: capture, preview JPEG, H.264 encode while recording |
| Trigger firmware | MCU | 1 kHz | SEA force loop, lever encoder, trigger servo, buttons, watchdog |
| i2rt motor chain | thread (in ArmWorker) | 250 Hz | DM motor MIT-mode control, gravity compensation |

Workers talk to the main process through `multiprocessing` queues (commands in,
samples/events out) and a shared-memory *state block* (latest snapshot, seqlock-protected)
that the UI streamer reads without blocking the control loop. For tests and debugging,
any worker can run as a thread in the main process (`runtime.workers: thread`).

## Station state machine

```
            power_on            start_arms (checks pass)        teleop on
  OFF ──────────────▶ IDLE ─────────────────────────▶ READY ───────────────▶ TELEOP
   ▲                   ▲  ◀──────── stop_arms ──────────┘  ◀──── teleop off ───┘ │
   │                   │                                                 start   │
   │  power_off        │                                                 record  ▼
   └───────────────────┘                    save ◀── SAVING ◀── save ── RECORDING
                                                                  └── abort ──▶ TELEOP
  any state ── fault / e-stop ──▶ FAULT ── clear_fault ──▶ IDLE
```

Phases (as reported in the API): `off`, `idle`, `starting`, `ready`, `teleop`,
`recording`, `saving`, `stopping`, `fault`.

## Data flow during a recording

1. `recording/start` → Recorder allocates `recordings/.staging/<uuid>/`, tells every
   `CameraWorker` to start encoding and every `ArmWorker` to start streaming samples.
2. ArmWorkers stream samples at the control rate (leader q, trigger pos/force, follower
   q/dq/τ, gripper pos/τ, estimated grip force, rendered force, commands) — written to
   `telemetry.mcap` as they arrive.
3. CameraWorkers write `cameras/<name>.mp4` plus `cameras/<name>.frames.csv`
   (frame index, capture timestamp in `CLOCK_MONOTONIC` ns).
4. `recording/save` → workers flush, Recorder writes `episode.json`, then atomically
   renames staging → `recordings/<department>/<user>/<YYYY-MM-DD_HH-MM-SS>_<task>/`
   and inserts the DB row. `recording/abort` deletes the staging directory.
5. Optional auto-export appends the episode to the department/task LeRobot dataset.

All timestamps share one clock (`time.monotonic_ns()` on the station PC; worker
processes use the same system-wide monotonic clock), so alignment is exact up to
capture latency, which is configurable per camera (`latency_ms`).

---

# API contract (v1)

Base URL `http://<station>:8000`. JSON everywhere. Errors:
`{"detail": "<human message>", "hint": "<what to try>"}` with a 4xx/5xx code.

## WebSocket `/ws/state` — live snapshot at 20 Hz

```jsonc
{
  "t": 12345.678,                     // station monotonic seconds
  "phase": "teleop",                  // off|idle|starting|ready|teleop|recording|saving|stopping|fault
  "phase_detail": "",                 // e.g. fault reason
  "sim": true,
  "session": {"operator_id": 1, "department_id": 2, "task_id": 3},
  "startup": {"steps": [               // last start_arms run
    {"id": "power", "label": "Power on arms", "status": "ok", "message": "", "duration_s": 0.4}
  ]},                                  // status: pending|running|ok|warn|error|skipped
  "arms": {
    "left": {
      "state": "teleop",              // offline|connecting|connected|syncing|teleop|fault
      "fault": null,
      "loop_hz": 200.1, "loop_jitter_ms": 0.21,
      "tracking_error_rad": 0.012,    // max |q_cmd - q_follower| over arm joints
      "leader":   {"ok": true, "q": [0,0,0,0,0,0]},            // rad, follower frame (after calibration)
      "follower": {"ok": true, "q": [6], "dq": [6], "tau": [6],
                   "gripper": 0.73, "gripper_tau": 0.12, "temps_c": [6]},
      "trigger":  {"ok": true, "pos": 0.27, "force_n": 2.1, "render_n": 0.8,
                   "buttons": [false, false], "mode": "render"},  // off|spring|render|position
      "grip_force_n": 11.4,           // estimated follower grip force
      "contact": true
    },
    "right": { /* same */ }
  },
  "cameras": {
    "overhead": {"ok": true, "fps": 29.97, "dropped": 0, "width": 640, "height": 480, "recording": false}
  },
  "recording": {"active": false, "episode_id": null, "elapsed_s": 0.0, "frames": 0, "size_mb": 0.0},
  "power": {"available": true, "estop_ok": true,
            "channels": [{"id": "left_follower", "label": "Left follower 24 V", "on": true}]},
  "calibration": {"active": null, "step": null, "live": {}},   // live readings for the active wizard
  "system": {"cpu_pct": 23.0, "mem_pct": 41.0, "disk_free_gb": 120.5, "disk_total_gb": 500.0}
}
```

## WebSocket `/ws/logs`

Each message: `{"ts": 1729450000.12, "level": "INFO", "source": "arm.left", "message": "..."}`.
On connect the server sends the last 200 lines.

## REST

### Station & session
| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/station` | | `{name, version, sim, arms:["left","right"], cameras:[{name,label}], power_channels:[{id,label}], data_root}` |
| GET | `/api/session` | | `{operator_id, department_id, task_id}` |
| PUT | `/api/session` | same | same |

### Organization (no passwords — station PCs are access-controlled)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/departments` | | `[Department]` |
| POST | `/api/departments` | `{name, color?, description?}` | `Department` |
| PATCH | `/api/departments/{id}` | partial | `Department` |
| DELETE | `/api/departments/{id}` | | `204` (409 if it has episodes) |
| GET | `/api/users` | `?include_inactive=false` | `[User]` |
| POST | `/api/users` | `{name, email?, role, department_ids}` | `User` |
| PATCH | `/api/users/{id}` | partial incl. `active` | `User` |
| GET | `/api/tasks` | `?department_id=` | `[Task]` |
| POST | `/api/tasks` | `{name, description?, department_id?}` | `Task` |
| PATCH / DELETE | `/api/tasks/{id}` | | |

`Department = {id, name, color, description, user_count, episode_count}`
`User = {id, name, email, role: "operator"|"admin", active, department_ids, episode_count, created_at}`
`Task = {id, name, slug, description, department_id}`

### Control
| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/api/control/power` | `{channel: "<id>"\|"all", on: bool}` | relay switching |
| POST | `/api/control/power_cycle` | `{channel: "<id>"\|"all", off_s?: 3}` | parks followers first |
| POST | `/api/control/start_arms` | `{arms?: ["left","right"]}` | runs startup steps (see `startup`) |
| POST | `/api/control/stop_arms` | | slow-moves followers to rest, disconnects |
| POST | `/api/control/teleop` | `{enabled: bool}` | engage = follower eases onto leader pose |
| POST | `/api/control/estop` | | software stop: every arm leaves teleop, followers hold their current pose (PD), triggers go to the passive spring, a take in progress is saved and tagged `fault`, phase → fault |
| POST | `/api/control/clear_fault` | | |
| POST | `/api/control/home` | | followers to rest pose |
| POST | `/api/control/action` | `{action}` | named actions shared by keys, handle buttons and pedals: `start_recording`, `save`, `abort`, `toggle_recording`, `teleop_toggle`, `mark_success`, `mark_failure`, `estop` |

### Recording
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/recording/start` | | `{episode_id}` — requires operator + department + task |
| POST | `/api/recording/save` | `{success?: bool, notes?: str}` | `Episode` |
| POST | `/api/recording/abort` | | `{deleted: true}` |

### Episodes & exports
| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/episodes` | `?department_id&user_id&task_id&success&q&limit=100&offset=0` | `{items:[Episode], total}` |
| GET | `/api/episodes/{id}` | | `Episode` |
| PATCH | `/api/episodes/{id}` | `{success?, notes?, tags?}` | `Episode` |
| DELETE | `/api/episodes/{id}` | | `204` |
| GET | `/api/episodes/{id}/video/{camera}` | | `video/mp4` |
| GET | `/api/episodes/{id}/telemetry` | `?max_points=1500` | `{t:[...], series:{"left.follower.q0":[...], ...}, video_offsets:{camera: s}}`, where `t = 0` is the first video frame |
| POST | `/api/exports` | `{episode_ids, name, fps?: 30}` | `Job` |
| GET | `/api/jobs` / `/api/jobs/{id}` | | `Job = {id, kind, status: queued\|running\|done\|error, progress 0..1, message, result}` |

`Episode = {id, user_id, user_name, department_id, department_name, task_id, task_name,
started_at (ISO), duration_s, frames, cameras:[...], size_mb, success, notes, tags, path, status}`

### Calibration
Calibration is a set of **procedures**, each a list of steps rendered by one generic wizard.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/calibration` | | `{items: [CalItem]}` |
| GET | `/api/calibration/procedures` | | `[Procedure]` |
| POST | `/api/calibration/procedures/{pid}/start` | | `RunState` |
| POST | `/api/calibration/procedures/{pid}/steps/{sid}` | `{inputs?: {...}}` | `RunState` |
| POST | `/api/calibration/procedures/{pid}/commit` | | `CalItem` |
| POST | `/api/calibration/procedures/{pid}/cancel` | | `{}` |
| POST | `/api/calibration/scripts` | `{procedure_id}` | `{filename, path, content}` — standalone script |
| GET | `/api/calibration/files/{item_id}` | | raw YAML of the stored calibration |
| GET | `/api/calibration/charuco.png` | `?square_mm&marker_mm` | printable ChArUco board (300 dpi) |

```jsonc
CalItem   = {"id": "leader_left", "label": "Left leader arm", "kind": "leader",
             "calibrated": true, "updated_at": "...", "updated_by": "Ana", "summary": "offsets ok, max residual 0.8°"}
Procedure = {"id": "leader_left", "title": "Left leader arm", "kind": "leader", "target": "left",
             "description": "...",
             "steps": [{"id": "pose_zero", "title": "Zero pose", "instruction": "…",
                        "action": "capture|auto|confirm|input", "inputs": [{"key": "mass_g", "label": "…", "type": "number"}],
                        "image": "/static/cal/leader_zero.svg"}]}
RunState  = {"procedure_id": "...", "step_index": 1, "steps": [{"id", "status": "pending|ok|error", "message", "data"}],
             "result": {...} | null, "can_commit": false}
```

### Health, logs, hardware
| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{checks: [{id, group, label, status: ok\|warn\|error\|unknown, message, hint}], ran_at}` |
| POST | `/api/health/run` | same, re-run now |
| GET | `/api/logs` | `?limit=500&level=&source=` → `[LogLine]` |
| POST | `/api/hardware/can/reset` | re-initializes CAN interfaces |
| POST | `/api/hardware/arms/{side}/reconnect` | restarts one ArmWorker |
| POST | `/api/hardware/dxl/{side}/scan` | `{found: [{id, model, firmware}]}` |

### Cameras
| Method | Path | Notes |
|---|---|---|
| GET | `/api/cameras/{name}/stream.mjpg` | `multipart/x-mixed-replace` preview (~15 fps, 640 px) |
| GET | `/api/cameras/{name}/snapshot.jpg` | `?overlay=charuco` draws detected board corners |

### Settings
`GET/PUT /api/settings`:
```jsonc
{
  "keybindings": {"start_recording": "KeyR", "save": "KeyS", "abort": "KeyX",
                  "teleop_toggle": "KeyT", "estop": "Escape", "mark_success": "KeyY", "mark_failure": "KeyN"},
  "handle_buttons": {"left_a": "save", "left_b": "abort", "right_a": "start_recording", "right_b": "teleop_toggle"},
  "haptics": {"left":  {"enabled": true, "feedback_gain": 0.25, "max_render_n": 15.0, "spring_n": 1.5, "damping": 0.02,
                        "force_input": true, "input_gain": 4.0, "max_grip_n": 50.0},
              "right": { /* same */ }},
  "recording": {"auto_export": false, "countdown_s": 0, "max_duration_s": 600, "confirm_abort_after_s": 10}
}
```
Key values are `KeyboardEvent.code` strings.
