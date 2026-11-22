import { Menu, PanelRight, RefreshCw } from "lucide-react";
import { BackendStatus } from "./backend-status";
import type { ConnectionState } from "./dashboard-types";
import { Button } from "@/components/ui/primitives";

export function DashboardHeader({
  connection,
  loading,
  onRefresh,
  onOpenNavigation,
  onOpenInspector,
}: {
  connection: ConnectionState;
  loading: boolean;
  onRefresh: () => void;
  onOpenNavigation: () => void;
  onOpenInspector: () => void;
}) {
  return (
    <header
      id="overview"
      className="flex flex-col items-stretch gap-6 border-b border-[var(--border)] pb-7 sm:flex-col sm:items-stretch xl:flex-row xl:items-end xl:justify-between"
    >
      <div className="min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--primary)]">
          Developer workspace
        </p>
        <h1 className="atlas-display mt-3 text-3xl font-semibold text-[var(--foreground)] sm:text-[2.4rem]">
          Your codebase, in context.
        </h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-[var(--muted)]">
          A grounded view of indexed repositories and the signals behind your
          CodeSage backend.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2.5">
        <Button
          onClick={onOpenNavigation}
          className="xl:hidden"
          aria-label="Open repository navigation"
        >
          <Menu aria-hidden="true" size={14} />
          <span className="sm:hidden">Explore</span>
        </Button>
        <Button
          onClick={onOpenInspector}
          className="xl:hidden"
          aria-label="Open contextual inspector"
        >
          <PanelRight aria-hidden="true" size={14} />
        </Button>
        <BackendStatus state={connection} />
        <Button
          onClick={onRefresh}
          disabled={loading}
        >
          <RefreshCw
            aria-hidden="true"
            size={14}
            className={loading ? "animate-spin" : ""}
          />
          Refresh
        </Button>
      </div>
    </header>
  );
}
