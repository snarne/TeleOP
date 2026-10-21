"""CameraWorker: one process per camera.

Captures at the camera's native rate, timestamps every frame with CLOCK_MONOTONIC right
after the grab returns (minus the configured latency), publishes downscaled JPEG previews
to shared memory for the UI, and, while recording, encodes H.264 into
`<episode>/cameras/<name>.mp4` with a sidecar `<name>.frames.csv` (index, t_ns).
"""

from __future__ import annotations

import csv
import logging
import math
import queue
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from station.config import CameraConfig, RecordingConfig
from station.ipc import JpegSlot, SharedBlock

log = logging.getLogger("station.camera")


# ----------------------------------------------------------------------------- sources


class Source:
    width = 640
    height = 480

    def open(self) -> None: ...
    def read(self) -> Optional[np.ndarray]: raise NotImplementedError
    def close(self) -> None: ...


class OpenCVSource(Source):
    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self.cap = None

    def open(self) -> None:
        import cv2

        dev: Any = self.cfg.device
        if isinstance(dev, str) and dev.isdigit():
            dev = int(dev)
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2) if hasattr(cv2, "CAP_V4L2") else cv2.VideoCapture(dev)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open camera {self.cfg.device}")
        if self.cfg.fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.cfg.fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
        cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.cap = cap

    def read(self) -> Optional[np.ndarray]:
        ok, frame = self.cap.read()
        return frame if ok else None

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()


class RealSenseSource(Source):
    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self.pipe = None

    def open(self) -> None:
        import pyrealsense2 as rs  # optional dependency

        self.pipe = rs.pipeline()
        c = rs.config()
        if self.cfg.serial:
            c.enable_device(self.cfg.serial)
        c.enable_stream(rs.stream.color, self.cfg.width, self.cfg.height, rs.format.bgr8, self.cfg.fps)
        self.pipe.start(c)
        self.width, self.height = self.cfg.width, self.cfg.height

    def read(self) -> Optional[np.ndarray]:
        frames = self.pipe.wait_for_frames(1000)
        color = frames.get_color_frame()
        return np.asanyarray(color.get_data()) if color else None

    def close(self) -> None:
        if self.pipe is not None:
            self.pipe.stop()


