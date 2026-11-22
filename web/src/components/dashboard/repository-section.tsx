import { ArrowUpRight, Database, FolderGit2, RefreshCw } from "lucide-react";
import type { DashboardResource, Repository } from "./dashboard-types";
import { Button, SectionHeading, Surface } from "@/components/ui/primitives";

function failureMessage(code: string): string {
  if (code === "BFF_DISABLED") {
    return "Repository data is unavailable because server-side BFF access is disabled.";
  }
  if (code === "UPSTREAM_NOT_CONFIGURED") {
    return "Configure the backend URL and API key on the server to load repositories.";
  }
  if (
    code === "UPSTREAM_UNAVAILABLE" ||
    code === "UPSTREAM_TIMEOUT" ||
    code === "BFF_UNAVAILABLE"
  ) {
    return "The backend could not be reached. Check the FastAPI service and try again.";
  }
  return "Repository data could not be loaded from the backend.";
}

export function RepositorySection({
  result,
  loading,
  onRefresh,
}: {
  result: DashboardResource<Repository[]> | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <Surface
      as="section"
      id="repositories"
      aria-labelledby="repositories-heading"
      className="min-w-0 p-5 sm:p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <SectionHeading
          eyebrow="Indexed codebases"
          title="Repositories"
          id="repositories-heading"
        />
        <div className="flex items-center gap-2">
          <Button
            onClick={onRefresh}
            disabled={loading}
            aria-label="Refresh repositories"
            className="h-9 px-2.5"
          >
            <RefreshCw
              aria-hidden="true"
              size={13}
              className={loading ? "animate-spin" : ""}
            />
            <span className="sr-only">Refresh repositories</span>
          </Button>
          <span className="flex size-9 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-raised)] text-[var(--muted)]">
            <Database aria-hidden="true" size={17} />
          </span>
        </div>
      </div>

      <div className="mt-5 border-t border-[var(--border)] pt-4">
        {loading || !result ? (
          <p className="py-5 text-sm text-[var(--muted)]" aria-live="polite">
            Loading indexed repositories...
          </p>
        ) : result.status === "error" ? (
          <div className="flex min-h-28 items-center gap-3 rounded-[var(--radius-md)] bg-[var(--surface-raised)] px-4">
            <FolderGit2
              aria-hidden="true"
              size={19}
              className="shrink-0 text-[var(--muted)]"
            />
            <p className="max-w-md text-sm leading-relaxed text-[var(--muted)]">
              {failureMessage(result.code)}
            </p>
          </div>
        ) : result.data.length === 0 ? (
          <div className="flex min-h-32 flex-col items-center justify-center rounded-[var(--radius-md)] border border-dashed border-[var(--border-strong)] bg-[var(--surface-raised)] px-4 text-center">
            <FolderGit2
              aria-hidden="true"
              size={21}
              className="text-[var(--muted)]"
              strokeWidth={1.6}
            />
            <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
              No repositories indexed
            </p>
            <p className="mt-1 max-w-xs text-xs leading-relaxed text-[var(--muted)]">
              Indexed GitHub codebases will appear here when backend access and
              ingestion are enabled.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {result.data.map((repository) => (
              <li
                key={repository.repo_name}
                className="flex items-center justify-between gap-4 py-3 first:pt-1 last:pb-1"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-[var(--surface-raised)] text-[var(--muted)]">
                    <FolderGit2 aria-hidden="true" size={15} />
                  </span>
                  <span className="atlas-mono truncate text-[13px] text-[var(--foreground)]">
                    {repository.repo_name}
                  </span>
                </div>
                <span className="flex shrink-0 items-center gap-1 text-[11px] text-[var(--muted)]">
                  {repository.points.toLocaleString()} stored points
                  <ArrowUpRight
                    aria-hidden="true"
                    size={13}
                    className="text-[var(--muted)]"
                  />
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Surface>
  );
}
