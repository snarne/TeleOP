import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, qs } from "../api/client";
import { useConnStatus, useLive } from "../api/live";
import type { Episode, Paged, Phase, StartupStep } from "../api/types";
import { ArmCard } from "../components/ArmCard";
import { CameraView } from "../components/CameraView";
import { IconLink, IconPlay, IconPower, IconRecord, IconSave, IconStop, IconUnlink, IconX } from "../components/icons";
import { Badge, Button, StatusIcon } from "../components/ui";
import { useAppData } from "../state/appdata";
import { keyLabel, useController } from "../state/controller";
import { clock, dateTime, duration } from "../lib/format";

const RAIL: { id: Phase; label: string; sub: string }[] = [
  { id: "off", label: "Off", sub: "Arms unpowered" },
  { id: "idle", label: "Powered", sub: "Power on, arms idle" },
  { id: "ready", label: "Arms ready", sub: "Connected and checked" },
  { id: "teleop", label: "Teleop", sub: "Followers track leaders" },
  { id: "recording", label: "Recording", sub: "Capturing an episode" },
];

function railIndex(p: Phase): number {
  switch (p) {
    case "off":
      return 0;
    case "idle":
    case "starting":
    case "fault":
      return 1;
    case "ready":
    case "stopping":
      return 2;
    case "teleop":
      return 3;
    case "recording":
    case "saving":
      return 4;
  }
}

