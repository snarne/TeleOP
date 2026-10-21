# Haptic grip feedback: station-side control

This page covers the station side of the haptic loop: estimating the follower's grip force
and coupling it to the trigger. The trigger's mechanism, firmware force loop, electronics
and CAD are in [hardware/haptic-trigger.md](hardware/haptic-trigger.md).

```
                 station ArmWorker (200 Hz)                                   HGM firmware (1 kHz)
 ┌──────────────────────────────────────────────────────────┐            ┌───────────────────────────┐
 │ YAM gripper τ, v ──▶ GripForceEstimator ──▶ F_grip ──┐    │  SETPOINT  │ F_des = spring(p) + F_fb  │
 │                       (friction-compensated, LPF)    │    │ ─────────▶ │         + b·ṗ             │
 │                                                      ▼    │            │ θ_s* = θ_l − F_des·r/k_θ  │──▶ XC330
 │                 GripperCoupler ── F_fb = g_fb·F_grip ─────│            │ (series-elastic: the      │
 │   trigger p, F_op ◀────────────────────────────────────── │ TELEMETRY  │  spring sets the force)   │◀── AS5600
 │        │                                                  │ ◀───────── │ p, F_op = k_θ·δ / r       │
 │        ▼                                                  │            └───────────────────────────┘
 │  gripper command x* ──▶ i2rt PD gripper (kp = 20 N·m/rad) │
 └──────────────────────────────────────────────────────────┘
```

## Estimating the follower's grip force

The linear_4310 gripper has no force sensor, but its DM4310 motor reports effort τ. The
lead screw maps 6.57 rad of motor travel to 96 mm of jaw travel, so:

```
F_grip = G · max(0, |τ| − τ_f(v))      G = 6.57 / 0.096 ≈ 68.4 N per N·m
```

* **Friction:** `τ_f` is subtracted in full while the jaws move (|v| > 0.05 s⁻¹) and only
  25% when they're still, because moving friction otherwise shows up as phantom grip force.
* **Filtering:** a first-order low-pass filter at 25 Hz takes out motor current ripple
  while adding only about 6 ms of lag.
* **Contact detection:** contact starts above 2.5 N with the jaws still and ends below
  1.2 N. The hysteresis stops it chattering.
* **Calibration:** the gripper-force wizard replaces the nominal G and τ_f with values fit
  against a force gauge.

## Design intent: the operator chooses the force, the data records it

The haptic system never limits the gripper. A full squeeze commands the gripper's **full
force** (`arms.<side>.follower.max_grip_force_n`), and any lighter squeeze commands a
proportionally lighter grip, so operators can use the whole range and grip each object as
it needs. Force feedback is only a *sensation*: its scale (`feedback_gain`) changes what
the operator feels, never what the follower does. Every take records the operator's
force command, the follower's grip force and the operator's finger force. The LeRobot
action includes the grip-force command, so a policy learns *how hard* to grip each object,
not just when to close.

## Feeling it like a hand

Human grip sense has two channels, and the station reproduces both:

| Hand | Station | Signal |
|---|---|---|
| **Slow-adapting** receptors: sustained pressure ("how hard am I holding this?") | trigger push-back from the series-elastic loop | follower grip force, continuously |
| **Fast-adapting** receptors: the instant of touch, slip, release | vibrotactile cues from the LRA in the trigger pad (HGM v1.1) | contact onset → TAP, slip → SLIP bursts, release → tick |

