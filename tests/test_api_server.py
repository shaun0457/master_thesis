"""API server endpoint tests — uses FastAPI TestClient with mocked diagnose_flow."""
from __future__ import annotations

import os
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")

import sqlite3
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


def test_index_lists_endpoints(api_client):
    r = api_client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert "POST /diagnose" in body["endpoints"]


def test_health_reports_components(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "sqlite_ok" in body
    assert "gemini_key_present" in body


def test_observations_ingest_and_list(api_client):
    payload = {
        "source": "test",
        "true_fault_hidden": 4,
        "rows": [{"xmeas_9": 120.0, "xmeas_7": 50.0}, {"xmeas_9": 121.0, "xmeas_7": 50.5}],
    }
    r = api_client.post("/observations", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["inserted"] == 2
    assert len(body["obs_ids"]) == 2

    r2 = api_client.get("/observations?limit=10")
    assert r2.status_code == 200
    items = r2.json()["items"]
    assert len(items) == 2
    assert items[0]["true_fault_hidden"] == 4


def test_observations_rejects_empty(api_client):
    r = api_client.post("/observations", json={"rows": []})
    assert r.status_code == 400


def test_diagnose_requires_path_or_rows(api_client):
    r = api_client.post("/diagnose", json={})
    assert r.status_code == 400


def test_diagnose_with_inline_rows_calls_orchestrator(api_client, tmp_path):
    from diagnose_flow import DiagnosisResult

    fake_result = DiagnosisResult(
        run_id="diag_abc",
        ts=1234.0,
        observation_path="/tmp/x.parquet",
        predicted_fault=4,
        fault_name="IDV_4",
        confidence=1.0,
        evidence_sensors=["xmeas_9", "xmeas_7", "xmv_6"],
        top_candidates=[{"fault_id": 4, "score": 1.0, "matched": ["xmeas_9"]}],
        summary="Predicted IDV_4 from cooling water signature.",
        true_fault=4,
        tool_events_count=3,
    )

    with patch("diagnose_flow.diagnose", return_value=fake_result):
        r = api_client.post("/diagnose", json={
            "rows": [{"xmeas_9": 120.0, "xmeas_7": 50.0}],
            "true_fault": 4,
        })

    assert r.status_code == 200
    body = r.json()
    assert body["predicted_fault"] == 4
    assert body["fault_name"] == "IDV_4"
    assert body["confidence"] == 1.0
    assert "xmeas_9" in body["evidence_sensors"]


def test_list_diagnoses_computes_accuracy(api_client, tmp_path, monkeypatch):
    import api_server

    api_server._ensure_buffer()
    conn = sqlite3.connect(api_server.BUFFER_DB)
    try:
        for run_id, pred, truth in [
            ("d1", 4, 4),  # correct
            ("d2", 11, 4),  # wrong (same family, but different ID)
            ("d3", 8, 8),  # correct
            ("d4", None, None),  # no truth
        ]:
            conn.execute(
                "INSERT INTO diagnoses (run_id, ts, obs_ids_json, predicted_fault, "
                "confidence, evidence_json, summary, true_fault_optional) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, 1.0, "[]", pred, 0.9, "{}", "", truth),
            )
        conn.commit()
    finally:
        conn.close()

    r = api_client.get("/diagnoses?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 4
    # 2 correct out of 3 with truth = 0.667
    assert body["accuracy"] is not None
    assert abs(body["accuracy"] - (2 / 3)) < 1e-6
