"use client";

import { useCallback, useEffect, useState } from "react";
import { FileSearch, X } from "lucide-react";
import { AppSidebar } from "./app-sidebar";
import { DashboardOverview } from "@/components/dashboard/dashboard-overview";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { selectRepository } from "@/lib/features/repository/repositorySlice";
import { selectActiveRepository, selectRepositories } from "@/lib/features/repository/repositorySelectors";
import { useGetMetricsQuery, useGetRepositoriesQuery } from "@/lib/services/codesageApi";
import type {
  ConnectionState,
  DashboardResource,
  LatencyMetric,
  Repository,
} from "@/components/dashboard/dashboard-types";
import { Button } from "@/components/ui/primitives";

type DashboardPayload<T> =
  | { status: "success"; data: T }
  | { status: "error"; code: string; httpStatus: number };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseMetrics(value: unknown): LatencyMetric[] | null {
  if (!isRecord(value) || !Array.isArray(value.latency)) {
    return null;
  }
  const metrics: LatencyMetric[] = [];
  for (const item of value.latency) {
    if (
      !isRecord(item) ||
      typeof item.stage !== "string" ||
      typeof item.count !== "number" ||
      !Number.isFinite(item.count) ||
      typeof item.p50_ms !== "number" ||
      !Number.isFinite(item.p50_ms) ||
      typeof item.p95_ms !== "number" ||
      !Number.isFinite(item.p95_ms) ||
      typeof item.p99_ms !== "number" ||
      !Number.isFinite(item.p99_ms)
    ) {
      return null;
    }
    metrics.push({
      stage: item.stage,
      count: item.count,
      p50_ms: item.p50_ms,
      p95_ms: item.p95_ms,
      p99_ms: item.p99_ms,
    });
  }
  return metrics;
}

function responseErrorCode(value: unknown, status: number): string {
  if (isRecord(value) && typeof value.error === "string") {
    return value.error;
  }
  if (status === 504) return "UPSTREAM_TIMEOUT";
  if (status === 502) return "UPSTREAM_UNAVAILABLE";
  return "UPSTREAM_REQUEST_FAILED";
}

