"""Unit tests for diagnose_flow — fault_id parsing, persistence, error paths.

Graph invocation is mocked so these tests do not require GOOGLE_API_KEY or Neo4j.
"""
from __future__ import annotations

import os
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def test_parse_fault_id_handles_common_formats():
    from diagnose_flow import _parse_fault_id

    assert _parse_fault_id("The predicted fault is IDV_4.") == 4
    assert _parse_fault_id("Conclusion: fault 11") == 11
    assert _parse_fault_id('{"idv_number": 8}') == 8
    assert _parse_fault_id("fault_id=14 sensors=...") == 14
    assert _parse_fault_id("idv-7 cooling water") == 7


def test_parse_fault_id_rejects_out_of_range_and_noise():
    from diagnose_flow import _parse_fault_id

    assert _parse_fault_id("") is None
    assert _parse_fault_id("no fault detected") is None
    assert _parse_fault_id("IDV_99 invalid") is None
    assert _parse_fault_id("xmeas_9 reading was 12.5") is None


def test_diagnose_missing_observation_returns_error():
    from diagnose_flow import diagnose

    result = diagnose("/nonexistent/path.parquet")
    assert result.error and "not found" in result.error
    assert result.predicted_fault is None
    assert result.run_id.startswith("diag_")


def _make_obs_parquet(tmp_path: Path, n: int = 5) -> str:
    df = pd.DataFrame({
        "sample": list(range(1, n + 1)),
        "xmeas_9": [120.5] * n,
        "xmeas_7": [50.1] * n,
        "xmv_6": [42.0] * n,
    })
    p = tmp_path / "obs.parquet"
    df.to_parquet(p, index=False)
    return str(p)


def _fake_graph_with_final_answer(answer_text: str, candidates: list[dict] | None = None):
    """Build a mock LangGraph returning a state with one AIMessage(final_answer) + events."""
    from langchain_core.messages import AIMessage

    def _invoke(state, config=None):
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "final_answer", "args": {"answer": answer_text}, "id": "x"}],
        )
        events = list(state.get("tool_events", []) or [])
        if candidates is not None:
            events.append({
                "tool": "kg_match_fault_by_sensors",
                "ok": True,
                "result": json.dumps(candidates),
            })
        out = dict(state)
        out["messages"] = list(state.get("messages", [])) + [msg]
        out["tool_events"] = events
        return out

    graph = MagicMock()
    graph.invoke.side_effect = _invoke
    return graph


def test_diagnose_persists_to_buffer_and_parses_fault(tmp_path):
    from diagnose_flow import diagnose
    from scripts.init_live_buffer import init as init_buffer

    obs_path = _make_obs_parquet(tmp_path)
    buf = str(tmp_path / "buf.db")
    init_buffer(buf)

    candidates = [
        {"fault_id": 4, "fault_name": "IDV_4",
         "description": "Reactor cooling water inlet temp step",
         "score": 1.0, "matched": ["xmeas_9", "xmeas_7", "xmv_6"],
         "source": "Neo4j KG"},
        {"fault_id": 11, "fault_name": "IDV_11",
         "description": "Reactor cooling water inlet random",
         "score": 1.0, "matched": ["xmeas_9", "xmeas_7", "xmv_6"],
         "source": "Neo4j KG"},
    ]
    answer = ("Diagnosis: most likely IDV_4. Evidence sensors are xmeas_9, "
              "xmeas_7, xmv_6 deviating from baseline.")

    with patch("supervisor_workflow.build_team_graph",
               return_value=_fake_graph_with_final_answer(answer, candidates)):
        result = diagnose(obs_path, true_fault=4, buffer_db=buf)

    assert result.error is None
    assert result.predicted_fault == 4
    assert result.fault_name == "IDV_4"
    # Two candidates tied at score=1.0 → weighted confidence = 1.0 * (0.5 + 0) = 0.5
    # (ambiguity between fault family siblings is reflected in confidence)
    assert result.confidence == 0.5
    assert "xmeas_9" in result.evidence_sensors
    assert len(result.top_candidates) == 2
    assert result.true_fault == 4
    assert result.tool_events_count >= 1

    # diagnoses table should have the row
    conn = sqlite3.connect(buf)
    try:
        row = conn.execute(
            "SELECT predicted_fault, true_fault_optional, confidence FROM diagnoses WHERE run_id=?",
            (result.run_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row == (4, 4, 0.5)


def test_diagnose_handles_graph_exception(tmp_path):
    from diagnose_flow import diagnose
    from scripts.init_live_buffer import init as init_buffer

    obs_path = _make_obs_parquet(tmp_path)
    buf = str(tmp_path / "buf.db")
    init_buffer(buf)

    bad_graph = MagicMock()
    bad_graph.invoke.side_effect = RuntimeError("boom")
    with patch("supervisor_workflow.build_team_graph", return_value=bad_graph):
        result = diagnose(obs_path, buffer_db=buf)

    assert result.error and "graph invoke failed" in result.error
    assert result.predicted_fault is None
