import { useEffect, useMemo, useState } from "react";
import type { ArmSide, HapticSettings, KeyAction, Settings } from "../api/types";
import { PageHeader } from "../components/Shell";
import { Button, Field, Kbd, Panel, Slider, Toggle } from "../components/ui";
import { useAppData } from "../state/appdata";
import { ACTION_LABELS } from "../state/controller";
import { useToast } from "../state/toasts";

const KEY_ORDER: KeyAction[] = ["start_recording", "save", "abort", "mark_success", "mark_failure", "teleop_toggle", "estop"];
const HANDLE_BUTTONS: { id: string; label: string }[] = [
  { id: "left_a", label: "Left handle, upper button (A)" },
  { id: "left_b", label: "Left handle, lower button (B)" },
  { id: "right_a", label: "Right handle, upper button (A)" },
  { id: "right_b", label: "Right handle, lower button (B)" },
];
const HANDLE_ACTIONS = ["none", "start_recording", "save", "abort", "teleop_toggle", "mark_success", "mark_failure"] as const;

function KeyCapture({ value, onChange, conflict }: { value: string; onChange: (code: string) => void; conflict: boolean }) {
  const [capturing, setCapturing] = useState(false);
  useEffect(() => {
    if (!capturing) return;
    document.body.dataset.capturingKey = "1";
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (["ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight", "AltLeft", "AltRight", "MetaLeft", "MetaRight"].includes(e.code)) return;
      onChange(e.code);
      setCapturing(false);
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => {
      delete document.body.dataset.capturingKey;
      window.removeEventListener("keydown", onKey, { capture: true });
    };
  }, [capturing, onChange]);
  return (
    <div className="keycap-wrap">
      <button type="button" className={`keycap ${capturing ? "capturing" : ""} ${conflict ? "conflict" : ""}`} onClick={() => setCapturing(!capturing)}>
        {capturing ? "Press a key…" : value ? <Kbd code={value} /> : "Not set"}
      </button>
      {capturing && (
        <button type="button" className="link-btn small" onClick={() => setCapturing(false)}>
          Cancel
        </button>
      )}
    </div>
  );
}

