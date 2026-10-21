// In-browser simulation of the station API (docs/architecture.md, "API contract").
// Enabled with VITE_MOCK=1 or ?mock=1. It doesn't aim for physical accuracy; it only
// needs to exercise every state the UI can be in.

import type {
  ArmSide,
  ArmSnapshot,
  CalItem,
  Department,
  Episode,
  HealthCheck,
  Job,
  LogLine,
  Phase,
  Procedure,
  RunState,
  Session,
  Settings,
  StartupStep,
  StateSnapshot,
  Task,
  User,
} from "../api/types";

type Resp = { status: number; body: unknown };
const ok = (body: unknown): Resp => ({ status: 200, body: body === undefined ? body : structuredClone(body) });
const err = (status: number, detail: string, hint?: string): Resp => ({ status, body: { detail, hint } });

const T0 = performance.now();
const now = () => (performance.now() - T0) / 1000;
const iso = (d: Date) => d.toISOString();
const slugify = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// --------------------------------------------------------------------------- org data

let nextId = 100;
const departments: Department[] = [
  { id: 1, name: "Manipulation", color: "#1D3F91", description: "Tabletop pick, place and assembly tasks.", user_count: 0, episode_count: 0 },
  { id: 2, name: "Household", color: "#2F7D5B", description: "Laundry folding, dishes, tidying.", user_count: 0, episode_count: 0 },
  { id: 3, name: "Fine motor", color: "#A2541B", description: "Cable routing, connectors, small parts.", user_count: 0, episode_count: 0 },
];
const users: User[] = [
  { id: 1, name: "Ana Ortiz", email: "ana@lab.local", role: "admin", active: true, department_ids: [1, 3], episode_count: 0, created_at: "2026-09-02T17:00:00Z" },
  { id: 2, name: "Marcus Lee", email: null, role: "operator", active: true, department_ids: [1], episode_count: 0, created_at: "2026-09-04T17:00:00Z" },
  { id: 3, name: "Priya Raman", email: "priya@lab.local", role: "operator", active: true, department_ids: [2], episode_count: 0, created_at: "2026-09-10T17:00:00Z" },
  { id: 4, name: "Jonah Weiss", email: null, role: "operator", active: true, department_ids: [2, 3], episode_count: 0, created_at: "2026-09-21T17:00:00Z" },
  { id: 5, name: "Sam Okafor", email: null, role: "operator", active: false, department_ids: [1], episode_count: 0, created_at: "2026-08-15T17:00:00Z" },
];
const tasks: Task[] = [
  { id: 1, name: "Pick cube into bin", slug: "pick-cube-into-bin", description: "Grasp the 4 cm cube and drop it in the bin.", department_id: 1 },
  { id: 2, name: "Hand-over sponge", slug: "hand-over-sponge", description: "Pick sponge with left, pass to right, place on tray.", department_id: 1 },
  { id: 3, name: "Fold towel", slug: "fold-towel", description: "Fold the hand towel in half twice.", department_id: 2 },
  { id: 4, name: "Load dishwasher rack", slug: "load-dishwasher-rack", description: "Place 3 plastic cups upside-down in the rack.", department_id: 2 },
  { id: 5, name: "Plug USB-C cable", slug: "plug-usb-c-cable", description: "Insert the cable into the test fixture.", department_id: 3 },
];

const episodes: Episode[] = [];
(function seedEpisodes() {
  const start = Date.now() - 1000 * 60 * 60 * 24 * 6;
  for (let i = 0; i < 26; i++) {
    const u = users[i % 4];
    const t = tasks[(i * 3) % tasks.length];
    const d = departments.find((x) => x.id === t.department_id)!;
    const when = new Date(start + i * 1000 * 60 * 37 * 7 + (i % 3) * 1000 * 60 * 11);
    const dur = 18 + ((i * 13) % 50);
    episodes.push({
      id: `ep_${(0x3a91 + i * 977).toString(16)}${i}`,
      user_id: u.id,
      user_name: u.name,
      department_id: d.id,
      department_name: d.name,
      task_id: t.id,
      task_name: t.name,
      started_at: iso(when),
      duration_s: dur,
      frames: dur * 30,
      cameras: ["left_wrist", "overhead", "right_wrist"],
      size_mb: Math.round(dur * 2.6 * 10) / 10,
      success: i % 7 === 3 ? false : i % 11 === 5 ? null : true,
      notes: i % 7 === 3 ? "Dropped the object on the way to the bin." : "",
      tags: i % 5 === 0 ? ["warmup"] : [],
      path: `recordings/${slugify(d.name)}/${slugify(u.name)}/${when.toISOString().slice(0, 19).replace(/[T:]/g, "-")}_${t.slug}`,
      status: "saved",
    });
  }
  episodes.reverse();
})();

function recount() {
  for (const d of departments) {
    d.user_count = users.filter((u) => u.active && u.department_ids.includes(d.id)).length;
    d.episode_count = episodes.filter((e) => e.department_id === d.id).length;
  }
  for (const u of users) u.episode_count = episodes.filter((e) => e.user_id === u.id).length;
}
recount();

// --------------------------------------------------------------------------- settings

let settings: Settings = {
  keybindings: {
    start_recording: "KeyR",
    save: "KeyS",
    abort: "KeyX",
    teleop_toggle: "KeyT",
    estop: "Escape",
    mark_success: "KeyY",
    mark_failure: "KeyN",
  },
  handle_buttons: { left_a: "save", left_b: "abort", right_a: "start_recording", right_b: "teleop_toggle" },
  haptics: {
    left: { enabled: true, feedback_gain: 0.25, max_render_n: 12, spring_n: 1.5, damping: 0.02, force_input: false, input_gain: 4, max_grip_n: 50, force_curve: 1 },
    right: { enabled: true, feedback_gain: 0.25, max_render_n: 12, spring_n: 1.5, damping: 0.02, force_input: false, input_gain: 4, max_grip_n: 50, force_curve: 1 },
  },
  recording: { auto_export: false, countdown_s: 0, max_duration_s: 600, confirm_abort_after_s: 10 },
};

// --------------------------------------------------------------------------- station state

const CAMERAS = [
  { name: "left_wrist", label: "Left wrist" },
  { name: "overhead", label: "Overhead" },
  { name: "right_wrist", label: "Right wrist" },
];
const POWER = [
  { id: "left_follower", label: "Left follower 24 V" },
  { id: "right_follower", label: "Right follower 24 V" },
  { id: "leaders", label: "Leader arms 5 V" },
  { id: "aux", label: "Camera hub" },
];

