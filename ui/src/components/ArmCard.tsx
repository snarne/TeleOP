import { armHistory } from "../api/history";
import { useLive } from "../api/live";
import type { ArmSide, ArmSnapshot } from "../api/types";
import { num, RAD2DEG } from "../lib/format";
import { LivePlot, type SeriesSpec } from "./Plot";
import { Badge, Meter } from "./ui";

const FORCE_SERIES: SeriesSpec[] = [
  { key: "force_n", label: "Squeeze", color: "--s-op", width: 2 },
  { key: "render_n", label: "Feedback", color: "--s-render", width: 1.75, dash: [5, 3] },
  { key: "grip_force_n", label: "Follower grip", color: "--s-grip", width: 2 },
];

const STATE_TONE: Record<ArmSnapshot["state"], "ok" | "warn" | "err" | "idle" | "primary"> = {
  offline: "idle",
  connecting: "warn",
  connected: "primary",
  syncing: "warn",
  teleop: "ok",
  fault: "err",
};
export const ARM_STATE_LABEL: Record<ArmSnapshot["state"], string> = {
  offline: "Offline",
  connecting: "Connecting",
  connected: "Connected",
  syncing: "Easing in",
  teleop: "Following",
  fault: "Fault",
};

function JointRow({ i, leader, follower, live }: { i: number; leader: number; follower: number; live: boolean }) {
  const range = Math.PI;
  const toPct = (v: number) => 50 + (Math.max(-range, Math.min(range, v)) / range) * 50;
  const delta = (leader - follower) * RAD2DEG;
  return (
    <div className="joint-row">
      <span className="joint-name">J{i + 1}</span>
      <div className="joint-track">
        <span className="joint-center" />
        {live && (
          <>
            <span className="joint-fill" style={{ left: `${Math.min(50, toPct(follower))}%`, width: `${Math.abs(toPct(follower) - 50)}%` }} />
            <span className="joint-leader" style={{ left: `${toPct(leader)}%` }} title="Leader" />
          </>
        )}
      </div>
      <span className="joint-val tnum">{live ? `${(follower * RAD2DEG).toFixed(0)}°` : "—"}</span>
      <span className={`joint-delta tnum ${Math.abs(delta) > 5 ? "warn" : ""}`}>{live ? `${delta >= 0 ? "+" : "−"}${Math.abs(delta).toFixed(1)}` : ""}</span>
    </div>
  );
}

export function ArmCard({ side }: { side: ArmSide }) {
  const a = useLive((s) => s.arms[side], undefined);
  const title = side === "left" ? "Left arm" : "Right arm";
  if (!a) {
    return (
      <section className="panel arm-card">
        <header className="panel-head">
          <h2 className="panel-title">{title}</h2>
          <Badge>No data yet</Badge>
        </header>
      </section>
    );
  }
  const up = a.state !== "offline";
  return (
    <section className={`panel arm-card ${a.state === "fault" ? "arm-fault" : ""}`}>
      <header className="panel-head arm-head">
        <div className="arm-title">
          <h2 className="panel-title">{title}</h2>
          <Badge tone={STATE_TONE[a.state]}>{ARM_STATE_LABEL[a.state]}</Badge>
          {a.contact && <Badge tone="ok">In contact</Badge>}
          {a.slip && <Badge tone="warn">Slipping</Badge>}
        </div>
        <div className="arm-stats tnum">
          <span title="Control loop rate">
            <b>{up ? num(a.loop_hz, 0) : "—"}</b> Hz
          </span>
          <span title="Control loop jitter (p99)">
            <b>{up ? num(a.loop_jitter_ms, 2) : "—"}</b> ms jitter
          </span>
          <span title="Max joint error between leader command and follower" className={a.tracking_error_rad * RAD2DEG > 5 ? "warn" : ""}>
            <b>{up ? num(a.tracking_error_rad * RAD2DEG, 1) : "—"}</b>° lag
          </span>
        </div>
      </header>
      {a.fault && <div className="arm-fault-msg">{a.fault}</div>}
      <div className="arm-body">
        <div className="arm-forces">
          <div className="force-readouts">
            <div className="force-readout">
              <span className="force-key" style={{ background: "var(--s-op)" }} />
              <span className="force-label" title="How hard the operator squeezes the trigger">Squeeze</span>
              <span className="force-num tnum">{up ? num(a.trigger.force_n, 1) : "—"}</span>
              <span className="unit">N</span>
            </div>
            <div className="force-readout">
              <span className="force-key dashed" style={{ borderColor: "var(--s-render)" }} />
              <span className="force-label" title="Resistance the trigger pushes back with">Feedback</span>
              <span className="force-num tnum">{up ? num(a.trigger.render_n, 1) : "—"}</span>
              <span className="unit">N</span>
            </div>
            <div className="force-readout">
              <span className="force-key" style={{ background: "var(--s-grip)" }} />
              <span className="force-label" title={a.grip_source === "fingertip" ? "Measured by the follower's fingertip load cells" : "Estimated from the gripper motor torque"}>
                Follower grip{a.grip_source === "fingertip" ? " · fingertips" : ""}
              </span>
              <span className="force-num tnum">{up ? num(a.grip_force_n, 1) : "—"}</span>
              <span className="unit">N</span>
            </div>
          </div>
          <LivePlot ring={armHistory[side]} series={FORCE_SERIES} windowS={10} height={118} yLabel="N" nonNegative />
        </div>
        <div className="arm-side">
          <div className="arm-meter-row">
            <span className="arm-meter-label">Trigger</span>
            <Meter value={a.trigger.pos} tone="op" label="Trigger position" />
            <span className="tnum arm-meter-val">{up ? `${Math.round(a.trigger.pos * 100)}%` : "—"}</span>
          </div>
          <div className="arm-meter-row">
            <span className="arm-meter-label">Gripper open</span>
            <Meter value={a.follower.gripper} tone="grip" label="Gripper opening" />
            <span className="tnum arm-meter-val">{up ? `${Math.round(a.follower.gripper * 100)}%` : "—"}</span>
          </div>
          <div className="arm-meta">
            <span>
              Trigger mode <b>{a.trigger.mode === "render" ? "Force feedback" : a.trigger.mode === "spring" ? "Spring only" : "Off"}</b>
            </span>
            <span>
              Hottest motor <b className="tnum">{up && a.follower.temps_c.length ? `${Math.max(...a.follower.temps_c).toFixed(0)} °C` : "—"}</b>
            </span>
          </div>
          <div className="joints" aria-label="Joint positions">
            <div className="joints-head">
              <span>Follower joints</span>
              <span className="joints-legend">
                <span className="jl-leader" /> leader <span className="jl-fol" /> follower <span className="joints-dl">Δ°</span>
              </span>
            </div>
            {a.follower.q.map((q, i) => (
              <JointRow key={i} i={i} leader={a.leader.q[i] ?? 0} follower={q} live={up} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
