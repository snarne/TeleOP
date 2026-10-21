import { useEffect } from "react";
import { useLive } from "../api/live";
import { useAppData } from "../state/appdata";
import { useController } from "../state/controller";
import { clock } from "../lib/format";
import { Button, Kbd, Modal } from "./ui";

export function SaveDialog() {
  const c = useController();
  const { settings, users, departments, tasks, session } = useAppData();
  const elapsed = useLive((s) => s.recording.elapsed_s, 0);
  const d = c.saveDialog;
  const kb = settings?.keybindings;

  useEffect(() => {
    if (!d.open) return;
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.tagName === "TEXTAREA";
      if (e.code === "Enter" && (!typing || e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        void c.confirmSave();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [d.open, c]);

  const op = users.find((u) => u.id === session.operator_id)?.name ?? "—";
  const dept = departments.find((x) => x.id === session.department_id)?.name ?? "—";
  const task = tasks.find((x) => x.id === session.task_id)?.name ?? "—";

  return (
    <Modal
      open={d.open}
      title="Save this episode?"
      onClose={() => c.setSaveDialog({ ...d, open: false })}
      width={540}
      footer={
        <>
          <Button variant="ghost" onClick={() => c.setSaveDialog({ ...d, open: false })}>
            Keep recording
          </Button>
          <span className="spacer" />
          <Button variant="danger" onClick={() => void c.confirmAbort()} kbd={kb?.abort}>
            Discard
          </Button>
          <Button variant="primary" onClick={() => void c.confirmSave()} kbd={kb?.save}>
            Save episode
          </Button>
        </>
      }
    >
      <div className="save-summary">
        <div>
          <div className="save-k">Length</div>
          <div className="save-v tnum">{clock(elapsed)}</div>
        </div>
        <div>
          <div className="save-k">Operator</div>
          <div className="save-v">{op}</div>
        </div>
        <div>
          <div className="save-k">Department</div>
          <div className="save-v">{dept}</div>
        </div>
        <div>
          <div className="save-k">Task</div>
          <div className="save-v">{task}</div>
        </div>
      </div>
      <div className="outcome" role="radiogroup" aria-label="Outcome">
        <button role="radio" aria-checked={d.success} className={`outcome-opt ok ${d.success ? "active" : ""}`} onClick={() => c.setSaveDialog({ ...d, success: true })}>
          <span>Task succeeded</span>
          <Kbd code={kb?.mark_success ?? ""} />
        </button>
        <button role="radio" aria-checked={!d.success} className={`outcome-opt err ${!d.success ? "active" : ""}`} onClick={() => c.setSaveDialog({ ...d, success: false })}>
          <span>Task failed</span>
          <Kbd code={kb?.mark_failure ?? ""} />
        </button>
      </div>
      <label className="field">
        <span className="field-label">Notes (optional)</span>
        <textarea
          rows={3}
          value={d.notes}
          placeholder="Anything a reviewer should know: dropped object, bumped the table…"
          onChange={(e) => c.setSaveDialog({ ...d, notes: e.target.value })}
        />
        <span className="field-hint">The recording keeps running until you save. Enter saves, Ctrl+Enter saves from the notes box.</span>
      </label>
    </Modal>
  );
}

export function AbortConfirm() {
  const c = useController();
  const { settings } = useAppData();
  const elapsed = useLive((s) => s.recording.elapsed_s, 0);
  return (
    <Modal
      open={c.abortConfirmOpen}
      title="Discard this recording?"
      onClose={() => c.setAbortConfirmOpen(false)}
      width={440}
      footer={
        <>
          <Button variant="ghost" onClick={() => c.setAbortConfirmOpen(false)}>
            Keep recording
          </Button>
          <Button variant="danger" onClick={() => void c.confirmAbort()} kbd={settings?.keybindings.abort} data-autofocus>
            Discard {clock(elapsed)} of data
          </Button>
        </>
      }
    >
      <p className="confirm-body">
        The video and arm data captured so far will be deleted and can't be recovered. Press <Kbd code={settings?.keybindings.abort ?? ""} /> again to confirm
        without the mouse.
      </p>
    </Modal>
  );
}

export function CountdownOverlay() {
  const c = useController();
  const { settings } = useAppData();
  if (!c.countdown) return null;
  return (
    <div className="countdown" role="alert">
      <div className="countdown-num tnum">{c.countdown}</div>
      <div className="countdown-text">Recording starts…</div>
      <Button variant="secondary" onClick={c.cancelCountdown} kbd={settings?.keybindings.abort}>
        Cancel
      </Button>
    </div>
  );
}
