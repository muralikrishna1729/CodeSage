# Latency Benchmark - `KOT_AI`

- **Generated:** 2026-10-22T18:56:04+00:00
- **Backend:** `http://localhost:8010`
- **Requests:** 12
- **Endpoint:** `/chat/debug` (the endpoint the UIs use)

## Request wall-clock (client-side)

- Successful requests: **12 / 12**
- min **4,429.9 ms** | median **5,892.1 ms** | max **33,648.2 ms**

## Per-stage latency (server-side, from `/metrics`)

| Stage | Samples | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|---:|
| `router` | 12 | 911.30 | 1,304.78 | 1,476.85 |
| `rewrite_query` | 10 | 1,009.43 | 1,174.76 | 1,187.40 |
| `retrieve_kb` | 10 | 74.79 | 97.30 | 107.95 |
| `grade_kb` | 10 | 0.01 | 0.02 | 0.02 |
| `grade_kb_fast` | 10 | 0.01 | 0.01 | 0.01 |
| `generate_kb` | 10 | 1,965.58 | 17,260.58 | 26,939.33 |
| `direct` | 2 | 1,675.11 | 1,788.75 | 1,798.85 |
| `chat_total` | 12 | 3,850.12 | 16,663.70 | 28,618.92 |

## Per-request detail

| # | Agent route | KB grade | Source | Wall (ms) | Status | Question |
|---:|---|---|---|---:|---:|---|
| 1 | kb | good | kb | 6,348.0 | 200 | How does the agent decide whether to use the web? |
| 2 | kb | good | kb | 5,783.5 | 200 | What retrieval strategies are implemented? |
| 3 | kb | good | kb | 5,583.6 | 200 | How are documents chunked and embedded? |
| 4 | kb | good | kb | 5,313.8 | 200 | What models does the LLM client support? |
| 5 | kb | good | kb | 6,196.5 | 200 | How does the API expose chat and ingest endpoints? |
| 6 | direct | None | direct | 4,781.1 | 200 | Explain how a B-tree index works |
| 7 | kb | good | kb | 6,478.7 | 200 | How does the agent decide whether to use the web? |
| 8 | kb | good | kb | 33,648.2 | 200 | What retrieval strategies are implemented? |
| 9 | kb | good | kb | 5,545.2 | 200 | How are documents chunked and embedded? |
| 10 | kb | good | kb | 6,000.7 | 200 | What models does the LLM client support? |
| 11 | kb | good | kb | 6,416.0 | 200 | How does the API expose chat and ingest endpoints? |
| 12 | direct | None | direct | 4,429.9 | 200 | Explain how a B-tree index works |

## Notes

- Embedding models are loaded in the FastAPI `lifespan` hook at startup, so model initialization is outside the request timers. This script does not restart the backend itself, so it cannot prove the server was freshly started for this run.
- 12 request(s) in this run. The per-stage sample counts above reflect only this run, because `/metrics/reset` was called first.

## How to read this

- Percentiles are computed by the backend over a rolling window of the last 500 samples per stage (`app/metrics.py`).
- The `Samples` column is the honest denominator. A p99 over a handful of samples is effectively the maximum, not a statistical percentile.
- `retrieve_kb` excludes model initialization: the backend warms the embedding models in its FastAPI `lifespan` hook at startup.
