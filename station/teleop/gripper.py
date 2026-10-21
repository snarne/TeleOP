"""Grip-force estimation and trigger ↔ gripper coupling.

Two coupling modes (Settings → Haptics → "force input"):

* **position–force** (default): in free space the follower gripper position follows the
  trigger. Once the jaws touch something (at trigger position p_c), the trigger commands
  grip *force* proportional to squeeze depth, `F* = max_grip_n · (p − p_c)/(1 − p_c)`,
  regulated by the station. The trigger always renders `feedback_gain × F_grip`, so
  squeezing deeper grips harder and feels harder. The felt stiffness past contact,
  `feedback_gain · max_grip_n / remaining travel`, stays below what the series-elastic
  trigger can render, so the loop can't chatter (see docs/hardware/haptic-trigger.md §5.3).

* **force command** (`force_input: true`): identical in free space. When the follower
  makes contact, the trigger turns into a firm wall at the contact position (HGM POSITION
  mode), and the series-elastic sensor measures how hard the operator pushes against it.
  The follower then regulates grip force to `input_gain × F_op`, capped at `max_grip_n`,
  independent of object stiffness. This suits delicate or deformable objects. Relaxing the
  push below `release_n` for 150 ms returns to position mode and opens with the trigger.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Tuple

import numpy as np


@dataclass
class GripForceEstimator:
    gain_n_per_nm: float = 68.4
    tau_friction_nm: float = 0.12     # extra effort needed to move the jaws (free air)
    contact_on_n: float = 2.5
    contact_off_n: float = 1.2
    still_speed: float = 0.5
    filter_hz: float = 25.0
    tau_offset_nm: float = 0.03       # effort reading at zero grip force with the jaws still (calibrated)
    force_n: float = 0.0
    contact: bool = False
    _prev_t: float = -1.0

    def update(self, t: float, tau: float, vel: float) -> Tuple[float, bool]:
        """tau = gripper motor effort (N·m), vel = normalized gripper velocity (1/s)."""
        # Coulomb friction appears while the jaws move; subtract it, then convert torque → force.
        moving = abs(vel) > 0.05
        f = max(0.0, abs(tau) - (max(self.tau_friction_nm, self.tau_offset_nm) if moving else self.tau_offset_nm))
        f *= self.gain_n_per_nm
        dt = 0.005 if self._prev_t < 0 else max(t - self._prev_t, 1e-4)
        self._prev_t = t
        a = 1.0 - math.exp(-2 * math.pi * self.filter_hz * dt)
        self.force_n += a * (f - self.force_n)
        if not self.contact and self.force_n > self.contact_on_n and abs(vel) < self.still_speed:
            self.contact = True
        elif self.contact and self.force_n < self.contact_off_n:
            self.contact = False
        return self.force_n, self.contact


@dataclass
class HapticSettings:
    enabled: bool = True
    feedback_gain: float = 0.25
    max_render_n: float = 12.0
    spring_n: float = 1.5
    spring_min_n: float = 1.2   # the HGM spring preload is 1.05 N at the finger
    damping: float = 0.02
    force_input: bool = False
    input_gain: float = 4.0
    max_grip_n: float = 50.0     # force at a full squeeze (defaults to the gripper's full force)
    force_curve: float = 1.0     # >1 gives finer control of light grips: F* = max · depth^curve
    release_n: float = 0.8
    # How grip force is presented to the finger. "perceptual" (default) follows how people sense
    # force (Weber/Stevens: ratios, not newtons): felt = max_render · (F / F_full)^exponent, so a
    # light hold is clearly felt and the gripper's full force still fits in the trigger's range.
    # "linear": felt = feedback_gain · F (saturates at max_render_n).
    feedback_mode: str = "perceptual"
    feedback_exponent: float = 0.6
    # Fast-adapting touch: vibrotactile cues on contact onset, slip and release (HGM v1.1 LRA)
    cues_enabled: bool = True
    cue_strength: float = 0.8
    slip_hf_n: float = 0.15      # slip-band RMS (fingertip sensors) above which the object is slipping
    slip_jaw_speed: float = 0.05  # jaw motion (opening fraction/s) above which the slip band is ignored

    @classmethod
    def from_dict(cls, d: dict) -> "HapticSettings":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def felt_force(s: "HapticSettings", grip_force: float) -> float:
    """Force rendered on the operator's finger for a given follower grip force."""
    f = max(grip_force, 0.0)
    if s.feedback_mode == "linear":
        return min(s.feedback_gain * f, s.max_render_n)
    full = max(s.max_grip_n, 1.0)
    return float(s.max_render_n * min(f / full, 1.0) ** max(s.feedback_exponent, 0.1))


