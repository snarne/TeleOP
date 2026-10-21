import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { CalItem, Procedure, ProcedureStep, RunState } from "../api/types";
import { CameraView } from "../components/CameraView";
import { IconChevron, IconRefresh, IconScript } from "../components/icons";
import { PageHeader } from "../components/Shell";
import { Badge, Button, Empty, Modal, StatusIcon } from "../components/ui";
import { useToast } from "../state/toasts";
import { ago } from "../lib/format";

const GROUPS: { kind: string; title: string; lead: string }[] = [
  { kind: "leader", title: "Leader arms", lead: "Maps each leader servo onto the matching follower joint." },
  { kind: "trigger", title: "Haptic triggers", lead: "Trigger travel, spring zero and spring stiffness." },
  { kind: "gripper", title: "Gripper force", lead: "Turns follower motor torque into newtons at the fingers." },
  { kind: "fingertips", title: "Fingertip sensors", lead: "Zeroes and scales the follower's jaw-pad load cells against a known weight." },
  { kind: "camera", title: "Cameras", lead: "Lens intrinsics from a printed ChArUco board." },
];

function downloadText(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/x-python" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function useScriptGenerator() {
  const toast = useToast();
  return useCallback(
    async (procedureId: string) => {
      try {
        const r = await api.post<{ filename: string; path: string; content: string }>("/api/calibration/scripts", { procedure_id: procedureId });
        downloadText(r.filename, r.content);
        toast.push("success", `Generated ${r.filename}`, `Also saved on the station at ${r.path}`);
      } catch (e) {
        toast.error(e, "Couldn't generate the script");
      }
    },
    [toast],
  );
}

function humanize(k: string): string {
  const s = k.replace(/_/g, " ");
  return s
    .replace(/\bdeg\b/, "(°)")
    .replace(/\bn\b$/, "(N)")
    .replace(/\bnm\b/, "(N·m)")
    .replace(/\bpx\b/, "(px)")
    .replace(/^./, (c) => c.toUpperCase());
}

