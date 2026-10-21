// Canvas-drawn camera frames for mock mode. They follow the simulated arm state so
// the previews move with the joints and gripper on screen.
import { live } from "../api/live";
import type { ArmSnapshot } from "../api/types";

function noise(ctx: CanvasRenderingContext2D, w: number, h: number, amt: number) {
  const n = 220;
  ctx.fillStyle = `rgba(255,255,255,${amt})`;
  for (let i = 0; i < n; i++) ctx.fillRect(Math.random() * w, Math.random() * h, 1, 1);
}

function drawTable(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, "#5f646a");
  g.addColorStop(1, "#4a4f55");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(255,255,255,0.05)";
  ctx.lineWidth = 1;
  for (let x = 0; x < w; x += 32) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  for (let y = 0; y < h; y += 32) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
}

function drawArmTop(ctx: CanvasRenderingContext2D, bx: number, by: number, a: ArmSnapshot | undefined, mirror: number, scale: number) {
  const q = a?.follower.q ?? [0, 0, 0, 0, 0, 0];
  const yaw = -Math.PI / 2 + q[0] * mirror;
  const reach1 = 120 * scale * Math.sin(Math.max(0.15, q[1]));
  const reach2 = 110 * scale * Math.sin(Math.max(0.1, q[1] + q[2] * 0.6));
  const x1 = bx + Math.cos(yaw) * reach1;
  const y1 = by + Math.sin(yaw) * reach1;
  const yaw2 = yaw + q[3] * 0.6 * mirror;
  const x2 = x1 + Math.cos(yaw2) * reach2;
  const y2 = y1 + Math.sin(yaw2) * reach2;
  // base
  ctx.fillStyle = "#2b2f34";
  ctx.beginPath();
  ctx.arc(bx, by, 26 * scale, 0, Math.PI * 2);
  ctx.fill();
  ctx.lineCap = "round";
  // links
  ctx.strokeStyle = "#d9dde1";
  ctx.lineWidth = 22 * scale;
  ctx.beginPath();
  ctx.moveTo(bx, by);
  ctx.lineTo(x1, y1);
  ctx.stroke();
  ctx.lineWidth = 17 * scale;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  ctx.strokeStyle = "#8f979f";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(bx, by);
  ctx.lineTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  // joint caps
  ctx.fillStyle = "#1f2327";
  for (const [x, y] of [[x1, y1], [x2, y2]]) {
    ctx.beginPath();
    ctx.arc(x, y, 9 * scale, 0, Math.PI * 2);
    ctx.fill();
  }
  // gripper
  const open = a?.follower.gripper ?? 1;
  const perp = yaw2 + Math.PI / 2;
  const jaw = (6 + open * 16) * scale;
  ctx.strokeStyle = "#f1f3f5";
  ctx.lineWidth = 6 * scale;
  for (const s of [-1, 1]) {
    const jx = x2 + Math.cos(perp) * jaw * s;
    const jy = y2 + Math.sin(perp) * jaw * s;
    ctx.beginPath();
    ctx.moveTo(jx, jy);
    ctx.lineTo(jx + Math.cos(yaw2) * 26 * scale, jy + Math.sin(yaw2) * 26 * scale);
    ctx.stroke();
  }
  return { x: x2 + Math.cos(yaw2) * 18 * scale, y: y2 + Math.sin(yaw2) * 18 * scale };
}

function stamp(ctx: CanvasRenderingContext2D, w: number, h: number, label: string, t: number) {
  ctx.font = "600 13px 'Barlow Semi Condensed', sans-serif";
  ctx.fillStyle = "rgba(0,0,0,0.45)";
  ctx.fillRect(8, h - 26, 172, 19);
  ctx.fillStyle = "#e8ecef";
  ctx.fillText(`${label}  t=${t.toFixed(2)} s`, 14, h - 12);
  void w;
}