let phase: Phase = "off";
let phaseDetail = "";
let session: Session = { operator_id: 2, department_id: 1, task_id: 1 };
const power: Record<string, boolean> = { left_follower: false, right_follower: false, leaders: false, aux: true };
let estopOk = true;
let startup: StartupStep[] = [];
let rec = { active: false, episode_id: null as string | null, t0: 0, frames: 0 };
let teleopSince = 0;
const armUp: Record<ArmSide, boolean> = { left: false, right: false };
let calActive: { pid: string; step: string | null } | null = null;

const STARTUP_TEMPLATE: Omit<StartupStep, "status" | "message" | "duration_s">[] = [
  { id: "power", label: "Power on arms" },
  { id: "can", label: "Bring up CAN interfaces" },
  { id: "followers", label: "Connect follower arms" },
  { id: "leaders", label: "Connect leader arms" },
  { id: "triggers", label: "Connect haptic triggers" },
  { id: "cameras", label: "Check cameras" },
  { id: "calibration", label: "Load calibration" },
  { id: "sync", label: "Check leader/follower pose gap" },
];
const STARTUP_MSG: Record<string, string> = {
  power: "4 relay channels on, e-stop released",
  can: "can_follower_l, can_follower_r up at 1 Mbit/s",
  followers: "YAM ×2, linear_4310 grippers calibrated",
  leaders: "7/7 Dynamixels found on each leader bus",
  triggers: "HGM fw 1.0.0 on /dev/hgm_left, /dev/hgm_right",
  cameras: "3/3 cameras streaming at 30 fps",
  calibration: "Leader, trigger and gripper files loaded",
  sync: "Max gap 9.4° (left J5). Followers will ease in over 3 s",
};

// --------------------------------------------------------------------------- logs

type LogSub = (l: LogLine) => void;
const logSubs = new Set<LogSub>();
const logBuf: LogLine[] = [];
function log(level: LogLine["level"], source: string, message: string) {
  const l: LogLine = { ts: Date.now() / 1000, level, source, message };
  logBuf.push(l);
  if (logBuf.length > 2000) logBuf.shift();
  logSubs.forEach((s) => s(l));
}
log("INFO", "station", "Teleop Station 1.0.0 started (simulation mode)");
log("INFO", "db", "Opened data/station.db (5 users, 3 departments, 26 episodes)");
log("INFO", "power", "Relay board: sim (4 channels), e-stop loop closed");
log("INFO", "camera.overhead", "Opened sim camera 640x480 @ 30 fps");
log("INFO", "camera.left_wrist", "Opened sim camera 640x480 @ 30 fps");
log("INFO", "camera.right_wrist", "Opened sim camera 640x480 @ 30 fps");
log("WARNING", "health", "Disk free 118 GB. About 12 h of recording at the current rate");

function setPhase(p: Phase, detail = "") {
  if (p !== phase) log(p === "fault" ? "ERROR" : "INFO", "orchestrator", `Phase ${phase} → ${p}${detail ? `: ${detail}` : ""}`);
  phase = p;
  phaseDetail = detail;
}

// --------------------------------------------------------------------------- arm sim

const DEG = Math.PI / 180;
function armSnapshot(side: ArmSide, t: number): ArmSnapshot {
  const s = side === "left" ? 0 : 1.7;
  const up = armUp[side];
  const engaged = up && (phase === "teleop" || phase === "recording" || phase === "saving");
  const lq = [
    0.4 * Math.sin(0.31 * t + s),
    0.8 + 0.3 * Math.sin(0.23 * t + s),
    0.9 + 0.25 * Math.sin(0.27 * t + 0.4 + s),
    0.2 * Math.sin(0.41 * t + s),
    -0.3 + 0.35 * Math.sin(0.37 * t + 1 + s),
    0.5 * Math.sin(0.19 * t + s),
  ];
  const lag = 0.12;
  const fq = engaged
    ? [
        0.4 * Math.sin(0.31 * (t - lag) + s),
        0.8 + 0.3 * Math.sin(0.23 * (t - lag) + s),
        0.9 + 0.25 * Math.sin(0.27 * (t - lag) + 0.4 + s),
        0.2 * Math.sin(0.41 * (t - lag) + s),
        -0.3 + 0.35 * Math.sin(0.37 * (t - lag) + 1 + s),
        0.5 * Math.sin(0.19 * (t - lag) + s),
      ]
    : [0, 0.05, 0.05, 0, 0, 0];
  const cyc = ((t + s * 2) % 7) / 7;
  const pos = engaged || up ? Math.max(0, Math.sin(cyc * Math.PI) ** 2 * 0.9 - 0.05) : 0;
  const contact = engaged && pos > 0.45;
  const grip = contact ? Math.min(48, (pos - 0.45) * 90 + 2 * Math.sin(t * 9)) : Math.max(0, 0.4 * Math.sin(t * 5));
  const hs = settings.haptics[side];
  const render = hs.enabled ? Math.min(hs.max_render_n, hs.feedback_gain * grip) : 0;
  const spring = hs.spring_n * pos + 0.3;
  const force = up ? render + spring + (contact ? 1.2 + 0.3 * Math.sin(t * 3) : 0.2) : 0;
  return {
    state: !up ? (power.left_follower || power.right_follower ? "offline" : "offline") : engaged ? "teleop" : "connected",
    fault: null,
    loop_hz: up ? 200 + 0.6 * Math.sin(t * 2.1 + s) : 0,
    loop_jitter_ms: up ? 0.18 + 0.06 * Math.abs(Math.sin(t * 0.7 + s)) : 0,
    tracking_error_rad: engaged ? Math.max(...lq.map((v, i) => Math.abs(v - fq[i]))) : 0,
    leader: { ok: up, q: up ? lq : [0, 0, 0, 0, 0, 0] },
    follower: {
      ok: up,
      q: fq,
      dq: fq.map((_, i) => (engaged ? 0.3 * Math.cos(0.3 * t + i) : 0)),
      tau: fq.map((_, i) => (up ? [0.1, 2.4, 1.6, 0.3, 0.4, 0.05][i] + 0.1 * Math.sin(t + i) : 0)),
      gripper: up ? Math.max(0.05, 1 - pos * (contact ? 0.6 : 1)) : 1,
      gripper_tau: grip / 68.4,
      temps_c: [38, 44, 42, 36, 35, 33].map((v, i) => (up ? v + 2 * Math.sin(t / 30 + i) + (side === "right" ? 1.5 : 0) : 24)),
    },
    trigger: {
      ok: up,
      pos,
      force_n: force,
      render_n: up ? render + spring : 0,
      buttons: [false, false],
      mode: !up ? "off" : engaged && hs.enabled ? "render" : "spring",
    },
    grip_force_n: up ? grip : 0,
    contact,
  };
}

