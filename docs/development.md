# Development

## Code tour

```
station/
  cli.py               `station …` commands
  config.py            pydantic models for config/station.yaml
  orchestrator.py      phase state machine, worker supervision, flows, snapshots
  api.py               FastAPI: REST + /ws/state + /ws/logs + MJPEG
  ipc.py               lock-free shared memory (seqlock blocks, JPEG slots)
  db.py                SQLite (SQLModel): departments, users, tasks, episodes, calibration log, settings
  health.py            `station doctor` checks
  logbus.py            log fan-out to the UI and into recordings
  input_devices.py     USB foot pedals (evdev) → actions
  hardware/
    leader.py          DynamixelLeader, SimLeader, SimOperator, leader → follower mapping
    follower.py        I2RTFollower (wraps i2rt get_yam_robot), SimFollower
    trigger.py         HGMTrigger, LegacyTrigger, SimHGM (physics + firmware control law), NoTrigger
    haptic_protocol.py HGM wire protocol (COBS + CRC-16), shared with the firmware tests
    power.py           Numato / LCUS / Modbus-TCP relays, e-stop sensing, SimRelay
  teleop/
    arm_worker.py      per-arm process: 200 Hz loop, engage/track/safety, samplers, commands
    gripper.py         grip-force estimator, trigger ↔ gripper coupling modes
  cameras/worker.py    per-camera process: capture, timestamps, previews, H.264
  recording/
    recorder.py        staging → commit, MCAP telemetry writer
    raw_episode.py     read raw episodes back (exporter, UI plots)
    lerobot_export.py  raw → LeRobot v3 (run as a subprocess)
  calibration/
    procedures.py      leader / trigger / gripper / camera wizards
    charuco.py         board, detection, calibration, synthetic views
    generator.py       standalone script generator (+ templates/)
ui/                    React + TypeScript web UI (served from ui/dist)
hardware/              CAD (CadQuery), electronics (schematics, BOM), HGM firmware
tests/                 unit, in-process integration, end-to-end
```

## Adding a hardware backend

Every device class is a small interface with a simulated twin. To add, for example, a
different leader arm:

1. Subclass `LeaderBase` in `station/hardware/leader.py` and implement `connect()`,
   `read() -> LeaderReading`, `scan()` and `close()`.
2. Add a `backend` literal to `LeaderConfig` and construct the class in `ArmWorker._build()`.
3. Add a health check in `health.py` (port present, permissions, and anything else a
   person would have to check by hand).

Followers (`FollowerBase`), triggers (`TriggerBase`), relay boards (`RelayDriver`) and
cameras (`Source`) work the same way.

## Tests

```bash
make test        # unit + in-process API integration (thread workers), about 45 s
make sim & make e2e   # full end-to-end tour against a real server with worker processes
make firmware-test    # HGM protocol: C++ against the shared test vectors
```

The protocol test vectors (`tests/vectors/haptic_protocol.json`) are generated from the
Python codec, and both the Python and C++ tests check them, so the wire format can't drift
between host and firmware.

## Conventions

* Radians, N·m and newtons everywhere. The gripper and trigger are normalized to 0..1.
* Every timestamp is `time.monotonic()` / `CLOCK_MONOTONIC`, shared by all processes.
* The control loop never blocks. Multi-sample measurements (calibration) are collected by
  tick-based samplers, never with `sleep()` in the loop.
* Errors raised to the UI are `StationError(detail, hint)`. Always say what to do next.
