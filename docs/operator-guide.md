# Operator guide

This is the day-to-day workflow at the station. Setting up a new PC is covered in
[getting-started.md](getting-started.md).

## The flow

```
 Power On ──▶ Start Arms ──▶ Engage Teleop ──▶ Record ──▶ Save ✓  /  Abort ✗ ──▶ Record …
                 │                                │
                 └─ checklist must be green/amber  └─ needs operator + department + task selected
```

1. **Pick yourself.** In the top bar, choose your name, your department and the task.
   Every episode is filed under `recordings/<department>/<you>/<date_time>_<task>/`.
2. **Start Arms.** The checklist covers power, CAN buses, leader buses, triggers,
   followers, calibration, cameras and a pose check. Green means ok. Amber means it will
   work but needs attention (for example, no calibration yet). Red stops the start, and
   the hint next to it says what to do.
3. **Engage Teleop** (`T`). Hold the leader handles. The followers ease onto the leaders'
   pose over 1–6 seconds, depending on how far apart they are, then track them.
4. **Record** (`R`, or a handle button). Cameras and arm telemetry start together. The
   timer and frame count appear in the top bar.
5. **Save** (`S`) or **Abort** (`X`). Saving can be marked as a success (`Y`) or a failure
   (`N`) first. Abort deletes the take. If the take is longer than 10 s, press `X` twice to
   confirm, so a stray key press can't throw away a long take.
6. Repeat 4–5. When you're done, **Disengage** (`T`) and **Stop Arms**. The followers
   park at their rest pose before their motors turn off.

## Keys and buttons

| Action | Key (default) | Handle button (default) |
|---|---|---|
| Start recording | `R` | right A |
| Save | `S` | left A |
| Abort / delete take | `X` (twice if > 10 s) | left B |
| Teleop on/off | `T` | right B |
| Mark success / failure | `Y` / `N` | — |
| **E-stop (software)** | `Esc` | — |

You can rebind every key and handle button in **Settings**. A USB foot pedal can be bound
in `config/station.yaml` → `inputs:`. It works even when the browser isn't focused.

## Feeling the grip

With the Haptic Grip Module installed, the trigger pushes back with a force proportional
to how hard the follower is gripping (Settings → Haptics → *feedback gain*). The default,
0.25, means 20 N of grip feels like 5 N on your finger.

* **Position mode** (default): the gripper follows the trigger until it touches something.
  From there, squeezing further sets *how hard* it grips. A full squeeze uses the gripper's
  full force, so grip each object the way it should be gripped: what you choose is what
  the robot learns. You feel the grip force in the trigger (scaled, so heavy grips stay
  comfortable). Open the trigger to let go.
* **Touch and slip cues:** you feel a crisp tap the moment the follower touches something,
  a buzz while the object is slipping (grip a little harder), and a soft tick when it lets
  go. Light holds are clearly felt, because the feedback follows how hands sense force.
* **Force mode** (*force input* on): once the follower touches something, the trigger
  becomes a firm stop and *how hard you push* sets the grip force (× *input gain*), up to
  *max grip force*. Relax your finger to release. Use this for fragile or squishy objects.

## When something goes wrong

* **Red banner / FAULT.** The banner text says what happened, for example
  `left arm: follower can't keep up: joint 3 is 40° behind`. The follower holds its pose
  and the trigger relaxes. A recording in progress is **saved and tagged `fault`**, so
  you can review what happened. Fix the cause, then **Clear fault**.
* **E-stop (hardware).** Arm power is cut immediately, so the followers will sag onto the
  table. Twist to release, then Start Arms again.
* **A camera tile is black.** Check Hardware → health. The usual causes are a USB cable
  or too many cameras on one USB controller.
* Everything else: [troubleshooting.md](troubleshooting.md).

## Safety rules

* Keep the followers' workspace clear of people while teleop is engaged.
* Never disable the YAM motor timeout (I2RT's `set_timeout.py`) on a shared station.
* Power-cycle from the UI (Hardware → Power), not by pulling plugs: the UI parks the arm first.
* The software e-stop (`Esc`) is a convenience. The red mushroom button is the safety device.