function snapshot(): StateSnapshot {
  const t = now();
  const cams: StateSnapshot["cameras"] = {};
  for (const c of CAMERAS) {
    const alive = power.aux;
    cams[c.name] = {
      ok: alive,
      fps: alive ? 29.97 + 0.03 * Math.sin(t + c.name.length) : 0,
      dropped: c.name === "right_wrist" ? 2 : 0,
      width: 640,
      height: 480,
      recording: rec.active,
    };
  }
  const elapsed = rec.active ? t - rec.t0 : 0;
  const arms: StateSnapshot["arms"] = { left: armSnapshot("left", t), right: armSnapshot("right", t) };
  const live: Record<string, unknown> = {};
  if (calActive) {
    const p = procedures.find((x) => x.id === calActive!.pid);
    if (p?.kind === "leader") {
      const q = [0.02, 0.01, -0.015, 0.03, -0.01, 0.02].map((v, i) => v + 0.004 * Math.sin(t * 3 + i));
      live.joints_deg = [...q.map((v) => +(v / DEG).toFixed(1)), 0];
      live.raw_ticks = [...q.map((v, i) => Math.round([2048, 1024, 3072, 2048, 2048, 1024][i] + v * 651.9)), 2900];
      live.bus = "ok, 7/7 servos";
    } else if (p?.kind === "trigger") {
      live.lever_deg = +(18 + 10 * Math.sin(t)).toFixed(2);
      live.servo_deg = +(17.4 + 10 * Math.sin(t - 0.05)).toFixed(2);
      live.deflection_deg = +(0.6 + 0.2 * Math.sin(t * 3)).toFixed(2);
      live.force_n = +(1.1 + 0.4 * Math.sin(t * 3)).toFixed(2);
    } else if (p?.kind === "gripper") {
      live.gripper_pos = +(0.5 + 0.4 * Math.sin(t / 2)).toFixed(3);
      live.motor_tau_nm = +(0.12 + 0.05 * Math.sin(t)).toFixed(3);
      live.est_force_n = +(8.2 + 3 * Math.sin(t)).toFixed(1);
    } else if (p?.kind === "camera") {
      live.corners_detected = Math.round(38 + 8 * Math.sin(t));
      live.views_captured = runs[p.id]?.steps.filter((s) => s.status === "ok").length ?? 0;
      live.reprojection_px = 0.31;
    }
  }
  return {
    t,
    phase,
    phase_detail: phaseDetail,
    sim: true,
    session,
    startup: { steps: startup.map((x) => ({ ...x })) },
    arms,
    cameras: cams,
    recording: {
      active: rec.active,
      episode_id: rec.episode_id,
      elapsed_s: elapsed,
      frames: Math.floor(elapsed * 30),
      size_mb: elapsed * 2.6,
    },
    power: { available: true, estop_ok: estopOk, channels: POWER.map((c) => ({ ...c, on: power[c.id] })) },
    calibration: { active: calActive?.pid ?? null, step: calActive?.step ?? null, live },
    system: {
      cpu_pct: 18 + (rec.active ? 22 : 0) + 4 * Math.sin(t / 3),
      mem_pct: 41 + (rec.active ? 6 : 0),
      disk_free_gb: 118.4 - (rec.active ? elapsed * 0.0026 : 0),
      disk_total_gb: 476.9,
    },
  };
}

type StateSub = (s: StateSnapshot) => void;
const stateSubs = new Set<StateSub>();
setInterval(() => {
  if (stateSubs.size === 0) return;
  const s = snapshot();
  stateSubs.forEach((f) => f(s));
}, 50);

let periodicLogT = 0;
setInterval(() => {
  periodicLogT++;
  if (phase === "teleop" || phase === "recording") {
    if (periodicLogT % 6 === 0) log("DEBUG", "arm.left", "loop 200.1 Hz, jitter p99 0.42 ms, tracking 0.6°");
    if (periodicLogT % 9 === 0) log("INFO", "haptics.right", "Contact detected, grip 14.2 N → render 3.6 N");
    if (periodicLogT % 23 === 0) log("WARNING", "camera.right_wrist", "Frame interval 52 ms (expected 33 ms), 1 frame dropped");
  }
}, 1000);

export function mockSubscribeState(f: StateSub): () => void {
  stateSubs.add(f);
  f(snapshot());
  return () => void stateSubs.delete(f);
}
export function mockSubscribeLogs(f: LogSub): () => void {
  logBuf.slice(-200).forEach(f);
  logSubs.add(f);
  return () => void logSubs.delete(f);
}

// --------------------------------------------------------------------------- calibration

const calItems: CalItem[] = [
  { id: "leader_left", label: "Left leader arm", kind: "leader", calibrated: true, updated_at: "2026-10-14T16:22:00Z", updated_by: "Ana Ortiz", summary: "Offsets set, max residual 0.8°" },
  { id: "leader_right", label: "Right leader arm", kind: "leader", calibrated: true, updated_at: "2026-10-14T16:31:00Z", updated_by: "Ana Ortiz", summary: "Offsets set, max residual 1.1°" },
  { id: "trigger_left", label: "Left haptic trigger", kind: "trigger", calibrated: true, updated_at: "2026-10-15T18:02:00Z", updated_by: "Ana Ortiz", summary: "k = 3.12 N·m/rad, travel 29.4°" },
  { id: "trigger_right", label: "Right haptic trigger", kind: "trigger", calibrated: false, updated_at: null, updated_by: null, summary: "Not calibrated. Using default stiffness" },
  { id: "gripper_left", label: "Left gripper force", kind: "gripper", calibrated: true, updated_at: "2026-10-12T20:10:00Z", updated_by: "Marcus Lee", summary: "G = 64.9 N/N·m, friction 0.06 N·m" },
  { id: "gripper_right", label: "Right gripper force", kind: "gripper", calibrated: true, updated_at: "2026-10-12T20:24:00Z", updated_by: "Marcus Lee", summary: "G = 66.1 N/N·m, friction 0.05 N·m" },
  { id: "camera_overhead", label: "Overhead camera", kind: "camera", calibrated: true, updated_at: "2026-10-01T19:00:00Z", updated_by: "Ana Ortiz", summary: "Reprojection 0.28 px, 24 views" },
  { id: "camera_left_wrist", label: "Left wrist camera", kind: "camera", calibrated: false, updated_at: null, updated_by: null, summary: "Not calibrated" },
  { id: "camera_right_wrist", label: "Right wrist camera", kind: "camera", calibrated: true, updated_at: "2026-10-01T19:20:00Z", updated_by: "Ana Ortiz", summary: "Reprojection 0.34 px, 20 views" },
];

