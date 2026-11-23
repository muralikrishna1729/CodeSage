import pytest

from eval.retrieval_metrics import evaluate_example_retrieval, retrieval_metrics


def test_perfect_retrieval_scores():
    retrieved = [
        {"file_path": "app/a.py", "function_name": "alpha"},
        {"file_path": "app/b.py", "function_name": "beta"},
    ]
    expected = [
        {"file_path": "app/a.py", "symbol": "alpha"},
        {"file_path": "app/b.py", "symbol": "beta"},
    ]

    result = retrieval_metrics(retrieved, expected, k=2)

    assert result["recall_at_k"] == 1.0
    assert result["precision_at_k"] == 1.0
    assert result["reciprocal_rank"] == 1.0


def test_recall_precision_and_mrr_for_partial_retrieval():
    retrieved = [
        {"file_path": "noise.py", "function_name": "noise"},
        {"file_path": "app/a.py", "function_name": "alpha"},
        {"file_path": "app/c.py", "function_name": "gamma"},
    ]
    expected = [
        {"file_path": "app/a.py", "symbol": "alpha"},
        {"file_path": "app/b.py", "symbol": "beta"},
    ]

    result = retrieval_metrics(retrieved, expected, k=3)

    assert result["recall_at_k"] == 0.5
    assert result["precision_at_k"] == pytest.approx(1 / 3)
    assert result["reciprocal_rank"] == 0.5


def test_path_separator_and_case_are_normalised():
    retrieved = [{"file_path": r".\app\A.py", "function_name": "Alpha"}]
    expected = [{"file_path": "app/a.py", "symbol": "alpha"}]

    result = retrieval_metrics(retrieved, expected, k=1)

    assert result["recall_at_k"] == 1.0


def test_symbol_must_match_when_labelled():
    retrieved = [{"file_path": "app/a.py", "function_name": "different"}]
    expected = [{"file_path": "app/a.py", "symbol": "alpha"}]

    result = retrieval_metrics(retrieved, expected, k=1)

    assert result["recall_at_k"] == 0.0
    assert result["reciprocal_rank"] == 0.0


def test_parent_symbol_can_match_expected_symbol():
    retrieved = [{"file_path": "app/a.py", "function_name": "method", "parent_symbol": "Container"}]
    expected = [{"file_path": "app/a.py", "symbol": "Container"}]

    assert retrieval_metrics(retrieved, expected, k=1)["recall_at_k"] == 1.0


def test_duplicate_retrievals_do_not_inflate_recall():
    retrieved = [
        {"file_path": "app/a.py", "function_name": "alpha"},
        {"file_path": "app/a.py", "function_name": "alpha"},
    ]
    expected = [{"file_path": "app/a.py", "symbol": "alpha"}]

    result = retrieval_metrics(retrieved, expected, k=2)

    assert result["recall_at_k"] == 1.0
    assert result["precision_at_k"] == 0.5


def test_empty_relevance_labels_return_zero_metrics():
    result = retrieval_metrics([{"file_path": "a.py"}], [], k=3)

    assert result["recall_at_k"] == 0.0
    assert result["precision_at_k"] == 0.0
    assert result["reciprocal_rank"] == 0.0


def test_invalid_k_is_rejected():
    with pytest.raises(ValueError):
        retrieval_metrics([], [], k=0)


def test_multiple_cutoffs():
    retrieved = [
        {"file_path": "noise.py", "function_name": "noise"},
        {"file_path": "app/a.py", "function_name": "alpha"},
    ]
    expected = [{"file_path": "app/a.py", "symbol": "alpha"}]

    result = evaluate_example_retrieval(retrieved, expected, ks=(1, 2))

    assert result["@1"]["recall_at_k"] == 0.0
    assert result["@2"]["recall_at_k"] == 1.0
