import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { IconCheck, IconDot, IconError, IconSpinner, IconWarn, IconX } from "./icons";
import { keyLabel } from "../state/controller";

// --------------------------------------------------------------------------- buttons

type BtnVariant = "primary" | "secondary" | "ghost" | "danger" | "record";
export function Button({
  variant = "secondary",
  size = "md",
  icon,
  kbd,
  loading,
  children,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: BtnVariant;
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
  kbd?: string;
  loading?: boolean;
}) {
  return (
    <button className={`btn btn-${variant} btn-${size} ${className}`} disabled={rest.disabled || loading} {...rest}>
      {loading ? <IconSpinner size={size === "lg" ? 20 : 16} /> : icon}
      {children && <span className="btn-label">{children}</span>}
      {kbd && <Kbd code={kbd} />}
    </button>
  );
}

export function Kbd({ code }: { code: string }) {
  if (!code) return null;
  return <kbd className="kbd">{keyLabel(code)}</kbd>;
}

// --------------------------------------------------------------------------- status

export type Status = "ok" | "warn" | "error" | "unknown" | "pending" | "running" | "skipped";
export function StatusIcon({ status, size = 18 }: { status: Status; size?: number }) {
  const cls = `status-icon st-${status}`;
  switch (status) {
    case "ok":
      return <span className={cls}><IconCheck size={size} /></span>;
    case "warn":
      return <span className={cls}><IconWarn size={size} /></span>;
    case "error":
      return <span className={cls}><IconError size={size} /></span>;
    case "running":
      return <span className={cls}><IconSpinner size={size} /></span>;
    case "skipped":
      return <span className={cls}><IconX size={size} /></span>;
    default:
      return <span className={cls}><IconDot size={size} /></span>;
  }
}

export function Badge({ tone = "idle", children }: { tone?: "ok" | "warn" | "err" | "idle" | "primary"; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

// --------------------------------------------------------------------------- panels

export function Panel({
  title,
  actions,
  children,
  className = "",
  subtitle,
  pad = true,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  pad?: boolean;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="panel-head">
          <div>
            {title && <h2 className="panel-title">{title}</h2>}
            {subtitle && <div className="panel-sub">{subtitle}</div>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      <div className={pad ? "panel-body" : "panel-body-flush"}>{children}</div>
    </section>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {children && <div className="empty-body">{children}</div>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}

// --------------------------------------------------------------------------- overlays

export function Modal({
  open,
  title,
  children,
  footer,
  onClose,
  width = 520,
}: {
  open: boolean;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  width?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) ref.current?.querySelector<HTMLElement>("[data-autofocus], button.btn-primary")?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" style={{ width }} ref={ref}>
        <header className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <IconX size={18} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}

export function Drawer({
  open,
  title,
  subtitle,
  children,
  onClose,
  width = 880,
}: {
  open: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  onClose: () => void;
  width?: number;
}) {
  if (!open) return null;
  return (
    <div className="overlay overlay-drawer" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" style={{ width: `min(${width}px, 100vw)` }} role="dialog" aria-modal="true">
        <header className="drawer-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <div className="drawer-sub">{subtitle}</div>}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <IconX size={20} />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}

export function ConfirmModal({
  open,
  title,
  body,
  confirmLabel,
  danger,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      width={440}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} data-autofocus>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="confirm-body">{body}</div>
    </Modal>
  );
}

// --------------------------------------------------------------------------- form controls

export function Field({ label, hint, children, inline }: { label: string; hint?: ReactNode; children: ReactNode; inline?: boolean }) {
  return (
    <label className={`field ${inline ? "field-inline" : ""}`}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className={`toggle ${checked ? "on" : ""}`}
      onClick={() => onChange(!checked)}
    >
      <span className="toggle-knob" />
    </button>
  );
}

export function Slider({
  value,
  min,
  max,
  step,
  onChange,
  unit,
  format,
  disabled,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  unit?: string;
  format?: (v: number) => string;
  disabled?: boolean;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div className={`slider ${disabled ? "disabled" : ""}`}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ ["--pct" as string]: `${pct}%` }}
      />
      <span className="slider-val tnum">
        {format ? format(value) : value}
        {unit && <span className="unit"> {unit}</span>}
      </span>
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="segmented" role="radiogroup">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          className={value === o.value ? "active" : ""}
          onClick={() => onChange(o.value)}
          type="button"
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Meter({ value, max = 1, tone = "primary", label }: { value: number; max?: number; tone?: string; label?: string }) {
  const pct = Math.max(0, Math.min(1, value / max)) * 100;
  return (
    <div className={`meter meter-${tone}`} aria-label={label} role="meter" aria-valuenow={value} aria-valuemax={max}>
      <div className="meter-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}