function leaderProc(side: ArmSide): Procedure {
  const S = side === "left" ? "Left" : "Right";
  return {
    id: `leader_${side}`,
    title: `${S} leader arm`,
    kind: "leader",
    target: side,
    description: "Maps each leader Dynamixel reading onto the matching YAM follower joint (offset and direction).",
    steps: [
      { id: "connect", title: "Connect to the leader bus", instruction: `Make sure the ${side} leader arm is powered and its U2D2 is plugged in. The station pings every servo.`, action: "auto" },
      { id: "pose_zero", title: "Zero pose", instruction: "Move the leader into the zero pose: upper arm straight up, forearm straight forward, wrist flat, handle level. Hold it still and capture.", action: "capture", image: null },
      { id: "pose_ref", title: "Reference pose", instruction: "Bend each joint about +90° in the direction marked on the arm (shoulder forward, elbow up, wrist down). Hold it still and capture.", action: "capture" },
      { id: "verify", title: "Check the result", instruction: "The station computes offsets and directions and checks them against both poses. Residuals under 2° are good.", action: "auto" },
    ],
  };
}
function triggerProc(side: ArmSide): Procedure {
  const S = side === "left" ? "Left" : "Right";
  return {
    id: `trigger_${side}`,
    title: `${S} haptic trigger`,
    kind: "trigger",
    target: side,
    description: "Sets trigger travel, zeroes the spring and measures spring stiffness with a known weight.",
    steps: [
      { id: "open", title: "Released position", instruction: "Let go of the trigger completely and capture.", action: "capture" },
      { id: "closed", title: "Fully squeezed", instruction: "Squeeze the trigger all the way and hold it, then capture.", action: "capture" },
      { id: "tare", title: "Zero the spring", instruction: "Let go again. The module records the spring's resting deflection.", action: "confirm" },
      { id: "stiffness", title: "Spring stiffness", instruction: "Hang a known weight from the finger pad (a water bottle works) with the handle held level, then enter its mass.", action: "input", inputs: [{ key: "mass_g", label: "Weight", type: "number", unit: "g", default: 500 }] },
    ],
  };
}
function gripperProc(side: ArmSide): Procedure {
  const S = side === "left" ? "Left" : "Right";
  return {
    id: `gripper_${side}`,
    title: `${S} gripper force`,
    kind: "gripper",
    target: side,
    description: "Fits motor torque to real fingertip force so haptic feedback and force limits are in newtons.",
    steps: [
      { id: "friction", title: "Measure friction", instruction: "Clear the gripper. It opens and closes slowly to measure friction.", action: "auto" },
      { id: "load1", title: "Light squeeze", instruction: "Put a luggage scale or force gauge between the fingers. The gripper squeezes gently. Enter the reading.", action: "input", inputs: [{ key: "force_n", label: "Scale reading", type: "number", unit: "N", default: 10 }] },
      { id: "load2", title: "Firm squeeze", instruction: "Same again with a firmer squeeze. Enter the reading.", action: "input", inputs: [{ key: "force_n", label: "Scale reading", type: "number", unit: "N", default: 30 }] },
      { id: "fit", title: "Fit the model", instruction: "The station fits gain and friction and shows the error.", action: "auto" },
    ],
  };
}
function cameraProc(name: string, label: string): Procedure {
  return {
    id: `camera_${name}`,
    title: `${label} camera`,
    kind: "camera",
    target: name,
    description: "Lens calibration (intrinsics) from a printed ChArUco board.",
    steps: [
      { id: "board", title: "Print the board", instruction: "Print the ChArUco board (docs/calibration/charuco_5x7.pdf) at 100% scale, tape it flat, and measure one square.", action: "input", inputs: [{ key: "square_mm", label: "Square size", type: "number", unit: "mm", default: 30 }] },
      { id: "view1", title: "Capture: board square-on", instruction: "Hold the board square-on to the camera, filling about half the frame.", action: "capture" },
      { id: "view2", title: "Capture: tilted left", instruction: "Tilt the board about 30° to the left.", action: "capture" },
      { id: "view3", title: "Capture: tilted right", instruction: "Tilt the board about 30° to the right.", action: "capture" },
      { id: "view4", title: "Capture: near a corner", instruction: "Move the board into a corner of the frame.", action: "capture" },
      { id: "solve", title: "Solve", instruction: "The station solves for focal length and distortion and reports the reprojection error.", action: "auto" },
    ],
  };
}
const procedures: Procedure[] = [
  leaderProc("left"),
  leaderProc("right"),
  triggerProc("left"),
  triggerProc("right"),
  gripperProc("left"),
  gripperProc("right"),
  ...CAMERAS.map((c) => cameraProc(c.name, c.label)),
];
const runs: Record<string, RunState> = {};

function stepData(p: Procedure, sid: string, inputs: Record<string, unknown>): { message: string; data: unknown } {
  if (p.kind === "leader") {
    if (sid === "connect") return { message: "Found 7 servos (IDs 1–7, XL330-M288) at 1 Mbps", data: { ids: [1, 2, 3, 4, 5, 6, 7] } };
    if (sid === "pose_zero") return { message: "Captured 200 samples, spread 0.2°", data: { ticks: [2047, 1022, 3069, 2050, 2046, 1024, 2900] } };
    if (sid === "pose_ref") return { message: "Captured 200 samples, spread 0.3°", data: { ticks: [3071, 2046, 2046, 3075, 3069, 2047, 2900] } };
    if (sid === "verify") return { message: "Offsets solved, max residual 0.8° (J4)", data: { residual_deg: [0.3, 0.5, 0.4, 0.8, 0.2, 0.6] } };
  }
  if (p.kind === "trigger") {
    if (sid === "open") return { message: "Open at 2.1°", data: { lever_deg: 2.1 } };
    if (sid === "closed") return { message: "Closed at 31.5°, travel 29.4°", data: { lever_deg: 31.5 } };
    if (sid === "tare") return { message: "Spring zero δ₀ = 0.42°", data: {} };
    if (sid === "stiffness") {
      const m = Number(inputs.mass_g ?? 500);
      return { message: `Deflection 8.1° under ${m} g, k = ${(3.12 * (m / 500)).toFixed(2)} N·m/rad`, data: { k: 3.12 } };
    }
  }
  if (p.kind === "gripper") {
    if (sid === "friction") return { message: "Coulomb friction 0.058 N·m, viscous 0.011 N·m·s", data: {} };
    if (sid.startsWith("load")) return { message: `Recorded ${inputs.force_n ?? "?"} N at τ = ${sid === "load1" ? "0.162" : "0.471"} N·m`, data: {} };
    if (sid === "fit") return { message: "G = 64.9 N/N·m (theory 68.4), RMS error 0.7 N", data: {} };
  }
  if (p.kind === "camera") {
    if (sid === "board") return { message: `Board 5×7, ${inputs.square_mm ?? 30} mm squares`, data: {} };
    if (sid.startsWith("view")) return { message: `${32 + sid.length * 2} corners detected`, data: {} };
    if (sid === "solve") return { message: "fx 612.4, fy 611.9, reprojection 0.29 px", data: {} };
  }
  return { message: "Done", data: {} };
}

