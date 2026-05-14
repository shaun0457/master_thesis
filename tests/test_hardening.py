"""Phase 6 hardening tests — weighted confidence, rate limit, stress."""
from __future__ import annotations

import os
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")

import concurrent.futures
import threading
from unittest.mock import patch

import pytest


# ----------------------- Confidence calibration ----------------------- #

def test_weighted_confidence_full_when_no_runner_up():
    from diagnose_flow import _weighted_confidence
    candidates = [
        {"fault_id": 4, "score": 1.0, "matched": ["xmeas_9"]},
    ]
    c = _weighted_confidence(candidates, predicted=4)
    # base=1.0, margin=1.0, conf = 1.0*(0.5+0.5*1.0) = 1.0
    assert c == 1.0


def test_weighted_confidence_drops_when_runner_up_close():
    from diagnose_flow import _weighted_confidence
    candidates = [
        {"fault_id": 4,  "score": 1.0, "matched": ["xmeas_9"]},
        {"fault_id": 11, "score": 0.9, "matched": ["xmeas_9"]},
    ]
    c = _weighted_confidence(candidates, predicted=4)
    # base=1.0, margin=0.1, conf = 1.0*(0.5+0.05) = 0.55
    assert abs(c - 0.55) < 1e-6


def test_weighted_confidence_handles_none_predicted():
    from diagnose_flow import _weighted_confidence
    assert _weighted_confidence([{"fault_id": 4, "score": 1.0}], predicted=None) is None


def test_weighted_confidence_handles_empty_candidates():
    from diagnose_flow import _weighted_confidence
    assert _weighted_confidence([], predicted=4) is None


def test_weighted_confidence_zero_base():
    from diagnose_flow import _weighted_confidence
    candidates = [{"fault_id": 4, "score": 0.0, "matched": []}]
    assert _weighted_confidence(candidates, predicted=4) == 0.0


# ----------------------- Rate limiting ----------------------- #

@pytest.fixture
def rate_limited_client(tmp_path, monkeypatch):
    """API client with rate limit enabled at 3 RPM for /observations."""
    from fastapi.testclient import TestClient
    import api_server

    buf = tmp_path / "buf.db"
    monkeypatch.setattr(api_server, "BUFFER_DB", str(buf))
    monkeypatch.setattr(api_server, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(api_server, "RATE_LIMIT_RPM", 3)
    monkeypatch.setattr(api_server, "RATE_LIMIT_PATHS", {"/diagnose"})
    # Clear any prior bucket state
    monkeypatch.setattr(api_server, "_rate_buckets", {})
    monkeypatch.setattr(api_server, "_buffer_initialised", set())
    return TestClient(api_server.app)


def test_rate_limit_blocks_after_threshold(rate_limited_client):
    # 3 allowed
    for i in range(3):
        r = rate_limited_client.post("/diagnose", json={
            "rows": [{"xmeas_9": 100.0 + i}],
        })
        # may 400 (validation) or 200 — we only care it's not 429
        assert r.status_code != 429

    # 4th hit on /diagnose: blocked
    r = rate_limited_client.post("/diagnose", json={
        "rows": [{"xmeas_9": 100.0}],
    })
    assert r.status_code == 429
    assert "rate limit" in r.json()["detail"]
    assert "retry_after_s" in r.json()


def test_rate_limit_does_not_affect_other_paths(rate_limited_client):
    # /diagnose limited; /observations is not
    for _ in range(6):
        r = rate_limited_client.post("/observations", json={
            "rows": [{"xmeas_9": 1.0}],
        })
        assert r.status_code == 200


def test_rate_limit_off_by_default(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import api_server

    buf = tmp_path / "buf.db"
    monkeypatch.setattr(api_server, "BUFFER_DB", str(buf))
    # default RATE_LIMIT_ENABLED is False; do many calls and confirm no 429
    monkeypatch.setattr(api_server, "_rate_buckets", {})
    monkeypatch.setattr(api_server, "_buffer_initialised", set())
    client = TestClient(api_server.app)
    for _ in range(50):
        r = client.post("/observations", json={"rows": [{"x": 1.0}]})
        assert r.status_code == 200


# ----------------------- Concurrent stress on buffer write path ----------------------- #

def test_concurrent_observation_ingest_thread_safe(tmp_path, monkeypatch):
    """50 concurrent POST /observations don't lose rows or deadlock."""
    from fastapi.testclient import TestClient
    import api_server

    buf = tmp_path / "buf.db"
    monkeypatch.setattr(api_server, "BUFFER_DB", str(buf))
    monkeypatch.setattr(api_server, "_rate_buckets", {})
    monkeypatch.setattr(api_server, "_buffer_initialised", set())
    client = TestClient(api_server.app)

    N = 50

    def _one(i):
        return client.post("/observations", json={
            "source": f"worker-{i}",
            "rows": [{"xmeas_9": float(i)}],
            "sample_indices": [i],
            "simulationruns": [1],
        })

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(_one, range(N)))

    assert all(r.status_code == 200 for r in results), \
        f"{sum(1 for r in results if r.status_code != 200)} failures"

    r = client.get("/observations?limit=200")
    assert r.json()["count"] == N
