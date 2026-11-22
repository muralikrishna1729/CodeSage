"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { GitBranch, LoaderCircle, Plus, RefreshCw } from "lucide-react";
import { Button, Surface } from "@/components/ui/primitives";
import {
  useGetIngestionStatusQuery,
  useStartIngestionMutation,
  type IngestStatus,
} from "@/lib/services/codesageApi";

type JobStatus = {
  status: "queued" | "running" | "done" | "error";
  stage: string;
  elapsed_s: number;
  chunks_stored: number | null;
  error: string | null;
};

type AcceptedJob = {
  job_id: string;
  repo_name: string;
};

const POLL_INTERVAL_MS = 1500;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isGitHubRepositoryUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    const segments = url.pathname.split("/").filter(Boolean);
    return (
      url.protocol === "https:" &&
      url.hostname === "github.com" &&
      !url.username &&
      !url.password &&
      segments.length === 2
    );
  } catch {
    return false;
  }
}

function ingestionError(value: unknown, status: number): string {
  if (isRecord(value) && value.error === "BFF_DISABLED") {
    return "Repository ingestion is disabled by server configuration.";
  }
  if (isRecord(value) && value.error === "INGESTION_DISABLED") {
    return "Ingestion is disabled by the independent server-side ingestion setting.";
  }
  if (status === 400) {
    return "The server rejected this repository URL. Check that the repository is public and the URL is valid.";
  }
  return "Could not start repository ingestion. Check the service and try again.";
}

export function RepositoryOnboarding({
  onComplete,
}: {
  onComplete: () => void;
}) {
  const [repoUrl, setRepoUrl] = useState("");
  const [submittedUrl, setSubmittedUrl] = useState<string | null>(null);
  const [job, setJob] = useState<AcceptedJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [pollError, setPollError] = useState(false);
  const completedJobRef = useRef<string | null>(null);

  const [startIngestion] = useStartIngestionMutation();
  const jobId = job?.job_id ?? "";
  const { data: statusData, refetch: refetchStatus } = useGetIngestionStatusQuery(
    jobId,
    { skip: !jobId },
  );

  useEffect(() => {
    if (!jobId || !statusData) return;

    if (statusData.status === "done") {
      if (completedJobRef.current !== jobId) {
        completedJobRef.current = jobId;
        onComplete();
      }
      return;
    }

    if (statusData.status === "error") return;

    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll(): Promise<void> {
      try {
        setPollError(false);
        await refetchStatus();
      } catch {
        if (!active) return;
        setPollError(true);
      }
      if (active) {
        timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
      }
    }

    void poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, statusData, refetchStatus, onComplete]);

  async function submit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedUrl = repoUrl.trim();
    setValidationError(null);
    setRequestError(null);
    if (!isGitHubRepositoryUrl(normalizedUrl)) {
      setValidationError(
        "Use a GitHub repository URL in the form https://github.com/owner/repository.",
      );
      return;
    }

    setSubmittedUrl(normalizedUrl);
    setStarting(true);
    try {
      const result = await startIngestion({ repo_url: normalizedUrl }).unwrap();
      setJob({ job_id: result.job_id, repo_name: result.repo_name });
    } catch (err) {
      const errorData = (err as { data?: unknown })?.data;
      const errorStatus = (err as { status?: number })?.status;
      setRequestError(ingestionError(errorData, errorStatus ?? 500));
      setSubmittedUrl(null);
    } finally {
      setStarting(false);
    }
  }

  const activeJob = Boolean(
    job && statusData && !["done", "error"].includes(statusData.status),
  );

  return (
    <Surface
      as="section"
      aria-labelledby="add-repository-heading"
      className="min-w-0 p-5 sm:p-6"
    >
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-raised)] text-[var(--primary)]">
          <GitBranch aria-hidden="true" size={17} />
        </span>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">
            Repository onboarding
          </p>
          <h2
            id="add-repository-heading"
            className="atlas-display mt-1 text-lg font-semibold text-[var(--foreground)]"
          >
            Add a GitHub repository
          </h2>
        </div>
      </div>

      <form onSubmit={submit} className="mt-5">
        <label
          htmlFor="github-repository-url"
          className="mb-2 block text-xs font-medium text-[var(--muted-strong)]"
        >
          GitHub repository URL
        </label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            id="github-repository-url"
            type="text"
            inputMode="url"
            autoComplete="url"
            placeholder="https://github.com/owner/repository"
            value={repoUrl}
            onChange={(event) => setRepoUrl(event.target.value)}
            aria-invalid={Boolean(validationError)}
            aria-describedby={
              validationError ? "repository-url-error" : undefined
            }
            disabled={starting || activeJob}
            className="h-10 min-w-0 flex-1 rounded-[var(--radius-md)] border border-[var(--border-strong)] bg-[var(--surface-raised)] px-3 text-sm text-[var(--foreground)] placeholder:text-[var(--muted)] focus-visible:outline-none"
          />
          <Button type="submit" disabled={starting || activeJob}>
            {starting ? (
              <LoaderCircle aria-hidden="true" size={14} className="animate-spin" />
            ) : (
              <Plus aria-hidden="true" size={14} />
            )}
            Add repository
          </Button>
        </div>
        {validationError && (
          <p id="repository-url-error" role="alert" className="mt-2 text-xs text-[var(--destructive)]">
            {validationError}
          </p>
        )}
        {requestError && (
          <p role="alert" className="mt-2 text-xs text-[var(--warning)]">
            {requestError}
          </p>
        )}
      </form>

      {submittedUrl && !job && !requestError && (
        <p className="mt-4 text-xs text-[var(--muted)]" aria-live="polite">
          Starting ingestion for <span className="atlas-mono">{submittedUrl}</span>â€¦
        </p>
      )}

      {job && (
        <div
          className="mt-5 border-t border-[var(--border)] pt-4"
          aria-live="polite"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="atlas-mono text-sm text-[var(--foreground)]">
              {job.repo_name}
            </p>
            <span className="text-[10px] uppercase tracking-[0.15em] text-[var(--muted)]">
              {statusData?.status ?? "Accepted"}
            </span>
          </div>
          {statusData ? (
            <>
              <p className="mt-2 text-sm text-[var(--muted-strong)]">
                {statusData.stage}
              </p>
              <p className="mt-1 text-xs text-[var(--muted)]">
                Elapsed {statusData.elapsed_s.toLocaleString("en-US")}s
                {statusData.chunks_stored !== null &&
                  ` · ${statusData.chunks_stored.toLocaleString()} chunks stored`}
              </p>
              {statusData.status === "error" && statusData.error && (
                <p role="alert" className="mt-2 text-xs text-[var(--destructive)]">
                  {statusData.error}
                </p>
              )}
            </>
          ) : (
            <p className="mt-2 text-xs text-[var(--muted)]">
              Indexing repository
            </p>
          )}
          {pollError && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-[var(--warning)]">
              <RefreshCw aria-hidden="true" size={12} />
              Progress unavailable; retrying safelyâ€¦
            </p>
          )}
        </div>
      )}
    </Surface>
  );
}