// --------------------------------------------------------------------------- health

function healthChecks(): HealthCheck[] {
  const armsOn = power.left_follower && power.right_follower;
  const up = armUp.left && armUp.right;
  return [
    { id: "power.relay", group: "Power", label: "Relay board", status: "ok", message: "Sim relay, 4 channels", hint: "" },
    { id: "power.estop", group: "Power", label: "E-stop loop", status: estopOk ? "ok" : "error", message: estopOk ? "Closed (released)" : "Open: e-stop pressed", hint: estopOk ? "" : "Twist the e-stop to release it, then clear the fault." },
    { id: "can.left", group: "Follower arms", label: "can_follower_l", status: armsOn ? "ok" : "warn", message: armsOn ? "UP, 1 Mbit/s, 0 bus errors" : "Down: arm not powered", hint: armsOn ? "" : "Power on the arms from the Power panel." },
    { id: "can.right", group: "Follower arms", label: "can_follower_r", status: armsOn ? "ok" : "warn", message: armsOn ? "UP, 1 Mbit/s, 0 bus errors" : "Down: arm not powered", hint: armsOn ? "" : "Power on the arms from the Power panel." },
    { id: "yam.temps", group: "Follower arms", label: "Motor temperatures", status: up ? "ok" : "unknown", message: up ? "Max 46 °C (right J2)" : "Arms not connected", hint: "" },
    { id: "dxl.left", group: "Leader arms", label: "Left leader bus", status: power.leaders ? "ok" : "warn", message: power.leaders ? "/dev/leader_left, 7 servos" : "No servos answering", hint: power.leaders ? "" : "Turn on the leader 5 V channel." },
    { id: "dxl.right", group: "Leader arms", label: "Right leader bus", status: power.leaders ? "ok" : "warn", message: power.leaders ? "/dev/leader_right, 7 servos" : "No servos answering", hint: power.leaders ? "" : "Turn on the leader 5 V channel." },
    { id: "hgm.left", group: "Haptic triggers", label: "Left trigger module", status: "ok", message: "fw 1.0.0, 500 Hz telemetry, 0 CRC errors", hint: "" },
    { id: "hgm.right", group: "Haptic triggers", label: "Right trigger module", status: "warn", message: "Stiffness not calibrated (using default 3.0 N·m/rad)", hint: "Run Calibrate → Right haptic trigger." },
    { id: "cam.overhead", group: "Cameras", label: "Overhead", status: "ok", message: "640×480 MJPG @ 30.0 fps", hint: "" },
    { id: "cam.left_wrist", group: "Cameras", label: "Left wrist", status: "ok", message: "640×480 MJPG @ 30.0 fps", hint: "" },
    { id: "cam.right_wrist", group: "Cameras", label: "Right wrist", status: "warn", message: "29.6 fps, 2 dropped frames in the last minute", hint: "Plug this camera into a USB port on a different controller than the other wrist camera." },
    { id: "sys.disk", group: "System", label: "Disk space", status: "ok", message: "118 GB free of 477 GB (~12 h of recording)", hint: "" },
    { id: "sys.clock", group: "System", label: "Clock sync", status: "ok", message: "All streams on CLOCK_MONOTONIC", hint: "" },
    { id: "sys.rt", group: "System", label: "Real-time priority", status: "warn", message: "Arm workers not running with SCHED_FIFO", hint: "Run scripts/setup_ubuntu.sh to grant rtprio to the station user." },
  ];
}

// --------------------------------------------------------------------------- jobs

const jobs: Record<string, Job> = {};

// --------------------------------------------------------------------------- startup sequence

let startupTimer: number | undefined;
function runStartup(arms: ArmSide[]) {
  setPhase("starting");
  startup = STARTUP_TEMPLATE.map((s) => ({ ...s, status: "pending", message: "", duration_s: 0 }));
  let i = 0;
  const tick = () => {
    if (phase !== "starting") return;
    if (i > 0) {
      const prev = startup[i - 1];
      prev.status = prev.id === "sync" ? "warn" : "ok";
      prev.message = STARTUP_MSG[prev.id];
      prev.duration_s = 0.3 + ((i * 37) % 10) / 10;
      if (prev.id === "power") for (const c of POWER) power[c.id] = true;
      log("INFO", "startup", `${prev.label}: ${prev.message}`);
    }
    if (i >= startup.length) {
      for (const a of arms) armUp[a] = true;
      setPhase("ready");
      return;
    }
    startup[i].status = "running";
    i++;
    startupTimer = window.setTimeout(tick, 550);
  };
  tick();
}

// --------------------------------------------------------------------------- router

function body<T>(b: unknown): T {
  return (b ?? {}) as T;
}

