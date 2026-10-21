// Types mirroring docs/architecture.md, "API contract (v1)".

export type Phase =
  | "off"
  | "idle"
  | "starting"
  | "ready"
  | "teleop"
  | "recording"
  | "saving"
  | "stopping"
  | "fault";

export type StepStatus = "pending" | "running" | "ok" | "warn" | "error" | "skipped";
export type ArmSide = "left" | "right";
export type ArmState = "offline" | "connecting" | "connected" | "syncing" | "teleop" | "fault";
export type TriggerMode = "off" | "spring" | "render";

export interface StartupStep {
  id: string;
  label: string;
  status: StepStatus;
  message: string;
  duration_s: number;
  hint?: string;
}

export interface ArmSnapshot {
  state: ArmState;
  fault: string | null;
  loop_hz: number;
  loop_jitter_ms: number;
  tracking_error_rad: number;
  leader: { ok: boolean; q: number[] };
  follower: {
    ok: boolean;
    q: number[];
    dq: number[];
    tau: number[];
    gripper: number;
    gripper_tau: number;
    temps_c: number[];
  };
  trigger: {
    ok: boolean;
    pos: number;
    force_n: number;
    render_n: number;
    buttons: boolean[];
    mode: TriggerMode;
  };
  grip_force_n: number;
  contact: boolean;
  /** Object slipping between the follower's jaws (fingertip slip band, or a sudden force drop). */
  slip?: boolean;
  /** Where grip force comes from: fingertip load cells, or the gripper motor-torque estimate. */
  grip_source?: "fingertip" | "motor";
  fingertips?: { ok: boolean; a_n: number | null; b_n: number | null };
}

export interface CameraSnapshot {
  ok: boolean;
  fps: number;
  dropped: number;
  width: number;
  height: number;
  recording: boolean;
}

export interface PowerChannel {
  id: string;
  label: string;
  on: boolean;
}

export interface StateSnapshot {
  t: number;
  phase: Phase;
  phase_detail: string;
  sim: boolean;
  session: Session;
  startup: { steps: StartupStep[] };
  arms: Partial<Record<ArmSide, ArmSnapshot>>;
  cameras: Record<string, CameraSnapshot>;
  recording: {
    active: boolean;
    episode_id: string | null;
    elapsed_s: number;
    frames: number;
    size_mb: number;
  };
  power: { available: boolean; estop_ok: boolean; channels: PowerChannel[] };
  calibration: { active: string | null; step: string | null; live: Record<string, unknown> };
  system: { cpu_pct: number; mem_pct: number; disk_free_gb: number; disk_total_gb: number };
}

export interface LogLine {
  ts: number;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL" | string;
  source: string;
  message: string;
}

export interface StationInfo {
  name: string;
  version: string;
  sim: boolean;
  arms: ArmSide[];
  cameras: { name: string; label: string }[];
  power_channels: { id: string; label: string }[];
  data_root: string;
  /** The gripper's full force per arm (N): a full trigger squeeze commands this much. */
  grip_force_max?: Partial<Record<ArmSide, number>>;
}

export interface Session {
  operator_id: number | null;
  department_id: number | null;
  task_id: number | null;
}

export interface Department {
  id: number;
  name: string;
  color: string;
  description: string;
  user_count: number;
  episode_count: number;
}

export interface User {
  id: number;
  name: string;
  email: string | null;
  role: "operator" | "admin";
  active: boolean;
  department_ids: number[];
  episode_count: number;
  created_at: string;
}

export interface Task {
  id: number;
  name: string;
  slug: string;
  description: string;
  department_id: number | null;
}

export interface Episode {
  id: string;
  user_id: number;
  user_name: string;
  department_id: number;
  department_name: string;
  task_id: number;
  task_name: string;
  started_at: string;
  duration_s: number;
  frames: number;
  cameras: string[];
  size_mb: number;
  success: boolean | null;
  notes: string;
  tags: string[];
  path: string;
  status: string;
}

export interface Paged<T> {
  items: T[];
  total: number;
}

export interface Telemetry {
  t: number[];
  series: Record<string, number[]>;
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  progress: number;
  message: string;
  result: unknown;
}

export interface CalItem {
  id: string;
  label: string;
  kind: string;
  calibrated: boolean;
  updated_at: string | null;
  updated_by: string | null;
  summary: string;
}

export interface ProcedureInput {
  key: string;
  label: string;
  type: "number" | "text" | "select" | string;
  unit?: string;
  default?: number | string;
  options?: string[];
}

export interface ProcedureStep {
  id: string;
  title: string;
  instruction: string;
  action: "capture" | "auto" | "confirm" | "input";
  inputs?: ProcedureInput[];
  image?: string | null;
}

export interface Procedure {
  id: string;
  title: string;
  kind: string;
  target: string;
  description: string;
  steps: ProcedureStep[];
}

export interface RunStepState {
  id: string;
  status: "pending" | "ok" | "error";
  message: string;
  data: unknown;
}

export interface RunState {
  procedure_id: string;
  step_index: number;
  steps: RunStepState[];
  result: Record<string, unknown> | null;
  can_commit: boolean;
}

export interface HealthCheck {
  id: string;
  group: string;
  label: string;
  status: "ok" | "warn" | "error" | "unknown";
  message: string;
  hint: string;
}

export interface HealthReport {
  checks: HealthCheck[];
  ran_at: string;
}

export type KeyAction =
  | "start_recording"
  | "save"
  | "abort"
  | "teleop_toggle"
  | "estop"
  | "mark_success"
  | "mark_failure";

export interface HapticSettings {
  enabled: boolean;
  feedback_gain: number;
  max_render_n: number;
  spring_n: number;
  damping: number;
  force_input: boolean;
  input_gain: number;
  max_grip_n: number;
  /** Shape of squeeze depth → grip force: 1 = linear, > 1 = finer control of light grips. */
  force_curve?: number;
  /** "perceptual" (default): felt = max_render · (grip / full)^exponent. "linear": felt = gain · grip. */
  feedback_mode?: "perceptual" | "linear";
  feedback_exponent?: number;
  cues_enabled?: boolean;
  cue_strength?: number;
}

export interface Settings {
  keybindings: Record<KeyAction, string>;
  handle_buttons: Record<string, string>;
  haptics: Record<ArmSide, HapticSettings>;
  recording: {
    auto_export: boolean;
    countdown_s: number;
    max_duration_s: number;
    confirm_abort_after_s?: number;
  };
}

export interface ApiErrorBody {
  detail: string;
  hint?: string;
}
