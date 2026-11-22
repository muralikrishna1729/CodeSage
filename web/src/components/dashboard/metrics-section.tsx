import { Activity, Gauge } from "lucide-react";
import type { DashboardResource, LatencyMetric } from "./dashboard-types";
import { SectionHeading, Surface } from "@/components/ui/primitives";

function failureMessage(code: string): string {
  if (code === "BFF_DISABLED") {
    return "Metrics are unavailable because server-side BFF access is disabled.";
  }
  if (code === "UPSTREAM_NOT_CONFIGURED") {
    return "Configure the backend URL and API key on the server to load metrics.";
  }
  if (
    code === "UPSTREAM_UNAVAILABLE" ||
    code === "UPSTREAM_TIMEOUT" ||
    code === "BFF_UNAVAILABLE"
  ) {
    return "The backend could not be reached. Check the FastAPI service and try again.";
  }
  return "Metrics could not be loaded from the backend.";
}

function formatMilliseconds(value: number): string {
  return `${new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
  }).format(value)} ms`;
}

export function MetricsSection({
  result,
  loading,
}: {
  result: DashboardResource<LatencyMetric[]> | null;
  loading: boolean;
}) {
  return (
    <Surface
      as="section"
      id="metrics"
      aria-labelledby="metrics-heading"
      className="min-w-0 p-5 sm:p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <SectionHeading
          eyebrow="Observed pipeline latency"
          title="Latency metrics"
          id="metrics-heading"
        />
        <span className="flex size-9 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-raised)] text-[var(--muted)]">
          <Gauge aria-hidden="true" size={17} />
        </span>
      </div>

      <div className="mt-5 border-t border-[var(--border)] pt-4">
        {loading || !result ? (
          <p className="py-5 text-sm text-[var(--muted)]" aria-live="polite">
            Loading latency metrics...
          </p>
        ) : result.status === "error" ? (
          <div className="flex min-h-28 items-center gap-3 rounded-[var(--radius-md)] bg-[var(--surface-raised)] px-4">
            <Activity
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
            <Activity
              aria-hidden="true"
              size={21}
              className="text-[var(--muted)]"
              strokeWidth={1.6}
            />
            <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
              No latency samples yet
            </p>
            <p className="mt-1 max-w-xs text-xs leading-relaxed text-[var(--muted)]">
              Pipeline percentiles will appear here after the backend records
              requests.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[430px] text-left">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.14em] text-[var(--muted)]">
                  <th scope="col" className="pb-3 font-medium">
                    Stage
                  </th>
                  <th scope="col" className="pb-3 text-right font-medium">
                    Samples
                  </th>
                  <th scope="col" className="pb-3 text-right font-medium">
                    p50
                  </th>
                  <th scope="col" className="pb-3 text-right font-medium">
                    p95
                  </th>
                  <th scope="col" className="pb-3 text-right font-medium">
                    p99
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {result.data.map((metric) => (
                  <tr key={metric.stage}>
                    <th
                      scope="row"
                      className="atlas-mono py-3 text-xs font-medium text-[var(--foreground)]"
                    >
                      {metric.stage}
                    </th>
                    <td className="py-3 text-right text-xs tabular-nums text-[var(--muted)]">
                      {metric.count.toLocaleString()}
                    </td>
                    <td className="py-3 text-right text-xs tabular-nums text-[var(--foreground)]">
                      {formatMilliseconds(metric.p50_ms)}
                    </td>
                    <td className="py-3 text-right text-xs tabular-nums text-[var(--muted-strong)]">
                      {formatMilliseconds(metric.p95_ms)}
                    </td>
                    <td className="py-3 text-right text-xs tabular-nums text-[var(--muted)]">
                      {formatMilliseconds(metric.p99_ms)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Surface>
  );
}