class SimSource(Source):
    """Synthetic views rendered from the live (simulated) arm state."""

    def __init__(self, name: str, cfg: CameraConfig, arm_blocks: Dict[str, SharedBlock]):
        self.name = name
        self.cfg = cfg
        self.arms = arm_blocks
        self.width, self.height = cfg.width, cfg.height
        self.period = 1.0 / cfg.fps
        self._next = time.monotonic()
        self.n = 0

    def read(self) -> Optional[np.ndarray]:
        self._next += self.period
        d = self._next - time.monotonic()
        if d > 0:
            time.sleep(d)
        else:
            self._next = time.monotonic()
        self.n += 1
        import cv2

        img = np.zeros((self.height, self.width, 3), np.uint8)
        if self.cfg.attached_to:
            self._wrist(img, cv2, self.cfg.attached_to)
        else:
            self._overhead(img, cv2)
        cv2.putText(img, f"{self.cfg.label or self.name}  #{self.n}", (10, self.height - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA)
        return img

    def _state(self, side: str) -> Optional[Dict[str, Any]]:
        b = self.arms.get(side)
        return b.read() if b is not None else None

    def _overhead(self, img, cv2) -> None:
        h, w = img.shape[:2]
        img[:] = (70, 64, 58)
        cv2.rectangle(img, (int(w * 0.08), int(h * 0.12)), (int(w * 0.92), int(h * 0.95)), (108, 100, 92), -1)
        for x in range(int(w * 0.08), int(w * 0.92), 40):
            cv2.line(img, (x, int(h * 0.12)), (x, int(h * 0.95)), (116, 108, 100), 1)
        cx, cy = w // 2, int(h * 0.62)
        cv2.rectangle(img, (cx - 18, cy - 18), (cx + 18, cy + 18), (40, 150, 230), -1)  # object
        scale = w * 0.55
        for side, bx in (("left", 0.25), ("right", 0.75)):
            st = self._state(side)
            base = (int(w * bx), int(h * 0.14))
            cv2.circle(img, base, 16, (30, 30, 30), -1)
            if not st or not np.all(np.isfinite(st["follower_q"])):
                continue
            q = st["follower_q"]
            yaw = (q[0] if side == "left" else q[0])
            r1 = 0.264 * math.sin(q[1])
            r2 = r1 + 0.25 * math.sin(q[1] - q[2] + math.pi / 2) * 0.9
            def pt(r):
                return (int(base[0] - r * scale * math.sin(yaw) * (1 if side == "left" else 1)),
                        int(base[1] + r * scale * math.cos(yaw)))
            elbow, wrist = pt(abs(r1)), pt(abs(r2) + 0.05)
            cv2.line(img, base, elbow, (220, 220, 220), 9, cv2.LINE_AA)
            cv2.line(img, elbow, wrist, (200, 200, 200), 7, cv2.LINE_AA)
            g = float(st["follower_gripper"]) if math.isfinite(st["follower_gripper"]) else 1.0
            gap = int(4 + 18 * g)
            col = (60, 200, 90) if st["contact"] > 0.5 else (230, 230, 230)
            cv2.circle(img, wrist, 6, (40, 40, 40), -1)
            cv2.line(img, (wrist[0] - gap, wrist[1] + 4), (wrist[0] - gap, wrist[1] + 22), col, 4)
            cv2.line(img, (wrist[0] + gap, wrist[1] + 4), (wrist[0] + gap, wrist[1] + 22), col, 4)

    def _wrist(self, img, cv2, side: str) -> None:
        h, w = img.shape[:2]
        st = self._state(side) or {}
        q = st.get("follower_q", np.zeros(6))
        q = np.nan_to_num(q)
        shift = int((q[0] * 300 + q[5] * 120) % 60)
        img[:] = (86, 78, 70)
        for y in range(-60, h + 60, 60):
            for x in range(-60, w + 60, 60):
                if ((x + y) // 60) % 2 == 0:
                    cv2.rectangle(img, (x + shift, y + int(q[1] * 80) % 60), (x + shift + 60, y + int(q[1] * 80) % 60 + 60),
                                  (98, 90, 82), -1)
        g = float(np.nan_to_num(st.get("follower_gripper", 1.0), nan=1.0))
        f = float(np.nan_to_num(st.get("grip_force", 0.0)))
        gap = int(40 + 160 * g)
        if st.get("contact", 0) > 0.5:
            cv2.rectangle(img, (w // 2 - gap + 18, h // 2 - 10), (w // 2 + gap - 18, h - 70), (40, 150, 230), -1)
        for sgn in (-1, 1):
            x = w // 2 + sgn * gap
            cv2.rectangle(img, (x - 14, h // 2), (x + 14, h), (35, 35, 38), -1)
        bar = int(min(f / 30.0, 1.0) * (w - 40))
        cv2.rectangle(img, (20, 20), (20 + bar, 32), (60, 200, 90), -1)
        cv2.putText(img, f"grip {f:5.1f} N", (20, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1, cv2.LINE_AA)


# ----------------------------------------------------------------------------- encoder


class Mp4Writer:
    def __init__(self, path: Path, width: int, height: int, fps: int, rec: RecordingConfig):
        import av

        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.container = av.open(str(path), mode="w", options={"movflags": "+faststart"})
        codec = rec.video_codec
        try:
            self.stream = self.container.add_stream(codec, rate=fps)
        except Exception:
            log.warning("codec %s unavailable, falling back to mpeg4", codec)
            self.stream = self.container.add_stream("mpeg4", rate=fps)
        self.stream.width, self.stream.height = width, height
        self.stream.pix_fmt = "yuv420p"
        if "264" in self.stream.codec_context.name:
            self.stream.options = {"crf": str(rec.video_crf), "preset": rec.video_preset, "tune": "zerolatency"}
        self.n = 0
        self._av = av
        self.csv_f = open(path.with_suffix(".frames.csv"), "w", newline="")
        self.csv = csv.writer(self.csv_f)
        self.csv.writerow(["frame_index", "t_ns"])

    def write(self, bgr: np.ndarray, t_ns: int) -> None:
        frame = self._av.VideoFrame.from_ndarray(bgr, format="bgr24")
        frame.pts = self.n
        for pkt in self.stream.encode(frame):
            self.container.mux(pkt)
        self.csv.writerow([self.n, t_ns])
        self.n += 1

    def close(self) -> int:
        for pkt in self.stream.encode():
            self.container.mux(pkt)
        self.container.close()
        self.csv_f.close()
        return self.n


# ----------------------------------------------------------------------------- worker


def run_camera_worker(name: str, cfg: CameraConfig, rec: RecordingConfig, state: SharedBlock, jpeg: JpegSlot,
                      cmd_q, evt_q, arm_blocks: Dict[str, SharedBlock], log_to_queue: bool = True) -> None:
    import cv2

    if log_to_queue:
        root = logging.getLogger()
        root.handlers[:] = [_CamLogHandler(evt_q, name)]
        root.setLevel(logging.INFO)

    def emit(**e):
        e.setdefault("camera", name)
        try:
            evt_q.put_nowait(e)
        except queue.Full:
            pass

    if cfg.backend == "sim":
        src: Source = SimSource(name, cfg, arm_blocks)
    elif cfg.backend == "realsense":
        src = RealSenseSource(cfg)
    else:
        src = OpenCVSource(cfg)

    running = True
    writer: Optional[Mp4Writer] = None
    opened = False
    retry_at = 0.0
    fps_ema, last_t, dropped = 0.0, None, 0
    win_t0, win_n = time.monotonic(), 0
    preview_every = 1.0 / max(rec.preview_fps, 1)
    last_preview = 0.0
    latency_ns = int(cfg.latency_ms * 1e6)

    import multiprocessing as mp

    parent = mp.parent_process() if log_to_queue else None
    n_loop = 0
    while running:
        n_loop += 1
        if parent is not None and n_loop % 30 == 0 and not parent.is_alive():
            log.error("camera %s: station server is gone, exiting", name)
            break
        # commands (a failing command must never kill the camera)
        while True:
            try:
                msg = cmd_q.get_nowait()
            except queue.Empty:
                break
            c = msg.get("cmd")
            try:
                if c == "stop":
                    running = False
                elif c == "record" and opened:
                    if writer is not None:
                        writer.close()
                    writer = Mp4Writer(Path(msg["path"]), src.width, src.height, cfg.fps, rec)
                    emit(type="reply", req=msg.get("req"), ok=True, data={})
                elif c == "record":
                    emit(type="reply", req=msg.get("req"), ok=False, error=f"camera {name} is not streaming")
                elif c == "stop_record":
                    w, writer = writer, None
                    n = w.close() if w else 0
                    emit(type="reply", req=msg.get("req"), ok=True, data={"frames": n})
                elif c == "capture_frame":
                    frame = src.read() if opened else None
                    if frame is None:
                        raise RuntimeError("no frame")
                    Path(msg["path"]).parent.mkdir(parents=True, exist_ok=True)
                    if not cv2.imwrite(msg["path"], frame):
                        raise RuntimeError(f"could not write {msg['path']}")
                    emit(type="reply", req=msg.get("req"), ok=True, data={"path": msg["path"]})
            except Exception as e:
                log.error("camera %s: command %s failed: %s", name, c, e)
                emit(type="reply", req=msg.get("req"), ok=False, error=f"{c}: {e}")
        if not running:
            break

        if not opened:
            if time.monotonic() < retry_at:
                time.sleep(0.05)
                continue
            try:
                src.open()
                opened = True
                log.info("camera %s streaming %dx%d", name, src.width, src.height)
            except Exception as e:
                log.error("camera %s: %s (retrying in 3 s)", name, e)
                state.write({"ok": 0.0, "t": time.monotonic()})
                retry_at = time.monotonic() + 3.0
                continue

        frame = src.read()
        t_ns = time.monotonic_ns() - latency_ns
        if frame is None:
            dropped += 1
            if dropped % 30 == 1:
                log.warning("camera %s: frame grab failed (%d)", name, dropped)
            if dropped > 90 and cfg.backend != "sim":
                src.close()
                opened = False
                retry_at = time.monotonic() + 1.0
            state.write({"ok": 0.0, "dropped": dropped, "t": time.monotonic()})
            continue
        t = t_ns / 1e9
        if last_t is not None:
            dt = t - last_t
            if dt > 1.8 / cfg.fps:  # a gap of ≥ 2 frame periods means frames were lost
                dropped += int(round(dt * cfg.fps)) - 1
        last_t = t
        win_n += 1
        if t - win_t0 >= 1.0:  # rate over a 1 s window
            fps_ema = win_n / (t - win_t0)
            win_t0, win_n = t, 0

        if writer is not None:
            try:
                writer.write(frame, t_ns)
            except Exception as e:
                log.error("camera %s encode failed: %s", name, e)

        now = time.monotonic()
        if now - last_preview >= preview_every:
            last_preview = now
            pv = frame
            if frame.shape[1] > rec.preview_width:
                s = rec.preview_width / frame.shape[1]
                pv = cv2.resize(frame, (rec.preview_width, int(frame.shape[0] * s)))
            ok, jpg = cv2.imencode(".jpg", pv, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
            if ok:
                jpeg.put(jpg.tobytes(), t_ns)

        state.write({"t": now, "ok": 1.0, "fps": fps_ema, "dropped": dropped, "width": src.width,
                     "height": src.height, "recording": 1.0 if writer else 0.0,
                     "frames_recorded": writer.n if writer else 0.0})

    if writer is not None:
        writer.close()
    src.close()
    state.write({"ok": 0.0, "recording": 0.0})


class _CamLogHandler(logging.Handler):
    def __init__(self, q, name: str):
        super().__init__()
        self.q = q
        self.name_ = name

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put_nowait({"type": "log", "camera": self.name_, "level": record.levelname,
                               "source": f"camera.{self.name_}", "message": record.getMessage(),
                               "ts": record.created})
        except Exception:
            pass
