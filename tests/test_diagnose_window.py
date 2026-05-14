"""Tests for POST /diagnose/window — pulls last N observations from buffer."""
from __future__ import annotations

import os
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import api_server

    buf = tmp_path / "buf.db"
    monkeypatch.setattr(api_server, "BUFFER_DB", str(buf))
    return TestClient(api_server.app)


def _seed_observations(api_client, source="simulator", n=10, true_fault=4):
    """Seed buffer via /observations endpoint."""
    rows = [{"xmeas_9": 100.0 + i, "xmeas_7": 50.0} for i in range(n)]
    r = api_client.post("/observations", json={
        "source": source,
        "true_fault_hidden": true_fault,
        "rows": rows,
        "sample_indices": list(range(1, n + 1)),
        "simulationruns": [1] * n,
    })
    assert r.status_code == 200


def test_window_returns_404_when_empty(api_client):
    r = api_client.post("/diagnose/window", json={"window_size": 50})
    assert r.status_code == 404


def test_window_calls_diagnose_with_last_n_rows(api_client):
    from diagnose_flow import DiagnosisResult

    _seed_observations(api_client, n=8)

    captured = {}

    def fake_diagnose(observation_path, true_fault, buffer_db,
                     recursion_limit, obs_ids):
        import pandas as pd
        df = pd.read_parquet(observation_path)
        captured["df"] = df
        captured["true_fault"] = true_fault
        captured["obs_ids"] = obs_ids
        return DiagnosisResult(
            run_id="diag_test", ts=1.0,
            observation_path=observation_path,
            predicted_fault=4, fault_name="IDV_4", confidence=1.0,
            evidence_sensors=["xmeas_9"], top_candidates=[],
            summary="window diagnosis", true_fault=true_fault,
            tool_events_count=2,
        )

    with patch("diagnose_flow.diagnose", side_effect=fake_diagnose):
        r = api_client.post("/diagnose/window", json={"window_size": 5})

    assert r.status_code == 200
    body = r.json()
    assert body["predicted_fault"] == 4
    assert len(captured["df"]) == 5
    assert len(captured["obs_ids"]) == 5
    # true_fault inferred from buffer majority
    assert captured["true_fault"] == 4


def test_window_source_filter(api_client):
    from diagnose_flow import DiagnosisResult

    _seed_observations(api_client, source="simulator", n=3, true_fault=4)
    _seed_observations(api_client, source="manual", n=2, true_fault=8)

    captured = {}

    def fake_diagnose(observation_path, true_fault, buffer_db,
                     recursion_limit, obs_ids):
        import pandas as pd
        captured["n"] = len(pd.read_parquet(observation_path))
        captured["true_fault"] = true_fault
        return DiagnosisResult(
            run_id="x", ts=0.0, observation_path=observation_path,
            predicted_fault=4, fault_name="IDV_4", confidence=1.0,
            evidence_sensors=[], top_candidates=[], summary="",
            true_fault=true_fault, tool_events_count=0,
        )

    with patch("diagnose_flow.diagnose", side_effect=fake_diagnose):
        r = api_client.post("/diagnose/window", json={
            "window_size": 10, "source": "manual",
        })

    assert r.status_code == 200
    assert captured["n"] == 2  # only manual rows
    assert captured["true_fault"] == 8


def test_window_request_validation_bounds(api_client):
    r = api_client.post("/diagnose/window", json={"window_size": 0})
    assert r.status_code == 422
    r = api_client.post("/diagnose/window", json={"window_size": 2000})
    assert r.status_code == 422


def test_window_explicit_true_fault_overrides_buffer(api_client):
    from diagnose_flow import DiagnosisResult

    _seed_observations(api_client, n=4, true_fault=4)

    captured = {}

    def fake_diagnose(observation_path, true_fault, **kw):
        captured["true_fault"] = true_fault
        return DiagnosisResult(
            run_id="x", ts=0.0, observation_path=observation_path,
            predicted_fault=None, fault_name=None, confidence=None,
            evidence_sensors=[], top_candidates=[], summary="",
            true_fault=true_fault, tool_events_count=0,
        )

    with patch("diagnose_flow.diagnose", side_effect=fake_diagnose):
        r = api_client.post("/diagnose/window", json={
            "window_size": 2, "true_fault": 11,
        })
    assert r.status_code == 200
    assert captured["true_fault"] == 11