function LiveReadings({ live }: { live: Record<string, unknown> }) {
  const entries = Object.entries(live);
  if (!entries.length) return <div className="live-empty">Waiting for live readings from the hardware…</div>;
  return (
    <div className="live-grid">
      {entries.map(([k, v]) => {
        if (Array.isArray(v) && v.every((x) => typeof x === "number")) {
          const arr = v as number[];
          const isJoints = k.includes("joint");
          return (
            <div key={k} className="live-array">
              <div className="live-k">{humanize(k)}</div>
              <div className="live-cells">
                {arr.map((x, i) => (
                  <div key={i} className="live-cell">
                    <span className="live-cell-k">{isJoints ? (i < 6 ? `J${i + 1}` : "Trig") : i + 1}</span>
                    <span className="live-cell-v tnum">{Number.isInteger(x) ? x : x.toFixed(1)}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        }
        return (
          <div key={k} className="live-scalar">
            <div className="live-k">{humanize(k)}</div>
            <div className="live-v tnum">{typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(2)) : String(v)}</div>
          </div>
        );
      })}
    </div>
  );
}

function StepAction({
  step,
  enabled,
  busy,
  onRun,
}: {
  step: ProcedureStep;
  enabled: boolean;
  busy: boolean;
  onRun: (inputs: Record<string, unknown>) => void;
}) {
  const [vals, setVals] = useState<Record<string, string>>({});
  useEffect(() => {
    const init: Record<string, string> = {};
    for (const i of step.inputs ?? []) init[i.key] = i.default !== undefined ? String(i.default) : "";
    setVals(init);
  }, [step]);
  const label = step.action === "capture" ? "Capture" : step.action === "auto" ? "Run" : step.action === "confirm" ? "Done, continue" : "Record value";
  const submit = () => {
    const inputs: Record<string, unknown> = {};
    for (const i of step.inputs ?? []) inputs[i.key] = i.type === "number" ? parseFloat(vals[i.key]) : vals[i.key];
    onRun(inputs);
  };
  return (
    <form
      className="step-action"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {(step.inputs ?? []).map((i) => (
        <label key={i.key} className="field step-input">
          <span className="field-label">{i.label}</span>
          <span className="input-unit">
            {i.type === "select" ? (
              <select value={vals[i.key] ?? ""} onChange={(e) => setVals({ ...vals, [i.key]: e.target.value })}>
                {(i.options ?? []).map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            ) : (
              <input
                type={i.type === "number" ? "number" : "text"}
                step="any"
                value={vals[i.key] ?? ""}
                onChange={(e) => setVals({ ...vals, [i.key]: e.target.value })}
                disabled={!enabled}
              />
            )}
            {i.unit && <span className="unit">{i.unit}</span>}
          </span>
        </label>
      ))}
      <Button variant="primary" size="lg" type="submit" disabled={!enabled} loading={busy}>
        {label}
      </Button>
    </form>
  );
}

function Wizard({ proc, onExit, onSaved }: { proc: Procedure; onExit: () => void; onSaved: () => void }) {
  const toast = useToast();
  const genScript = useScriptGenerator();
  const [run, setRun] = useState<RunState | null>(null);
  const [view, setView] = useState(0);
  const [busy, setBusy] = useState(false);
  const [startError, setStartError] = useState<{ detail: string; hint?: string } | null>(null);
  const live = useLive((s) => (s.calibration.active === proc.id ? s.calibration.live : null), null);

  const start = useCallback(async () => {
    setBusy(true);
    setStartError(null);
    try {
      const r = await api.post<RunState>(`/api/calibration/procedures/${proc.id}/start`);
      setRun(r);
      setView(0);
    } catch (e) {
      const err = e as { message?: string; hint?: string };
      setStartError({ detail: err.message ?? "The station refused to start this calibration.", hint: err.hint });
    } finally {
      setBusy(false);
    }
  }, [proc.id, toast]);

  useEffect(() => {
    void start();
  }, [start]);

  const runStep = async (idx: number, inputs: Record<string, unknown>) => {
    setBusy(true);
    try {
      const r = await api.post<RunState>(`/api/calibration/procedures/${proc.id}/steps/${proc.steps[idx].id}`, { inputs });
      setRun(r);
      const st = r.steps[idx];
      if (st.status === "ok") setView(Math.min(proc.steps.length - 1, idx + 1));
      else toast.push("error", `${proc.steps[idx].title} failed`, st.message);
    } catch (e) {
      toast.error(e, "Step failed");
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    try {
      await api.post(`/api/calibration/procedures/${proc.id}/cancel`);
    } catch {
      /* already gone */
    }
    onExit();
  };

  const commit = async () => {
    setBusy(true);
    try {
      await api.post<CalItem>(`/api/calibration/procedures/${proc.id}/commit`);
      toast.push("success", `${proc.title} calibrated`, "The new calibration is active now.");
      onSaved();
    } catch (e) {
      toast.error(e, "Couldn't save calibration");
    } finally {
      setBusy(false);
    }
  };

  const step = proc.steps[view];
  const stepState = run?.steps[view];
  const reachable = run ? view <= run.step_index : false;
  const done = run?.steps.filter((s) => s.status === "ok").length ?? 0;

  return (
    <div className="wizard">
      <div className="wizard-head">
        <button className="crumb" onClick={() => void cancel()}>
          All calibrations
        </button>
        <IconChevron size={14} />
        <span className="crumb-current">{proc.title}</span>
      </div>
      <div className="page-head">
        <div>
          <h1>{proc.title}</h1>
          <p className="page-lead">{proc.description}</p>
        </div>
        <div className="page-head-actions">
          <Button variant="secondary" icon={<IconScript size={18} />} onClick={() => void genScript(proc.id)}>
            Generate standalone script
          </Button>
          <Button variant="ghost" onClick={() => void cancel()}>
            Cancel
          </Button>
        </div>
      </div>

      {startError && (
        <div className="start-error" role="alert">
          <div>
            <strong>This calibration can't start yet.</strong> {startError.detail.charAt(0).toUpperCase() + startError.detail.slice(1).replace(/\.$/, "")}.
            {startError.hint && <span className="start-error-hint">{startError.hint}</span>}
          </div>
          <Button variant="secondary" size="sm" icon={<IconRefresh size={15} />} onClick={() => void start()} loading={busy}>
            Try again
          </Button>
        </div>
      )}
      <div className="wizard-body">
        <ol className="wizard-steps" aria-label="Steps">
          {proc.steps.map((s, i) => {
            const st = run?.steps[i];
            const state = st?.status === "ok" ? "ok" : st?.status === "error" ? "error" : run && i === run.step_index ? "current" : "pending";
            return (
              <li key={s.id}>
                <button
                  className={`wstep ws-${state} ${i === view ? "viewing" : ""}`}
                  onClick={() => setView(i)}
                  disabled={!run || i > run.step_index}
                >
                  <span className="wstep-num">{st?.status === "ok" ? <StatusIcon status="ok" size={14} /> : i + 1}</span>
                  <span className="wstep-text">
                    <span className="wstep-title">{s.title}</span>
                    {st?.message && <span className="wstep-msg">{st.message}</span>}
                  </span>
                </button>
              </li>
            );
          })}
          <li className="wizard-progress tnum">
            {done} of {proc.steps.length} steps done
          </li>
        </ol>

        <section className="panel wizard-stage">
          {step && (
            <>
              <header className="stage-head">
                <span className="stage-count tnum">
                  Step {view + 1} of {proc.steps.length}
                </span>
                <h2>{step.title}</h2>
              </header>
              <div className="stage-grid">
                <div className="stage-main">
                  <p className="stage-instruction">{step.instruction}</p>
                  {step.image && <img className="stage-image" src={step.image} alt="" />}
                  {stepState?.status === "ok" && (
                    <div className="stage-result ok">
                      <StatusIcon status="ok" />
                      <span>{stepState.message}</span>
                    </div>
                  )}
                  {stepState?.status === "error" && (
                    <div className="stage-result err">
                      <StatusIcon status="error" />
                      <span>{stepState.message}</span>
                    </div>
                  )}
                  <StepAction step={step} enabled={reachable && !busy} busy={busy} onRun={(inp) => void runStep(view, inp)} />
                  {stepState?.status === "ok" && view < proc.steps.length - 1 && (
                    <Button variant="ghost" onClick={() => void runStep(view, {})} icon={<IconRefresh size={16} />} disabled={busy}>
                      Redo this step
                    </Button>
                  )}
                </div>
                <div className="stage-side">
                  {proc.kind === "camera" ? (
                    <CameraView name={proc.target} label={proc.title.replace(/ camera$/, "")} overlay="charuco" />
                  ) : null}
                  <div className="live-box">
                    <div className="live-title">Live readings</div>
                    <LiveReadings live={live ?? {}} />
                  </div>
                </div>
              </div>
            </>
          )}
          {run?.can_commit && (
            <footer className="stage-commit">
              <div>
                <strong>All steps done.</strong> Save to make this calibration active. The previous file is kept as a backup.
              </div>
              <Button variant="primary" size="lg" onClick={() => void commit()} loading={busy}>
                Save calibration
              </Button>
            </footer>
          )}
        </section>
      </div>
    </div>
  );
}

export function CalibrationPage() {
  const toast = useToast();
  const genScript = useScriptGenerator();
  const [items, setItems] = useState<CalItem[] | null>(null);
  const [procs, setProcs] = useState<Procedure[]>([]);
  const [params, setParams] = useSearchParams();
  const [fileView, setFileView] = useState<{ id: string; text: string } | null>(null);
  const activeElsewhere = useLive((s) => s.calibration.active, null as string | null);
  const runId = params.get("run");

  const load = useCallback(async () => {
    try {
      const [i, p] = await Promise.all([
        api.get<{ items: CalItem[] }>("/api/calibration"),
        api.get<Procedure[]>("/api/calibration/procedures"),
      ]);
      setItems(i.items);
      setProcs(p);
    } catch (e) {
      toast.error(e, "Couldn't load calibration status");
      setItems([]);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const proc = useMemo(() => procs.find((p) => p.id === runId), [procs, runId]);
  if (runId && proc)
    return (
      <div className="page">
        <Wizard
          key={proc.id}
          proc={proc}
          onExit={() => setParams({})}
          onSaved={() => {
            setParams({});
            void load();
          }}
        />
      </div>
    );

  const missing = (items ?? []).filter((i) => !i.calibrated).length;

  return (
    <div className="page">
      <PageHeader
        title="Calibration"
        lead={
          items
            ? missing
              ? `${missing} item${missing > 1 ? "s" : ""} still need${missing > 1 ? "" : "s"} calibrating. Each wizard takes 2–5 minutes.`
              : "Everything is calibrated. Recalibrate after re-assembling an arm or moving a camera."
            : "Loading calibration status…"
        }
      />
      {activeElsewhere && !runId && (
        <div className="inline-note">
          A calibration is in progress ({activeElsewhere.replace(/_/g, " ")}).{" "}
          <button className="link-btn" onClick={() => setParams({ run: activeElsewhere })}>
            Open it
          </button>
        </div>
      )}
      {items && items.length === 0 && <Empty title="No calibration procedures are configured">Check the station configuration file.</Empty>}
      <div className="cal-groups">
        {GROUPS.map((g) => {
          const gi = (items ?? []).filter((i) => i.kind === g.kind);
          if (!gi.length) return null;
          return (
            <section key={g.kind} className="panel cal-group">
              <header className="panel-head">
                <div>
                  <h2 className="panel-title">{g.title}</h2>
                  <div className="panel-sub">{g.lead}</div>
                </div>
              </header>
              <ul className="cal-rows">
                {gi.map((it) => (
                  <li key={it.id} className={`cal-row ${it.calibrated ? "" : "needs"}`}>
                    <StatusIcon status={it.calibrated ? "ok" : "warn"} size={20} />
                    <div className="cal-row-text">
                      <div className="cal-row-title">
                        <h3>{it.label}</h3>
                        {!it.calibrated && <Badge tone="warn">Needs calibration</Badge>}
                      </div>
                      <p className="cal-summary">{it.summary}</p>
                      <p className="cal-meta">{it.updated_at ? `Updated ${ago(it.updated_at)}${it.updated_by ? ` by ${it.updated_by}` : ""}` : "Never calibrated on this station"}</p>
                    </div>
                    <div className="cal-actions">
                      {it.calibrated && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={async () => {
                            try {
                              const t = await api.text(`/api/calibration/files/${it.id}`);
                              setFileView({ id: it.id, text: t });
                            } catch (e) {
                              toast.error(e, "Couldn't open the file");
                            }
                          }}
                        >
                          File
                        </Button>
                      )}
                      <Button variant="ghost" size="sm" icon={<IconScript size={16} />} onClick={() => void genScript(it.id)} title="Download a standalone Python script for this calibration">
                        Script
                      </Button>
                      <Button variant={it.calibrated ? "secondary" : "primary"} size="sm" onClick={() => setParams({ run: it.id })} disabled={!procs.some((p) => p.id === it.id)}>
                        {it.calibrated ? "Recalibrate" : "Calibrate"}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
      <Modal open={!!fileView} title={`${fileView?.id ?? ""}.yaml`} onClose={() => setFileView(null)} width={640}>
        <pre className="filebox">{fileView?.text}</pre>
      </Modal>
    </div>
  );
}
