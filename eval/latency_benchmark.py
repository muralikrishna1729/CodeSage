"""
Latency Benchmark Suite for the Codebase RAG Agent (CodeSage).

Drives a set of questions against a running backend, pulls the live latency
metrics from ``GET /metrics``, and writes a Markdown + JSON report to
``eval/results/``.

The point is to produce a *repeatable* measurement artifact rather than
eyeballing ``/metrics`` in a browser: every run records the repo, the
question set, the per-stage percentiles, and the sample count behind each
percentile (so thin samples are obvious instead of silently misleading).

Usage:
  python -m eval.latency_benchmark --repo support-ticket-ai
  python -m eval.latency_benchmark --repo KOT_AI --repeat 3
  python -m eval.latency_benchmark --repo support-ticket-ai --out mysummary

Prerequisites:
  - Backend running (default http://localhost:8010) with the target repo
    already ingested (see POST /ingest).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DEFAULT_BASE_URL = os.environ.get("BENCH_BASE_URL", "http://localhost:8010")
RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Question sets per repo. Each repo gets questions that should hit the
# knowledge base, plus a couple that are deliberately out-of-scope so the
# web-search and fallback branches get exercised too.
QUESTION_SETS: dict[str, list[str]] = {
    "support-ticket-ai": [
        "How are support tickets categorised into categories?",
        "What database models are defined for the ticket schema?",
        "How does the prediction pipeline load and use the trained model?",
        "Which AWS services are used for storage, email and queues?",
        "How is the Streamlit app wired to the API routes?",
        "What is the difference between a binary hash table and a binary tree?",
    ],
    "KOT_AI": [
        "How does the agent decide whether to use the web?",
        "What retrieval strategies are implemented?",
        "How are documents chunked and embedded?",
        "What models does the LLM client support?",
        "How does the API expose chat and ingest endpoints?",
        "Explain how a B-tree index works",
    ],
}


def default_questions(repo: str) -> list[str]:
    """Questions for `repo`, falling back to a generic set for unknown repos."""
    if repo in QUESTION_SETS:
        return list(QUESTION_SETS[repo])
    return [
        "How is this project structured?",
        "What are the main modules and their responsibilities?",
        "How are errors handled?",
        "How does the API layer work?",
    ]


def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}"


def wait_for_backend(base_url: str, timeout_s: float = 120.0) -> bool:
    """Block until the backend answers /metrics, or time out."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            requests.get(f"{base_url}/metrics", timeout=5).raise_for_status()
            return True
        except Exception:
            time.sleep(2)
    return False



