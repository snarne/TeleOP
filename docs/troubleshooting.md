# Troubleshooting

Start with **`station doctor`** (or **Hardware → Health → Run checks**). Every check prints
what it found and the fix. The table below covers what the checks can't see.

| Symptom | Likely cause | Fix |
|---|---|---|
| Loop rate ≈ 60 Hz instead of 200 | U2D2 USB latency timer at 16 ms | install `scripts/udev/99-teleop-station.rules`, replug; `cat /sys/bus/usb-serial/devices/ttyUSB0/latency_timer` → `1` |
| "Dynamixel IDs [5] did not answer" | loose daisy-chain cable, wrong baud, or a servo in error | Hardware → Scan; reseat the JST cable at that joint; try `station dxl scan --port … --baud 57600` |
| Follower moves the wrong way on one joint | leader joint mapped with the wrong sign | rerun Calibration → Leader arm (it detects and fixes signs) |
| Follower offset by a constant angle | leader re-horned since calibration | rerun the leader calibration |
| "follower can't keep up: joint N is X° behind" | collision, joint limit, overheated or errored motor | check the arm; Hardware → logs; I2RT `motor_check.py`; let it cool |
| CAN interface missing | CANable unplugged, or the udev name doesn't match the config | `ip link`; scripts/udev/README.md |
| CAN interface down | not brought up after a replug | Hardware → Reset CAN (needs the sudo rule from `setup_ubuntu.sh`) |
| Gripper doesn't open at start | I2RT gripper auto-calibration needs free travel | clear the fingers, Hardware → Reconnect arm |
| Camera tile black or < 25 fps | bandwidth: several cameras on one USB controller | use MJPG (`fourcc: MJPG`), lower resolution, or spread the cameras across ports (`lsusb -t`) |
| Two identical cameras swap places | `/dev/videoN` numbering | use `/dev/v4l/by-path/…` (tied to the physical port) |
| Trigger feels dead and the trigger step shows "continuing without haptics" | HGM not found | check `/dev/hgm_<side>` exists; udev rule; USB-C cable is a data cable |
| Trigger buzzes or chatters | gains too high for your spring | lower *feedback gain* or raise *damping* in Settings; recalibrate stiffness |
| Trigger pushes too weakly | force capped by `max_render_n` or the servo current limit | raise *max render force* (≤ 15 N); check the leader 5 V supply is ≥ 6 A |
| Grip force reads high while the gripper moves freely | friction not calibrated | Calibration → Gripper force |
| Export fails: "lerobot is not installed" | the exporter runs as a subprocess | `pip install "lerobot[dataset]"`, or set `export.python` to a venv that has it |
| Episode saved with tag `fault` | a fault happened mid-take; the take was auto-saved | review it (Episodes → telemetry), or delete it |
| `recordings/.crashed/…` exists | the server was killed mid-recording | inspect or delete; these are never imported automatically |

## Looking deeper

* **Live logs:** Hardware → Logs. Filter by source (`arm.left`, `camera.overhead`,
  `orchestrator`, …). Every worker's log is collected here.
* **Inside a recording:** open `telemetry.mcap` in Foxglove. Plot
  `/left/sample.q_cmd[2]` against `/left/sample.follower_q[2]` to see tracking, and
  `trigger_force` against `trigger_render` to see haptic transparency. The `/log` panel
  shows what every process said during the take.
* **Without hardware:** `station serve --sim` runs the identical code paths against
  simulated arms, triggers, cameras and relays, which is handy for reproducing UI or
  recording bugs.
* **Threads instead of processes:** `station serve --threads` runs every worker inside one
  process, so a debugger can step through the control loop.
