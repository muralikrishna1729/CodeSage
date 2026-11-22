"use client";

import {
  MetricsSection,
} from "./metrics-section";
import { RepositorySection } from "./repository-section";
import type {
  ConnectionState,
  DashboardResource,
  LatencyMetric,
  Repository,
} from "./dashboard-types";
import { DashboardHeader } from "./dashboard-header";
import { RepositoryOnboarding } from "./repository-onboarding";
import { Surface } from "@/components/ui/primitives";
export function DashboardOverview({
  repositories,
  metrics,
  loading,
  connection,
  onRefresh,
  onOpenNavigation,
  onOpenInspector,
  activeRepository,
  onRefreshRepositories,
}: {
  repositories: DashboardResource<Repository[]> | null;
  metrics: DashboardResource<LatencyMetric[]> | null;
  loading: boolean;
  connection: ConnectionState;
  onRefresh: () => void;
  onOpenNavigation: () => void;
  onOpenInspector: () => void;
  activeRepository: Repository | null;
  onRefreshRepositories: () => void;
}) {
  const notice =
    connection === "disabled"
      ? "BFF access is disabled by server configuration. Enable it only after a trusted deployment access boundary is in place."
      : connection === "unavailable"
        ? "The FastAPI backend could not be reached. Check its configured URL and availability."
        : connection === "not-configured"
          ? "The backend URL or server-side API key is not configured."
          : connection === "degraded"
            ? "The backend returned an incomplete response. Some dashboard data may be unavailable."
            : null;

  return (
    <main className="min-w-0 flex-1" aria-busy={loading}>
      <div className="mx-auto w-full max-w-[1440px] px-4 pb-10 pt-7 sm:px-7 sm:pt-9 lg:px-10 lg:pt-11">
        <DashboardHeader
          connection={connection}
          loading={loading}
          onRefresh={onRefresh}
          onOpenNavigation={onOpenNavigation}
          onOpenInspector={onOpenInspector}
        />
        {activeRepository && (
          <p className="mt-4 text-xs text-[var(--muted)]">
            Active repository:{" "}
            <span className="atlas-mono text-[var(--foreground)]">
              {activeRepository.repo_name}
            </span>
          </p>
        )}

        {notice && (
          <div
            role="alert"
            className="mt-5 rounded-[var(--radius-md)] border border-[var(--warning)] bg-[var(--warning-soft)] px-4 py-3 text-xs leading-relaxed text-[var(--foreground)]"
          >
            {notice}
          </div>
        )}

        <RepositoryOnboarding onComplete={onRefreshRepositories} />

        <Surface
          aria-labelledby="repository-context-heading"
          className="mt-4 flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6"
        >
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">
              Selected repository
            </p>
            <h2
              id="repository-context-heading"
              className="atlas-display mt-1 truncate text-base font-semibold text-[var(--foreground)]"
            >
              {activeRepository?.repo_name ?? "No repository selected"}
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-[var(--muted)]">
              {activeRepository
                ? "File tree, symbols, and repository map are planned for a later stage."
                : "Choose an indexed repository from navigation or add one above."}
            </p>
          </div>
          {activeRepository && (
            <p className="shrink-0 text-xs text-[var(--muted)]">
              {activeRepository.points.toLocaleString()} stored points
            </p>
          )}
        </Surface>

        <div className="mt-7 grid min-w-0 gap-4 xl:grid-cols-[0.92fr_1.08fr]">
          <RepositorySection
            result={repositories}
            loading={loading}
            onRefresh={onRefreshRepositories}
          />
          <MetricsSection result={metrics} loading={loading} />
        </div>

        <footer className="mt-7 flex flex-col gap-2 border-t border-[var(--border)] pt-4 text-[10px] leading-relaxed text-[var(--muted)] sm:flex-row sm:items-center sm:justify-between">
          <span>Dashboard data is read from the configured FastAPI backend.</span>
          <span>This frontend does not provide individual-user authentication.</span>
        </footer>
      </div>
    </main>
  );
}
