import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";
import type { LatencyMetric, Repository } from "@/components/dashboard/dashboard-types";

export type ChatSource = "kb" | "web" | "direct" | "fallback";
export type ChatRequest = { question: string; repo_name: string; history: { role: string; content: string }[] };
export type ChatResponse = { answer: string; source: ChatSource };
export type IngestResponse = { job_id: string; repo_name: string };
export type IngestStatus = { job_id: string; repo_name: string; status: "queued" | "running" | "done" | "error"; stage: string; elapsed_s: number; chunks_stored: number | null; error: string | null };

export const codesageApi = createApi({
  reducerPath: "codesageApi",
  baseQuery: fetchBaseQuery({ baseUrl: "/api/codesage/" }),
  tagTypes: ["Repositories", "Metrics", "Ingestion"],
  endpoints: (builder) => ({
    getRepositories: builder.query<Repository[], void>({ query: () => "repos", providesTags: ["Repositories"] }),
    getMetrics: builder.query<{ latency: LatencyMetric[] }, void>({ query: () => "metrics", providesTags: ["Metrics"] }),
    startIngestion: builder.mutation<IngestResponse, { repo_url: string; force?: boolean }>({ query: (body) => ({ url: "ingest", method: "POST", body }), invalidatesTags: ["Ingestion"] }),
    getIngestionStatus: builder.query<IngestStatus, string>({ query: (jobId) => `ingest/${encodeURIComponent(jobId)}`, providesTags: (_result, _error, jobId) => [{ type: "Ingestion", id: jobId }] }),
    chat: builder.mutation<ChatResponse, ChatRequest>({ query: (body) => ({ url: "chat", method: "POST", body }) }),
  }),
});

export const { useGetRepositoriesQuery, useGetMetricsQuery, useStartIngestionMutation, useGetIngestionStatusQuery, useChatMutation } = codesageApi;
