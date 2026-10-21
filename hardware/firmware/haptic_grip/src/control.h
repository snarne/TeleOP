// Series-elastic trigger control law (pure C++, no Arduino deps, host-testable).
//
//   p      = (θl − θopen) / (θclosed − θopen)                 trigger position, 0 open … 1 squeezed
//   τs     = τp + kθ · max(0, wrap(θl − θs − δ0))              spring torque (preloaded against the backstop)
//   Fop    = τs / rf   (reported 0 while the lever rests on the open stop)
//   Fdes   = clamp(spring_min + spring_n·p + Fhaptic + b·ṗ,  Fmin, min(max_n, Fhard))
//   θs*    = θl − δ0 − (Fdes·rf − τp)/kθ − Ki∫(Fdes − Fs)dt
//
// The servo runs in current-based position mode, so θs* is a position command and the
// servo's current limit also caps the torque in hardware.
#pragma once

#include <stdint.h>

#include "protocol.h"

namespace hgm {

struct ControlParams {
  float k_theta = 3.14f;          // N·m/rad, calibrated
  float finger_radius = 0.045f;   // m
  float theta_open = 0.0f;        // rad, lever encoder frame
  float theta_closed = 0.5236f;   // rad
  float sea_zero = 0.0f;          // rad, deflection at backstop contact (δ0)
  float ki = 0.0f;                // rad/(N·s)
  float preload_nm = 0.047f;      // N·m, spring preload torque at the backstop
  float hard_max_n = 15.0f;       // absolute cap (below the 17 N overload stop)
  float haptic_slew_n_per_s = 300.0f;
  float vel_cutoff_hz = 30.0f;
  float servo_margin_rad = 0.05f;
  float sea_travel_rad = 0.230f;  // geometric spring travel (13.2°)
};

struct ControlInput {
  float lever_rad;   // θl (after direction), unwrapped near the travel centre
  float servo_rad;   // θs (after direction)
  float dt;          // s
  Setpoint sp;
};

struct ControlOutput {
  bool torque_on = false;
  float servo_cmd_rad = 0.f;
  float pos = 0.f;          // clamped 0..1
  float vel = 0.f;          // 1/s
  float force_spring_n = 0.f;
  float force_op_n = 0.f;
  float force_cmd_n = 0.f;
  bool on_open_stop = false;
  bool overforce = false;
};

float wrap_pi(float a);
// Bring an encoder angle onto the branch nearest `centre` (handles 0/2π wrap).
float unwrap_near(float a, float centre);

class TriggerController {
 public:
  void set_params(const ControlParams& p) { p_ = p; }
  const ControlParams& params() const { return p_; }
  void reset();
  ControlOutput step(const ControlInput& in);

  // Helpers exposed for calibration and tests
  float position(float lever_rad) const;
  float spring_torque(float lever_rad, float servo_rad) const;

 private:
  ControlParams p_;
  bool init_ = false;
  float p_prev_ = 0.f;
  float vel_ = 0.f;
  float haptic_ = 0.f;
  float integ_ = 0.f;
};

}  // namespace hgm
