// Rolling time-series buffers fed by the live state stream. They live at module level so
// plots keep their history when the user switches pages.

import type { StateSnapshot } from "./types";
import { live } from "./live";

export type Series = { t: Float64Array; cols: Record<string, Float64Array>; n: number };

export class Ring {
  readonly cap: number;
  t: Float64Array;
  cols: Record<string, Float64Array> = {};
  len = 0;
  private head = 0;
  constructor(cap: number, keys: string[]) {
    this.cap = cap;
    this.t = new Float64Array(cap);
    for (const k of keys) this.cols[k] = new Float64Array(cap);
  }
  push(t: number, vals: Record<string, number>) {
    this.t[this.head] = t;
    for (const k in this.cols) this.cols[k][this.head] = vals[k] ?? NaN;
    this.head = (this.head + 1) % this.cap;
    this.len = Math.min(this.len + 1, this.cap);
  }
  /** Ordered copy of the most recent `windowS` seconds. */
  window(windowS: number): { t: number[]; cols: Record<string, number[]> } {
    const out: { t: number[]; cols: Record<string, number[]> } = { t: [], cols: {} };
    for (const k in this.cols) out.cols[k] = [];
    if (!this.len) return out;
    const start = (this.head - this.len + this.cap) % this.cap;
    const tLast = this.t[(this.head - 1 + this.cap) % this.cap];
    for (let i = 0; i < this.len; i++) {
      const j = (start + i) % this.cap;
      if (tLast - this.t[j] > windowS) continue;
      out.t.push(this.t[j]);
      for (const k in this.cols) out.cols[k].push(this.cols[k][j]);
    }
    return out;
  }
}

const ARM_KEYS = ["force_n", "render_n", "grip_force_n", "pos", "tracking_deg", "loop_hz", "jitter_ms", "tmax"];

export const armHistory = {
  left: new Ring(20 * 120, ARM_KEYS),
  right: new Ring(20 * 120, ARM_KEYS),
};
export const systemHistory = new Ring(20 * 120, ["cpu", "mem"]);

let wired = false;
export function startHistory() {
  if (wired) return;
  wired = true;
  live.onSnapshot((s: StateSnapshot) => {
    for (const side of ["left", "right"] as const) {
      const a = s.arms[side];
      if (!a) continue;
      armHistory[side].push(s.t, {
        force_n: a.trigger.force_n,
        render_n: a.trigger.render_n,
        grip_force_n: a.grip_force_n,
        pos: a.trigger.pos,
        tracking_deg: (a.tracking_error_rad * 180) / Math.PI,
        loop_hz: a.loop_hz,
        jitter_ms: a.loop_jitter_ms,
        tmax: a.follower.temps_c.length ? Math.max(...a.follower.temps_c) : NaN,
      });
    }
    systemHistory.push(s.t, { cpu: s.system.cpu_pct, mem: s.system.mem_pct });
  });
}
