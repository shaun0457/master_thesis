"""Tests for reverse fault lookup — match_fault_by_sensors (local + Neo4j paths)."""
from __future__ import annotations

import os
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")

import json
from unittest.mock import MagicMock, patch


def test_local_jaccard_ranks_exact_match_first():
    from tep_knowledge import match_fault_by_sensors_local

    # Fault 4/11/14 all share {xmeas_9, xmeas_7, xmv_6}
    out = match_fault_by_sensors_local(["xmeas_9", "xmeas_7", "xmv_6"], top_k=5)

    assert out, "expected at least one candidate"
    top = out[0]
    assert top["score"] == 1.0
    assert set(top["matched"]) == {"xmeas_9", "xmeas_7", "xmv_6"}
    # Fault 4 wins tie-break by lower fault_id
    assert top["fault_id"] == 4
    # Fault 13 has a partial match (xmeas_9, xmeas_7) — should appear with score < 1
    fids = [r["fault_id"] for r in out]
    assert 13 in fids


def test_local_empty_input_returns_empty():
    from tep_knowledge import match_fault_by_sensors_local
    assert match_fault_by_sensors_local([]) == []
    assert match_fault_by_sensors_local([], top_k=10) == []


def test_local_no_overlap_returns_empty():
    from tep_knowledge import match_fault_by_sensors_local
    # Sensor that no fault uses
    assert match_fault_by_sensors_local(["xmeas_999"]) == []


def test_local_top_k_limits_results():
    from tep_knowledge import match_fault_by_sensors_local
    # xmeas_9 alone matches faults 4, 11, 13, 14
    out = match_fault_by_sensors_local(["xmeas_9"], top_k=2)
    assert len(out) == 2


def _mock_driver(records):
    """Build a mock neo4j driver returning the given records from session.run()."""
    session = MagicMock()
    session.run.return_value = iter(records)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=session)
    cm.__exit__ = MagicMock(return_value=False)
    driver = MagicMock()
    driver.session.return_value = cm
    return driver


def _mock_record(fault_id, description, matched):
    rec = MagicMock()
    rec.__getitem__ = MagicMock(side_effect=lambda k: {
        "fault_id": fault_id,
        "description": description,
        "matched": matched,
        "hits": len(matched),
    }[k])
    return rec


def test_neo4j_path_returns_neo4j_source():
    from neo4j_kg import match_fault_by_sensors

    records = [
        _mock_record(4, "Reactor cooling water inlet temperature step", ["xmeas_9", "xmeas_7", "xmv_6"]),
    ]
    with patch("neo4j_kg._get_kg_driver", return_value=_mock_driver(records)):
        out = match_fault_by_sensors(["xmeas_9", "xmeas_7", "xmv_6"], top_k=3)

    assert out
    assert out[0]["source"] == "Neo4j KG"
    assert out[0]["fault_id"] == 4
    assert out[0]["score"] == 1.0


def test_neo4j_failure_falls_back_to_local():
    from neo4j_kg import match_fault_by_sensors

    with patch("neo4j_kg._get_kg_driver", side_effect=EnvironmentError("NEO4J_URI not set")):
        out = match_fault_by_sensors(["xmeas_9", "xmeas_7", "xmv_6"], top_k=3)

    assert out
    assert out[0]["source"].startswith("tep_knowledge")
    assert out[0]["fault_id"] == 4


def test_neo4j_empty_records_falls_back_to_local():
    from neo4j_kg import match_fault_by_sensors

    with patch("neo4j_kg._get_kg_driver", return_value=_mock_driver([])):
        out = match_fault_by_sensors(["xmeas_9"], top_k=3)

    assert out  # local fallback produces results
    assert all(r["source"].startswith("tep_knowledge") for r in out)


def test_me_tool_wrapper_returns_json():
    from me_tools import kg_match_fault_by_sensors

    with patch("neo4j_kg._get_kg_driver", side_effect=EnvironmentError("offline")):
        raw = kg_match_fault_by_sensors.invoke({"sensors": ["xmeas_9", "xmv_6"], "top_k": 2})

    parsed = json.loads(raw)
    assert isinstance(parsed, list)
    assert len(parsed) <= 2
    assert parsed[0]["fault_id"] in {4, 11, 13, 14}
