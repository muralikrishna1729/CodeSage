import {
  Activity,
  AlertTriangle,
  CircleDashed,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import type { ConnectionState } from "./dashboard-types";

const statusContent: Record<
  ConnectionState,
  { label: string; detail: string; icon: typeof Activity; color: string }
> = {
  checking: {
    label: "Checking connection",
    detail: "Contacting the server-side API",
    icon: CircleDashed,
    color: "text-[var(--muted)]",
  },
  connected: {
    label: "Connected",
    detail: "FastAPI is responding",
    icon: ShieldCheck,
    color: "text-[var(--primary)]",
  },
  disabled: {
    label: "Access disabled",
    detail: "BFF access is disabled by server configuration",
    icon: ShieldAlert,
    color: "text-[var(--warning)]",
  },
  unavailable: {
    label: "Backend unavailable",
    detail: "The configured backend could not be reached",
    icon: AlertTriangle,
    color: "text-[var(--destructive)]",
  },
  "not-configured": {
    label: "Backend not configured",
    detail: "Server-side backend settings are incomplete",
    icon: AlertTriangle,
    color: "text-[var(--warning)]",
  },
  degraded: {
    label: "Partial response",
    detail: "One or more backend requests failed",
    icon: Activity,
    color: "text-[var(--warning)]",
  },
};

export function BackendStatus({ state }: { state: ConnectionState }) {
  const { label, detail, icon: Icon, color } = statusContent[state];

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-w-0 items-center gap-3 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-raised)] px-3.5 py-2.5"
    >
      <Icon aria-hidden="true" size={17} className={color} strokeWidth={1.8} />
      <span className="min-w-0">
        <span className={`block text-xs font-medium ${color}`}>{label}</span>
        <span className="hidden truncate text-[10px] text-[var(--muted)] sm:block">
          {detail}
        </span>
      </span>
    </div>
  );
}
