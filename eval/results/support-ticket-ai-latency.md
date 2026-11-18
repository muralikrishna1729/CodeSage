# Latency Benchmark - `support-ticket-ai`

- **Generated:** 2026-10-22T18:52:19+00:00
- **Backend:** `http://localhost:8010`
- **Requests:** 12
- **Endpoint:** `/chat/debug` (the endpoint the UIs use)

## Request wall-clock (client-side)

- Successful requests: **12 / 12**
- min **4,489.6 ms** | median **6,041.8 ms** | max **34,021.3 ms**

## Per-stage latency (server-side, from `/metrics`)

| Stage | Samples | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|---:|
| `router` | 12 | 885.19 | 987.86 | 1,033.37 |
| `rewrite_query` | 8 | 1,060.78 | 1,182.29 | 1,205.11 |
| `retrieve_kb` | 8 | 70.85 | 74.72 | 75.01 |
| `grade_kb` | 8 | 0.01 | 0.01 | 0.02 |
| `grade_kb_fast` | 8 | 0.01 | 0.01 | 0.01 |
| `web_search` | 2 | 1,134.51 | 1,190.19 | 1,195.14 |
| `grade_web` | 2 | 14,944.51 | 27,445.32 | 28,556.50 |
| `generate_kb` | 8 | 1,910.76 | 3,653.77 | 4,004.88 |
| `fallback` | 2 | 1,129.99 | 1,153.71 | 1,155.82 |
| `direct` | 2 | 1,652.79 | 1,726.93 | 1,733.52 |
| `chat_total` | 12 | 3,968.36 | 17,808.91 | 29,149.08 |

## Per-request detail

| # | Agent route | KB grade | Source | Wall (ms) | Status | Question |
|---:|---|---|---|---:|---:|---|
| 1 | kb | good | kb | 6,274.8 | 200 | How are support tickets categorised into categories? |
| 2 | kb | good | kb | 5,669.7 | 200 | What database models are defined for the ticket schema? |
| 3 | kb | good | kb | 8,253.4 | 200 | How does the prediction pipeline load and use the trained model? |
| 4 | web | None | fallback | 6,315.7 | 200 | Which AWS services are used for storage, email and queues? |
| 5 | kb | good | kb | 5,911.5 | 200 | How is the Streamlit app wired to the API routes? |
| 6 | direct | None | direct | 4,699.0 | 200 | What is the difference between a binary hash table and a binary tree? |
| 7 | kb | good | kb | 5,704.9 | 200 | How are support tickets categorised into categories? |
| 8 | kb | good | kb | 5,592.7 | 200 | What database models are defined for the ticket schema? |
| 9 | kb | good | kb | 6,799.6 | 200 | How does the prediction pipeline load and use the trained model? |
| 10 | web | None | fallback | 34,021.3 | 200 | Which AWS services are used for storage, email and queues? |
| 11 | kb | good | kb | 6,172.1 | 200 | How is the Streamlit app wired to the API routes? |
| 12 | direct | None | direct | 4,489.6 | 200 | What is the difference between a binary hash table and a binary tree? |

## Notes

- Embedding models are loaded in the FastAPI `lifespan` hook at startup, so model initialization is outside the request timers. This script does not restart the backend itself, so it cannot prove the server was freshly started for this run.
- 12 request(s) in this run. The per-stage sample counts above reflect only this run, because `/metrics/reset` was called first.

## How to read this

- Percentiles are computed by the backend over a rolling window of the last 500 samples per stage (`app/metrics.py`).
- The `Samples` column is the honest denominator. A p99 over a handful of samples is effectively the maximum, not a statistical percentile.
- `retrieve_kb` excludes model initialization: the backend warms the embedding models in its FastAPI `lifespan` hook at startup.