def run_questions(
    base_url: str,
    repo: str,
    questions: list[str],
    timeout_s: float = 300.0,
    route: str = "/chat/debug",
) -> list[dict]:
    """Send each question to the backend and record the observed wall time."""
    results = []
    for question in questions:
        payload = {"question": question, "repo_name": repo}
        t0 = time.perf_counter()
        entry: dict = {"question": question, "endpoint": route}
        try:
            resp = requests.post(f"{base_url}{route}", json=payload, timeout=timeout_s)
            entry["status"] = resp.status_code
            entry["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            if resp.status_code == 200:
                body = resp.json()
                entry["agent_route"] = body.get("route")
                entry["kb_grade"] = body.get("kb_grade")
                entry["web_grade"] = body.get("web_grade")
                entry["source"] = body.get("source")
            else:
                entry["error"] = resp.text[:300]
        except Exception as exc:  # noqa: BLE001 - a failed request is data, not a crash
            entry["status"] = 0
            entry["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
        results.append(entry)
        print(
            f"  [{entry['status']:>3}] {entry['elapsed_ms']:>9.1f} ms  "
            f"{str(entry.get('agent_route', '-')):<8} {question[:60]}"
        )
    return results


def fetch_metrics(base_url: str) -> list[dict]:
    """Pull the current per-stage percentiles from the backend."""
    resp = requests.get(f"{base_url}/metrics", timeout=30)
    resp.raise_for_status()
    return resp.json().get("latency", []) or []


def build_report(
    repo: str,
    base_url: str,
    question_results: list[dict],
    latency: list[dict],
    notes: list[str],
) -> str:
    """Render the Markdown report."""
    lines: list[str] = []
    lines.append(f"# Latency Benchmark - `{repo}`")
    lines.append("")
    lines.append(f"- **Generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"- **Backend:** `{base_url}`")
    lines.append(f"- **Requests:** {len(question_results)}")
    lines.append("- **Endpoint:** `/chat/debug` (the endpoint the UIs use)")
    lines.append("")

    ok = [r for r in question_results if r.get("status") == 200]
    failed = [r for r in question_results if r.get("status") != 200]
    wall = [r["elapsed_ms"] for r in ok]

    lines.append("## Request wall-clock (client-side)")
    lines.append("")
    lines.append(f"- Successful requests: **{len(ok)} / {len(question_results)}**")
    if failed:
        lines.append(f"- Failed requests: **{len(failed)}**")
    if wall:
        lines.append(
            f"- min **{_fmt(min(wall))} ms** | median **{_fmt(statistics.median(wall))} ms** | "
            f"max **{_fmt(max(wall))} ms**"
        )
    lines.append("")

    lines.append("## Per-stage latency (server-side, from `/metrics`)")
    lines.append("")
    lines.append("| Stage | Samples | p50 (ms) | p95 (ms) | p99 (ms) |")
    lines.append("|---|---:|---:|---:|---:|")
    for row in latency:
        lines.append(
            f"| `{row['stage']}` | {row['count']} | "
            f"{_fmt(row['p50_ms'], 2)} | {_fmt(row['p95_ms'], 2)} | {_fmt(row['p99_ms'], 2)} |"
        )
    lines.append("")

    lines.append("## Per-request detail")
    lines.append("")
    lines.append("| # | Agent route | KB grade | Source | Wall (ms) | Status | Question |")
    lines.append("|---:|---|---|---|---:|---:|---|")
    for i, r in enumerate(question_results, 1):
        question = r["question"].replace("|", "\\|")
        lines.append(
            f"| {i} | {r.get('agent_route', '-')} | {r.get('kb_grade', '-')} | "
            f"{r.get('source', '-')} | {_fmt(r['elapsed_ms'])} | {r.get('status')} | {question} |"
        )
    lines.append("")

    if notes:
        lines.append("## Notes")
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("## How to read this")
    lines.append("")
    lines.append(
        "- Percentiles are computed by the backend over a rolling window of the "
        "last 500 samples per stage (`app/metrics.py`)."
    )
    lines.append(
        "- The `Samples` column is the honest denominator. A p99 over a handful "
        "of samples is effectively the maximum, not a statistical percentile."
    )
    lines.append(
        "- `retrieve_kb` excludes model initialization: the backend warms the "
        "embedding models in its FastAPI `lifespan` hook at startup."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Latency benchmark for the Codebase RAG Agent.")
    parser.add_argument("--repo", required=True, help="Repo name already ingested into Qdrant.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend base URL.")
    parser.add_argument("--repeat", type=int, default=1, help="How many times to repeat the question set.")
    parser.add_argument("--route", default="/chat/debug", help="Endpoint to drive.")
    parser.add_argument("--timeout", type=float, default=300.0, help="Per-request timeout in seconds.")
    parser.add_argument("--out", default=None, help="Output stem (default: auto from repo + timestamp).")
    parser.add_argument("--no-reset", action="store_true", help="Do not reset metrics before the run.")
    parser.add_argument(
        "--question",
        action="append",
        default=None,
        help="Custom question (repeatable). Overrides the built-in set for the repo.",
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    print(f"Waiting for backend at {base_url} ...")
    if not wait_for_backend(base_url):
        print(f"ERROR: backend at {base_url} did not respond. Is it running?", file=sys.stderr)
        return 1
    print("Backend is up.")

    questions = args.question if args.question else default_questions(args.repo)

    if not args.no_reset:
        requests.post(f"{base_url}/metrics/reset", timeout=30)
        print("Metrics reset.")

    all_results: list[dict] = []
    for rep in range(1, args.repeat + 1):
        print(f"\n--- Pass {rep}/{args.repeat} ({len(questions)} questions) ---")
        all_results.extend(run_questions(base_url, args.repo, questions, args.timeout, args.route))

    latency = fetch_metrics(base_url)

    notes = [
        "Embedding models are loaded in the FastAPI `lifespan` hook at startup, so "
        "model initialization is outside the request timers. This script does not "
        "restart the backend itself, so it cannot prove the server was freshly "
        "started for this run.",
        f"{len(all_results)} request(s) in this run. The per-stage sample counts above reflect only "
        "this run, because `/metrics/reset` was called first.",
    ]

    stem = args.out or f"{args.repo}-latency-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = RESULTS_DIR / f"{stem}.md"
    json_path = RESULTS_DIR / f"{stem}.json"

    report = build_report(args.repo, base_url, all_results, latency, notes)
    md_path.write_text(report, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "repo": args.repo,
                "base_url": base_url,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "questions": questions,
                "requests": all_results,
                "latency": latency,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\nMarkdown: {md_path}")
    print(f"JSON:     {json_path}")
    print("\nPer-stage latency:")
    for row in latency:
        print(
            f"  {row['stage']:<16} n={row['count']:<4} "
            f"p50={_fmt(row['p50_ms'], 2):>10}  p95={_fmt(row['p95_ms'], 2):>10}  "
            f"p99={_fmt(row['p99_ms'], 2):>10}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
