# Getting started

## 0 · Try it without hardware (5 minutes, any Linux or macOS machine)

```bash
git clone <this repo> teleop-station && cd teleop-station
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
(cd ui && npm ci && npm run build)
station serve --sim            # → http://localhost:8000
```

Everything runs simulated: two arms with a scripted operator doing pick-and-place, haptic
triggers, three synthetic cameras and a relay board. Work through Start Arms → Calibration
→ Engage → Record → Save → Episodes → Export. `make e2e` runs the same tour automatically.

## 1 · Station PC

* Ubuntu 22.04 or 24.04, x86-64.
* **CPU:** 6 or more cores (two 200 Hz control processes, three video encoders, the UI).
* **RAM:** 16 GB.
* **Storage:** an SSD with ≥ 500 GB free. Raw episodes take roughly 1–2 MB/s (≈ 5 GB per hour) with three
  640×480 cameras.
* **USB:** at least two separate USB controllers for the cameras, a powered USB 3 hub for
  the U2D2s/HGMs, and the two CANables plugged directly into the PC. Check with `lsusb -t`.
* A GPU isn't needed for teleop or recording.

```bash
bash scripts/setup_ubuntu.sh     # apt, venv, I2RT SDK, LeRobot, groups, udev, sudo rule for CAN, UI build
# log out + in
```

## 2 · Hardware bring-up checklist

Bring up one subsystem at a time and run `station doctor` after each step.

1. **Followers (YAM).** Power each arm from its 24 V supply. Plug in each CANable and give
   it a persistent name (`can_follower_l`, `can_follower_r`) by following
   [scripts/udev/README.md](../scripts/udev/README.md). Check with
   `python third_party/i2rt/i2rt/robots/motor_chain_robot.py --channel can_follower_l --gripper linear_4310`:
   the arm should float in zero-gravity mode.
2. **Leaders (Dynamixel).** Plug in each U2D2 and run
   `station dxl scan --port /dev/serial/by-id/<…>`. IDs 1–6 should answer (7 is the legacy
   trigger). Put the by-id path in `arms.<side>.leader.port`.
3. **Triggers.** Keep the original trigger servo (`trigger.backend: dynamixel_legacy`)
   until the [Haptic Grip Module](hardware/haptic-trigger.md) is built. Then flash the
   firmware, add the udev rule, and switch to `backend: hgm`.
4. **Cameras.** `v4l2-ctl --list-devices` and `ls -l /dev/v4l/by-id/`. Put the paths in
   `cameras.*.device`. Check that each camera holds 30 fps at 640×480 MJPG:
   `v4l2-ctl -d <dev> --list-formats-ext`.
5. **Power and e-stop.** Wire them as in [hardware/electronics.md](hardware/electronics.md),
   set `power.backend: numato` and the port, then try `station power cycle left_leader`.
6. **Run it.** `station serve`, then open `http://localhost:8000`. In Organization, add
   your departments, people and tasks. In Calibration, do the leader arms first, then the
   triggers, gripper force and cameras.

## 3 · Configuration reference

All configuration lives in `config/station.yaml`; every field is documented inline. The
fields you change most often:

| Key | What |
|---|---|
| `station.data_root` | where recordings, datasets, calibration and the database live |
| `arms.<side>.follower.can_channel / arm_type / gripper_type` | YAM bus and variant |
| `arms.<side>.leader.port / baudrate / joint_ids` | leader Dynamixel bus |
| `arms.<side>.trigger.backend` | `hgm`, `dynamixel_legacy`, or `none` |
| `cameras.<name>.device / width / height / fps / fourcc` | capture settings |
| `power.backend / port / channels / estop_input` | relay board and e-stop sensing |
| `runtime.control_hz` | teleop loop rate (200 by default) |
| `export.python` | an interpreter with `lerobot` installed, if not the station's own |
| `inputs` | USB foot pedals → actions |

Operator-facing settings (keybindings, handle buttons, haptic gains, recording limits) are
edited in the UI and stored in the station database. They are not in the YAML.
