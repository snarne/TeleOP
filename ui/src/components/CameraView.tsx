import { useEffect, useRef, useState } from "react";
import { MOCK } from "../api/client";
import { useLive } from "../api/live";
import { drawMockCharuco, drawMockFrame } from "../mock/camera";
import { IconCamera } from "./icons";

/** Live preview of one camera: an MJPEG stream from the station, or a canvas in mock mode. */
export function CameraView({
  name,
  label,
  overlay,
  className = "",
}: {
  name: string;
  label: string;
  overlay?: "charuco";
  className?: string;
}) {
  const cam = useLive((s) => s.cameras[name], undefined);
  const recording = useLive((s) => s.recording.active, false);
  const [failed, setFailed] = useState(false);
  const [nonce, setNonce] = useState(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Retry the stream a few seconds after a failure.
  useEffect(() => {
    if (!failed) return;
    const t = setTimeout(() => {
      setFailed(false);
      setNonce((n) => n + 1);
    }, 3000);
    return () => clearTimeout(t);
  }, [failed]);

  // Overlay snapshots refresh at ~2 Hz instead of streaming.
  useEffect(() => {
    if (MOCK || !overlay) return;
    const iv = setInterval(() => setNonce((n) => n + 1), 500);
    return () => clearInterval(iv);
  }, [overlay]);

  useEffect(() => {
    if (!MOCK) return;
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    let last = 0;
    const loop = (ts: number) => {
      raf = requestAnimationFrame(loop);
      if (ts - last < (overlay ? 500 : 66)) return;
      last = ts;
      if (overlay) drawMockCharuco(ctx, c.width, c.height, ts / 1000);
      else drawMockFrame(ctx, name, c.width, c.height);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [name, overlay]);

  const ok = cam?.ok ?? !MOCK;
  const src = overlay
    ? `/api/cameras/${name}/snapshot.jpg?overlay=${overlay}&n=${nonce}`
    : `/api/cameras/${name}/stream.mjpg?n=${nonce}`;

  return (
    <figure className={`cam ${className} ${!ok || failed ? "cam-down" : ""}`}>
      <div className="cam-frame">
        {MOCK ? (
          <canvas ref={canvasRef} width={640} height={480} />
        ) : (
          !failed && <img src={src} alt={`${label} camera`} onError={() => setFailed(true)} />
        )}
        {(!ok || failed) && (
          <div className="cam-nosignal">
            <IconCamera size={28} />
            <span>No signal from {label.toLowerCase()} camera</span>
            <span className="cam-nosignal-hint">Retrying every 3 s. Check its USB cable in Hardware.</span>
          </div>
        )}
        {recording && ok && !overlay && <span className="cam-rec">REC</span>}
      </div>
      <figcaption className="cam-cap">
        <span className="cam-name">{label}</span>
        {cam && (
          <span className={`cam-fps tnum ${cam.fps < 28 ? "warn" : ""}`}>
            {cam.ok ? `${cam.fps.toFixed(1)} fps` : "offline"}
            {cam.dropped > 0 && <span className="cam-drop">{cam.dropped} dropped</span>}
          </span>
        )}
      </figcaption>
    </figure>
  );
}
