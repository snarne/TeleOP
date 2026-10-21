#include "control.h"

#include <math.h>

namespace hgm {

namespace {
constexpr float kPi = 3.14159265358979f;
constexpr float kTwoPi = 6.28318530717959f;
constexpr float kStopBand = 0.02f;     // p below this = resting on the open stop
inline float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
}  // namespace

float wrap_pi(float a) {
  while (a > kPi) a -= kTwoPi;
  while (a <= -kPi) a += kTwoPi;
  return a;
}

float unwrap_near(float a, float centre) { return centre + wrap_pi(a - centre); }

void TriggerController::reset() {
  init_ = false;
  vel_ = 0.f;
  haptic_ = 0.f;
  integ_ = 0.f;
}

float TriggerController::position(float lever_rad) const {
  float span = p_.theta_closed - p_.theta_open;
  if (fabsf(span) < 1e-4f) return 0.f;
  return (lever_rad - p_.theta_open) / span;
}

float TriggerController::spring_torque(float lever_rad, float servo_rad) const {
  float defl = wrap_pi(lever_rad - servo_rad - p_.sea_zero);
  if (defl < 0.f) defl = 0.f;  // the backstop prevents negative deflection; noise only
  return p_.preload_nm + p_.k_theta * defl;
}

ControlOutput TriggerController::step(const ControlInput& in) {
  ControlOutput out;
  const float dt = in.dt > 1e-5f ? in.dt : 1e-3f;
  const float p_raw = position(in.lever_rad);
  if (!init_) {
    p_prev_ = p_raw;
    vel_ = 0.f;
    init_ = true;
  }
  // velocity: finite difference + first-order low-pass
  const float v_raw = (p_raw - p_prev_) / dt;
  const float rc = 1.f / (kTwoPi * p_.vel_cutoff_hz);
  vel_ += (dt / (dt + rc)) * (v_raw - vel_);
  p_prev_ = p_raw;

  const float tau_s = spring_torque(in.lever_rad, in.servo_rad);
  const float rf = p_.finger_radius;
  out.pos = clampf(p_raw, 0.f, 1.f);
  out.vel = vel_;
  out.force_spring_n = tau_s / rf;
  out.on_open_stop = p_raw < kStopBand;
  out.force_op_n = out.on_open_stop ? 0.f : out.force_spring_n;
  out.overforce = out.force_spring_n > p_.hard_max_n + 2.0f;

  const Setpoint& sp = in.sp;
  if (sp.mode == kModeOff) {
    out.torque_on = false;
    out.servo_cmd_rad = in.servo_rad;
    haptic_ = 0.f;
    integ_ = 0.f;
    return out;
  }
  out.torque_on = true;
  const float f_min = p_.preload_nm / rf + 0.05f;               // keep the tab off the backstop
  const float f_max = fminf(sp.max_n > 0.f ? sp.max_n : p_.hard_max_n, p_.hard_max_n);

  if (sp.mode == kModePosition) {
    const float target = p_.theta_open + clampf(sp.pos_cmd, 0.f, 1.f) * (p_.theta_closed - p_.theta_open);
    out.servo_cmd_rad = target - p_.sea_zero;
    out.force_cmd_n = 0.f;
    integ_ = 0.f;
    haptic_ = 0.f;
  } else {
    // slew-limit the host's haptic force (rate limiting keeps the loop passive)
    const float h_target = (sp.mode == kModeRender) ? clampf(sp.haptic_n, 0.f, f_max) : 0.f;
    const float step = p_.haptic_slew_n_per_s * dt;
    haptic_ += clampf(h_target - haptic_, -step, step);
    float f_des = sp.spring_min_n + sp.spring_n * out.pos + haptic_ + sp.damping * vel_;
    f_des = clampf(f_des, f_min, f_max);
    out.force_cmd_n = f_des;
    // optional integral on force error, only in free travel
    if (p_.ki > 0.f && !out.on_open_stop && p_raw < 1.f - kStopBand) {
      const float err = f_des - out.force_spring_n;
      if (fabsf(err) < 5.f) integ_ += err * dt;
      const float lim = 0.05f / p_.ki;
      integ_ = clampf(integ_, -lim, lim);
    } else {
      integ_ *= 0.99f;
    }
    const float defl_cmd = (f_des * rf - p_.preload_nm) / p_.k_theta;
    out.servo_cmd_rad = in.lever_rad - p_.sea_zero - clampf(defl_cmd, 0.f, p_.sea_travel_rad) - p_.ki * integ_;
  }
  // never command the servo past the mechanical envelope
  const float lo = p_.theta_open - p_.sea_zero - p_.sea_travel_rad - p_.servo_margin_rad;
  const float hi = p_.theta_closed - p_.sea_zero + p_.servo_margin_rad;
  out.servo_cmd_rad = clampf(out.servo_cmd_rad, fminf(lo, hi), fmaxf(lo, hi));
  return out;
}

}  // namespace hgm