export function drawMockFrame(ctx: CanvasRenderingContext2D, name: string, w: number, h: number) {
  const s = live.snapshot;
  const t = s?.t ?? performance.now() / 1000;
  const cam = s?.cameras[name];
  if (s && cam && !cam.ok) {
    ctx.fillStyle = "#1a1f24";
    ctx.fillRect(0, 0, w, h);
    return;
  }
  if (name === "overhead") {
    drawTable(ctx, w, h);
    // bin and tray
    ctx.fillStyle = "#2d5fa8";
    ctx.fillRect(w * 0.44, h * 0.14, w * 0.12, h * 0.16);
    ctx.fillStyle = "#24497f";
    ctx.fillRect(w * 0.455, h * 0.16, w * 0.09, h * 0.12);
    const sc = w / 640;
    drawArmTop(ctx, w * 0.25, h * 0.98, s?.arms.left, 1, sc);
    const tip = drawArmTop(ctx, w * 0.75, h * 0.98, s?.arms.right, -1, sc);
    // cube near right gripper when in contact, else on table
    const contact = s?.arms.right?.contact;
    ctx.fillStyle = "#d8812f";
    const cx = contact ? tip.x - 12 * sc : w * 0.62;
    const cy = contact ? tip.y - 12 * sc : h * 0.42;
    ctx.fillRect(cx, cy, 24 * sc, 24 * sc);
  } else {
    const side = name.startsWith("left") ? "left" : "right";
    const a = s?.arms[side];
    // blurred table view from the wrist
    const g = ctx.createRadialGradient(w / 2, h * 0.55, 20, w / 2, h * 0.55, w * 0.8);
    g.addColorStop(0, "#6b7177");
    g.addColorStop(1, "#3b4045");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
    const q = a?.follower.q ?? [0, 0, 0, 0, 0, 0];
    const ox = Math.sin(q[0] * 2 + t * 0.2) * w * 0.18;
    const oy = Math.cos(q[4] * 2) * h * 0.08;
    // object
    const pos = a?.trigger.pos ?? 0;
    const sz = w * (0.16 + pos * 0.12);
    ctx.fillStyle = side === "right" ? "#d8812f" : "#e3d34f";
    ctx.save();
    ctx.translate(w / 2 + ox, h * 0.5 + oy);
    ctx.rotate(q[5] * 0.6);
    ctx.fillRect(-sz / 2, -sz / 2, sz, sz);
    ctx.restore();
    // jaws
    const open = a?.follower.gripper ?? 1;
    const gap = w * (0.12 + open * 0.28);
    ctx.fillStyle = "#e9ecef";
    ctx.fillRect(w / 2 - gap / 2 - w * 0.09, h * 0.62, w * 0.09, h * 0.38);
    ctx.fillRect(w / 2 + gap / 2, h * 0.62, w * 0.09, h * 0.38);
    ctx.fillStyle = "#b9c0c6";
    ctx.fillRect(w / 2 - gap / 2 - w * 0.012, h * 0.62, w * 0.012, h * 0.38);
    ctx.fillRect(w / 2 + gap / 2, h * 0.62, w * 0.012, h * 0.38);
    if (a?.contact) {
      ctx.strokeStyle = "rgba(79,193,138,0.9)";
      ctx.lineWidth = 3;
      ctx.strokeRect(6, 6, w - 12, h - 12);
    }
  }
  noise(ctx, w, h, 0.05);
  stamp(ctx, w, h, name, t);
}

/** Draws a ChArUco-like board with detected corner markers (calibration overlay). */
export function drawMockCharuco(ctx: CanvasRenderingContext2D, w: number, h: number, t: number) {
  drawTable(ctx, w, h);
  ctx.save();
  ctx.translate(w / 2 + Math.sin(t * 0.7) * 30, h / 2 + Math.cos(t * 0.5) * 20);
  ctx.rotate(Math.sin(t * 0.4) * 0.25);
  const cols = 7;
  const rows = 5;
  const sq = Math.min(w, h) / 8;
  ctx.fillStyle = "#f4f4f4";
  ctx.fillRect((-cols / 2) * sq - 8, (-rows / 2) * sq - 8, cols * sq + 16, rows * sq + 16);
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++) {
      const x = (c - cols / 2) * sq;
      const y = (r - rows / 2) * sq;
      if ((r + c) % 2 === 0) {
        ctx.fillStyle = "#111";
        ctx.fillRect(x, y, sq, sq);
      } else {
        ctx.fillStyle = "#111";
        ctx.fillRect(x + sq * 0.25, y + sq * 0.25, sq * 0.5, sq * 0.5);
        ctx.fillStyle = "#f4f4f4";
        ctx.fillRect(x + sq * 0.35, y + sq * 0.35, sq * 0.12, sq * 0.12);
      }
    }
  ctx.strokeStyle = "#2fd27a";
  ctx.fillStyle = "#2fd27a";
  ctx.lineWidth = 2;
  for (let r = 1; r < rows; r++)
    for (let c = 1; c < cols; c++) {
      const x = (c - cols / 2) * sq;
      const y = (r - rows / 2) * sq;
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
    }
  ctx.restore();
  noise(ctx, w, h, 0.05);
}