async function loadResource<T>(
  path: string,
  parse: (value: unknown) => T | null,
): Promise<DashboardPayload<T>> {
  try {
    const response = await fetch(path, {
      headers: { accept: "application/json" },
      cache: "no-store",
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      return {
        status: "error",
        code: responseErrorCode(payload, response.status),
        httpStatus: response.status,
      };
    }
    const data = parse(payload);
    return data
      ? { status: "success", data }
      : {
          status: "error",
          code: "INVALID_BACKEND_RESPONSE",
          httpStatus: response.status,
        };
  } catch {
    return {
      status: "error",
      code: "BFF_UNAVAILABLE",
      httpStatus: 0,
    };
  }
}

function deriveConnection(
  repositories: DashboardResource<Repository[]> | null,
  metrics: DashboardResource<LatencyMetric[]> | null,
  loading: boolean,
): ConnectionState {
  if (loading && !repositories && !metrics) return "checking";
  const resources = [repositories, metrics];
  const codes: string[] = [];
  for (const resource of resources) {
    if (resource?.status === "error") {
      codes.push(resource.code);
    }
  }
  if (codes.includes("BFF_DISABLED")) return "disabled";
  if (
    codes.some((code) =>
      ["UPSTREAM_UNAVAILABLE", "UPSTREAM_TIMEOUT", "BFF_UNAVAILABLE"].includes(
        code,
      ),
    )
  ) {
    return "unavailable";
  }
  if (codes.includes("UPSTREAM_NOT_CONFIGURED")) return "not-configured";
  if (codes.length > 0) return "degraded";
  return resources.every((resource) => resource !== null)
    ? "connected"
    : "checking";
}

export function ApplicationShell() {
  const dispatch = useAppDispatch();
  const repositories = useAppSelector(selectRepositories);
  const activeRepository = useAppSelector(selectActiveRepository);
  const repositoryQuery = useGetRepositoriesQuery();
  const metricsQuery = useGetMetricsQuery();

  const repositoriesResource: DashboardResource<Repository[]> | null =
    repositoryQuery.data
      ? { status: "success", data: repositoryQuery.data }
      : repositoryQuery.isError
        ? { status: "error", code: "UPSTREAM_REQUEST_FAILED", httpStatus: 0 }
        : null;

  const metricsResource: DashboardResource<LatencyMetric[]> | null =
    metricsQuery.data
      ? { status: "success", data: metricsQuery.data.latency }
      : metricsQuery.isError
        ? { status: "error", code: "UPSTREAM_REQUEST_FAILED", httpStatus: 0 }
        : null;

  const loading = repositoryQuery.isLoading || metricsQuery.isLoading;
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);

  useEffect(() => {
    if (!activeRepository && repositoryQuery.data?.[0]) {
      dispatch(selectRepository(repositoryQuery.data[0].repo_name));
    }
  }, [activeRepository, dispatch, repositoryQuery.data]);

  useEffect(() => {
    function handleEscape(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        setNavigationOpen(false);
        setInspectorOpen(false);
      }
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, []);

  const refresh = useCallback(() => {
    void repositoryQuery.refetch();
    void metricsQuery.refetch();
  }, [metricsQuery, repositoryQuery]);

  const isLoading = loading;
  const connection = deriveConnection(repositoriesResource, metricsResource, isLoading);

  return (
    <div className="atlas-shell min-h-screen text-[var(--foreground)]">
      <div className="grid min-h-screen grid-cols-1 xl:grid-cols-[244px_minmax(0,1fr)_260px] 2xl:grid-cols-[252px_minmax(0,1fr)_280px]">
        <AppSidebar
          repositories={repositoriesResource}
          loading={isLoading}
          activeRepository={activeRepository}
          onSelectRepository={(repository) => {
            dispatch(selectRepository(repository.repo_name));
            setNavigationOpen(false);
          }}
        />

        <DashboardOverview
          repositories={repositoriesResource}
          metrics={metricsResource}
          loading={isLoading}
          connection={connection}
          onRefresh={refresh}
          onOpenNavigation={() => setNavigationOpen(true)}
          onOpenInspector={() => setInspectorOpen(true)}
          activeRepository={activeRepository}
          onRefreshRepositories={refresh}
        />

        <aside
          aria-label="Contextual inspector"
          className="sticky top-0 hidden h-screen flex-col border-l border-[var(--border)] bg-[var(--surface)] px-4 py-5 xl:flex"
        >
          <InspectorContent />
        </aside>
      </div>

      {navigationOpen && (
        <DrawerBackdrop
          onClose={() => setNavigationOpen(false)}
          label="Repository navigation drawer"
        >
          <AppSidebar
            drawer
            repositories={repositoriesResource}
            loading={loading}
            activeRepository={activeRepository}
            onSelectRepository={(repository) => {
              dispatch(selectRepository(repository.repo_name));
              setNavigationOpen(false);
            }}
            onClose={() => setNavigationOpen(false)}
          />
        </DrawerBackdrop>
      )}

      {inspectorOpen && (
        <DrawerBackdrop
          onClose={() => setInspectorOpen(false)}
          label="Contextual inspector drawer"
          alignRight
        >
          <aside
            aria-label="Contextual inspector"
            className="flex h-full w-[300px] flex-col border-l border-[var(--border)] bg-[var(--surface)] px-4 py-5"
          >
            <Button
              onClick={() => setInspectorOpen(false)}
              aria-label="Close contextual inspector"
              className="mb-4 self-end"
            >
              <X aria-hidden="true" size={15} />
            </Button>
            <InspectorContent />
          </aside>
        </DrawerBackdrop>
      )}
    </div>
  );
}

function InspectorContent() {
  return (
    <>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">
            Context
          </p>
          <h2 className="atlas-display mt-2 text-base font-semibold text-[var(--foreground)]">
            Inspector
          </h2>
        </div>
        <span className="flex size-8 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border)] text-[var(--muted)]">
          <FileSearch aria-hidden="true" size={15} />
        </span>
      </div>
      <div className="mt-5 flex min-h-44 flex-col items-center justify-center rounded-[var(--radius-md)] border border-dashed border-[var(--border-strong)] bg-[var(--surface-raised)] px-4 text-center">
        <FileSearch
          aria-hidden="true"
          size={20}
          className="text-[var(--muted)]"
        />
        <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
          Nothing selected
        </p>
        <p className="mt-2 text-xs leading-relaxed text-[var(--muted)]">
          Structured source evidence and file context will appear here in a
          later stage.
        </p>
      </div>
    </>
  );
}

function DrawerBackdrop({
  children,
  onClose,
  label,
  alignRight = false,
}: {
  children: React.ReactNode;
  onClose: () => void;
  label: string;
  alignRight?: boolean;
}) {
  return (
    <div
      role="dialog"
      aria-label={label}
      aria-modal="true"
      className="fixed inset-0 z-50 flex bg-black/45"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={alignRight ? "ml-auto" : "mr-auto"}>{children}</div>
    </div>
  );
}


