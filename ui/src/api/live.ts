// Live streams: /ws/state (20 Hz snapshots) and /ws/logs. Each auto-reconnects with backoff.
// The state stream lives in a tiny external store so components can subscribe to slices
// through useSyncExternalStore without re-rendering the whole app at 20 Hz.

import { useSyncExternalStore, useRef } from "react";
import type { LogLine, StateSnapshot } from "./types";
import { MOCK, wsUrl } from "./client";
import { mockSubscribeLogs, mockSubscribeState } from "../mock/server";

export type ConnStatus = "connecting" | "open" | "closed";

type Listener = () => void;

class LiveStore {
  snapshot: StateSnapshot | null = null;
  conn: ConnStatus = "connecting";
  lastMessageAt = 0;
  private listeners = new Set<Listener>();
  private connListeners = new Set<Listener>();
  private snapshotListeners = new Set<(s: StateSnapshot) => void>();

  subscribe = (l: Listener) => {
    this.listeners.add(l);
    return () => void this.listeners.delete(l);
  };
  subscribeConn = (l: Listener) => {
    this.connListeners.add(l);
    return () => void this.connListeners.delete(l);
  };
  /** Raw per-message hook, used by history buffers. */
  onSnapshot = (f: (s: StateSnapshot) => void) => {
    this.snapshotListeners.add(f);
    return () => void this.snapshotListeners.delete(f);
  };
  push(s: StateSnapshot) {
    this.snapshot = s;
    this.lastMessageAt = performance.now();
    this.snapshotListeners.forEach((f) => f(s));
    this.listeners.forEach((l) => l());
  }
  setConn(c: ConnStatus) {
    if (c === this.conn) return;
    this.conn = c;
    this.connListeners.forEach((l) => l());
  }
}

export const live = new LiveStore();

let started = false;
export function startLive() {
  if (started) return;
  started = true;
  if (MOCK) {
    live.setConn("open");
    mockSubscribeState((s) => live.push(s));
    return;
  }
  let delay = 500;
  const connect = () => {
    live.setConn("connecting");
    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl("/ws/state"));
    } catch {
      setTimeout(connect, delay);
      return;
    }
    ws.onopen = () => {
      delay = 500;
      live.setConn("open");
    };
    ws.onmessage = (ev) => {
      try {
        live.push(JSON.parse(ev.data as string) as StateSnapshot);
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onclose = () => {
      live.setConn("closed");
      setTimeout(connect, delay);
      delay = Math.min(delay * 2, 5000);
    };
    ws.onerror = () => ws.close();
  };
  connect();
  // Treat a silent socket as disconnected (backend hung, laptop asleep).
  setInterval(() => {
    if (live.conn === "open" && performance.now() - live.lastMessageAt > 3000) live.setConn("closed");
  }, 1000);
}

/** Subscribe to a slice of the live snapshot. `select` may return a fresh object; the
 * component then re-renders on every snapshot (20 Hz), which is fine for small widgets. */
export function useLive<T>(select: (s: StateSnapshot) => T, fallback: T): T {
  const selRef = useRef(select);
  selRef.current = select;
  const cache = useRef<{ snap: StateSnapshot | null; val: T }>({ snap: null, val: fallback });
  return useSyncExternalStore(live.subscribe, () => {
    const s = live.snapshot;
    if (!s) return cache.current.val;
    if (cache.current.snap === s) return cache.current.val;
    const v = selRef.current(s);
    // keep primitives stable to avoid needless renders
    if (Object.is(v, cache.current.val)) {
      cache.current.snap = s;
      return cache.current.val;
    }
    cache.current = { snap: s, val: v };
    return v;
  });
}

export function useConnStatus(): ConnStatus {
  return useSyncExternalStore(live.subscribeConn, () => live.conn);
}

// --------------------------------------------------------------------------- logs

export function subscribeLogs(onLine: (l: LogLine) => void): () => void {
  if (MOCK) return mockSubscribeLogs(onLine);
  let closed = false;
  let ws: WebSocket | null = null;
  let delay = 500;
  const connect = () => {
    if (closed) return;
    ws = new WebSocket(wsUrl("/ws/logs"));
    ws.onopen = () => (delay = 500);
    ws.onmessage = (ev) => {
      try {
        onLine(JSON.parse(ev.data as string) as LogLine);
      } catch {
        /* ignore */
      }
    };
    ws.onclose = () => {
      if (closed) return;
      setTimeout(connect, delay);
      delay = Math.min(delay * 2, 5000);
    };
    ws.onerror = () => ws?.close();
  };
  connect();
  return () => {
    closed = true;
    ws?.close();
  };
}
