"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { FileSearch, X } from "lucide-react";
import { AppSidebar, type WorkspaceSection } from "./app-sidebar";
import { DashboardOverview } from "@/components/dashboard/dashboard-overview";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { selectRepository } from "@/lib/features/repository/repositorySlice";
import { selectActiveRepository } from "@/lib/features/repository/repositorySelectors";
import {
  codesageApi,
  useGetMetricsQuery,
  useGetRepositoriesQuery,
} from "@/lib/services/codesageApi";
import type {
  ConnectionState,
  DashboardResource,
  LatencyMetric,
  Repository,
} from "@/components/dashboard/dashboard-types";
import { Button } from "@/components/ui/primitives";

function deriveConnection(
  repositories: DashboardResource<Repository[]> | null,
  metrics: DashboardResource<LatencyMetric[]> | null,
  loading: boolean,
): ConnectionState {
  if (loading && !repositories && !metrics) return "checking";
  const resources = [repositories, metrics];
  const codes = resources.flatMap((resource) =>
    resource?.status === "error" ? [resource.code] : [],
  );

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

export function ApplicationShell({
  children,
  activeSection = "overview",
  inspectorContent,
}: {
  children?: ReactNode;
  activeSection?: WorkspaceSection;
  inspectorContent?: ReactNode;
}) {
  const dispatch = useAppDispatch();
  const activeRepository = useAppSelector(selectActiveRepository);
  const repositoryQuery = useGetRepositoriesQuery();
  const metricsQuery = useGetMetricsQuery(undefined, {
    skip: activeSection === "chat",
  });

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

  const loading =
    repositoryQuery.isLoading ||
    (activeSection === "overview" && metricsQuery.isLoading);
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
    dispatch(codesageApi.util.invalidateTags(["Repositories", "Metrics"]));
  }, [dispatch]);

  const connection = deriveConnection(
    repositoriesResource,
    metricsResource,
    loading,
  );

  const sidebar = (
    <AppSidebar
      repositories={repositoriesResource}
      loading={loading}
      activeRepository={activeRepository}
      activeSection={activeSection}
      onSelectRepository={(repository) => {
        dispatch(selectRepository(repository.repo_name));
        setNavigationOpen(false);
      }}
    />
  );

  return (
    <div className="atlas-shell min-h-screen text-[var(--foreground)]">
      <div className="grid min-h-screen grid-cols-1 xl:grid-cols-[244px_minmax(0,1fr)_260px] 2xl:grid-cols-[252px_minmax(0,1fr)_280px]">
        {sidebar}

        {children ?? (
          <DashboardOverview
            repositories={repositoriesResource}
            metrics={metricsResource}
            loading={loading}
            connection={connection}
            onRefresh={refresh}
            onOpenNavigation={() => setNavigationOpen(true)}
            onOpenInspector={() => setInspectorOpen(true)}
            activeRepository={activeRepository}
            onRefreshRepositories={refresh}
          />
        )}

        <aside
          aria-label="Contextual inspector"
          className="sticky top-0 hidden h-screen flex-col border-l border-[var(--border)] bg-[var(--surface)] px-4 py-5 xl:flex"
        >
          <InspectorContent
            activeRepository={activeRepository}
            activeSection={activeSection}
          >
            {inspectorContent}
          </InspectorContent>
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
            activeSection={activeSection}
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
            <InspectorContent
              activeRepository={activeRepository}
              activeSection={activeSection}
            >
              {inspectorContent}
            </InspectorContent>
          </aside>
        </DrawerBackdrop>
      )}
    </div>
  );
}

function InspectorContent({
  activeRepository,
  activeSection,
  children,
}: {
  activeRepository: Repository | null;
  activeSection: WorkspaceSection;
  children?: ReactNode;
}) {
  return (
    <>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">
            {activeSection === "chat" ? "Codebase context" : "Context"}
          </p>
          <h2 className="atlas-display mt-2 text-base font-semibold text-[var(--foreground)]">
            {activeSection === "chat" ? "Chat inspector" : "Inspector"}
          </h2>
        </div>
        <span className="flex size-8 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border)] text-[var(--muted)]">
          <FileSearch aria-hidden="true" size={15} />
        </span>
      </div>

      {activeRepository ? (
        <div className="mt-5 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-raised)] p-4">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">
            Active repository
          </p>
          <p className="atlas-mono mt-2 break-all text-xs font-medium text-[var(--foreground)]">
            {activeRepository.repo_name}
          </p>
          <p className="mt-2 text-xs text-[var(--muted)]">
            {activeRepository.points.toLocaleString()} indexed points
          </p>
        </div>
      ) : (
        <div className="mt-5 flex min-h-40 flex-col items-center justify-center rounded-[var(--radius-md)] border border-dashed border-[var(--border-strong)] bg-[var(--surface-raised)] px-4 text-center">
          <FileSearch
            aria-hidden="true"
            size={20}
            className="text-[var(--muted)]"
          />
          <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
            No repository selected
          </p>
          <p className="mt-2 text-xs leading-relaxed text-[var(--muted)]">
            Select an indexed repository to establish codebase context.
          </p>
        </div>
      )}

      {children}
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
