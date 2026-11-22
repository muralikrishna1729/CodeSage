"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { DashboardResource, Repository } from "@/components/dashboard/dashboard-types";

export interface RepositoryContextValue {
  repositories: DashboardResource<Repository[]> | null;
  activeRepository: Repository | null;
  setActiveRepository: (repository: Repository | null) => void;
  loading: boolean;
  refreshRepositories: () => void;
}

const defaultValue: RepositoryContextValue = {
  repositories: null,
  activeRepository: null,
  setActiveRepository: () => {},
  loading: true,
  refreshRepositories: () => {},
};

const RepositoryContext = createContext<RepositoryContextValue>(defaultValue);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseRepositories(value: unknown): Repository[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const repositories: Repository[] = [];
  for (const item of value) {
    if (
      !isRecord(item) ||
      typeof item.repo_name !== "string" ||
      typeof item.points !== "number" ||
      !Number.isFinite(item.points)
    ) {
      return null;
    }
    repositories.push({ repo_name: item.repo_name, points: item.points });
  }
  return repositories;
}

export function RepositoryProvider({
  children,
  initialRepositories,
  initialActiveRepository,
}: {
  children: ReactNode;
  initialRepositories?: Repository[];
  initialActiveRepository?: Repository | null;
}) {
  const [repositories, setRepositories] =
    useState<DashboardResource<Repository[]> | null>(
      initialRepositories
        ? { status: "success", data: initialRepositories }
        : null
    );
  const [activeRepository, setActiveRepositoryState] =
    useState<Repository | null>(initialActiveRepository ?? null);
  const [loading, setLoading] = useState(!initialRepositories);
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    if (initialRepositories) {
      return;
    }
    let active = true;
    fetch("/api/codesage/repos", {
      headers: { accept: "application/json" },
      cache: "no-store",
    })
      .then(async (response) => {
        if (!active) {
          return;
        }
        let payload: unknown;
        try {
          payload = await response.json();
        } catch {
          payload = null;
        }
        if (!response.ok) {
          setRepositories({
            status: "error",
            code:
              response.status === 504
                ? "UPSTREAM_TIMEOUT"
                : response.status === 502
                  ? "UPSTREAM_UNAVAILABLE"
                  : "UPSTREAM_REQUEST_FAILED",
            httpStatus: response.status,
          });
          setLoading(false);
          return;
        }
        const data = parseRepositories(payload);
        setRepositories(
          data
            ? { status: "success", data }
            : {
                status: "error",
                code: "INVALID_BACKEND_RESPONSE",
                httpStatus: response.status,
              }
        );
        setLoading(false);
      })
      .catch(() => {
        if (!active) {
          return;
        }
        setRepositories({ status: "error", code: "BFF_UNAVAILABLE", httpStatus: 0 });
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [refreshVersion, initialRepositories]);

  const setActiveRepository = useCallback(
    (repository: Repository | null) => {
      setActiveRepositoryState(repository);
    },
    []
  );

  const refreshRepositories = useCallback(() => {
    setRefreshVersion((version) => version + 1);
  }, []);

  return (
    <RepositoryContext.Provider
      value={{
        repositories,
        activeRepository,
        setActiveRepository,
        loading,
        refreshRepositories,
      }}
    >
      {children}
    </RepositoryContext.Provider>
  );
}

export function useRepositoryContext() {
  return useContext(RepositoryContext);
}

export function useRepositories() {
  return useContext(RepositoryContext).repositories;
}

export function useActiveRepository() {
  return useContext(RepositoryContext).activeRepository;
}

export function useSetActiveRepository() {
  return useContext(RepositoryContext).setActiveRepository;
}

export function useRepositoryLoading() {
  return useContext(RepositoryContext).loading;
}

export function useRefreshRepositories() {
  return useContext(RepositoryContext).refreshRepositories;
}

export function selectRepositories(value: RepositoryContextValue) {
  return value.repositories;
}

export function selectActiveRepository(value: RepositoryContextValue) {
  return value.activeRepository;
}

export function useAppSelector<T>(
  selector: (value: RepositoryContextValue) => T
): T {
  return selector(useContext(RepositoryContext));
}