@dataclass
class TouchEvents:
    """Fast-adapting touch channel: turns the follower's contact state into discrete cues, the
    way skin signals the *moment* of contact and slip on top of sustained pressure.

    Slip comes from the fingertip sensors' slip band when present; otherwise it is inferred
    from a sudden drop in grip force while the operator isn't releasing."""

    slip: bool = False
    _contact: bool = False
    _last_slip_cue: float = -1.0
    _f_hist: list = field(default_factory=list)

    def update(self, t: float, contact: bool, grip_force: float, hf: float, has_hf: bool,
               releasing: bool, s: "HapticSettings", jaw_speed: float = 0.0):
        """Returns (cue or None, amplitude 0..255)."""
        from station.hardware.haptic_protocol import Cue

        amp = int(255 * min(max(s.cue_strength, 0.0), 1.0))
        cue = None
        if contact and not self._contact:
            cue = Cue.TAP
        elif self._contact and not contact:
            cue = Cue.RELEASE
            amp = amp // 2
        self._contact = contact
        self._f_hist.append((t, grip_force))
        while self._f_hist and t - self._f_hist[0][0] > 0.06:
            self._f_hist.pop(0)
        if contact and has_hf:
            # Closing the jaws or a fast squeeze also excites the slip band, so only trust it
            # while the jaws are (nearly) still.
            self.slip = hf > s.slip_hf_n and jaw_speed < s.slip_jaw_speed
        elif contact and len(self._f_hist) > 3:
            f0 = max(f for _, f in self._f_hist)
            self.slip = (not releasing) and f0 > 2.0 and grip_force < 0.7 * f0
        else:
            self.slip = False
        if cue is None and self.slip and t - self._last_slip_cue > 0.06:
            cue = Cue.SLIP
            self._last_slip_cue = t
        if not s.cues_enabled or not s.enabled:
            return None, 0
        return cue, amp


@dataclass
class GripCommand:
    gripper_cmd: float          # normalized 0 closed … 1 open
    trigger_mode: int           # haptic_protocol.Mode
    haptic_n: float
    pos_cmd: float = 0.0        # trigger position for POSITION mode
    target_force_n: float = float("nan")