function HapticsColumn({ side, h, onChange, gripMax }: { side: ArmSide; h: HapticSettings; onChange: (h: HapticSettings) => void; gripMax: number }) {
  const set = <K extends keyof HapticSettings>(k: K, v: HapticSettings[K]) => onChange({ ...h, [k]: v });
  return (
    <div className="haptics-col">
      <div className="haptics-col-head">
        <h3>{side === "left" ? "Left trigger" : "Right trigger"}</h3>
        <label className="inline-toggle">
          <Toggle checked={h.enabled} onChange={(v) => set("enabled", v)} label={`${side} force feedback`} />
          <span>Force feedback</span>
        </label>
      </div>
      <label className="field field-inline">
        <span>
          <span className="field-label">Natural feel</span>
          <span className="field-hint block">On: grip force is felt the way hands sense force, so light holds are clearly felt and the gripper's full force maps to the strongest push. Off: a fixed fraction of the grip force.</span>
        </span>
        <Toggle checked={(h.feedback_mode ?? "perceptual") === "perceptual"} onChange={(v) => set("feedback_mode", v ? "perceptual" : "linear")} label={`${side} natural feel`} />
      </label>
      {(h.feedback_mode ?? "perceptual") === "perceptual" ? (
        <Field label="Light-touch sensitivity" hint="Lower values make light grips feel stronger; 1.0 is proportional. Around 0.6 matches human force perception.">
          <Slider value={h.feedback_exponent ?? 0.6} min={0.3} max={1} step={0.05} onChange={(v) => set("feedback_exponent", v)} format={(v) => v.toFixed(2)} unit="" disabled={!h.enabled} />
        </Field>
      ) : (
        <Field label="Feedback strength" hint="Share of the follower's grip force pushed back into your finger. 0.25 means 20 N of grip feels like 5 N.">
          <Slider value={h.feedback_gain} min={0} max={1} step={0.01} onChange={(v) => set("feedback_gain", v)} format={(v) => v.toFixed(2)} unit="×" disabled={!h.enabled} />
        </Field>
      )}
      <label className="field field-inline">
        <span>
          <span className="field-label">Touch and slip cues</span>
          <span className="field-hint block">A tap in the trigger the instant the gripper touches something, a buzz while it slips, a tick on release (needs the trigger's vibration motor).</span>
        </span>
        <Toggle checked={h.cues_enabled ?? true} onChange={(v) => set("cues_enabled", v)} label={`${side} touch cues`} />
      </label>
      <Field label="Cue strength" hint="">
        <Slider value={h.cue_strength ?? 0.8} min={0.1} max={1} step={0.05} onChange={(v) => set("cue_strength", v)} format={(v) => `${Math.round(v * 100)}%`} unit="" disabled={!(h.cues_enabled ?? true)} />
      </Field>
      <Field label="Maximum feedback force" hint="Upper limit on what the trigger will push with.">
        <Slider value={h.max_render_n} min={0} max={15} step={0.5} onChange={(v) => set("max_render_n", v)} format={(v) => v.toFixed(1)} unit="N" disabled={!h.enabled} />
      </Field>
      <Field label="Return spring" hint="Light force that reopens the trigger when you let go.">
        <Slider value={h.spring_n} min={0} max={5} step={0.1} onChange={(v) => set("spring_n", v)} format={(v) => v.toFixed(1)} unit="N" />
      </Field>
      <Field label="Damping" hint="Smooths the trigger. Raise it if the trigger buzzes on contact.">
        <Slider value={h.damping} min={0} max={0.1} step={0.005} onChange={(v) => set("damping", v)} format={(v) => v.toFixed(3)} unit="N·s" />
      </Field>
      <div className="haptics-sep" />
      <Field label="Grip force at a full squeeze" hint={`Once the gripper touches an object, how far you squeeze sets the grip force, from a light hold up to this at a full squeeze. Defaults to the gripper's full force (${gripMax.toFixed(0)} N), so operators choose the force for each object and it is recorded with the episode.`}>
        <Slider value={h.max_grip_n} min={5} max={gripMax} step={1} onChange={(v) => set("max_grip_n", v)} format={(v) => v.toFixed(0)} unit="N" />
      </Field>
      <Field label="Light-grip precision" hint="1 = squeeze depth maps linearly to force. Higher spreads light forces over more of the trigger's travel, so delicate grips are easier to dose; a full squeeze still reaches full force.">
        <Slider value={h.force_curve ?? 1} min={1} max={2.5} step={0.1} onChange={(v) => set("force_curve", v)} format={(v) => v.toFixed(1)} unit="" />
      </Field>
      <label className="field field-inline">
        <span>
          <span className="field-label">Push-force mode</span>
          <span className="field-hint block">Alternative: on contact the trigger becomes a firm stop and how hard you push (not how far you squeeze) sets the grip force.</span>
        </span>
        <Toggle checked={h.force_input} onChange={(v) => set("force_input", v)} label={`${side} force input`} />
      </label>
      <Field label="Push to grip ratio" hint="Follower grip force per newton of push (push-force mode only).">
        <Slider value={h.input_gain} min={1} max={10} step={0.5} onChange={(v) => set("input_gain", v)} format={(v) => v.toFixed(1)} unit="×" disabled={!h.force_input} />
      </Field>
    </div>
  );
}

export function SettingsPage() {
  const { settings, saveSettings, station } = useAppData();
  const toast = useToast();
  const [draft, setDraft] = useState<Settings | null>(settings);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (settings && !draft) setDraft(settings);
  }, [settings, draft]);
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(settings), [draft, settings]);
  const conflicts = useMemo(() => {
    const seen = new Map<string, KeyAction[]>();
    if (!draft) return new Set<KeyAction>();
    for (const a of KEY_ORDER) {
      const c = draft.keybindings[a];
      if (!c) continue;
      seen.set(c, [...(seen.get(c) ?? []), a]);
    }
    return new Set([...seen.values()].filter((v) => v.length > 1).flat());
  }, [draft]);

  if (!draft) return <div className="page">Loading settings…</div>;

  const save = async () => {
    if (conflicts.size) {
      toast.push("error", "Two actions share a key", "Give each action its own key before saving.");
      return;
    }
    setSaving(true);
    try {
      await saveSettings(draft);
      toast.push("success", "Settings saved", "Haptic changes take effect immediately.");
    } catch (e) {
      toast.error(e, "Couldn't save settings");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page settings">
      <PageHeader title="Settings" lead="Shortcuts, handle buttons and how the triggers feel. Changes apply to everyone using this station." />

      <div className="settings-grid">
        <Panel title="Keyboard shortcuts" subtitle="Click a key, then press the new one. Foot pedals that act as keyboards work too." pad={false}>
          <ul className="keybind-list">
            {KEY_ORDER.map((a) => (
              <li key={a} className={conflicts.has(a) ? "has-conflict" : ""}>
                <div>
                  <div className="kb-label">{ACTION_LABELS[a]}</div>
                  {conflicts.has(a) && <div className="kb-conflict">Same key as another action</div>}
                  {a === "estop" && <div className="kb-note">Works even while typing in a field.</div>}
                </div>
                <KeyCapture
                  value={draft.keybindings[a]}
                  conflict={conflicts.has(a)}
                  onChange={(code) => setDraft({ ...draft, keybindings: { ...draft.keybindings, [a]: code } })}
                />
              </li>
            ))}
          </ul>
        </Panel>

        <div className="settings-col">
          <Panel title="Handle buttons" subtitle="The two thumb buttons on each haptic grip." pad={false}>
            <ul className="keybind-list">
              {HANDLE_BUTTONS.map((b) => (
                <li key={b.id}>
                  <div className="kb-label">{b.label}</div>
                  <select
                    value={draft.handle_buttons[b.id] ?? "none"}
                    onChange={(e) => setDraft({ ...draft, handle_buttons: { ...draft.handle_buttons, [b.id]: e.target.value } })}
                  >
                    {HANDLE_ACTIONS.map((a) => (
                      <option key={a} value={a}>
                        {a === "none" ? "Do nothing" : ACTION_LABELS[a]}
                      </option>
                    ))}
                  </select>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Recording">
            <label className="field field-inline">
              <span>
                <span className="field-label">Export to LeRobot on save</span>
                <span className="field-hint block">Appends each saved episode to its department and task dataset.</span>
              </span>
              <Toggle checked={draft.recording.auto_export} onChange={(v) => setDraft({ ...draft, recording: { ...draft.recording, auto_export: v } })} label="Auto export" />
            </label>
            <Field label="Countdown before recording starts">
              <Slider
                value={draft.recording.countdown_s}
                min={0}
                max={5}
                step={1}
                onChange={(v) => setDraft({ ...draft, recording: { ...draft.recording, countdown_s: v } })}
                format={(v) => (v === 0 ? "Off" : `${v}`)}
                unit={draft.recording.countdown_s ? "s" : undefined}
              />
            </Field>
            <Field label="Stop recordings automatically after">
              <Slider
                value={draft.recording.max_duration_s / 60}
                min={1}
                max={30}
                step={1}
                onChange={(v) => setDraft({ ...draft, recording: { ...draft.recording, max_duration_s: v * 60 } })}
                format={(v) => v.toFixed(0)}
                unit="min"
              />
            </Field>
            <Field label="Ask before discarding recordings longer than">
              <Slider
                value={draft.recording.confirm_abort_after_s ?? 10}
                min={0}
                max={60}
                step={5}
                onChange={(v) => setDraft({ ...draft, recording: { ...draft.recording, confirm_abort_after_s: v } })}
                format={(v) => (v === 0 ? "Always ask" : v.toFixed(0))}
                unit={(draft.recording.confirm_abort_after_s ?? 10) ? "s" : undefined}
              />
            </Field>
          </Panel>
        </div>
      </div>

      <Panel title="Haptic triggers" subtitle="How the follower's grip is felt at the trigger, and how your squeeze drives the follower." className="haptics-panel">
        <div className="haptics-grid">
          {(["left", "right"] as ArmSide[]).map((s) => (
            <HapticsColumn key={s} side={s} h={draft.haptics[s]} gripMax={station?.grip_force_max?.[s] ?? 50} onChange={(h) => setDraft({ ...draft, haptics: { ...draft.haptics, [s]: h } })} />
          ))}
        </div>
      </Panel>

      {dirty && (
        <div className="savebar" role="region" aria-label="Unsaved changes">
          <span>
            <strong>Unsaved changes.</strong> {conflicts.size ? "Fix the key conflict to save." : "Save to apply them to the station."}
          </span>
          <span className="spacer" />
          <Button variant="ghost" onClick={() => setDraft(settings)}>
            Discard
          </Button>
          <Button variant="primary" onClick={() => void save()} loading={saving} disabled={conflicts.size > 0}>
            Save settings
          </Button>
        </div>
      )}
    </div>
  );
}
