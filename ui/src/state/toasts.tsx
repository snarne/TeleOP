import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";

export type ToastKind = "info" | "success" | "warn" | "error";
export interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  body?: string;
}

interface ToastApi {
  push: (kind: ToastKind, title: string, body?: string) => void;
  error: (e: unknown, fallbackTitle?: string) => void;
}

const Ctx = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const id = useRef(1);

  const dismiss = useCallback((tid: number) => setToasts((t) => t.filter((x) => x.id !== tid)), []);
  const push = useCallback(
    (kind: ToastKind, title: string, body?: string) => {
      const tid = id.current++;
      setToasts((t) => [...t.slice(-4), { id: tid, kind, title, body }]);
      setTimeout(() => dismiss(tid), kind === "error" ? 8000 : 3500);
    },
    [dismiss],
  );
  const error = useCallback(
    (e: unknown, fallbackTitle = "Something went wrong") => {
      if (e instanceof ApiError) push("error", e.message, e.hint);
      else if (e instanceof Error) push("error", fallbackTitle, e.message);
      else push("error", fallbackTitle);
    },
    [push],
  );
  const apiObj = useMemo(() => ({ push, error }), [push, error]);

  return (
    <Ctx.Provider value={apiObj}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`} onClick={() => dismiss(t.id)}>
            <div className="toast-title">{t.title}</div>
            {t.body && <div className="toast-body">{t.body}</div>}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastApi {
  const c = useContext(Ctx);
  if (!c) throw new Error("useToast outside ToastProvider");
  return c;
}
