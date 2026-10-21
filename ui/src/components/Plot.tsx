import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { Ring } from "../api/history";

export interface SeriesSpec {
  key: string;
  label: string;
  color: string; // CSS variable name, e.g. "--s-op"
  width?: number;
  dash?: number[];
  fill?: boolean;
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

function axisStyle(): Partial<uPlot.Axis> {
  return {
    stroke: cssVar("--muted"),
    grid: { stroke: cssVar("--line-soft"), width: 1 },
    ticks: { stroke: cssVar("--line-soft"), width: 1, size: 4 },
    font: "12px Barlow, sans-serif",
  };
}

function useThemeVersion(cb: () => void) {
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const obs = new MutationObserver(cb);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    mq.addEventListener("change", cb);
    return () => {
      obs.disconnect();
      mq.removeEventListener("change", cb);
    };
  }, [cb]);
}

/** Rolling plot over a live Ring buffer. */
export function LivePlot({
  ring,
  series,
  windowS = 10,
  height = 140,
  yRange,
  yLabel,
  refreshMs = 100,
  nonNegative,
}: {
  ring: Ring;
  series: SeriesSpec[];
  windowS?: number;
  height?: number;
  yRange?: [number, number];
  yLabel?: string;
  refreshMs?: number;
  nonNegative?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  const specKey = series.map((s) => s.key + s.color).join("|");
  const build = useRef<() => void>(() => {});

  build.current = () => {
    const el = host.current;
    if (!el) return;
    plot.current?.destroy();
    const w = el.clientWidth || 300;
    const opts: uPlot.Options = {
      width: w,
      height,
      legend: { show: false },
      cursor: { show: false },
      scales: {
        x: { time: false },
        y: yRange ? { range: () => yRange } : { auto: true },
      },
      axes: [
        { ...axisStyle(), values: (_u, v) => v.map(() => ""), size: 8, ticks: { show: false } },
        { ...axisStyle(), size: 38, label: yLabel, labelSize: 14, labelFont: "12px Barlow, sans-serif" },
      ],
      series: [
        {},
        ...series.map((s) => ({
          label: s.label,
          stroke: cssVar(s.color),
          width: s.width ?? 1.75,
          dash: s.dash,
          fill: s.fill ? cssVar(s.color) + "22" : undefined,
          points: { show: false },
        })),
      ],
    };
    const empty: uPlot.AlignedData = [[], ...series.map(() => [] as number[])];
    plot.current = new uPlot(opts, empty, el);
  };

  useEffect(() => {
    build.current();
    const el = host.current;
    const ro = new ResizeObserver(() => {
      if (plot.current && el) plot.current.setSize({ width: el.clientWidth, height });
    });
    if (el) ro.observe(el);
    const iv = setInterval(() => {
      const p = plot.current;
      if (!p) return;
      const win = ring.window(windowS);
      if (!win.t.length) return;
      const t0 = win.t[win.t.length - 1];
      const xs = win.t.map((t) => t - t0);
      p.setData([xs, ...series.map((s) => win.cols[s.key])] as uPlot.AlignedData, false);
      p.setScale("x", { min: -windowS, max: 0 });
      if (!yRange) {
        let lo = Infinity;
        let hi = -Infinity;
        for (const s of series)
          for (const v of win.cols[s.key])
            if (isFinite(v)) {
              lo = Math.min(lo, v);
              hi = Math.max(hi, v);
            }
        if (isFinite(lo)) {
          const pad = Math.max((hi - lo) * 0.12, 0.5);
          p.setScale("y", { min: nonNegative ? 0 : Math.min(0, lo - pad), max: Math.max(hi + pad, nonNegative ? 5 : hi + pad) });
        }
      }
    }, refreshMs);
    return () => {
      clearInterval(iv);
      ro.disconnect();
      plot.current?.destroy();
      plot.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ring, specKey, windowS, height, refreshMs, yRange?.[0], yRange?.[1]]);

  useThemeVersion(useRefCallback(() => build.current()));

  return <div className="plot" ref={host} style={{ height }} />;
}

function useRefCallback(f: () => void) {
  const r = useRef(f);
  r.current = f;
  const stable = useRef(() => r.current());
  return stable.current;
}

/** Static plot with an optional playhead (episode telemetry). */
export function StaticPlot({
  t,
  series,
  data,
  height = 180,
  playhead,
  onSeek,
  yLabel,
}: {
  t: number[];
  series: SeriesSpec[];
  data: Record<string, number[]>;
  height?: number;
  playhead?: number;
  onSeek?: (t: number) => void;
  yLabel?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  const head = useRef(playhead ?? 0);
  head.current = playhead ?? 0;
  const seekRef = useRef(onSeek);
  seekRef.current = onSeek;

  const build = useRefCallback(() => {
    const el = host.current;
    if (!el) return;
    plot.current?.destroy();
    const opts: uPlot.Options = {
      width: el.clientWidth || 400,
      height,
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, points: { show: false } },
      scales: { x: { time: false } },
      axes: [
        { ...axisStyle(), size: 26, values: (_u, v) => v.map((x) => `${x}s`) },
        { ...axisStyle(), size: 40, label: yLabel, labelSize: 14, labelFont: "12px Barlow, sans-serif" },
      ],
      series: [{}, ...series.map((s) => ({ label: s.label, stroke: cssVar(s.color), width: s.width ?? 1.5, dash: s.dash, points: { show: false } }))],
      hooks: {
        draw: [
          (u) => {
            const x = u.valToPos(head.current, "x", true);
            const ctx = u.ctx;
            ctx.save();
            ctx.strokeStyle = cssVar("--ink");
            ctx.lineWidth = 1.5 * devicePixelRatio;
            ctx.beginPath();
            ctx.moveTo(x, u.bbox.top);
            ctx.lineTo(x, u.bbox.top + u.bbox.height);
            ctx.stroke();
            ctx.restore();
          },
        ],
      },
    };
    plot.current = new uPlot(opts, [t, ...series.map((s) => data[s.key] ?? [])] as uPlot.AlignedData, el);
    plot.current.over.addEventListener("click", (e) => {
      const p = plot.current;
      if (!p || !seekRef.current) return;
      const rect = p.over.getBoundingClientRect();
      seekRef.current(p.posToVal(e.clientX - rect.left, "x"));
    });
  });

  useEffect(() => {
    build();
    const el = host.current;
    const ro = new ResizeObserver(() => {
      if (plot.current && el) plot.current.setSize({ width: el.clientWidth, height });
    });
    if (el) ro.observe(el);
    return () => {
      ro.disconnect();
      plot.current?.destroy();
      plot.current = null;
    };
  }, [t, data, series, height, build]);

  useEffect(() => {
    plot.current?.redraw(false, false);
  }, [playhead]);

  useThemeVersion(build);

  return <div className={`plot ${onSeek ? "plot-seek" : ""}`} ref={host} style={{ height }} />;
}

export function Legend({ series }: { series: SeriesSpec[] }) {
  return (
    <div className="legend">
      {series.map((s) => (
        <span key={s.key + s.label} className="legend-item">
          <span className={`legend-swatch ${s.dash ? "dashed" : ""}`} style={{ background: `var(${s.color})`, borderColor: `var(${s.color})` }} />
          {s.label}
        </span>
      ))}
    </div>
  );
}
