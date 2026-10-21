# Haptic Grip Module (HGM): design brief

This is the original engineering brief the CAD, electronics and firmware started from. The full
write-up with calculations, renders and assembly steps is in
[haptic-trigger.md](haptic-trigger.md).

> **Where the final design differs from this brief:** the detailed design uses **one**
> preloaded compression spring (7.86 N/mm, 20 mm from the pivot) against a printed
> backstop, rather than a symmetric pair. That gives k_θ = 3.14 N·m/rad and a 1.05 N preload
> at the finger. The station uses the contact-relative force law in haptic-trigger.md §5.3.
> Where they disagree, haptic-trigger.md and `hardware/cad/params.py` are authoritative.

## Problem

Today the leader handle's trigger is a Dynamixel run as a weak spring: it re-opens when
released, but the operator can't feel what the follower gripper is doing, and the station
can't tell how hard the operator is squeezing. The goals are:

1. **Sense** how hard the operator squeezes (operator force `F_op`, newtons) so the
   follower's grip force can follow the hand, not only the trigger position.
2. **Render** the follower's actual grip force back to the finger as resistance
   (`F_fb`), so grasping a sponge feels different from grasping a block.
3. Keep the leader **light and easy to move**. Haptics stay at the trigger only, and the
   module's mass target is ≤ 130 g including the actuator.

## Chosen concept: series-elastic trigger

```
 finger ─▶ trigger lever ──[ spring pack, k_θ ]── drive disc ── servo horn ── XC330 servo
             │  θ_l (AS5600 magnetic encoder)                     θ_s (servo's own encoder)
             ▼
   τ_spring = τ_p + k_θ · (θ_l − θ_s − δ₀)      F_op = τ_spring / r_f     (τ_p: spring preload against the backstop)
```

* The trigger lever and the servo output share one pivot axis. The servo never touches the
  lever directly: it drives a **drive disc** whose tab sits between **two preloaded
  compression springs** in a pocket on the lever (a series elastic actuator, after Pratt &
  Williamson, 1995).
* The lever angle `θ_l` is read by an **AS5600** sensing a diametric magnet in the lever
  hub. The servo angle `θ_s` is the XC330's own 12-bit encoder. Spring deflection × stiffness
  gives the finger force directly. There's no strain-gauge amplifier, no drift, and no
  gear friction in the measurement.
* **Force control is position control:** to render force `F_des`, the MCU commands the
  servo to `θ_s* = θ_l − F_des·r_f / k_θ`. The servo's stiff internal position loop sets the
  spring deflection, and the spring sets the force. The compliance keeps the loop stable
  against a stiff, position-controlled gearmotor and keeps the finger safe.

### Trade study (summarized in the full doc)

| Option | Senses F_op | Renders F_fb | Stability with geared servo | Cost | Verdict |
|---|---|---|---|---|---|
| Servo current only (today) | poor: gear friction and hysteresis | weak, open-loop | ok | $0 | rejected |
| FSR on trigger face | nonlinear, ±25% | no | n/a | $8 | rejected |
| Load cell + HX711/NAU7802 in the linkage | excellent | yes | **poor**: stiff sensor + stiff servo chatters | $15 | backup |
| **Series elastic (springs + AS5600)** | good (±0.2 N) | yes, closed loop | **excellent** | $10 | **chosen** |
| Voice-coil / BLDC direct drive | excellent | excellent | excellent | $60–120 + driver | future v2 |

## Key components

