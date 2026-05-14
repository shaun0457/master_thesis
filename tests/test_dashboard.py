"""Tests for monitoring dashboard rendering + /dashboard endpoint."""
from __future__ import annotations

import os
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")

import sqlite3
from pathlib import Path

import pytest


def _seed_diagnoses(buf_path: str) -> None:
    from scripts.init_live_buffer import init as init_buffer

    init_buffer(buf_path)
    conn = sqlite3.connect(buf_path)
    try:
        # 2 correct, 1 wrong, 1 no truth
        items = [
            ("d1", 1.0, "[]", 4, 1.0,
             '{"sensors":["xmeas_9","xmeas_7"]}', "Predicted IDV_4.", 4),
            ("d2", 2.0, "[]", 8, 0.9,
             '{"sensors":["xmeas_23"]}', "Predicted IDV_8.", 8),
            ("d3", 3.0, "[]", 11, 0.7,
             '{"sensors":["xmeas_9"]}', "Predicted IDV_11.", 4),  # wrong
            ("d4", 4.0, "[]", 5, 0.6,
             '{"sensors":["xmeas_11"]}', "Predicted IDV_5.", None),
        ]
        for row in items:
            conn.execute(
                "INSERT INTO diagnoses (run_id, ts, obs_ids_json, predicted_fault, "
                "confidence, evidence_json, summary, true_fault_optional) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        # one observation row
        conn.execute(
            "INSERT INTO observations (ts, source, true_fault_hidden, payload_json) "
            "VALUES (?, ?, ?, ?)",
            (5.0, "test", 4, '{"xmeas_9": 120.0}'),
        )
        conn.commit()
    finally:
        conn.close()


def test_render_dashboard_shows_accuracy_and_counts(tmp_path):
    from monitoring.dashboard import render_dashboard

    buf = str(tmp_path / "buf.db")
    _seed_diagnoses(buf)
    html = render_dashboard(buf, limit=50)

    assert "TEP Diagnosis Monitor" in html
    assert "1" in html  # live obs count
    # 2 correct out of 3 with truth = 66.7%
    assert "66.7%" in html or "67%" in html
    assert "d1" in html and "d2" in html
    assert "xmeas_9" in html  # evidence sensors


def test_render_dashboard_handles_empty_buffer(tmp_path):
    from monitoring.dashboard import render_dashboard
    html = render_dashboard(str(tmp_path / "nonexistent.db"))
    assert "No live buffer" in html


def test_dashboard_endpoint_returns_html(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import api_server

    buf = str(tmp_path / "buf.db")
    _seed_diagnoses(buf)
    monkeypatch.setattr(api_server, "BUFFER_DB", buf)

    client = TestClient(api_server.app)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "TEP Diagnosis Monitor" in r.text


def test_phase_snippet_contains_diagnosis_rules():
    """Sanity check the Supervisor:diagnose snippet has the hard-rule lines."""
    from context_assembler import PHASE_SNIPPETS

    snippet = PHASE_SNIPPETS.get("Supervisor:diagnose", "")
    assert snippet, "Supervisor:diagnose snippet must exist"
    assert "faultnumber" in snippet.lower()
    assert "kg_match_fault_by_sensors" in snippet
    assert "obs_" in snippet
    assert "baseline_stats" in snippet


def test_diagnose_flow_sets_phase_to_diagnose(tmp_path):
    """diagnose_flow should set state['phase']='diagnose' so prompt snippet fires."""
    import pandas as pd
    from unittest.mock import MagicMock, patch
    from diagnose_flow import diagnose

    obs = tmp_path / "obs.parquet"
    pd.DataFrame({"xmeas_9": [120.0], "xmeas_7": [50.0]}).to_parquet(obs, index=False)

    captured_state = {}

    def _spy_invoke(state, config=None):
        captured_state.update(state)
        from langchain_core.messages import AIMessage
        return {
            **state,
            "messages": list(state.get("messages", [])) + [
                AIMessage(content="", tool_calls=[{
                    "name": "final_answer",
                    "args": {"answer": "IDV_4"}, "id": "x",
                }]),
            ],
        }

    graph = MagicMock()
    graph.invoke.side_effect = _spy_invoke

    with patch("supervisor_workflow.build_team_graph", return_value=graph):
        diagnose(str(obs), buffer_db=str(tmp_path / "b.db"))

    assert captured_state.get("phase") == "diagnose"
    assert captured_state.get("topic_ctx", {}).get("mode") == "diagnose"
