"""Deterministic retrieval metrics for labelled CodeSage evaluation examples.

Relevant items are labelled by repository-relative file path and, optionally,
qualified symbol. This intentionally avoids Qdrant point IDs: the current
ingestion pipeline assigns random UUIDs to points.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _normalise_path(value: Any) -> str:
    """Normalise path separators and harmless leading ./ segments."""
    path = str(value or "").replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    return path.casefold()


def _normalise_symbol(value: Any) -> str:
    return str(value or "").strip().casefold()


def _matches(result: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    if _normalise_path(result.get("file_path")) != _normalise_path(expected.get("file_path")):
        return False

    expected_symbol = _normalise_symbol(expected.get("symbol"))
    if not expected_symbol:
        return True

    actual_symbols = {
        _normalise_symbol(result.get("function_name")),
        _normalise_symbol(result.get("parent_symbol")),
    }
    return expected_symbol in actual_symbols


def _relevant_ranked_indices(
    retrieved: list[Mapping[str, Any]],
    relevant_items: list[Mapping[str, Any]],
) -> list[int]:
    """Return 1-based ranks of the first retrieved match for each expected item."""
    ranks: list[int] = []
    for expected in relevant_items:
        for rank, result in enumerate(retrieved, start=1):
            if _matches(result, expected):
                ranks.append(rank)
                break
    return ranks


def retrieval_metrics(
    retrieved: Iterable[Mapping[str, Any]],
    relevant_items: Iterable[Mapping[str, Any]],
    k: int,
) -> dict[str, float | int]:
    """Calculate Recall@K, Precision@K, and Reciprocal Rank.

    Precision@K uses K as its denominator, even when fewer than K results are
    returned. Recall@K uses the number of labelled relevant items. Duplicate
    retrieved chunks can only satisfy a given labelled item once.
    """
    if k < 1:
        raise ValueError("k must be at least 1")

    results = list(retrieved)
    expected = list(relevant_items)
    if not expected:
        return {
            "recall_at_k": 0.0,
            "precision_at_k": 0.0,
            "reciprocal_rank": 0.0,
            "relevant_retrieved": 0,
            "relevant_total": 0,
        }

    ranks = _relevant_ranked_indices(results[:k], expected)
    # MRR is computed against the full retrieved ranking, not just the cutoff.
    all_ranks = _relevant_ranked_indices(results, expected)
    first_relevant_rank = min(all_ranks, default=None)
    relevant_retrieved = len(ranks)

    return {
        "recall_at_k": relevant_retrieved / len(expected),
        "precision_at_k": relevant_retrieved / k,
        "reciprocal_rank": 1.0 / first_relevant_rank if first_relevant_rank else 0.0,
        "relevant_retrieved": relevant_retrieved,
        "relevant_total": len(expected),
    }


def evaluate_example_retrieval(
    retrieved: Iterable[Mapping[str, Any]],
    relevant_items: Iterable[Mapping[str, Any]],
    ks: Iterable[int] = (1, 3),
) -> dict[str, dict[str, float | int]]:
    """Calculate retrieval metrics at multiple cutoffs."""
    results = list(retrieved)
    expected = list(relevant_items)
    return {f"@{k}": retrieval_metrics(results, expected, k) for k in ks}
