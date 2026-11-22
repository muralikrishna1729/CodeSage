export type Repository = {
  repo_name: string;
  points: number;
};

export type LatencyMetric = {
  stage: string;
  count: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
};

export type DashboardResource<T> =
  | { status: "success"; data: T }
  | { status: "error"; code: string; httpStatus: number };

export type ConnectionState =
  | "checking"
  | "connected"
  | "disabled"
  | "unavailable"
  | "not-configured"
  | "degraded";
