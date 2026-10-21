// Station actions shared by buttons and keyboard shortcuts, plus the save and abort dialogs.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { live } from "../api/live";
import type { Episode, KeyAction } from "../api/types";
import { useAppData } from "./appdata";
import { useToast } from "./toasts";

export const ACTION_LABELS: Record<KeyAction, string> = {
  start_recording: "Start recording",
  save: "Save recording",
  abort: "Abort recording",
  teleop_toggle: "Engage / release teleop",
  estop: "Emergency stop",
  mark_success: "Mark success",
  mark_failure: "Mark failure",
};

interface Controller {
  busy: string | null;
  powerAll: (on: boolean) => Promise<void>;
  startArms: () => Promise<void>;
  stopArms: () => Promise<void>;
  setTeleop: (on: boolean) => Promise<void>;
  startRecording: () => Promise<void>;
  countdown: number;
  cancelCountdown: () => void;
  requestSave: () => void;
  requestAbort: () => void;
  estop: () => Promise<void>;
  clearFault: () => Promise<void>;
  saveDialog: { open: boolean; success: boolean; notes: string };
  setSaveDialog: (d: { open: boolean; success: boolean; notes: string }) => void;
  confirmSave: () => Promise<void>;
  abortConfirmOpen: boolean;
  setAbortConfirmOpen: (v: boolean) => void;
  confirmAbort: () => Promise<void>;
  lastSaved: Episode | null;
  episodesVersion: number;
  bumpEpisodes: () => void;
  run: (label: string, fn: () => Promise<unknown>, okMsg?: string) => Promise<boolean>;
}

const Ctx = createContext<Controller | null>(null);

export function keyLabel(code: string | undefined): string {
  if (!code) return "";
  if (code.startsWith("Key")) return code.slice(3);
  if (code.startsWith("Digit")) return code.slice(5);
  const map: Record<string, string> = {
    Escape: "Esc",
    Space: "Space",
    Enter: "Enter",
    Backspace: "⌫",
    ArrowUp: "↑",
    ArrowDown: "↓",
    ArrowLeft: "←",
    ArrowRight: "→",
    Backquote: "`",
    Minus: "-",
    Equal: "=",
    BracketLeft: "[",
    BracketRight: "]",
    Semicolon: ";",
    Quote: "'",
    Comma: ",",
    Period: ".",
    Slash: "/",
    Backslash: "\\",
  };
  return map[code] ?? code.replace(/^Numpad/, "Num ");
}