function StateRail() {
  const phase = useLive((s) => s.phase, "off" as Phase);
  const idx = railIndex(phase);
  const transitional = phase === "starting" || phase === "stopping" || phase === "saving";
  return (
    <ol className={`rail ph-${phase}`} aria-label="Station progress">
      {RAIL.map((r, i) => {
        const state = i < idx ? "done" : i === idx ? "current" : "todo";
        return (
          <li key={r.id} className={`rail-step ${state} ${state === "current" && transitional ? "busy" : ""}`} aria-current={state === "current" ? "step" : undefined}>
            <span className="rail-node" />
            <span className="rail-text">
              <span className="rail-label">{r.label}</span>
              <span className="rail-sub">
                {state === "current" && phase === "starting"
                  ? "Running startup checks"
                  : state === "current" && phase === "stopping"
                    ? "Parking followers"
                    : state === "current" && phase === "saving"
                      ? "Writing episode to disk"
                      : state === "current" && phase === "fault"
                        ? "Stopped: clear the fault"
                        : r.sub}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function ActionBar() {
  const c = useController();
  const { settings, session } = useAppData();
  const phase = useLive((s) => s.phase, "off" as Phase);
  const rec = useLive((s) => s.recording, { active: false, episode_id: null, elapsed_s: 0, frames: 0, size_mb: 0 });
  const kb = settings?.keybindings;
  const conn = useConnStatus();
  const hasData = useLive(() => true, false);
  const sessionReady = !!(session.operator_id && session.department_id && session.task_id);
  const b = c.busy;

  let main: React.ReactNode = null;
  let side: React.ReactNode = null;
  let note: React.ReactNode = null;

  if (conn !== "open" || !hasData) {
    return (
      <div className="actionbar">
        <div className="actionbar-main">
          <Button variant="primary" size="lg" disabled>
            Waiting for the station
          </Button>
        </div>
        <p className="actionbar-note">Controls unlock as soon as the station service answers.</p>
      </div>
    );
  }

  switch (phase) {
    case "off":
      main = (
        <Button variant="primary" size="lg" icon={<IconPower size={20} />} onClick={() => void c.powerAll(true)} loading={b === "Power on"}>
          Power on arms
        </Button>
      );
      note = "Switches the relay channels for both followers, the leaders and the camera hub.";
      break;
    case "idle":
      main = (
        <Button variant="primary" size="lg" icon={<IconPlay size={20} />} onClick={() => void c.startArms()} loading={b === "Start arms"}>
          Start arms
        </Button>
      );
      side = (
        <Button variant="ghost" icon={<IconPower size={18} />} onClick={() => void c.powerAll(false)} loading={b === "Power off"}>
          Power off
        </Button>
      );
      note = "Connects every device and runs the startup checks. Keep the leaders roughly matched to the followers.";
      break;
    case "starting":
      main = (
        <Button variant="primary" size="lg" loading>
          Starting arms
        </Button>
      );
      note = "Running the checklist below. This takes about 5 seconds.";
      break;
    case "ready":
      main = (
        <Button variant="primary" size="lg" icon={<IconLink size={20} />} kbd={kb?.teleop_toggle} onClick={() => void c.setTeleop(true)} loading={b === "Engage teleop"}>
          Engage teleop
        </Button>
      );
      side = (
        <Button variant="ghost" icon={<IconStop size={18} />} onClick={() => void c.stopArms()} loading={b === "Stop arms"}>
          Stop arms
        </Button>
      );
      note = "The followers ease onto the leader pose over 3 seconds, then track it.";
      break;
    case "teleop":
      main = (
        <Button
          variant="record"
          size="lg"
          icon={<IconRecord size={20} />}
          kbd={kb?.start_recording}
          onClick={() => void c.startRecording()}
          loading={b === "Start recording"}
          disabled={!sessionReady}
        >
          Start recording
        </Button>
      );
      side = (
        <Button variant="ghost" icon={<IconUnlink size={18} />} kbd={kb?.teleop_toggle} onClick={() => void c.setTeleop(false)} loading={b === "Release teleop"}>
          Release teleop
        </Button>
      );
      note = sessionReady ? "Episodes are filed by department, operator and start time." : (
        <span className="note-warn">Choose an operator, department and task in the top bar to record.</span>
      );
      break;
    case "recording":
      main = (
        <>
          <Button variant="primary" size="lg" icon={<IconSave size={20} />} kbd={kb?.save} onClick={c.requestSave} loading={b === "Save"}>
            Save
          </Button>
          <Button variant="danger" size="lg" icon={<IconX size={20} />} kbd={kb?.abort} onClick={c.requestAbort} loading={b === "Abort"}>
            Abort
          </Button>
        </>
      );
      side = (
        <div className="rec-stats tnum">
          <span className="rec-big">{clock(rec.elapsed_s)}</span>
          <span>{rec.frames.toLocaleString()} frames</span>
          <span>{rec.size_mb.toFixed(0)} MB</span>
        </div>
      );
      note = "Save files the episode. Abort deletes it.";
      break;
    case "saving":
      main = (
        <Button variant="primary" size="lg" loading>
          Saving episode
        </Button>
      );
      break;
    case "stopping":
      main = (
        <Button variant="secondary" size="lg" loading>
          Stopping arms
        </Button>
      );
      break;
    case "fault":
      main = (
        <Button variant="primary" size="lg" onClick={() => void c.clearFault()} loading={b === "Clear fault"}>
          Clear fault
        </Button>
      );
      note = "Clearing returns the station to Powered. Start the arms again to continue.";
      break;
  }

  return (
    <div className="actionbar">
      <div className="actionbar-main">{main}</div>
      {side && <div className="actionbar-side">{side}</div>}
      {note && <p className="actionbar-note">{note}</p>}
    </div>
  );
}

function StartupChecklist() {
  const steps = useLive((s) => s.startup.steps, [] as StartupStep[]);
  const phase = useLive((s) => s.phase, "off" as Phase);
  const [dismissed, setDismissed] = useState<string>("");
  const sig = steps.map((s) => s.id + s.status).join(",");
  if (!steps.length) return null;
  const problems = steps.some((s) => s.status === "error" || s.status === "warn");
  const visible = phase === "starting" || ((phase === "ready" || phase === "idle" || phase === "fault") && problems && dismissed !== sig);
  if (!visible) return null;
  const done = steps.filter((s) => s.status !== "pending" && s.status !== "running").length;
  return (
    <section className="panel checklist">
      <header className="panel-head">
        <div>
          <h2 className="panel-title">Startup checks</h2>
          <div className="panel-sub tnum">
            {done} of {steps.length} done
          </div>
        </div>
        {phase !== "starting" && (
          <Button variant="ghost" size="sm" onClick={() => setDismissed(sig)}>
            Hide
          </Button>
        )}
      </header>
      <ol className="checklist-steps" style={{ gridTemplateRows: `repeat(${Math.ceil(steps.length / 2)}, auto)` }}>
        {steps.map((s) => (
          <li key={s.id} className={`check-step cs-${s.status}`}>
            <StatusIcon status={s.status} />
            <span className="check-label">{s.label}</span>
            <span className="check-msg">
              {s.message}
              {s.hint && <span className="check-hint">{s.hint}</span>}
            </span>
            <span className="check-time tnum">{s.duration_s > 0 ? `${s.duration_s.toFixed(1)} s` : ""}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function RecentEpisodes() {
  const { session } = useAppData();
  const { episodesVersion } = useController();
  const [eps, setEps] = useState<Episode[] | null>(null);
  useEffect(() => {
    let off = false;
    api
      .get<Paged<Episode>>(`/api/episodes${qs({ user_id: session.operator_id, limit: 6 })}`)
      .then((r) => !off && setEps(r.items))
      .catch(() => !off && setEps([]));
    return () => {
      off = true;
    };
  }, [session.operator_id, episodesVersion]);
  return (
    <section className="panel recent">
      <header className="panel-head">
        <h2 className="panel-title">{session.operator_id ? "Your recent episodes" : "Recent episodes"}</h2>
        <Link to="/episodes" className="link">
          All episodes
        </Link>
      </header>
      {eps && eps.length === 0 && <div className="recent-empty">No episodes yet. Engage teleop and press record to capture the first one.</div>}
      <ul className="recent-list">
        {(eps ?? []).map((e) => (
          <li key={e.id}>
            <span className={`outcome-dot ${e.success === true ? "ok" : e.success === false ? "err" : "unk"}`} title={e.success === true ? "Success" : e.success === false ? "Failure" : "Not marked"} />
            <span className="recent-task">{e.task_name}</span>
            <span className="recent-when">{dateTime(e.started_at)}</span>
            <span className="recent-dur tnum">{duration(e.duration_s)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function OperatePage() {
  const { station } = useAppData();
  const cams = station?.cameras ?? [
    { name: "left_wrist", label: "Left wrist" },
    { name: "overhead", label: "Overhead" },
    { name: "right_wrist", label: "Right wrist" },
  ];
  const order = ["left_wrist", "overhead", "right_wrist"];
  const rank = (n: string) => (order.indexOf(n) < 0 ? 99 : order.indexOf(n));
  const sorted = [...cams].sort((a, b) => rank(a.name) - rank(b.name));
  const sim = useLive((s) => s.sim, false);
  return (
    <div className="page operate">
      <div className="operate-top">
        <StateRail />
        <ActionBar />
      </div>
      <StartupChecklist />
      <div className={`cams cams-${sorted.length}`}>
        {sorted.map((c) => (
          <CameraView key={c.name} name={c.name} label={c.label} className={c.name === "overhead" ? "cam-main" : ""} />
        ))}
      </div>
      <div className="arms">
        {(station?.arms ?? ["left", "right"]).map((s) => (
          <ArmCard key={s} side={s} />
        ))}
      </div>
      <div className="operate-foot">
        <RecentEpisodes />
        <KeyHelp />
      </div>
      {sim && <div className="sim-note"><Badge tone="warn">Simulation</Badge> All hardware on this station is simulated. Data recorded here is synthetic.</div>}
    </div>
  );
}

function KeyHelp() {
  const { settings } = useAppData();
  if (!settings) return null;
  const k = settings.keybindings;
  const rows: [string, string][] = [
    [k.start_recording, "Start recording"],
    [k.save, "Save (opens the save dialog, press again to confirm)"],
    [k.abort, "Abort (press twice for long recordings)"],
    [k.mark_success, "Mark success"],
    [k.mark_failure, "Mark failure"],
    [k.teleop_toggle, "Engage or release teleop"],
    [k.estop, "Emergency stop"],
  ];
  const hb = settings.handle_buttons;
  const label = (a: string) => a.replace(/_/g, " ");
  return (
    <section className="panel keyhelp">
      <header className="panel-head">
        <h2 className="panel-title">Shortcuts</h2>
        <Link to="/settings" className="link">
          Change
        </Link>
      </header>
      <dl className="keyhelp-list">
        {rows.map(([code, text]) => (
          <div key={text}>
            <dt>
              <kbd className="kbd">{code ? keyLabel(code) : "—"}</kbd>
            </dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
      <div className="keyhelp-handles">
        Handle buttons: left A {label(hb.left_a ?? "—")}, left B {label(hb.left_b ?? "—")}, right A {label(hb.right_a ?? "—")}, right B {label(hb.right_b ?? "—")}.
      </div>
    </section>
  );
}
