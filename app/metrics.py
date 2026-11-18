"""
Lightweight in-memory latency metrics store.
Tracks p50 / p95 / p99 for each named stage using a fixed-size
circular buffer (deque). Thread-safe via a single lock.
"""

import threading
import time
from collections import deque
from contextlib import contextmanager

import numpy as np

# Maximum number of durations to keep per stage.
# 500 covers ~8 hours at 1 req/min without unbounded memory growth.
_MAX_SAMPLES = 500
_lock = threading.Lock()
# Each key is a stage name (str), value is a deque of float durations (seconds).
_store: dict[str, deque] = {}


def record(stage:str, duration_s:float)->None:
    """Record one latency sample for the given stage."""
    with _lock:
        if stage not in _store:
            _store[stage] = deque(maxlen=_MAX_SAMPLES)
        _store[stage].append(duration_s)


@contextmanager
def timer(stage: str):
    """Time a block of work and record it under `stage`.

    The sample is recorded even if the block raises, so a failed stage still
    shows up in the percentiles instead of silently disappearing.
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        record(stage, time.perf_counter() - t0)


def get_percentiles(stage: str) -> dict:
    """
    Return p50 / p95 / p99 (in milliseconds) and sample count for a stage.
    Returns zeros if no data has been recorded yet.
    """
    with _lock:
        samples = list(_store.get(stage, []))
    if not samples:
        return {"stage": stage, "count": 0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}
    arr = np.array(samples) * 1000  # convert seconds → milliseconds
    p50, p95, p99 = np.percentile(arr, [50, 95, 99])
    return {
        "stage": stage,
        "count": len(samples),
        "p50_ms": round(float(p50), 2),
        "p95_ms": round(float(p95), 2),
        "p99_ms": round(float(p99), 2),
    }


# Canonical pipeline order, used to keep /metrics output stable across calls.
# Stages not listed here (added later) are appended alphabetically at the end.
STAGE_ORDER = [
    "router",
    "rewrite_query",
    "retrieve_kb",
    "grade_kb",
    "grade_kb_fast",
    "grade_kb_llm",
    "web_search",
    "grade_web",
    "generate_kb",
    "generate_web",
    "fallback",
    "direct",
    "chat_total",
    "chat_error",
]


def get_all_percentiles() -> list[dict]:
    """Return percentiles for every recorded stage, in a stable order."""
    with _lock:
        stages = list(_store.keys())
    ordered = [s for s in STAGE_ORDER if s in stages]
    ordered += sorted(s for s in stages if s not in STAGE_ORDER)
    return [get_percentiles(s) for s in ordered]


def reset() -> None:
    """Drop every recorded sample (used by tests and the /metrics/reset route)."""
    with _lock:
        _store.clear()