export function ControllerProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const { settings } = useAppData();
  const [busy, setBusy] = useState<string | null>(null);
  const [saveDialog, setSaveDialog] = useState({ open: false, success: true, notes: "" });
  const [abortConfirmOpen, setAbortConfirmOpen] = useState(false);
  const [lastSaved, setLastSaved] = useState<Episode | null>(null);
  const [episodesVersion, setEpisodesVersion] = useState(0);
  const [countdown, setCountdown] = useState(0);
  const countdownTimer = useRef<number | undefined>(undefined);
  const lastAbortPress = useRef(0);
  const abortOpenRef = useRef(false);
  abortOpenRef.current = abortConfirmOpen;

  const run = useCallback(
    async (label: string, fn: () => Promise<unknown>, okMsg?: string) => {
      setBusy(label);
      try {
        await fn();
        if (okMsg) toast.push("success", okMsg);
        return true;
      } catch (e) {
        toast.error(e, `${label} failed`);
        return false;
      } finally {
        setBusy(null);
      }
    },
    [toast],
  );

  const powerAll = useCallback(
    async (on: boolean) => {
      await run(on ? "Power on" : "Power off", () => api.post("/api/control/power", { channel: "all", on }), on ? "Powered on" : "Powered off");
    },
    [run],
  );
  const startArms = useCallback(async () => {
    await run("Start arms", () => api.post("/api/control/start_arms", {}), "Starting arms");
  }, [run]);
  const stopArms = useCallback(async () => {
    await run("Stop arms", () => api.post("/api/control/stop_arms"), "Stopping arms. Followers are moving to rest");
  }, [run]);
  const setTeleop = useCallback(
    async (on: boolean) => {
      await run(on ? "Engage teleop" : "Release teleop", () => api.post("/api/control/teleop", { enabled: on }), on ? "Teleop engaged" : "Teleop released");
    },
    [run],
  );
  const cancelCountdown = useCallback(() => {
    window.clearInterval(countdownTimer.current);
    countdownTimer.current = undefined;
    setCountdown(0);
  }, []);
  const startRecording = useCallback(async () => {
    if (countdownTimer.current !== undefined) return;
    const go = () => run("Start recording", () => api.post("/api/recording/start"), "Recording started");
    const n = settings?.recording.countdown_s ?? 0;
    if (n <= 0 || live.snapshot?.phase !== "teleop") {
      await go();
      return;
    }
    let left = n;
    setCountdown(left);
    countdownTimer.current = window.setInterval(() => {
      left -= 1;
      if (left <= 0) {
        cancelCountdown();
        void go();
      } else setCountdown(left);
    }, 1000);
  }, [run, settings, cancelCountdown]);
  const requestSave = useCallback(() => {
    if (!live.snapshot?.recording.active) {
      toast.push("warn", "Nothing is being recorded", "Start a recording first.");
      return;
    }
    setSaveDialog((d) => (d.open ? d : { open: true, success: true, notes: "" }));
  }, [toast]);
  const confirmSave = useCallback(async () => {
    const d = saveDialog;
    setSaveDialog({ ...d, open: false });
    setBusy("Save");
    try {
      const ep = await api.post<Episode>("/api/recording/save", { success: d.success, notes: d.notes });
      setLastSaved(ep);
      setEpisodesVersion((v) => v + 1);
      toast.push("success", `Saved ${ep.duration_s.toFixed(1)} s episode`, `${ep.department_name} / ${ep.user_name}, marked ${d.success ? "success" : "failure"}`);
    } catch (e) {
      toast.error(e, "Save failed");
    } finally {
      setBusy(null);
    }
  }, [saveDialog, toast]);
  const confirmAbort = useCallback(async () => {
    setAbortConfirmOpen(false);
    setSaveDialog((d) => ({ ...d, open: false }));
    await run("Abort", () => api.post("/api/recording/abort"), "Recording aborted and deleted");
  }, [run]);
  const requestAbort = useCallback(() => {
    const snap = live.snapshot;
    if (!snap?.recording.active) {
      toast.push("warn", "Nothing is being recorded");
      return;
    }
    const threshold = settings?.recording.confirm_abort_after_s ?? 10;
    const t = performance.now();
    if (snap.recording.elapsed_s < threshold || abortOpenRef.current || t - lastAbortPress.current < 2000) {
      lastAbortPress.current = 0;
      void confirmAbort();
      return;
    }
    lastAbortPress.current = t;
    setAbortConfirmOpen(true);
  }, [confirmAbort, settings, toast]);
  const estop = useCallback(async () => {
    setSaveDialog((d) => ({ ...d, open: false }));
    setAbortConfirmOpen(false);
    try {
      await api.post("/api/control/estop");
      toast.push("error", "Emergency stop", "Triggers off, followers damped. Clear the fault to continue.");
    } catch (e) {
      toast.error(e, "E-stop request failed. Use the hardware e-stop button");
    }
  }, [toast]);
  const clearFault = useCallback(async () => {
    await run("Clear fault", () => api.post("/api/control/clear_fault"), "Fault cleared");
  }, [run]);

  const markLast = useCallback(
    async (success: boolean) => {
      if (saveDialog.open) {
        setSaveDialog({ ...saveDialog, success });
        return;
      }
      if (!lastSaved) {
        toast.push("warn", "No episode to mark", "Marks apply to the save dialog or the last saved episode.");
        return;
      }
      await run("Mark episode", async () => {
        const ep = await api.patch<Episode>(`/api/episodes/${lastSaved.id}`, { success });
        setLastSaved(ep);
        setEpisodesVersion((v) => v + 1);
      }, `Marked last episode as ${success ? "success" : "failure"}`);
    },
    [lastSaved, run, saveDialog, toast],
  );

  // Global keyboard shortcuts.
  const handlers = useRef<Record<KeyAction, () => void>>({} as Record<KeyAction, () => void>);
  handlers.current = {
    start_recording: () => void startRecording(),
    save: () => (saveDialog.open ? void confirmSave() : requestSave()),
    abort: () => (countdownTimer.current !== undefined ? cancelCountdown() : requestAbort()),
    teleop_toggle: () => {
      const p = live.snapshot?.phase;
      if (p === "teleop") void setTeleop(false);
      else if (p === "ready") void setTeleop(true);
      else toast.push("warn", "Teleop isn't available right now", p === "recording" ? "Save or abort the recording first." : "Start the arms first.");
    },
    estop: () => void estop(),
    mark_success: () => void markLast(true),
    mark_failure: () => void markLast(false),
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!settings) return;
      const el = e.target as HTMLElement | null;
      const typing =
        el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      if (document.body.dataset.capturingKey === "1") return;
      const action = (Object.keys(settings.keybindings) as KeyAction[]).find((a) => settings.keybindings[a] === e.code);
      if (!action) return;
      // The e-stop key works everywhere; other shortcuts are ignored while typing in a field.
      if (typing && action !== "estop") return;
      if (e.repeat) return;
      e.preventDefault();
      handlers.current[action]();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [settings]);

  const value = useMemo(
    () => ({
      busy,
      powerAll,
      startArms,
      stopArms,
      setTeleop,
      startRecording,
      countdown,
      cancelCountdown,
      requestSave,
      requestAbort,
      estop,
      clearFault,
      saveDialog,
      setSaveDialog,
      confirmSave,
      abortConfirmOpen,
      setAbortConfirmOpen,
      confirmAbort,
      lastSaved,
      episodesVersion,
      bumpEpisodes: () => setEpisodesVersion((v) => v + 1),
      run,
    }),
    [busy, powerAll, startArms, stopArms, setTeleop, startRecording, countdown, cancelCountdown, requestSave, requestAbort, estop, clearFault, saveDialog, confirmSave, abortConfirmOpen, confirmAbort, lastSaved, episodesVersion, run],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useController(): Controller {
  const c = useContext(Ctx);
  if (!c) throw new Error("useController outside provider");
  return c;
}
