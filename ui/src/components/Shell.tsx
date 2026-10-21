import { useEffect, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { MOCK } from "../api/client";
import { useConnStatus, useLive } from "../api/live";
import type { Phase } from "../api/types";
import { useAppData } from "../state/appdata";
import { useController } from "../state/controller";
import { clock, PHASE_LABEL } from "../lib/format";
import {
  IconCalibrate,
  IconEpisodes,
  IconHardware,
  IconMoon,
  IconOperate,
  IconPeople,
  IconSettings,
  IconSun,
} from "./icons";
import { Kbd } from "./ui";

export function PhasePill({ phase, large }: { phase: Phase; large?: boolean }) {
  return (
    <span className={`phase-pill ph-${phase} ${large ? "large" : ""}`}>
      <span className="phase-dot" />
      {PHASE_LABEL[phase]}
    </span>
  );
}

function SessionSelectors() {
  const { users, departments, tasks, session, setSession } = useAppData();
  const operators = users.filter((u) => u.active);
  const deptTasks = tasks.filter((t) => t.department_id === session.department_id || t.department_id === null);
  const recording = useLive((s) => s.recording.active, false);
  const op = users.find((u) => u.id === session.operator_id);

  return (
    <div className="session">
      <label className="session-field">
        <span>Operator</span>
        <select
          value={session.operator_id ?? ""}
          disabled={recording}
          onChange={(e) => {
            const id = e.target.value ? +e.target.value : null;
            const u = users.find((x) => x.id === id);
            const dept = u && session.department_id && u.department_ids.includes(session.department_id) ? session.department_id : u?.department_ids[0] ?? null;
            void setSession({ operator_id: id, department_id: dept, task_id: dept === session.department_id ? session.task_id : null });
          }}
        >
          <option value="">Choose…</option>
          {operators.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </select>
      </label>
      <label className="session-field">
        <span>Department</span>
        <select
          value={session.department_id ?? ""}
          disabled={recording}
          onChange={(e) => void setSession({ department_id: e.target.value ? +e.target.value : null, task_id: null })}
        >
          <option value="">Choose…</option>
          {departments.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
              {op && !op.department_ids.includes(d.id) ? " (not a member)" : ""}
            </option>
          ))}
        </select>
      </label>
      <label className="session-field session-task">
        <span>Task</span>
        <select value={session.task_id ?? ""} disabled={recording || !session.department_id} onChange={(e) => void setSession({ task_id: e.target.value ? +e.target.value : null })}>
          <option value="">{session.department_id ? "Choose…" : "Pick a department"}</option>
          {deptTasks.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function RecordingIndicator() {
  const rec = useLive((s) => (s.recording.active ? s.recording.elapsed_s : -1), -1);
  if (rec < 0) return null;
  return (
    <div className="rec-indicator" title="Recording">
      <span className="rec-dot" />
      <span className="tnum">{clock(rec)}</span>
    </div>
  );
}

function EStopButton() {
  const { estop } = useController();
  const { settings } = useAppData();
  return (
    <button className="estop" onClick={() => void estop()} title="Software emergency stop. The red hardware button always works too.">
      <span className="estop-ring">
        <span className="estop-cap">STOP</span>
      </span>
      <span className="estop-meta">
        <span>E-stop</span>
        <Kbd code={settings?.keybindings.estop ?? "Escape"} />
      </span>
    </button>
  );
}

export function TopBar() {
  const { station } = useAppData();
  const phase = useLive((s) => s.phase, "off" as Phase);
  const conn = useConnStatus();
  const hasData = useLive(() => true, false);
  const sim = useLive((s) => s.sim, station?.sim ?? false);
  return (
    <header className="topbar">
      <div className="topbar-id">
        <div className="station-name">{station?.name ?? "Teleop Station"}</div>
        <div className="station-flags">
          {conn === "open" && hasData ? (
            <PhasePill phase={phase} />
          ) : (
            <span className="phase-pill ph-offline">
              <span className="phase-dot" />
              Not connected
            </span>
          )}
          {sim && <span className="sim-badge" title="All hardware is simulated">Simulation</span>}
          {MOCK && <span className="sim-badge mock" title="UI is running against an in-browser mock">Mock data</span>}
        </div>
      </div>
      <SessionSelectors />
      <div className="topbar-right">
        <RecordingIndicator />
        <EStopButton />
      </div>
    </header>
  );
}

const NAV = [
  { to: "/", label: "Operate", icon: IconOperate, end: true },
  { to: "/calibration", label: "Calibrate", icon: IconCalibrate },
  { to: "/hardware", label: "Hardware", icon: IconHardware },
  { to: "/episodes", label: "Episodes", icon: IconEpisodes },
  { to: "/organization", label: "People", icon: IconPeople },
  { to: "/settings", label: "Settings", icon: IconSettings },
];

type Theme = "system" | "light" | "dark";
function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const t = localStorage.getItem("ts.theme");
      return t === "light" || t === "dark" ? t : "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    try {
      if (theme === "system") localStorage.removeItem("ts.theme");
      else localStorage.setItem("ts.theme", theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);
  return [theme, setTheme];
}

export function NavRail() {
  const [theme, setTheme] = useTheme();
  const isDark =
    theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const fault = useLive((s) => s.phase === "fault", false);
  const healthWarn = useLive(
    (s) => Object.values(s.arms).some((a) => a && a.state === "fault") || !s.power.estop_ok,
    false,
  );
  return (
    <nav className="navrail" aria-label="Main">
      <div className="nav-logo" aria-hidden="true">
        <svg viewBox="0 0 32 32" width="30" height="30">
          <rect width="32" height="32" rx="7" fill="var(--primary)" />
          <path d="M8 23 L13 12 L19 17 L24 9" stroke="var(--safety)" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="8" cy="23" r="2.6" fill="var(--primary-ink)" />
          <circle cx="24" cy="9" r="2.6" fill="var(--primary-ink)" />
        </svg>
      </div>
      <ul>
        {NAV.map((n) => (
          <li key={n.to}>
            <NavLink to={n.to} end={n.end} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <n.icon size={22} />
              <span>{n.label}</span>
              {n.to === "/hardware" && (fault || healthWarn) && <span className="nav-alert" />}
            </NavLink>
          </li>
        ))}
      </ul>
      <button
        className="nav-theme"
        onClick={() => setTheme(isDark ? "light" : "dark")}
        title={`Switch to ${isDark ? "light" : "dark"} theme`}
        aria-label={`Switch to ${isDark ? "light" : "dark"} theme`}
      >
        {isDark ? <IconSun size={20} /> : <IconMoon size={20} />}
      </button>
    </nav>
  );
}

export function ConnectionBanner() {
  const conn = useConnStatus();
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (conn === "open") {
      setShow(false);
      return;
    }
    const t = setTimeout(() => setShow(true), 1200);
    return () => clearTimeout(t);
  }, [conn]);
  if (!show) return null;
  return (
    <div className="conn-banner" role="alert">
      <span>
        <strong>Can't reach the station service.</strong> Reconnecting automatically, and controls are paused until it's back. If this persists,
        check that <code>station serve</code> is running on the station PC.
      </span>
    </div>
  );
}

export function FaultBanner() {
  const phase = useLive((s) => s.phase, "off" as Phase);
  const detail = useLive((s) => s.phase_detail, "");
  const estopOk = useLive((s) => s.power.estop_ok, true);
  const { clearFault, busy } = useController();
  if (phase !== "fault" && estopOk) return null;
  return (
    <div className="fault-banner" role="alert">
      <div>
        <strong>{!estopOk ? "Hardware e-stop is pressed." : "Station stopped."}</strong>{" "}
        {!estopOk ? "Twist the red button to release it, then clear the fault." : detail || "Check the logs in Hardware for the cause."}
      </div>
      {phase === "fault" && (
        <button className="btn btn-secondary btn-sm" onClick={() => void clearFault()} disabled={!estopOk || busy !== null}>
          Clear fault
        </button>
      )}
    </div>
  );
}

export function PageHeader({ title, children, lead }: { title: string; children?: ReactNode; lead?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {lead && <p className="page-lead">{lead}</p>}
      </div>
      {children && <div className="page-head-actions">{children}</div>}
    </div>
  );
}
