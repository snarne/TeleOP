import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, MOCK, qs } from "../api/client";
import type { Episode, Job, Paged, Telemetry } from "../api/types";
import { drawMockFrame } from "../mock/camera";
import { IconExport, IconPause, IconPlay, IconSearch, IconTrash } from "../components/icons";
import { Legend, StaticPlot, type SeriesSpec } from "../components/Plot";
import { PageHeader } from "../components/Shell";
import { Badge, Button, ConfirmModal, Drawer, Empty, Field, Meter, Modal, Segmented } from "../components/ui";
import { useAppData } from "../state/appdata";
import { useController } from "../state/controller";
import { useToast } from "../state/toasts";
import { cameraLabel, clock, dateTime, duration } from "../lib/format";

type Outcome = "all" | "true" | "false" | "null";
const PAGE = 50;

function OutcomeBadge({ success }: { success: boolean | null }) {
  if (success === true) return <Badge tone="ok">Success</Badge>;
  if (success === false) return <Badge tone="err">Failure</Badge>;
  return <Badge>Unmarked</Badge>;
}

// --------------------------------------------------------------------------- synced player

function SyncedVideos({ episode, t, playing, onTime, onDuration, seekTo }: { episode: Episode; t: number; playing: boolean; onTime: (t: number) => void; onDuration: (d: number) => void; seekTo: { t: number; n: number } }) {
  const refs = useRef<(HTMLVideoElement | null)[]>([]);
  const canvases = useRef<(HTMLCanvasElement | null)[]>([]);
  const [failed, setFailed] = useState<Record<string, boolean>>({});

  // real videos: master is the first; others follow
  useEffect(() => {
    if (MOCK) return;
    const vids = refs.current.filter(Boolean) as HTMLVideoElement[];
    vids.forEach((v) => (playing ? void v.play().catch(() => undefined) : v.pause()));
  }, [playing]);
  useEffect(() => {
    if (MOCK) return;
    (refs.current.filter(Boolean) as HTMLVideoElement[]).forEach((v) => (v.currentTime = seekTo.t));
  }, [seekTo]);
  useEffect(() => {
    if (MOCK) return;
    const iv = setInterval(() => {
      const [m, ...rest] = refs.current.filter(Boolean) as HTMLVideoElement[];
      if (!m) return;
      for (const v of rest) if (Math.abs(v.currentTime - m.currentTime) > 0.08) v.currentTime = m.currentTime;
    }, 500);
    return () => clearInterval(iv);
  }, []);

  // mock: draw frames on canvases
  useEffect(() => {
    if (!MOCK) return;
    canvases.current.forEach((c, i) => {
      const ctx = c?.getContext("2d");
      if (c && ctx) drawMockFrame(ctx, episode.cameras[i], c.width, c.height);
    });
  }, [t, episode]);

  return (
    <div className={`ep-videos n${episode.cameras.length}`}>
      {episode.cameras.map((cam, i) => (
        <figure key={cam} className="ep-video">
          <div className="cam-frame">
            {MOCK ? (
              <canvas ref={(el) => (canvases.current[i] = el)} width={640} height={480} />
            ) : (
              <video
                ref={(el) => (refs.current[i] = el)}
                src={`/api/episodes/${episode.id}/video/${cam}`}
                muted
                playsInline
                preload="auto"
                onTimeUpdate={i === 0 ? (e) => onTime(e.currentTarget.currentTime) : undefined}
                onLoadedMetadata={i === 0 ? (e) => onDuration(e.currentTarget.duration) : undefined}
                onError={() => setFailed((f) => ({ ...f, [cam]: true }))}
              />
            )}
            {failed[cam] && (
              <div className="cam-nosignal">
                <span>This browser can't play this video.</span>
                <span className="cam-nosignal-hint">
                  Use Chrome or Firefox, or{" "}
                  <a href={`/api/episodes/${episode.id}/video/${cam}`} download>
                    download the MP4
                  </a>
                  .
                </span>
              </div>
            )}
          </div>
          <figcaption className="cam-cap">
            <span className="cam-name">{cameraLabel(cam)}</span>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

// Backends may name force series "left.grip_force_n" or "left.grip_force"; match both.
const isOpForce = (k: string) => /trigger[._]force/.test(k);
const isRender = (k: string) => /render/.test(k);
const isGrip = (k: string) => /grip_force/.test(k);

function pickDefaultSeries(keys: string[]): string[] {
  const got = keys.filter((k) => isOpForce(k) || isRender(k) || isGrip(k));
  return got.length ? got : keys.slice(0, 4);
}

const PALETTE = ["--s-op", "--s-render", "--s-grip", "--s-aux", "--primary", "--warn", "--ok", "--err"];

function seriesSpec(key: string, i: number): SeriesSpec {
  const color = isOpForce(key) ? "--s-op" : isRender(key) ? "--s-render" : isGrip(key) ? "--s-grip" : PALETTE[i % PALETTE.length];
  return { key, label: key, color, dash: key.startsWith("right.") ? [6, 3] : undefined };
}

function EpisodeDetail({ episode, onChanged, onDeleted }: { episode: Episode; onChanged: (e: Episode) => void; onDeleted: () => void }) {
  const toast = useToast();
  const [tel, setTel] = useState<Telemetry | null>(null);
  const [sel, setSel] = useState<string[]>([]);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(episode.duration_s);
  const [playing, setPlaying] = useState(false);
  const [seek, setSeek] = useState({ t: 0, n: 0 });
  const [notes, setNotes] = useState(episode.notes);
  const [confirmDel, setConfirmDel] = useState(false);
  const [tags, setTags] = useState(episode.tags.join(", "));

  useEffect(() => {
    setNotes(episode.notes);
    setTags(episode.tags.join(", "));
  }, [episode.notes, episode.tags]);

  useEffect(() => {
    setT(0);
    setPlaying(false);
    setDur(episode.duration_s);
    let off = false;
    api
      .get<Telemetry>(`/api/episodes/${episode.id}/telemetry?max_points=1500`)
      .then((r) => {
        if (off) return;
        setTel(r);
        setSel(pickDefaultSeries(Object.keys(r.series)));
      })
      .catch((e) => {
        if (!off) {
          setTel({ t: [], series: {} });
          toast.error(e, "Couldn't load telemetry");
        }
      });
    return () => {
      off = true;
    };
  }, [episode.id, episode.duration_s, toast]);

  // mock playback clock
  useEffect(() => {
    if (!MOCK || !playing) return;
    let last = performance.now();
    let raf = 0;
    const loop = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setT((x) => {
        const n = x + dt;
        if (n >= dur) {
          setPlaying(false);
          return dur;
        }
        return n;
      });
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, dur]);

  const doSeek = (v: number) => {
    const c = Math.max(0, Math.min(dur, v));
    setT(c);
    setSeek((s) => ({ t: c, n: s.n + 1 }));
  };

  const patch = async (body: Partial<Episode>, msg: string) => {
    try {
      const e = await api.patch<Episode>(`/api/episodes/${episode.id}`, body);
      onChanged(e);
      toast.push("success", msg);
    } catch (e) {
      toast.error(e, "Couldn't update the episode");
    }
  };

  const specs = useMemo(() => sel.map((k, i) => seriesSpec(k, i)), [sel]);
  const allKeys = tel ? Object.keys(tel.series) : [];

  return (
    <div className="ep-detail">
      <SyncedVideos episode={episode} t={t} playing={playing} onTime={setT} onDuration={(d) => isFinite(d) && setDur(d)} seekTo={seek} />
      <div className="player-bar">
        <Button variant="primary" size="sm" icon={playing ? <IconPause size={16} /> : <IconPlay size={16} />} onClick={() => setPlaying(!playing)}>
          {playing ? "Pause" : "Play"}
        </Button>
        <input
          type="range"
          className="scrub"
          min={0}
          max={dur || 1}
          step={0.033}
          value={t}
          onChange={(e) => doSeek(parseFloat(e.target.value))}
          aria-label="Playback position"
          style={{ ["--pct" as string]: `${(t / (dur || 1)) * 100}%` }}
        />
        <span className="tnum player-time">
          {clock(t)} / {clock(dur)}
        </span>
      </div>

      <section className="panel ep-tel">
        <header className="panel-head">
          <div>
            <h2 className="panel-title">Telemetry</h2>
            <div className="panel-sub">Click the plot to jump the videos to that moment. Dashed lines are the right arm.</div>
          </div>
        </header>
        <div className="panel-body">
          {!tel && <div className="muted">Loading telemetry…</div>}
          {tel && tel.t.length === 0 && <div className="muted">This episode has no telemetry samples.</div>}
          {tel && tel.t.length > 0 && (
            <>
              <StaticPlot t={tel.t} data={tel.series} series={specs} height={200} playhead={t} onSeek={doSeek} />
              <Legend series={specs} />
              <div className="series-chips">
                {allKeys.map((k) => (
                  <button key={k} className={`chip ${sel.includes(k) ? "on" : ""}`} onClick={() => setSel(sel.includes(k) ? sel.filter((x) => x !== k) : [...sel, k])}>
                    {k}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </section>

      <section className="panel ep-meta">
        <div className="panel-body ep-meta-grid">
          <div>
            <Field label="Outcome">
              <Segmented
                value={episode.success === true ? "true" : episode.success === false ? "false" : "null"}
                options={[
                  { value: "true", label: "Success" },
                  { value: "false", label: "Failure" },
                  { value: "null", label: "Unmarked" },
                ]}
                onChange={(v) => void patch({ success: v === "true" ? true : v === "false" ? false : null }, "Outcome updated")}
              />
            </Field>
            <Field label="Notes">
              <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== episode.notes && void patch({ notes }, "Notes saved")} />
            </Field>
            <Field label="Tags" hint="Comma separated, e.g. warmup, occluded">
              <input
                type="text"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                onBlur={() => {
                  const next = tags.split(",").map((x) => x.trim()).filter(Boolean);
                  if (next.join(",") !== episode.tags.join(",")) void patch({ tags: next }, "Tags saved");
                }}
              />
            </Field>
          </div>
          <dl className="ep-facts">
            <div>
              <dt>Operator</dt>
              <dd>{episode.user_name}</dd>
            </div>
            <div>
              <dt>Department</dt>
              <dd>{episode.department_name}</dd>
            </div>
            <div>
              <dt>Started</dt>
              <dd>{new Date(episode.started_at).toLocaleString()}</dd>
            </div>
            <div>
              <dt>Length</dt>
              <dd className="tnum">
                {duration(episode.duration_s)}, {episode.frames.toLocaleString()} frames
              </dd>
            </div>
            <div>
              <dt>Size</dt>
              <dd className="tnum">{episode.size_mb.toFixed(1)} MB</dd>
            </div>
            <div>
              <dt>Folder</dt>
              <dd>
                <code className="path">{episode.path}</code>
              </dd>
            </div>
            <div>
              <dt>Episode ID</dt>
              <dd>
                <code>{episode.id}</code>
              </dd>
            </div>
          </dl>
        </div>
        <footer className="ep-meta-foot">
          <Button variant="danger" size="sm" icon={<IconTrash size={16} />} onClick={() => setConfirmDel(true)}>
            Delete episode
          </Button>
        </footer>
      </section>
      <ConfirmModal
        open={confirmDel}
        title="Delete this episode?"
        danger
        confirmLabel="Delete permanently"
        onClose={() => setConfirmDel(false)}
        onConfirm={async () => {
          setConfirmDel(false);
          try {
            await api.del(`/api/episodes/${episode.id}`);
            toast.push("success", "Episode deleted");
            onDeleted();
          } catch (e) {
            toast.error(e, "Couldn't delete the episode");
          }
        }}
        body={
          <>
            The videos and telemetry in <code>{episode.path}</code> are removed from disk. Datasets already exported keep their copy.
          </>
        }
      />
    </div>
  );
}

// --------------------------------------------------------------------------- export

function ExportModal({ ids, open, onClose, onDone }: { ids: string[]; open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const { session, tasks, departments } = useAppData();
  const defaultName = useMemo(() => {
    const d = departments.find((x) => x.id === session.department_id)?.name ?? "station";
    const t = tasks.find((x) => x.id === session.task_id)?.slug ?? "episodes";
    return `${d.toLowerCase().replace(/\s+/g, "-")}_${t}_${new Date().toISOString().slice(0, 10)}`;
  }, [departments, tasks, session]);
  const [name, setName] = useState(defaultName);
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    if (open) {
      setName(defaultName);
      setJob(null);
    }
  }, [open, defaultName]);
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const iv = setInterval(async () => {
      try {
        const j = await api.get<Job>(`/api/jobs/${job.id}`);
        setJob(j);
        if (j.status === "done") {
          toast.push("success", "Export finished", j.message);
          onDone();
        }
        if (j.status === "error") toast.push("error", "Export failed", j.message);
      } catch (e) {
        toast.error(e, "Lost track of the export job");
      }
    }, 600);
    return () => clearInterval(iv);
  }, [job, toast, onDone]);

  const start = async () => {
    try {
      setJob(await api.post<Job>("/api/exports", { episode_ids: ids, name, fps: 30 }));
    } catch (e) {
      toast.error(e, "Couldn't start the export");
    }
  };
  const result = job?.result as { path?: string; repo_id?: string } | null | undefined;

  return (
    <Modal
      open={open}
      title={`Export ${ids.length} episode${ids.length === 1 ? "" : "s"} to LeRobot`}
      onClose={onClose}
      width={560}
      footer={
        job ? (
          <Button variant={job.status === "done" ? "primary" : "secondary"} onClick={onClose}>
            {job.status === "done" || job.status === "error" ? "Close" : "Run in background"}
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" icon={<IconExport size={16} />} onClick={() => void start()} disabled={!name.trim()}>
              Start export
            </Button>
          </>
        )
      }
    >
      {!job && (
        <>
          <p className="confirm-body" style={{ marginBottom: 14 }}>
            Builds a LeRobot v3 dataset (parquet and AV1 video at 30 fps) from the raw recordings. The raw episodes stay untouched, so you can re-export any time.
          </p>
          <Field label="Dataset name" hint="Becomes the folder name under datasets/ and the local repo id.">
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} data-autofocus />
          </Field>
        </>
      )}
      {job && (
        <div className="job">
          <div className="job-line">
            <span className="job-status">{job.status === "done" ? "Done" : job.status === "error" ? "Failed" : job.status === "queued" ? "Queued" : "Exporting"}</span>
            <span className="tnum">{Math.round(job.progress * 100)}%</span>
          </div>
          <Meter value={job.progress} tone={job.status === "error" ? "err" : "primary"} />
          <div className="job-msg">{job.message}</div>
          {job.status === "done" && result?.path && (
            <div className="job-result">
              Saved to <code>{result.path}</code>
              {result.repo_id && (
                <>
                  {" "}
                  as <code>{result.repo_id}</code>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

function RunningJobs({ version }: { version: number }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  useEffect(() => {
    let off = false;
    const poll = async () => {
      try {
        const j = await api.get<Job[]>("/api/jobs");
        if (!off) setJobs(j.filter((x) => x.status === "running" || x.status === "queued"));
      } catch {
        /* jobs endpoint optional */
      }
    };
    void poll();
    const iv = setInterval(poll, 2000);
    return () => {
      off = true;
      clearInterval(iv);
    };
  }, [version]);
  if (!jobs.length) return null;
  return (
    <div className="running-jobs">
      {jobs.map((j) => (
        <div key={j.id} className="running-job">
          <span className="running-job-label">LeRobot export</span>
          <Meter value={j.progress} />
          <span className="tnum running-job-pct">{Math.round(j.progress * 100)}%</span>
          <span className="muted running-job-msg">{j.message}</span>
        </div>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------- page

export function EpisodesPage() {
  const toast = useToast();
  const { departments, users, tasks } = useAppData();
  const { episodesVersion } = useController();
  const [filters, setFilters] = useState({ department_id: "", user_id: "", task_id: "", success: "all" as Outcome, q: "" });
  const [qInput, setQInput] = useState("");
  const [page, setPage] = useState(0);
  const [data, setData] = useState<Paged<Episode> | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Episode | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportIds, setExportIds] = useState<string[]>([]);

  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => ({ ...f, q: qInput })), 250);
    return () => clearTimeout(t);
  }, [qInput]);

  const load = useCallback(async () => {
    try {
      setData(
        await api.get<Paged<Episode>>(
          `/api/episodes${qs({
            department_id: filters.department_id,
            user_id: filters.user_id,
            task_id: filters.task_id,
            success: filters.success === "all" ? null : filters.success,
            q: filters.q,
            limit: PAGE,
            offset: page * PAGE,
          })}`,
        ),
      );
    } catch (e) {
      toast.error(e, "Couldn't load episodes");
      setData({ items: [], total: 0 });
    }
  }, [filters, page, toast]);

  useEffect(() => {
    void load();
  }, [load, episodesVersion]);
  useEffect(() => setPage(0), [filters]);

  const items = data?.items ?? [];
  const allOnPage = items.length > 0 && items.every((e) => selected.has(e.id));
  const toggle = (id: string) => {
    const s = new Set(selected);
    if (s.has(id)) s.delete(id);
    else s.add(id);
    setSelected(s);
  };
  const filtered = filters.department_id || filters.user_id || filters.task_id || filters.success !== "all" || filters.q;
  const totalDur = items.reduce((a, e) => a + e.duration_s, 0);

  return (
    <div className="page">
      <PageHeader
        title="Episodes"
        lead={data ? `${data.total.toLocaleString()} episode${data.total === 1 ? "" : "s"}${filtered ? " match these filters" : " recorded on this station"}.` : "Loading…"}
      >
        <Button variant="primary" icon={<IconExport size={18} />} disabled={!selected.size} onClick={() => {
            setExportIds([...selected]);
            setExporting(true);
          }}>
          Export {selected.size ? `${selected.size} ` : ""}to LeRobot
        </Button>
      </PageHeader>

      <div className="filters">
        <label className="search">
          <IconSearch size={16} />
          <input type="search" placeholder="Search task, operator, notes" value={qInput} onChange={(e) => setQInput(e.target.value)} />
        </label>
        <select value={filters.department_id} onChange={(e) => setFilters({ ...filters, department_id: e.target.value })} aria-label="Department">
          <option value="">All departments</option>
          {departments.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        <select value={filters.user_id} onChange={(e) => setFilters({ ...filters, user_id: e.target.value })} aria-label="Operator">
          <option value="">All operators</option>
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
              {u.active ? "" : " (inactive)"}
            </option>
          ))}
        </select>
        <select value={filters.task_id} onChange={(e) => setFilters({ ...filters, task_id: e.target.value })} aria-label="Task">
          <option value="">All tasks</option>
          {tasks
            .filter((t) => !filters.department_id || t.department_id === +filters.department_id)
            .map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
        </select>
        <Segmented
          value={filters.success}
          options={[
            { value: "all", label: "Any outcome" },
            { value: "true", label: "Success" },
            { value: "false", label: "Failure" },
            { value: "null", label: "Unmarked" },
          ]}
          onChange={(v) => setFilters({ ...filters, success: v })}
        />
        {filtered && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setQInput("");
              setFilters({ department_id: "", user_id: "", task_id: "", success: "all", q: "" });
            }}
          >
            Clear filters
          </Button>
        )}
      </div>

      <RunningJobs version={exportIds.length + (exporting ? 1 : 0)} />
      <section className="panel table-panel">
        {data && items.length === 0 ? (
          <Empty title={filtered ? "No episodes match these filters" : "No episodes yet"}>
            {filtered ? "Try clearing a filter or searching for something else." : "Go to Operate, engage teleop and press record. Saved episodes appear here."}
          </Empty>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th className="col-check">
                  <input
                    type="checkbox"
                    aria-label="Select all on this page"
                    checked={allOnPage}
                    onChange={() => {
                      const s = new Set(selected);
                      items.forEach((e) => (allOnPage ? s.delete(e.id) : s.add(e.id)));
                      setSelected(s);
                    }}
                  />
                </th>
                <th>Task</th>
                <th>Operator</th>
                <th>Department</th>
                <th>Started</th>
                <th className="num">Length</th>
                <th className="num">Size</th>
                <th>Outcome</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id} className={`${selected.has(e.id) ? "selected" : ""} ${open?.id === e.id ? "opened" : ""}`} onClick={() => setOpen(e)}>
                  <td className="col-check" onClick={(ev) => ev.stopPropagation()}>
                    <input type="checkbox" aria-label={`Select ${e.task_name} ${dateTime(e.started_at)}`} checked={selected.has(e.id)} onChange={() => toggle(e.id)} />
                  </td>
                  <td className="strong">{e.task_name}</td>
                  <td>{e.user_name}</td>
                  <td>
                    <span className="dept-dot" style={{ background: departments.find((d) => d.id === e.department_id)?.color ?? "var(--idle)" }} />
                    {e.department_name}
                  </td>
                  <td className="nowrap">{dateTime(e.started_at)}</td>
                  <td className="num tnum">{duration(e.duration_s)}</td>
                  <td className="num tnum">{e.size_mb.toFixed(0)} MB</td>
                  <td>
                    <OutcomeBadge success={e.success} />
                  </td>
                  <td className="notes-cell">
                    {e.tags.map((t) => (
                      <span key={t} className="tag">
                        {t}
                      </span>
                    ))}
                    {e.notes}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && data.total > 0 && (
          <footer className="table-foot">
            <span className="muted tnum">
              Showing {page * PAGE + 1}–{Math.min(data.total, (page + 1) * PAGE)} of {data.total}, {duration(totalDur)} on this page
              {selected.size > 0 && `, ${selected.size} selected`}
            </span>
            <span className="spacer" />
            {selected.size > 0 && (
              <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
                Clear selection
              </Button>
            )}
            <Button size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            <Button size="sm" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(page + 1)}>
              Next
            </Button>
          </footer>
        )}
      </section>

      <Drawer
        open={!!open}
        onClose={() => setOpen(null)}
        title={open?.task_name ?? ""}
        subtitle={open ? `${open.user_name}, ${open.department_name}, ${dateTime(open.started_at)}` : ""}
        width={980}
      >
        {open && (
          <EpisodeDetail
            episode={open}
            onChanged={(e) => {
              setOpen(e);
              setData((d) => (d ? { ...d, items: d.items.map((x) => (x.id === e.id ? e : x)) } : d));
            }}
            onDeleted={() => {
              setOpen(null);
              const s = new Set(selected);
              s.delete(open.id);
              setSelected(s);
              void load();
            }}
          />
        )}
      </Drawer>
      <ExportModal
        ids={exportIds}
        open={exporting}
        onClose={() => setExporting(false)}
        onDone={() => setSelected(new Set())}
      />
    </div>
  );
}
