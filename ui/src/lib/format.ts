import type { Phase } from "../api/types";

export const RAD2DEG = 180 / Math.PI;

export function clock(s: number): string {
  if (!isFinite(s) || s < 0) s = 0;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function duration(s: number): string {
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s % 60)} s`;
}

export function dateTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "—";
  const d = new Date(isoStr);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return `Today ${time}`;
  const y = new Date(today);
  y.setDate(today.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `Yesterday ${time}`;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric", year: d.getFullYear() === today.getFullYear() ? undefined : "numeric" })}, ${time}`;
}

export function ago(isoStr: string | null | undefined): string {
  if (!isoStr) return "never";
  const s = (Date.now() - new Date(isoStr).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const d = Math.round(s / 86400);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export const PHASE_LABEL: Record<Phase, string> = {
  off: "Powered off",
  idle: "Idle",
  starting: "Starting",
  ready: "Ready",
  teleop: "Teleop",
  recording: "Recording",
  saving: "Saving",
  stopping: "Stopping",
  fault: "Fault",
};

export function num(v: number | undefined | null, digits = 1): string {
  if (v === undefined || v === null || !isFinite(v)) return "—";
  return v.toFixed(digits);
}

export function cameraLabel(name: string): string {
  return name
    .split("_")
    .map((w, i) => (i === 0 ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}
