"""Run labelled retrieval evaluation against the existing CodeSage LangGraph.

Usage:
    python -m eval.retrieval_benchmark --repo CodeSage

The runner invokes the existing graph (and therefore its configured LLM and
Qdrant dependencies) but only scores the graph's returned kb_results. It does
not alter production routing, grading, or retrieval behavior.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent.graph import agent_graph
from app.agent.nodes import KB_TOP_K
from app.config import settings
from eval.retrieval_metrics import evaluate_example_retrieval

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path(__file__).with_name("dataset.jsonl")


def load_dataset(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata: dict[str, Any] = {}
    examples: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if "_meta" in record:
                if metadata:
                    raise ValueError("Dataset must contain at most one _meta record")
                metadata = record["_meta"]
            else:
                required = {"id", "question", "repo_name", "expected_route", "relevant_items"}
                missing = required - record.keys()
                if missing:
                    raise ValueError(
                        f"Dataset line {line_number} is missing fields: {sorted(missing)}"
                    )
                examples.append(record)
    if not examples:
        raise ValueError(f"No evaluation examples found in {path}")
    return metadata, examples


def _git_commit_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_benchmark(
    repo_override: str | None = None,
    dataset_path: Path = DEFAULT_DATASET,
    ks: tuple[int, ...] = (1, 3),
) -> dict[str, Any]:
    dataset_meta, examples = load_dataset(dataset_path)
    rows: list[dict[str, Any]] = []

    for example in examples:
        repo_name = repo_override or example["repo_name"]
        print(f"[{example['id']}] {example['question']}")
        output = agent_graph.invoke({
            "question": example["question"],
            "repo_name": repo_name,
        })
        retrieved = output.get("kb_results") or []
        actual_route = output.get("route") or output.get("source")
        scores = evaluate_example_retrieval(
            retrieved,
            example["relevant_items"],
            ks=ks,
        ) if example["expected_route"] == "kb" else {}

        rows.append({
            "id": example["id"],
            "question": example["question"],
            "repo_name": repo_name,
            "expected_route": example["expected_route"],
            "actual_route": actual_route,
            "route_correct": actual_route == example["expected_route"],
            "answerable": example.get("answerable"),
            "retrieved_count": len(retrieved),
            "retrieved_items": [
                {
                    "file_path": item.get("file_path"),
                    "function_name": item.get("function_name"),
                    "parent_symbol": item.get("parent_symbol"),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                }
                for item in retrieved
            ],
            "retrieval_metrics": scores,
        })

    kb_rows = [row for row in rows if row["expected_route"] == "kb"]
    summary: dict[str, Any] = {
        "examples": len(rows),
        "route_accuracy": (
            sum(row["route_correct"] for row in rows) / len(rows) if rows else 0.0
        ),
        "kb_examples": len(kb_rows),
    }
    for k in ks:
        key = f"@{k}"
        metric_rows = [
            row["retrieval_metrics"][key]
            for row in kb_rows
            if key in row["retrieval_metrics"]
        ]
        if metric_rows:
            summary[f"recall{key}"] = sum(m["recall_at_k"] for m in metric_rows) / len(metric_rows)
            summary[f"precision{key}"] = sum(m["precision_at_k"] for m in metric_rows) / len(metric_rows)
            summary[f"mrr{key}"] = sum(m["reciprocal_rank"] for m in metric_rows) / len(metric_rows)

    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repository": repo_override or dataset_meta.get("repository"),
            "git_commit_sha": _git_commit_sha(),
            "dataset_name": dataset_meta.get("dataset_name"),
            "dataset_version": dataset_meta.get("version"),
            "embedding_model": getattr(settings, "embed_model", None),
            "retrieval_top_k": KB_TOP_K,
            "evaluation_cutoffs": list(ks),
        },
        "summary": summary,
        "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CodeSage labelled retrieval quality.")
    parser.add_argument("--repo", default=None, help="Override repo_name for every dataset example.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON report path.")
    args = parser.parse_args()

    report = run_benchmark(repo_override=args.repo, dataset_path=args.dataset)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(f"\nSaved report: {args.out}")
    print("\n=== Retrieval Evaluation Summary ===")
    print(json.dumps(report["summary"], indent=2))
    print("Metadata:")
    print(json.dumps(report["metadata"], indent=2))


if __name__ == "__main__":
    main()
