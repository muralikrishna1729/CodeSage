# P1.2 — Labelled Retrieval Evaluation

This evaluation layer measures whether CodeSage retrieves source-code evidence
that human-labelled examples identify as relevant. It is separate from the
existing latency benchmark and LangSmith answer-quality experiment.

## What's included

- `dataset.jsonl`: versioned, manually labelled benchmark examples.
- `retrieval_metrics.py`: deterministic Recall@K, Precision@K, and MRR.
- `retrieval_benchmark.py`: runs the existing LangGraph and scores its
  returned `kb_results`.
- `tests/test_retrieval_metrics.py`: offline unit tests for metric behavior.

## Run the offline metric tests

From the repository root:

```bash
pytest -q tests/test_retrieval_metrics.py
```

These tests do not require Qdrant, embedding models, API keys, or an LLM.

## Run the end-to-end benchmark

Prerequisites:
- The target repository has already been ingested into the configured Qdrant
  collection.
- Qdrant is reachable.
- Required embedding models and agent LLM credentials are configured.
- The active Python environment has the project dependencies installed.

Run:

```bash
python -m eval.retrieval_benchmark --repo CodeSage
```

Optionally save a JSON report:

```bash
python -m eval.retrieval_benchmark --repo CodeSage --out eval/results/codesage-retrieval.json
```

The runner invokes the current LangGraph, so it includes the existing router and
query rewrite behavior. It records the actual route and returned retrieval
items, then calculates retrieval metrics for examples labelled with
`expected_route: "kb"`. It does not modify production code or thresholds.

## Metric definitions

For a cutoff K:

- **Recall@K** = number of labelled relevant items retrieved in the first K
  results / total labelled relevant items.
- **Precision@K** = number of labelled relevant items retrieved in the first K
  results / K. K remains the denominator if fewer than K results are returned.
- **MRR** = reciprocal rank of the first relevant retrieved item. The
  implementation reports per-example reciprocal rank; the benchmark summary
  averages those values.

A relevant item is matched by repository-relative `file_path` and, when
provided, exact `symbol` against the result's `function_name` or
`parent_symbol`. Paths are case-insensitive and Windows separators are
normalised. Duplicate retrieved chunks cannot satisfy the same labelled item
more than once.

## Interpretation and limitations

- Current Qdrant point IDs are random UUIDs, so this first version deliberately
  labels file paths and symbols rather than chunk IDs. No ingestion or Qdrant
  schema change is required.
- The dataset is an initial, small benchmark for CodeSage's own source tree.
  Labels should be reviewed against the target repository revision before
  treating scores as a regression gate.
- `REPO_MAP` is not a substitute for a labelled code chunk and should not be
  added as a relevant code item.
- Qdrant RRF scores are ranking scores, not calibrated probabilities.
- The end-to-end runner requires the existing agent and infrastructure. Only
  the metric unit tests are fully offline.
- This layer measures retrieval and route correctness. It does not yet score
  citation line-range correctness, evidence-grader accuracy, or answer
  factuality. Those are later evaluation layers.

## Reproducibility

Each JSON report records:
- UTC generation time
- Repository name
- Local Git commit SHA, when run from a Git checkout
- Dataset name and version
- Configured embedding model
- Production retrieval top-k
- Evaluation cutoffs

Increment the dataset version when changing labels or benchmark coverage.
