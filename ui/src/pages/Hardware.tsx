import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { armHistory, systemHistory } from "../api/history";
import { subscribeLogs, useLive } from "../api/live";
import type { ArmSide, HealthCheck, HealthReport, LogLine, PowerChannel } from "../api/types";
import { IconCopy, IconCycle, IconPause, IconPlay, IconRefresh, IconSearch } from "../components/icons";
import { Legend, LivePlot, type SeriesSpec } from "../components/Plot";
import { PageHeader } from "../components/Shell";
import { Badge, Button, ConfirmModal, Panel, StatusIcon, Toggle } from "../components/ui";
import { useAppData } from "../state/appdata";
import { useController } from "../state/controller";
import { useToast } from "../state/toasts";
import { ago } from "../lib/format";
import { ARM_STATE_LABEL } from "../components/ArmCard";

// --------------------------------------------------------------------------- health

function HealthPanel() {
  const toast = useToast();
  const [report, setReport] = useState<HealthReport | null>(null);
  const [running, setRunning] = useState(false);
  const load = useCallback(
    async (rerun: boolean) => {
      setRunning(rerun);
      try {
        setReport(rerun ? await api.post<HealthReport>("/api/health/run") : await api.get<HealthReport>("/api/health"));
      } catch (e) {
        toast.error(e, "Couldn't load health checks");
      } finally {
        setRunning(false);
      }
    },
    [toast],
  );
  useEffect(() => {
    void load(false);
    const iv = setInterval(() => void load(false), 10000);
    return () => clearInterval(iv);
  }, [load]);

  const groups = useMemo(() => {
    const m = new Map<string, HealthCheck[]>();
    for (const c of report?.checks ?? []) {
      if (!m.has(c.group)) m.set(c.group, []);
      m.get(c.group)!.push(c);
    }
    return [...m.entries()];
  }, [report]);
  const counts = useMemo(() => {
    const c = { ok: 0, warn: 0, error: 0, unknown: 0 };
    for (const x of report?.checks ?? []) c[x.status]++;
    return c;
  }, [report]);

  return (
    <Panel
      className="health"
      title="Health checks"
      subtitle={report ? `Checked ${ago(report.ran_at)}. ${counts.error} problem${counts.error === 1 ? "" : "s"}, ${counts.warn} warning${counts.warn === 1 ? "" : "s"}` : "Loading…"}
      actions={
        <Button size="sm" icon={<IconRefresh size={16} />} onClick={() => void load(true)} loading={running}>
          Run checks
        </Button>
      }
      pad={false}
    >
      <div className="health-groups">
        {groups.map(([g, checks]) => (
          <div key={g} className="health-group">
            <h3 className="health-group-title">{g.charAt(0).toUpperCase() + g.slice(1)}</h3>
            <ul>
              {checks.map((c) => (
                <li key={c.id} className={`health-row hs-${c.status}`}>
                  <StatusIcon status={c.status} />
                  <span className="health-label">{c.label}</span>
                  <span className="health-msg">
                    {c.message}
                    {c.hint && c.status !== "ok" && <span className="health-hint">{c.hint}</span>}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// --------------------------------------------------------------------------- power

function PowerPanel() {
  const { run } = useController();
  const power = useLive((s) => s.power, { available: false, estop_ok: true, channels: [] as PowerChannel[] });
  const [confirm, setConfirm] = useState<{ kind: "cycle" | "off"; channel: string; label: string } | null>(null);

  const doConfirm = async () => {
    if (!confirm) return;
    const c = confirm;
    setConfirm(null);
    if (c.kind === "cycle") await run("Power cycle", () => api.post("/api/control/power_cycle", { channel: c.channel, off_s: 3 }), `Power-cycling ${c.label}`);
    else await run("Power off", () => api.post("/api/control/power", { channel: c.channel, on: false }), `${c.label} off`);
  };

  return (
    <Panel
      className="power"
      title="Power"
      subtitle={power.available ? "Relay board channels" : "No relay board configured"}
      actions={
        <Button size="sm" icon={<IconCycle size={16} />} onClick={() => setConfirm({ kind: "cycle", channel: "all", label: "everything" })} disabled={!power.available}>
          Cycle all
        </Button>
      }
      pad={false}
    >
      <div className={`estop-status ${power.estop_ok ? "ok" : "bad"}`}>
        <span className="estop-mini" aria-hidden="true" />
        <div>
          <div className="estop-status-title">{power.estop_ok ? "E-stop released" : "E-stop pressed"}</div>
          <div className="estop-status-sub">{power.estop_ok ? "The hardware stop loop is closed. Arms can be powered." : "Arm power is cut. Twist the red button to release it."}</div>
        </div>
      </div>
      <ul className="power-list">
        {power.channels.map((ch) => (
          <li key={ch.id}>
            <span className={`power-led ${ch.on ? "on" : ""}`} />
            <span className="power-label">{ch.label}</span>
            <Button variant="ghost" size="sm" icon={<IconCycle size={15} />} onClick={() => setConfirm({ kind: "cycle", channel: ch.id, label: ch.label })} disabled={!ch.on}>
              Cycle
            </Button>
            <Toggle
              checked={ch.on}
              label={`${ch.label} power`}
              onChange={(v) => {
                if (!v && ch.id.includes("follower")) setConfirm({ kind: "off", channel: ch.id, label: ch.label });
                else void run(v ? "Power on" : "Power off", () => api.post("/api/control/power", { channel: ch.id, on: v }));
              }}
            />
          </li>
        ))}
      </ul>
      <ConfirmModal
        open={!!confirm}
        title={confirm?.kind === "cycle" ? `Power-cycle ${confirm.label}?` : `Turn off ${confirm?.label}?`}
        confirmLabel={confirm?.kind === "cycle" ? "Power-cycle" : "Turn off"}
        danger
        onClose={() => setConfirm(null)}
        onConfirm={() => void doConfirm()}
        body={
          confirm?.kind === "cycle" ? (
            <>Followers are parked in their rest pose first, then power is off for 3 seconds. Any running teleop stops, and you'll need to start the arms again.</>
          ) : (
            <>The station parks this follower before cutting power. If parking fails, the arm will sag onto the table when power drops, so keep the workspace clear.</>
          )
        }
      />
    </Panel>
  );
}

// --------------------------------------------------------------------------- device tools

function DevicesPanel() {
  const { station } = useAppData();
  const { run } = useController();
  const toast = useToast();
  const [scan, setScan] = useState<Partial<Record<ArmSide, { id: number; model: string; firmware: number }[] | "scanning">>>({});
  const arms = useLive((s) => s.arms, {});

  const doScan = async (side: ArmSide) => {
    setScan((x) => ({ ...x, [side]: "scanning" }));
    try {
      const r = await api.post<{ found: { id: number; model: string; firmware: number }[] }>(`/api/hardware/dxl/${side}/scan`);
      setScan((x) => ({ ...x, [side]: r.found }));
    } catch (e) {
      toast.error(e, "Scan failed");
      setScan((x) => ({ ...x, [side]: undefined }));
    }
  };

  return (
    <Panel title="Devices" subtitle="Reconnect a single arm or look for servos without restarting the station" pad={false}>
      <div className="dev-row">
        <div>
          <div className="dev-title">CAN interfaces</div>
          <div className="dev-sub">Brings every follower CAN adapter down and up again at 1 Mbit/s.</div>
        </div>
        <Button size="sm" onClick={() => void run("Reset CAN", () => api.post("/api/hardware/can/reset"), "CAN interfaces reset")}>
          Reset CAN
        </Button>
      </div>
      {(station?.arms ?? ["left", "right"]).map((side) => {
        const res = scan[side];
        const a = arms[side];
        return (
          <div key={side} className="dev-row dev-arm">
            <div>
              <div className="dev-title">
                {side === "left" ? "Left" : "Right"} arm{" "}
                {a && <Badge tone={a.state === "fault" ? "err" : a.state === "offline" ? "idle" : "ok"}>{ARM_STATE_LABEL[a.state] ?? a.state}</Badge>}
              </div>
              <div className="dev-sub">
                {a?.fault ? <span className="dev-fault">{a.fault}</span> : "Restart its worker process (leader bus, trigger and follower)."}
              </div>
              {res && res !== "scanning" && (
                <div className="scan-result">
                  {res.length === 0 ? (
                    <span className="dev-fault">No servos answered. Check the leader's 5 V supply and U2D2 cable.</span>
                  ) : (
                    <table>
                      <thead>
                        <tr>
                          <th>ID</th>
                          <th>Model</th>
                          <th>Firmware</th>
                        </tr>
                      </thead>
                      <tbody>
                        {res.map((f) => (
                          <tr key={f.id}>
                            <td className="tnum">{f.id}</td>
                            <td>{f.model}</td>
                            <td className="tnum">{f.firmware}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
            <div className="dev-actions">
              <Button size="sm" variant="ghost" onClick={() => void doScan(side)} loading={res === "scanning"}>
                Scan servos
              </Button>
              <Button size="sm" onClick={() => void run("Reconnect", () => api.post(`/api/hardware/arms/${side}/reconnect`), `${side === "left" ? "Left" : "Right"} arm reconnecting`)}>
                Reconnect
              </Button>
            </div>
          </div>
        );
      })}
    </Panel>
  );
}

// --------------------------------------------------------------------------- plots

const HZ: SeriesSpec[] = [
  { key: "loop_hz", label: "Left", color: "--s-op" },
  { key: "loop_hz", label: "Right", color: "--s-grip" },
];

function PlotsPanel() {
  const sys = useLive((s) => s.system, { cpu_pct: 0, mem_pct: 0, disk_free_gb: 0, disk_total_gb: 0 });
  return (
    <Panel title="Live performance" subtitle="Last 60 seconds" className="perf">
      <div className="perf-grid">
        <div>
          <div className="perf-title">Control loop rate (Hz)</div>
          <div className="perf-pair">
            <LivePlot ring={armHistory.left} series={[{ key: "loop_hz", label: "Left", color: "--s-op" }]} windowS={60} height={90} refreshMs={250} />
            <LivePlot ring={armHistory.right} series={[{ key: "loop_hz", label: "Right", color: "--s-grip" }]} windowS={60} height={90} refreshMs={250} />
          </div>
          <Legend series={HZ} />
        </div>
        <div>
          <div className="perf-title">Tracking error (°)</div>
          <div className="perf-pair">
            <LivePlot ring={armHistory.left} series={[{ key: "tracking_deg", label: "Left", color: "--s-op" }]} windowS={60} height={90} refreshMs={250} nonNegative />
            <LivePlot ring={armHistory.right} series={[{ key: "tracking_deg", label: "Right", color: "--s-grip" }]} windowS={60} height={90} refreshMs={250} nonNegative />
          </div>
        </div>
        <div>
          <div className="perf-title">Hottest follower motor (°C)</div>
          <div className="perf-pair">
            <LivePlot ring={armHistory.left} series={[{ key: "tmax", label: "Left", color: "--s-op" }]} windowS={60} height={90} refreshMs={500} />
            <LivePlot ring={armHistory.right} series={[{ key: "tmax", label: "Right", color: "--s-grip" }]} windowS={60} height={90} refreshMs={500} />
          </div>
        </div>
        <div>
          <div className="perf-title">
            Station PC <span className="perf-inline tnum">CPU {sys.cpu_pct.toFixed(0)}%, memory {sys.mem_pct.toFixed(0)}%, {sys.disk_free_gb.toFixed(0)} GB free</span>
          </div>
          <LivePlot
            ring={systemHistory}
            series={[
              { key: "cpu", label: "CPU", color: "--s-render" },
              { key: "mem", label: "Memory", color: "--s-aux" },
            ]}
            windowS={60}
            height={90}
            refreshMs={500}
            yRange={[0, 100]}
          />
          <Legend
            series={[
              { key: "cpu", label: "CPU %", color: "--s-render" },
              { key: "mem", label: "Memory %", color: "--s-aux" },
            ]}
          />
        </div>
      </div>
    </Panel>
  );
}

// --------------------------------------------------------------------------- logs

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;
const LEVEL_RANK: Record<string, number> = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 4 };

function LogConsole() {
  const toast = useToast();
  const [lines, setLines] = useState<LogLine[]>([]);
  const [paused, setPaused] = useState(false);
  const [minLevel, setMinLevel] = useState<string>("INFO");
  const [source, setSource] = useState("");
  const [q, setQ] = useState("");
  const buf = useRef<LogLine[]>([]);
  const pausedRef = useRef(false);
  pausedRef.current = paused;
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const unsub = subscribeLogs((l) => {
      buf.current.push(l);
      if (buf.current.length > 5000) buf.current.splice(0, buf.current.length - 5000);
    });
    const iv = setInterval(() => {
      if (!pausedRef.current) setLines(buf.current.slice());
    }, 250);
    return () => {
      unsub();
      clearInterval(iv);
    };
  }, []);

  const sources = useMemo(() => [...new Set(lines.map((l) => l.source))].sort(), [lines]);
  const shown = useMemo(() => {
    const ql = q.toLowerCase();
    return lines.filter(
      (l) => (LEVEL_RANK[l.level] ?? 1) >= LEVEL_RANK[minLevel] && (!source || l.source === source || l.source.startsWith(source + ".")) && (!ql || l.message.toLowerCase().includes(ql) || l.source.includes(ql)),
    );
  }, [lines, minLevel, source, q]);

  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [shown]);

  const fmt = (l: LogLine) => {
    const d = new Date(l.ts * 1000);
    return `${d.toLocaleTimeString([], { hour12: false })}.${String(d.getMilliseconds()).padStart(3, "0")}`;
  };

  const copy = async () => {
    const text = shown.map((l) => `${fmt(l)} ${l.level.padEnd(7)} ${l.source}: ${l.message}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      toast.push("success", `Copied ${shown.length} log lines`);
    } catch {
      toast.push("error", "Couldn't copy to the clipboard", "The browser blocked clipboard access on this page.");
    }
  };

  return (
    <Panel
      className="logs"
      title="Logs"
      subtitle={`${shown.length.toLocaleString()} of ${lines.length.toLocaleString()} lines`}
      pad={false}
      actions={
        <>
          <Button size="sm" variant="ghost" icon={<IconCopy size={15} />} onClick={() => void copy()}>
            Copy
          </Button>
          <Button size="sm" variant={paused ? "primary" : "secondary"} icon={paused ? <IconPlay size={15} /> : <IconPause size={15} />} onClick={() => setPaused(!paused)}>
            {paused ? "Resume" : "Pause"}
          </Button>
        </>
      }
    >
      <div className="log-filters">
        <div className="segmented" role="radiogroup" aria-label="Minimum level">
          {LEVELS.map((l) => (
            <button key={l} role="radio" aria-checked={minLevel === l} className={minLevel === l ? "active" : ""} onClick={() => setMinLevel(l)}>
              {l === "WARNING" ? "Warning" : l[0] + l.slice(1).toLowerCase()}
              {l !== "ERROR" ? "+" : ""}
            </button>
          ))}
        </div>
        <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="Source">
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <label className="search">
          <IconSearch size={16} />
          <input type="search" placeholder="Search messages" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
      </div>
      <div
        className="log-box"
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
        }}
      >
        {shown.length === 0 && <div className="log-empty">No log lines match these filters.</div>}
        {shown.map((l, i) => (
          <div key={i} className={`log-line lv-${l.level}`}>
            <span className="log-ts tnum">{fmt(l)}</span>
            <span className="log-lv">{l.level === "WARNING" ? "WARN" : l.level}</span>
            <span className="log-src">{l.source}</span>
            <span className="log-msg">{l.message}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function HardwarePage() {
  return (
    <div className="page">
      <PageHeader title="Hardware and diagnostics" lead="Start here when something isn't working. Every check says what's wrong and what to try next." />
      <div className="hw-grid">
        <HealthPanel />
        <div className="hw-side">
          <PowerPanel />
          <DevicesPanel />
        </div>
      </div>
      <PlotsPanel />
      <LogConsole />
    </div>
  );
}