export async function mockFetch(method: string, url: string, b?: unknown): Promise<Resp> {
  await new Promise((r) => setTimeout(r, 60 + Math.random() * 90));
  const [path, query = ""] = url.split("?");
  const q = new URLSearchParams(query);
  const m = (re: RegExp) => path.match(re);
  let r: RegExpMatchArray | null;

  // station / session
  if (path === "/api/station" && method === "GET")
    return ok({ name: "Bay 2 bimanual cell", version: "1.0.0", sim: true, arms: ["left", "right"], cameras: CAMERAS, power_channels: POWER, data_root: "/home/lab/teleop-data" });
  if (path === "/api/session") {
    if (method === "PUT") {
      session = { ...session, ...body<Session>(b) };
      log("INFO", "session", `Session set: operator ${session.operator_id}, department ${session.department_id}, task ${session.task_id}`);
    }
    return ok(session);
  }

  // org
  if (path === "/api/departments") {
    if (method === "POST") {
      const d = body<Partial<Department>>(b);
      if (!d.name?.trim()) return err(422, "Department name is required.");
      if (departments.some((x) => x.name.toLowerCase() === d.name!.trim().toLowerCase())) return err(409, `A department named "${d.name}" already exists.`);
      const nd: Department = { id: nextId++, name: d.name.trim(), color: d.color ?? "#5B6875", description: d.description ?? "", user_count: 0, episode_count: 0 };
      departments.push(nd);
      return ok(nd);
    }
    recount();
    return ok(departments);
  }
  if ((r = m(/^\/api\/departments\/(\d+)$/))) {
    const d = departments.find((x) => x.id === +r![1]);
    if (!d) return err(404, "Department not found.");
    if (method === "PATCH") Object.assign(d, body<Partial<Department>>(b));
    if (method === "DELETE") {
      if (episodes.some((e) => e.department_id === d.id)) return err(409, `${d.name} has recorded episodes and can't be deleted.`, "Move or delete its episodes first.");
      departments.splice(departments.indexOf(d), 1);
      return { status: 204, body: undefined };
    }
    return ok(d);
  }
  if (path === "/api/users") {
    if (method === "POST") {
      const u = body<Partial<User>>(b);
      if (!u.name?.trim()) return err(422, "Name is required.");
      const nu: User = { id: nextId++, name: u.name.trim(), email: u.email || null, role: u.role ?? "operator", active: true, department_ids: u.department_ids ?? [], episode_count: 0, created_at: iso(new Date()) };
      users.push(nu);
      recount();
      return ok(nu);
    }
    recount();
    return ok(q.get("include_inactive") === "true" ? users : users.filter((u) => u.active));
  }
  if ((r = m(/^\/api\/users\/(\d+)$/))) {
    const u = users.find((x) => x.id === +r![1]);
    if (!u) return err(404, "Person not found.");
    if (method === "PATCH") Object.assign(u, body<Partial<User>>(b));
    recount();
    return ok(u);
  }
  if (path === "/api/tasks") {
    if (method === "POST") {
      const t = body<Partial<Task>>(b);
      if (!t.name?.trim()) return err(422, "Task name is required.");
      const nt: Task = { id: nextId++, name: t.name.trim(), slug: slugify(t.name), description: t.description ?? "", department_id: t.department_id ?? null };
      tasks.push(nt);
      return ok(nt);
    }
    const did = q.get("department_id");
    return ok(did ? tasks.filter((t) => t.department_id === +did) : tasks);
  }
  if ((r = m(/^\/api\/tasks\/(\d+)$/))) {
    const t = tasks.find((x) => x.id === +r![1]);
    if (!t) return err(404, "Task not found.");
    if (method === "PATCH") Object.assign(t, body<Partial<Task>>(b), body<Partial<Task>>(b).name ? { slug: slugify(body<Task>(b).name) } : {});
    if (method === "DELETE") {
      tasks.splice(tasks.indexOf(t), 1);
      return { status: 204, body: undefined };
    }
    return ok(t);
  }

  // control
  if (path === "/api/control/power") {
    const { channel, on } = body<{ channel: string; on: boolean }>(b);
    if (!estopOk && on) return err(409, "E-stop is pressed.", "Release the e-stop and clear the fault first.");
    const ids = channel === "all" ? POWER.map((c) => c.id) : [channel];
    ids.forEach((id) => (power[id] = on));
    if (!on && (channel === "all" || channel.includes("follower"))) {
      armUp.left = armUp.right = false;
      if (phase !== "fault") setPhase(channel === "all" ? "off" : "idle");
    }
    if (on && phase === "off") setPhase("idle");
    log("INFO", "power", `${ids.join(", ")} → ${on ? "on" : "off"}`);
    return ok({ channels: POWER.map((c) => ({ ...c, on: power[c.id] })) });
  }
  if (path === "/api/control/power_cycle") {
    const { channel, off_s = 3 } = body<{ channel: string; off_s?: number }>(b);
    const ids = channel === "all" ? POWER.map((c) => c.id) : [channel];
    log("INFO", "power", `Power-cycling ${ids.join(", ")} (parking followers first, off for ${off_s} s)`);
    ids.forEach((id) => (power[id] = false));
    if (ids.some((id) => id.includes("follower"))) {
      armUp.left = armUp.right = false;
      if (phase !== "off") setPhase("idle");
    }
    setTimeout(() => {
      ids.forEach((id) => (power[id] = true));
      log("INFO", "power", `${ids.join(", ")} back on`);
    }, off_s * 1000);
    return ok({});
  }
  if (path === "/api/control/start_arms") {
    if (!estopOk) return err(409, "E-stop is pressed.", "Release the e-stop, then clear the fault.");
    if (phase === "starting") return err(409, "Startup is already running.");
    if (["ready", "teleop", "recording"].includes(phase)) return err(409, "Arms are already running.");
    runStartup(body<{ arms?: ArmSide[] }>(b).arms ?? ["left", "right"]);
    return ok({ steps: startup });
  }
  if (path === "/api/control/stop_arms") {
    if (rec.active) return err(409, "A recording is in progress.", "Save or abort it before stopping the arms.");
    setPhase("stopping");
    window.clearTimeout(startupTimer);
    setTimeout(() => {
      armUp.left = armUp.right = false;
      setPhase("idle");
    }, 1500);
    return ok({});
  }
  if (path === "/api/control/teleop") {
    const { enabled } = body<{ enabled: boolean }>(b);
    if (enabled) {
      if (phase !== "ready") return err(409, "Start the arms before engaging teleop.", "Press Start arms and wait for the checklist to finish.");
      setPhase("teleop");
      teleopSince = now();
      log("INFO", "teleop", "Teleop engaged. Followers easing onto leader pose (3 s)");
    } else {
      if (rec.active) return err(409, "A recording is in progress.", "Save or abort it first.");
      if (phase === "teleop") setPhase("ready");
    }
    return ok({ teleop: phase === "teleop", since: teleopSince });
  }
  if (path === "/api/control/estop") {
    estopOk = true;
    if (rec.active) {
      rec.active = false;
      log("WARNING", "recorder", "Recording aborted by e-stop");
    }
    armUp.left = armUp.right = false;
    window.clearTimeout(startupTimer);
    setPhase("fault", "Software e-stop: triggers off, followers damped");
    return ok({});
  }
  if (path === "/api/control/clear_fault") {
    if (phase !== "fault") return ok({});
    setPhase("idle");
    return ok({});
  }
  if (path === "/api/control/home") {
    log("INFO", "teleop", "Moving followers to rest pose");
    return ok({});
  }

  // recording
  if (path === "/api/recording/start") {
    if (phase !== "teleop") return err(409, "Engage teleop before recording.", "Press Engage teleop (T) first.");
    if (!session.operator_id || !session.department_id || !session.task_id)
      return err(422, "Choose an operator, department and task first.", "Use the selectors in the top bar.");
    rec = { active: true, episode_id: `ep_${Math.random().toString(16).slice(2, 10)}`, t0: now(), frames: 0 };
    setPhase("recording");
    log("INFO", "recorder", `Recording ${rec.episode_id} → recordings/.staging/${rec.episode_id}`);
    return ok({ episode_id: rec.episode_id });
  }
  if (path === "/api/recording/save") {
    if (!rec.active) return err(409, "Nothing is being recorded.");
    const { success = true, notes = "" } = body<{ success?: boolean; notes?: string }>(b);
    const dur = now() - rec.t0;
    setPhase("saving");
    const u = users.find((x) => x.id === session.operator_id)!;
    const d = departments.find((x) => x.id === session.department_id)!;
    const t = tasks.find((x) => x.id === session.task_id)!;
    const when = new Date(Date.now() - dur * 1000);
    const ep: Episode = {
      id: rec.episode_id!,
      user_id: u.id,
      user_name: u.name,
      department_id: d.id,
      department_name: d.name,
      task_id: t.id,
      task_name: t.name,
      started_at: iso(when),
      duration_s: Math.round(dur * 10) / 10,
      frames: Math.floor(dur * 30),
      cameras: CAMERAS.map((c) => c.name),
      size_mb: Math.round(dur * 2.6 * 10) / 10,
      success,
      notes,
      tags: [],
      path: `recordings/${slugify(d.name)}/${slugify(u.name)}/${when.toISOString().slice(0, 19).replace(/[T:]/g, "-")}_${t.slug}`,
      status: "saved",
    };
    episodes.unshift(ep);
    recount();
    rec = { active: false, episode_id: null, t0: 0, frames: 0 };
    await new Promise((r2) => setTimeout(r2, 400));
    setPhase("teleop");
    log("INFO", "recorder", `Saved ${ep.id} (${ep.duration_s} s, ${ep.frames} frames) → ${ep.path}`);
    return ok(ep);
  }
  if (path === "/api/recording/abort") {
    if (!rec.active) return err(409, "Nothing is being recorded.");
    log("WARNING", "recorder", `Aborted ${rec.episode_id}, staging deleted`);
    rec = { active: false, episode_id: null, t0: 0, frames: 0 };
    setPhase("teleop");
    return ok({ deleted: true });
  }

  // episodes
  if (path === "/api/episodes") {
    let list = episodes.slice();
    const f = (k: string) => q.get(k);
    if (f("department_id")) list = list.filter((e) => e.department_id === +f("department_id")!);
    if (f("user_id")) list = list.filter((e) => e.user_id === +f("user_id")!);
    if (f("task_id")) list = list.filter((e) => e.task_id === +f("task_id")!);
    if (f("success")) list = list.filter((e) => String(e.success) === f("success"));
    if (f("q")) {
      const s = f("q")!.toLowerCase();
      list = list.filter((e) => [e.user_name, e.task_name, e.department_name, e.notes, e.id].join(" ").toLowerCase().includes(s));
    }
    const off = +(f("offset") ?? 0);
    const lim = +(f("limit") ?? 100);
    return ok({ items: list.slice(off, off + lim), total: list.length });
  }
  if ((r = m(/^\/api\/episodes\/([^/]+)\/telemetry$/))) {
    const e = episodes.find((x) => x.id === r![1]);
    if (!e) return err(404, "Episode not found.");
    const n = Math.min(+(q.get("max_points") ?? 1500), Math.round(e.duration_s * 30));
    const tt: number[] = [];
    const series: Record<string, number[]> = {};
    const keys = ["left.trigger.pos", "left.grip_force_n", "left.trigger.render_n", "left.trigger.force_n", "right.trigger.pos", "right.grip_force_n", "right.trigger.render_n", "right.trigger.force_n", "left.follower.q0", "left.follower.q1", "right.follower.q0", "right.follower.q1"];
    keys.forEach((k) => (series[k] = []));
    for (let i = 0; i < n; i++) {
      const t = (i / n) * e.duration_s;
      tt.push(t);
      for (const side of ["left", "right"]) {
        const ph = side === "left" ? 0 : 1.4;
        const pos = Math.max(0, Math.sin(((t + ph) / 6) * Math.PI) ** 2 * 0.9 - 0.05);
        const contact = pos > 0.45;
        const grip = contact ? (pos - 0.45) * 90 : 0;
        series[`${side}.trigger.pos`].push(pos);
        series[`${side}.grip_force_n`].push(grip);
        series[`${side}.trigger.render_n`].push(Math.min(12, grip * 0.25) + 1.5 * pos + 0.3);
        series[`${side}.trigger.force_n`].push(Math.min(12, grip * 0.25) + 1.5 * pos + 0.3 + (contact ? 1.1 : 0.2));
        series[`${side}.follower.q0`].push(0.4 * Math.sin(0.31 * t + ph));
        series[`${side}.follower.q1`].push(0.8 + 0.3 * Math.sin(0.23 * t + ph));
      }
    }
    return ok({ t: tt, series });
  }
  if ((r = m(/^\/api\/episodes\/([^/]+)$/))) {
    const e = episodes.find((x) => x.id === r![1]);
    if (!e) return err(404, "Episode not found.");
    if (method === "PATCH") Object.assign(e, body<Partial<Episode>>(b));
    if (method === "DELETE") {
      episodes.splice(episodes.indexOf(e), 1);
      recount();
      log("WARNING", "episodes", `Deleted ${e.id} (${e.path})`);
      return { status: 204, body: undefined };
    }
    return ok(e);
  }
  if (path === "/api/exports") {
    const { episode_ids = [], name = "export" } = body<{ episode_ids: string[]; name: string }>(b);
    if (!episode_ids.length) return err(422, "Select at least one episode to export.");
    const id = `job_${Math.random().toString(16).slice(2, 8)}`;
    const job: Job = { id, kind: "lerobot_export", status: "queued", progress: 0, message: "Queued", result: null };
    jobs[id] = job;
    log("INFO", "export", `Export ${name}: ${episode_ids.length} episode(s) queued`);
    let i = 0;
    const iv = setInterval(() => {
      i++;
      job.status = "running";
      job.progress = Math.min(1, i / (episode_ids.length * 4 + 2));
      const ep = Math.min(episode_ids.length, Math.floor(i / 4) + 1);
      job.message = `Encoding episode ${ep}/${episode_ids.length} (AV1, 3 cameras)`;
      if (job.progress >= 1) {
        clearInterval(iv);
        job.status = "done";
        job.message = `Wrote ${episode_ids.length} episodes`;
        job.result = { path: `/home/lab/teleop-data/datasets/${slugify(name)}`, repo_id: `local/${slugify(name)}`, episodes: episode_ids.length };
        log("INFO", "export", `Export ${name} done → datasets/${slugify(name)}`);
      }
    }, 300);
    return ok({ ...job });
  }
  if (path === "/api/jobs") return ok(Object.values(jobs).map((j) => ({ ...j })));
  if ((r = m(/^\/api\/jobs\/([^/]+)$/))) {
    const j = jobs[r[1]];
    return j ? ok({ ...j }) : err(404, "Job not found.");
  }

  // calibration
  if (path === "/api/calibration") return ok({ items: structuredClone(calItems) });
  if (path === "/api/calibration/procedures") return ok(procedures);
  if ((r = m(/^\/api\/calibration\/procedures\/([^/]+)\/(start|commit|cancel)$/))) {
    const p = procedures.find((x) => x.id === r![1]);
    if (!p) return err(404, "Unknown procedure.");
    if (r[2] === "start") {
      runs[p.id] = { procedure_id: p.id, step_index: 0, steps: p.steps.map((s) => ({ id: s.id, status: "pending", message: "", data: null })), result: null, can_commit: false };
      calActive = { pid: p.id, step: p.steps[0].id };
      log("INFO", "calibration", `Started ${p.title}`);
      return ok(structuredClone(runs[p.id]));
    }
    if (r[2] === "cancel") {
      delete runs[p.id];
      calActive = null;
      log("INFO", "calibration", `Cancelled ${p.title}`);
      return ok({});
    }
    const run = runs[p.id];
    if (!run?.can_commit) return err(409, "Finish every step before saving.");
    const item = calItems.find((c) => c.id === p.id);
    const u = users.find((x) => x.id === session.operator_id);
    if (item) {
      item.calibrated = true;
      item.updated_at = iso(new Date());
      item.updated_by = u?.name ?? null;
      item.summary = String(run.steps[run.steps.length - 1].message);
    }
    delete runs[p.id];
    calActive = null;
    log("INFO", "calibration", `Saved ${p.title} → calibration/${p.id}.yaml`);
    return ok(item);
  }
  if ((r = m(/^\/api\/calibration\/procedures\/([^/]+)\/steps\/([^/]+)$/))) {
    const p = procedures.find((x) => x.id === r![1]);
    const run = p && runs[p.id];
    if (!p || !run) return err(409, "Start the procedure first.");
    const idx = p.steps.findIndex((s) => s.id === r![2]);
    if (idx < 0) return err(404, "Unknown step.");
    if (idx > run.step_index) return err(409, "Complete the earlier steps first.");
    await new Promise((r2) => setTimeout(r2, p.steps[idx].action === "auto" ? 900 : 350));
    const { inputs = {} } = body<{ inputs?: Record<string, unknown> }>(b);
    const res = stepData(p, p.steps[idx].id, inputs);
    run.steps[idx] = { id: p.steps[idx].id, status: "ok", message: res.message, data: res.data };
    run.step_index = Math.max(run.step_index, idx + 1);
    calActive = { pid: p.id, step: p.steps[run.step_index]?.id ?? null };
    run.can_commit = run.steps.every((s) => s.status === "ok");
    if (run.can_commit) run.result = { summary: res.message };
    return ok(structuredClone(run));
  }
  if (path === "/api/calibration/scripts") {
    const { procedure_id } = body<{ procedure_id: string }>(b);
    const p = procedures.find((x) => x.id === procedure_id);
    if (!p) return err(404, "Unknown procedure.");
    const filename = `calibrate_${p.id}.py`;
    return ok({
      filename,
      path: `calibration/generated/${filename}`,
      content: `#!/usr/bin/env python3\n"""Standalone calibration: ${p.title}.\n\nGenerated by Teleop Station (mock). Run on the station PC:\n    python ${filename}\n"""\n\nfrom station.calibration.runner import run_procedure\n\nif __name__ == "__main__":\n    run_procedure("${p.id}", interactive=True)\n`,
    });
  }
  if ((r = m(/^\/api\/calibration\/files\/([^/]+)$/))) return ok(`# ${r[1]}.yaml (mock)\nversion: 1\n`);

  // health / logs / hardware
  if (path === "/api/health" || path === "/api/health/run") {
    if (path.endsWith("run")) await new Promise((r2) => setTimeout(r2, 700));
    return ok({ checks: healthChecks(), ran_at: iso(new Date()) });
  }
  if (path === "/api/logs") return ok(logBuf.slice(-(+(q.get("limit") ?? 500))));
  if (path === "/api/hardware/can/reset") {
    log("INFO", "can", "Reset all CAN interfaces (ip link down/up, 1 Mbit/s)");
    return ok({});
  }
  if ((r = m(/^\/api\/hardware\/arms\/(left|right)\/reconnect$/))) {
    log("INFO", `arm.${r[1]}`, "ArmWorker restarted");
    return ok({});
  }
  if ((r = m(/^\/api\/hardware\/dxl\/(left|right)\/scan$/))) {
    await new Promise((r2) => setTimeout(r2, 800));
    if (!power.leaders) return ok({ found: [] });
    return ok({
      found: [1, 2, 3, 4, 5, 6].map((id) => ({ id, model: "XL330-M288-T", firmware: 52 })).concat(r[1] === "left" ? [] : []),
    });
  }

  // settings
  if (path === "/api/settings") {
    if (method === "PUT") {
      settings = body<Settings>(b);
      log("INFO", "settings", "Settings updated");
    }
    return ok(settings);
  }

  return err(404, `No mock route for ${method} ${path}`);
}
