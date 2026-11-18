"""Tests for the latency metrics store and its instrumentation."""

import time

import pytest
from fastapi.testclient import TestClient

from app import metrics
from app.api import routes


@pytest.fixture(autouse=True)
def _clean_store():
    metrics.reset()
    yield
    metrics.reset()


def test_empty_stage_reports_zeros():
    p = metrics.get_percentiles("nothing_here")
    assert p == {
        "stage": "nothing_here",
        "count": 0,
        "p50_ms": 0.0,
        "p95_ms": 0.0,
        "p99_ms": 0.0,
    }


def test_record_converts_seconds_to_milliseconds():
    metrics.record("x", 1.5)
    assert metrics.get_percentiles("x")["p50_ms"] == 1500.0


def test_percentiles_match_numpy_on_known_values():
    for ms in (100, 200, 300, 400, 500):
        metrics.record("y", ms / 1000)
    p = metrics.get_percentiles("y")
    assert p["count"] == 5
    assert p["p50_ms"] == 300.0
    assert p["p95_ms"] == 480.0
    assert p["p99_ms"] == 496.0


def test_store_is_capped_at_max_samples():
    for i in range(metrics._MAX_SAMPLES + 100):
        metrics.record("z", 0.001)
    assert metrics.get_percentiles("z")["count"] == metrics._MAX_SAMPLES


def test_timer_records_elapsed_time():
    with metrics.timer("timed"):
        time.sleep(0.05)
    p = metrics.get_percentiles("timed")
    assert p["count"] == 1
    assert 45 <= p["p50_ms"] <= 500


def test_timer_records_even_when_block_raises():
    with pytest.raises(ValueError):
        with metrics.timer("failed"):
            raise ValueError("boom")
    assert metrics.get_percentiles("failed")["count"] == 1


def test_get_all_percentiles_uses_pipeline_order():
    for stage in ("direct", "chat_total", "router", "grade_kb"):
        metrics.record(stage, 0.01)
    names = [d["stage"] for d in metrics.get_all_percentiles()]
    assert names == ["router", "grade_kb", "direct", "chat_total"]


def test_unknown_stage_is_appended_after_known_ones():
    metrics.record("router", 0.01)
    metrics.record("brand_new_stage", 0.01)
    names = [d["stage"] for d in metrics.get_all_percentiles()]
    assert names == ["router", "brand_new_stage"]


def test_reset_clears_everything():
    metrics.record("a", 0.01)
    metrics.reset()
    assert metrics.get_all_percentiles() == []


def test_concurrent_record_and_read_is_safe():
    import threading

    def worker():
        for _ in range(200):
            metrics.record("concurrent", 0.001)
            metrics.get_percentiles("concurrent")

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert metrics.get_percentiles("concurrent")["count"] == metrics._MAX_SAMPLES



@pytest.fixture
def client():
    return TestClient(routes.app, raise_server_exceptions=False)


def test_chat_route_records_chat_total(client, monkeypatch):
    monkeypatch.setattr(
        routes.agent_graph,
        "invoke",
        lambda payload: {"answer": "ok", "source": "kb"},
    )
    resp = client.post("/chat", json={"question": "q", "repo_name": "r"})
    assert resp.status_code == 200
    assert metrics.get_percentiles("chat_total")["count"] == 1


def test_chat_debug_route_records_chat_total(client, monkeypatch):
    """The UIs call /chat/debug, so it must feed the same metric as /chat."""
    monkeypatch.setattr(
        routes.agent_graph,
        "invoke",
        lambda payload: {"answer": "ok", "source": "kb", "route": "kb"},
    )
    resp = client.post("/chat/debug", json={"question": "q", "repo_name": "r"})
    assert resp.status_code == 200
    assert metrics.get_percentiles("chat_total")["count"] == 1


def test_failed_chat_still_records_chat_total_and_error(client, monkeypatch):
    def boom(payload):
        raise RuntimeError("provider outage")

    monkeypatch.setattr(routes.agent_graph, "invoke", boom)
    resp = client.post("/chat", json={"question": "q", "repo_name": "r"})
    assert resp.status_code == 500
    assert metrics.get_percentiles("chat_total")["count"] == 1
    assert metrics.get_percentiles("chat_error")["count"] == 1


def test_metrics_endpoint_returns_all_stages(client):
    metrics.record("router", 0.01)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    names = [d["stage"] for d in resp.json()["latency"]]
    assert "router" in names


def test_metrics_reset_endpoint_clears_the_store(client):
    metrics.record("router", 0.01)
    resp = client.post("/metrics/reset")
    assert resp.status_code == 200
    assert metrics.get_all_percentiles() == []
