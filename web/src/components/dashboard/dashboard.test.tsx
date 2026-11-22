import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BackendStatus } from "./backend-status";
import { MetricsSection } from "./metrics-section";
import { RepositorySection } from "./repository-section";
import type { LatencyMetric, Repository } from "./dashboard-types";

describe("Dashboard components", () => {
  it("shows the connected backend status", () => {
    render(<BackendStatus state="connected" />);

    expect(screen.getByRole("status")).toHaveTextContent("Connected");
    expect(screen.getByText("FastAPI is responding")).toBeInTheDocument();
  });

  it("renders indexed repositories and invokes refresh", () => {
    const onRefresh = vi.fn();
    const repositories: Repository[] = [
      { repo_name: "owner/repo-a", points: 42 },
      { repo_name: "owner/repo-b", points: 18 },
    ];

    render(
      <RepositorySection
        result={{ status: "success", data: repositories }}
        loading={false}
        onRefresh={onRefresh}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Repositories" }),
    ).toBeInTheDocument();
    expect(screen.getByText("owner/repo-a")).toBeInTheDocument();
    expect(screen.getByText("42 stored points")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Refresh repositories" }),
    );

    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it("renders latency samples with formatted percentile values", () => {
    const metrics: LatencyMetric[] = [
      {
        stage: "retrieval",
        count: 10,
        p50_ms: 12.5,
        p95_ms: 20.25,
        p99_ms: 30.75,
      },
    ];

    render(
      <MetricsSection
        result={{ status: "success", data: metrics }}
        loading={false}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Latency metrics" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("retrieval")).toBeInTheDocument();
    expect(screen.getByText("12.5 ms")).toBeInTheDocument();
    expect(screen.getByText("20.25 ms")).toBeInTheDocument();
    expect(screen.getByText("30.75 ms")).toBeInTheDocument();
  });
});
