"""End-to-end integration: simulator → /observations → /diagnose/window → /dashboard.

The graph itself is mocked so the test runs deterministically without Gemini.
Validates: data flow through the entire pipeline, accuracy is computed,
sample-axis fields propagate, and the dashboard reflects the diagnosis.
"""
from __future__ import annotations

import os
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def api_with_seeded_buffer(tmp_path, monkeypatch):
    """FastAPI TestClient with an isolated live buffer."""
    from fastapi.testclient import TestClient
    import api_server

    buf = str(tmp_path / "buf.db")
    monkeypatch.setattr(api_server, "BUFFER_DB", buf)
    return TestClient(api_server.app), buf


def _fake_diagnose_result(predicted=4, true_fault=4, run_id_suffix=""):
    from simulation.diagnose_flow import DiagnosisResult
    import uuid
    return DiagnosisResult(
        run_id=f"diag_e2e_{predicted}_{run_id_suffix or uuid.uuid4().hex[:6]}",
        ts=1.0,
        observation_path="/tmp/x.parquet",
        predicted_fault=predicted,
        fault_name=f"IDV_{predicted}",
        confidence=1.0,
        evidence_sensors=["xmeas_9", "xmeas_7", "xmv_6"],
        top_candidates=[{
            "fault_id": predicted, "fault_name": f"IDV_{predicted}",
            "description": "reactor cooling water",
            "score": 1.0,
            "matched": ["xmeas_9", "xmeas_7", "xmv_6"],
            "source": "Neo4j KG",
        }],
        summary=f"Predicted IDV_{predicted} from cooling water signature.",
        true_fault=true_fault,
        tool_events_count=4,
    )


def _persist_via_real_helper(result, buffer_db: str, obs_ids):
    """Use the real _persist_diagnosis from diagnose_flow."""
    from simulation.diagnose_flow import _persist_diagnosis
    _persist_diagnosis(buffer_db, result, obs_ids=obs_ids)


def _make_mock_diagnose(buffer_db: str, predicted: int, true_fault: int):
    """Side-effect that persists via the real helper so /diagnoses sees the row."""
    def _side(observation_path, true_fault=None, buffer_db=buffer_db,
              recursion_limit=60, obs_ids=None):
        result = _fake_diagnose_result(predicted=predicted, true_fault=true_fault)
        _persist_via_real_helper(result, buffer_db, obs_ids or [])
        return result
    return _side


def test_e2e_simulator_to_dashboard(api_with_seeded_buffer):
    """Simulate three batches → diagnose window → confirm dashboard accuracy."""
    client, buf = api_with_seeded_buffer

    # Step 1: ingest 3 batches of observations (simulating stream_simulator)
    for i, (sample_offset, fault) in enumerate([(1, 4), (10, 4), (20, 4)]):
        rows = [{"xmeas_9": 120.0 + j, "xmeas_7": 50.0 + j * 0.1}
                for j in range(5)]
        r = client.post("/observations", json={
            "source": "simulator",
            "true_fault_hidden": fault,
            "rows": rows,
            "sample_indices": list(range(sample_offset, sample_offset + 5)),
            "simulationruns": [1] * 5,
        })
        assert r.status_code == 200

    # Step 2: confirm buffer has the rows with sample_idx persisted
    r = client.get("/observations?limit=20")
    items = r.json()["items"]
    assert len(items) == 15
    # observations endpoint returns latest first; ensure sample_idx propagated
    # (it's stored in DB but not returned by the current endpoint shape — verify in DB)
    conn = sqlite3.connect(buf)
    try:
        sample_idxs = [r[0] for r in conn.execute(
            "SELECT sample_idx FROM observations ORDER BY obs_id"
        ).fetchall()]
    finally:
        conn.close()
    assert sample_idxs == list(range(1, 6)) + list(range(10, 15)) + list(range(20, 25))

    # Step 3: run window diagnosis with mocked graph (persists via real helper)
    with patch("diagnose_flow.diagnose", side_effect=_make_mock_diagnose(buf, 4, 4)):
        r = client.post("/diagnose/window", json={"window_size": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["predicted_fault"] == 4
    assert body["true_fault"] == 4
    assert "xmeas_9" in body["evidence_sensors"]

    # Step 4: GET /diagnoses computes accuracy
    r = client.get("/diagnoses?limit=10")
    diag_body = r.json()
    assert diag_body["count"] == 1
    assert diag_body["accuracy"] == 1.0  # 1/1 correct

    # Step 5: /dashboard renders with accuracy + observation count
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "TEP Diagnosis Monitor" in r.text
    assert "100" in r.text  # 100% accuracy badge
    assert "15" in r.text   # 15 observations


def test_e2e_wrong_prediction_drops_accuracy(api_with_seeded_buffer):
    """Simulate one correct + one wrong → accuracy = 50%."""
    client, buf = api_with_seeded_buffer

    # Correct: true=4, predicted=4
    client.post("/observations", json={
        "source": "sim", "true_fault_hidden": 4,
        "rows": [{"xmeas_9": 120.0}],
        "sample_indices": [1], "simulationruns": [1],
    })
    with patch("diagnose_flow.diagnose", side_effect=_make_mock_diagnose(buf, 4, 4)):
        client.post("/diagnose/window", json={"window_size": 1})

    # Wrong: true=8, predicted=4 (cross-family)
    client.post("/observations", json={
        "source": "sim", "true_fault_hidden": 8,
        "rows": [{"xmeas_23": 0.5}],
        "sample_indices": [2], "simulationruns": [2],
    })
    with patch("diagnose_flow.diagnose", side_effect=_make_mock_diagnose(buf, 4, 8)):
        client.post("/diagnose/window", json={"window_size": 1, "source": "sim"})

    r = client.get("/diagnoses?limit=10")
    body = r.json()
    assert body["count"] == 2
    assert abs(body["accuracy"] - 0.5) < 1e-6


def test_e2e_health_reports_baseline_present(api_with_seeded_buffer):
    """/health should report baseline_present=True since the parquet is committed."""
    client, _ = api_with_seeded_buffer
    r = client.get("/health")
    body = r.json()
    assert body["sqlite_ok"] is True
    assert body["baseline_present"] is True
    assert body["gemini_key_present"] is True