**Pressure mapped the way people perceive force.** People sense force ratios, not
newtons (Weber's law; perceived magnitude ≈ force^0.6, Stevens). A linear scale makes light
holds disappear and saturates heavy ones. The default *natural feel* mapping is

```
felt = max_render_n · (F_grip / F_full)^0.6           F_full = force at a full squeeze (the gripper's full force)
```

| follower grip | 2 N | 5 N | 10 N | 20 N | 35 N | 50 N |
|---|---|---|---|---|---|---|
| felt (sim, measured) | 2.2 N | 3.1 N | 4.7 N | 7.0 N | 9.7 N | 12 N |

A 2 N hold is clearly felt, every increase in grip feels like an increase, and the
gripper's full force still fits within the trigger's range. In contact, the trigger's
return spring is switched off, so what you feel is the grip force alone (above the
spring's 1.05 N mechanical preload).

**The force comes from the follower's fingertips.** When the follower has fingertip
sensors (FGS, [hardware/fingertip-sensor.md](hardware/fingertip-sensor.md)), the true
contact force at the pads drives the feedback, the contact detection and the force
regulation, and their slip band drives the slip cue. Without them the station uses the
motor-torque estimate below and infers slip from a sudden drop in grip force. The UI
shows which source is active ("Follower grip · fingertips").

## Two coupling modes

**Position–force (default), with a contact-relative force law.** In free space the gripper
position follows the trigger. When the jaws make contact (at trigger position `p_c`), the
station switches from commanding jaw *position* to commanding grip *force*, proportional
to how far past contact the operator squeezes:

```
free space:       x* = map(p)
contact at p_c:   F* = clamp(max_grip_n · ((p − p_c)/(1 − p_c))^curve, 2 N, max_grip_n)     x* = x_measured − F*/K_x
render, always:   F_fb = g_fb · F_grip            (capped at max_render_n)
release:          p < p_c − 0.03  →  back to position following (the jaws open with the trigger)
```

Why not keep commanding jaw position past contact? The i2rt gripper's PD is very stiff
(≈ 94 N/mm at the jaws). Mapped through the trigger, that stiffness would ask the trigger
to render hundreds of N/mm, far beyond the ≈ 1.5 N/mm the series-elastic spring can
render, and with 10–20 ms of loop delay it would chatter. With the force law, the stiffness
the operator feels past contact is `g_fb · max_grip_n / remaining travel`, for example
0.25 · 40 N / 15 mm ≈ 0.67 N/mm, which is well inside what the trigger can render. So:
*squeeze deeper → grip harder → feels harder*. See
[hardware/haptic-trigger.md §5.3](hardware/haptic-trigger.md) for the derivation. While
the station regulates force, i2rt's own stall limiter is switched off (it would fight the
regulation) and the station's `max_grip_n` cap applies instead. It is switched back on
the moment contact ends or teleop stops.

**Force command (`force_input: true`).** In free space this mode behaves the same. On
contact, the trigger switches to POSITION mode at the contact point: it becomes a firm
wall whose compliance is the series-elastic spring. The SEA then measures how hard the
operator pushes against that wall, and the follower regulates grip force to

```
F_target = clamp(g_in · F_op, 0, max_grip_n)      x* = x_measured − F_target / K_x
K_x = G · kp · stroke ≈ 68.4 · 20 · 6.57 ≈ 9.0 kN per unit opening
```

The force target is slew-limited (400 N/s), so a sudden squeeze can't crush an object.
Holding the push below `release_n` for 150 ms leaves force mode, and the gripper opens
with the trigger again. While force mode is active, i2rt's own stall limiter is turned
off, because it would otherwise force the grip to its 50 N setpoint.

Why not command grip force from the measured F_op while rendering grip force back? Because
an SEA under force control measures the force it renders, not the operator's intent. At
rest F_op equals the rendered force, which closes an algebraic loop with gain
`feedback_gain × input_gain` that drifts or runs away. Force mode avoids this: it stops
rendering grip force and turns the trigger into a wall, so F_op is the operator's push.
In position–force mode, F_op is recorded as an operator-effort signal only.

## Stability and safety notes

* **Loop delay** is about 5 ms (one 200 Hz tick) plus USB latency (≤ 1 ms). With
  `g_fb ≤ 0.5` and the SEA's mechanical compliance, the loop is passive in practice. The
  firmware's damping term `b·ṗ` adds margin, so raise *damping* first if a trigger
  chatters.
* **Watchdog:** if the trigger receives no setpoint for 100 ms (a dead server or a USB
  unplug), it falls back to a passive spring and flags WATCHDOG.
* **Faults:** on any arm fault the trigger is set to SPRING and the follower holds its pose.
* **Caps:** the rendered force is capped by `max_render_n` (default 12 N) and by the
  firmware's servo current limit (1.2 A). The grip force is capped by `max_grip_n`.

## Tuning (Settings → Haptics)

| Setting | Effect | Start at |
|---|---|---|
| feedback gain | felt force per newton of grip | 0.25 |
| max render force | cap on trigger force | 12 N |
| spring / preload | free-space return spring (N per unit travel / N at released; the HGM's mechanical preload is 1.05 N) | 1.5 / 1.2 |
| damping | resists fast trigger motion, stabilizes | 0.02 N·s |
| force input | enables force-command mode | off |
| input gain | grip force per newton of push (force mode) | 4 |
| grip force at a full squeeze | full squeeze → this force (defaults to the gripper's full force) | `max_grip_force_n` |
| light-grip precision (`force_curve`) | 1 = linear; > 1 spreads light forces over more trigger travel | 1.0 |

Everything in the loop is recorded: `trigger_force`, `trigger_render`, `grip_force`,
`target_force` and `force_mode`. A policy can therefore learn grip force as well as grip
position, and transparency can be checked offline, for example by plotting
`trigger_render` against `trigger_force`.