| Function | Part | Notes |
|---|---|---|
| Actuator | ROBOTIS **XC330-M288-T** | Same 20×34×26 mm, 23 g body as the XL330. Metal gears, 0.93 N·m stall at 5 V (1.80 A), 4 Mbps TTL. Runs on the leader's existing 5 V supply. |
| Lever encoder | **AS5600** breakout + 6×2.5 mm diametric N52 magnet | 12-bit, I²C at 1 MHz |
| MCU | **Seeed XIAO RP2040** | 21×17.5 mm, USB-C, onboard RGB LED; runs the 1 kHz loop |
| Half-duplex TTL | **74LVC2G241** at 3.3 V + 10 k pull-up | Canonical Dynamixel half-duplex interface. LVC inputs tolerate 5 V. |
| Servo power gate | P-MOSFET (AO3401A) + NPN driver; 1.5 A polyfuse; SMBJ6.0A TVS; 470 µF bulk | MCU enables servo power only after self-test |
| Buttons | 2× Omron D2F-01 micro switches (thumb A/B) | Bindable: save / abort / record / teleop |
| Springs | 2× compression springs, OD ≈ 5 mm, rate ≈ 6–10 N/mm | Stiffness `k_θ` calibrated per module |
| Bearings | 6700ZZ (10×15×4) for the lever hub, MR63ZZ (3×6×2.5) pilot | |

**Power:** the servo draws from the leader arm's 5 V Dynamixel bus through the free
JST-EH port on joint 6 (GND and VDD only; DATA isn't connected). The MCU runs from USB.
Grounds are common. The leader's 5 V supply must handle ≥ 6 A (see electronics.md for the budget).

**Target numbers:** finger radius `r_f` = 45 mm, lever travel 30°, rendered force 0–15 N
peak (12 N default cap), force resolution ≈ 0.15 N, spring deflection ≤ ±12° at full force,
local loop 1 kHz, telemetry 500 Hz, host setpoints ≥ 100 Hz, watchdog 100 ms.

## Control law (firmware, 1 kHz)

```
p        = (θ_l − θ_open) / (θ_closed − θ_open)          trigger position 0 = open … 1 = squeezed
ṗ        = filtered derivative of p
F_op     = (τ_p + k_θ (θ_l − θ_s − δ₀)) / r_f              operator squeeze force (+ = squeezing; 0 on the open stop)
F_des    = clamp(spring_min + spring_n · p + F_haptic + b · ṗ, τ_p/r_f + 0.05, min(F_max, 15 N))
θ_s*     = θ_l − δ₀ − (F_des · r_f − τ_p) / k_θ − K_i ∫(F_des − F_op) dt     (anti-windup, clamped)
θ_s*     = clamp(θ_s*, θ_open − margin, θ_closed + margin)
```

Modes: `0 OFF` (torque disabled), `1 SPRING` (F_haptic = 0, the passive return spring),
`2 RENDER` (F_haptic from the host), `3 POSITION` (host commands p, used for
calibration and self-test). In RENDER, if no setpoint arrives for 100 ms, the module
drops to SPRING and sets the WATCHDOG flag.

## Station-side haptic loop (ArmWorker, 200 Hz)

```
τ_g       = follower gripper motor effort (N·m, from i2rt get_observations()["gripper_eff"])
F_grip    = max(0, |τ_g| − τ_friction(v)) · G_grip            G_grip = motor_stroke / gripper_stroke = 6.57/0.096 ≈ 68.4 N/N·m (linear_4310), calibrated
contact   = F_grip > F_contact and |v_grip| < v_still           (with hysteresis)
F_haptic  = clamp(feedback_gain · F_grip, 0, max_render_n)      sent to the trigger
Gripper command: free space → position follows p;
                 in contact and force_input on → target force = input_gain · F_op (≤ max_grip_n),
                 realized through i2rt's gripper PD: x* = x − F_target / k_x,eff
```

## As-built numbers (see haptic-trigger.md)

k_s = 7.86 N/mm at R_s = 20 mm → **k_θ = 3.144 N·m/rad** (1.22 N/° at the finger). Preload
0.3 mm → τ_p = 0.047 N·m (1.05 N at the finger), so the default `spring_min_n` is 1.2 N.
15 N needs 11.5° of deflection; the overload rim sits at 13.2° (17.1 N). Module mass is
≈ 128 g. Firmware param 13 `preload_nm` extends the v1 parameter table.

## Serial protocol (USB CDC)

The full spec is in [../protocol/haptic-protocol.md](../protocol/haptic-protocol.md):
COBS-framed packets with a 0x00 delimiter and a CRC-16/CCITT-FALSE trailer.