@dataclass
class GripperCoupler:
    """Stateful trigger → gripper → trigger mapping, run every control tick."""

    settings: HapticSettings = field(default_factory=HapticSettings)
    k_x: float = 68.4 * 20.0 * 6.57   # N per normalized gripper unit (G · kp · raw stroke)
    open_at: float = 1.0               # gripper command when trigger released
    closed_at: float = 0.0             # gripper command when trigger fully squeezed
    force_mode_active: bool = False
    contact_active: bool = False       # position–force mode, past the contact point
    release_margin: float = 0.04       # mapped trigger opening beyond the jaws that releases
    hold_force_n: float = 2.0          # minimum grip force while in contact
    _p_contact: float = 0.0
    _lost_t: float = -1.0
    _contact_pos: float = 0.0
    _release_t: float = -1.0
    _target_force: float = 0.0

    def gripper_to_trigger(self, x: float) -> float:
        span = self.closed_at - self.open_at
        return min(max((x - self.open_at) / span, 0.0), 1.0) if span else 0.0

    def trigger_to_gripper(self, p: float) -> float:
        p = min(max(p, 0.0), 1.0)
        return self.open_at + (self.closed_at - self.open_at) * p

    def step(self, t: float, trigger_pos: float, trigger_force: float, grip_x: float, grip_force: float,
             contact: bool, senses_force: bool) -> GripCommand:
        from station.hardware.haptic_protocol import Mode

        s = self.settings
        render = felt_force(s, grip_force) if s.enabled else 0.0
        use_force = s.enabled and s.force_input and senses_force and np.isfinite(trigger_force)

        if use_force and not self.force_mode_active and contact:
            self.contact_active = False
            self.force_mode_active = True
            self._contact_pos = trigger_pos
            self._target_force = grip_force
            self._release_t = -1.0

        if self.force_mode_active:
            if not use_force:
                self.force_mode_active = False
            else:
                f_t = float(np.clip(s.input_gain * max(trigger_force, 0.0), 0.0, s.max_grip_n))
                # slew-limit the force target (protects objects from a sudden squeeze)
                self._target_force += float(np.clip(f_t - self._target_force, -400.0 * 0.005, 400.0 * 0.005))
                if trigger_force < s.release_n:
                    if self._release_t < 0:
                        self._release_t = t
                    elif t - self._release_t > 0.15:
                        self.force_mode_active = False
                else:
                    self._release_t = -1.0
                if self.force_mode_active:
                    x_cmd = grip_x - self._target_force / self.k_x
                    return GripCommand(float(np.clip(x_cmd, 0, 1)), int(Mode.POSITION), 0.0,
                                       pos_cmd=self._contact_pos, target_force_n=self._target_force)

        mode = Mode.RENDER if s.enabled else Mode.SPRING
        p = min(max(trigger_pos, 0.0), 1.0)

        # Contact-relative force law (docs/hardware/haptic-trigger.md §5.3). Past the contact point
        # the trigger commands grip *force* proportional to squeeze depth instead of jaw position,
        # so the operator never has to render the i2rt gripper's stiff PD (~94 N/mm).
        x_map = self.trigger_to_gripper(p)
        # Enter only when the operator is actually closing *into* the object (trigger asks for a
        # jaw position at or past where the jaws have stopped), not merely because contact is sensed.
        if s.enabled and contact and not self.contact_active and x_map <= grip_x + 0.01:
            self.contact_active = True
            # contact point = trigger position that maps to where the jaws actually stopped
            # (the operator may already be squeezing past it by the time contact is confirmed)
            self._p_contact = min(p, self.gripper_to_trigger(grip_x))
            self._target_force = grip_force
            self._lost_t = -1.0
        if self.contact_active:
            if contact:
                self._lost_t = -1.0
            elif self._lost_t < 0:
                self._lost_t = t
            if x_map > grip_x + self.release_margin:
                self.contact_active = False  # trigger asks for more opening than the jaws have: let go
            elif self._lost_t >= 0 and t - self._lost_t > 0.2:
                self.contact_active = False  # object slipped out or was taken: back to position following
            else:
                depth = (p - self._p_contact) / max(1.0 - self._p_contact, 0.05)
                depth = min(max(depth, 0.0), 1.0) ** max(s.force_curve, 0.1)
                f_t = float(np.clip(s.max_grip_n * depth, self.hold_force_n, s.max_grip_n))
                self._target_force += float(np.clip(f_t - self._target_force, -400.0 * 0.005, 400.0 * 0.005))
                x_cmd = grip_x - self._target_force / self.k_x
                return GripCommand(float(np.clip(x_cmd, 0, 1)), int(mode), render, target_force_n=self._target_force)
        return GripCommand(self.trigger_to_gripper(p), int(mode), render)

    @property
    def regulating(self) -> bool:
        """True while the station (not i2rt's stall limiter) is regulating grip force."""
        return self.contact_active or self.force_mode_active
