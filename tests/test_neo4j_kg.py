"""Tests for neo4j_kg.py — KG-5 Neo4j fault query with local fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: build a mock neo4j record
# ---------------------------------------------------------------------------

def _mock_record(
    desc="Reactor cooling water step change",
    summary_md="## IDV_4\n...",
    evidence=None,
    symptoms=None,
    observed_by=None,
    affected_units=None,
    suggested_actions=None,
    actuators=None,
    constraints=None,
    risks=None,
):
    rec = MagicMock()
    rec.__getitem__ = lambda self, key: {
        "desc": desc,
        "summary_md": summary_md,
        "evidence": evidence or [
            {
                "chunk_id": "abc123_chunk_0001",
                "content_md": "## Section\nIDV(4) introduces a step change.",
                "heading": "## Fault Descriptions",
                "page": 12,
                "source_doc": "DOWNS.pdf",
                "section_type": "definition",
            }
        ],
        "symptoms": symptoms or ["High reactor temperature"],
        "observed_by": observed_by or ["xmeas_9"],
        "affected_units": affected_units or ["Reactor"],
        "suggested_actions": suggested_actions or ["Increase cooling water flow"],
        "actuators": actuators or ["xmv_6"],
        "constraints": constraints or ["Avoid separator flooding"],
        "risks": risks or ["Off-spec product"],
    }[key]
    return rec


def _mock_driver(record=None):
    """Build a mock neo4j driver that returns `record` from session.run().single()."""
    mock_session = MagicMock()
    mock_run = MagicMock()
    mock_run.single.return_value = record
    mock_session.run.return_value = mock_run
    mock_session.__enter__ = lambda s: mock_session
    mock_session.__exit__ = MagicMock(return_value=False)

    driver = MagicMock()
    driver.session.return_value = mock_session
    return driver


# ---------------------------------------------------------------------------
# query_fault_kg — happy path (Neo4j available + has data)
# ---------------------------------------------------------------------------

def test_query_fault_kg_enriched_result():
    """When Neo4j returns data, result should include summary_md and evidence."""
    from knowledge.neo4j_kg import query_fault_kg

    with patch("neo4j_kg._get_kg_driver", return_value=_mock_driver(_mock_record())):
        result = query_fault_kg(4)

    assert result["fault_id"] == 4
    assert result["fault_name"] == "IDV_4"
    assert "Reactor cooling water" in result["description"]
    assert result["summary_md"] == "## IDV_4\n..."
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["chunk_id"] == "abc123_chunk_0001"
    assert len(result["context_chunks"]) == 1
    assert result["graph_context"]["affected_units"] == ["Reactor"]
    assert result["graph_context"]["suggested_actions"] == ["Increase cooling water flow"]
    assert result["source"] == "Neo4j KG + PDF evidence"


def test_query_fault_kg_always_has_diagnostic_sensors():
    """diagnostic_sensors should always come from tep_knowledge (authoritative)."""
    from knowledge.neo4j_kg import query_fault_kg

    with patch("neo4j_kg._get_kg_driver", return_value=_mock_driver(_mock_record())):
        result = query_fault_kg(4)

    assert "diagnostic_sensors" in result
    assert len(result["diagnostic_sensors"]) > 0
    sensor_cols = [s["column"] for s in result["diagnostic_sensors"]]
    assert "xmeas_9" in sensor_cols  # IDV_4's primary sensor


def test_query_fault_kg_uses_neo4j_description_when_available():
    """description from Neo4j overrides local when Neo4j record is present."""
    from knowledge.neo4j_kg import query_fault_kg

    custom_desc = "Custom Neo4j description for IDV_4"
    with patch("neo4j_kg._get_kg_driver", return_value=_mock_driver(_mock_record(desc=custom_desc))):
        result = query_fault_kg(4)

    assert result["description"] == custom_desc


# ---------------------------------------------------------------------------
# Fallback cases
# ---------------------------------------------------------------------------

def test_query_fault_kg_fallback_on_no_env_vars():
    """When NEO4J_URI is not set, should return local fallback without crashing."""
    import os
    from knowledge.neo4j_kg import query_fault_kg

    with patch.dict(os.environ, {}, clear=False):
        # Ensure NEO4J_URI is not set
        env = {k: v for k, v in os.environ.items() if k != "NEO4J_URI"}
        env.pop("NEO4J_URI", None)
        with patch.dict(os.environ, env, clear=True):
            result = query_fault_kg(4)

    assert result["fault_id"] == 4
    assert "diagnostic_sensors" in result
    assert result.get("evidence", []) == []
    assert result.get("context_chunks", []) == []
    assert result["graph_context"]["suggested_actions"] == []


def test_query_fault_kg_fallback_on_driver_exception():
    """When neo4j driver raises (e.g. AuraDB paused), fallback to local data."""
    from knowledge.neo4j_kg import query_fault_kg

    def _broken_driver():
        raise ConnectionError("AuraDB paused")

    with patch("neo4j_kg._get_kg_driver", side_effect=_broken_driver):
        result = query_fault_kg(4)

    assert result["fault_id"] == 4
    assert result.get("evidence", []) == []
    assert result["source"] == "tep_knowledge (local fallback)"
    assert result["graph_context"]["risks"] == []


def test_query_fault_kg_fallback_on_query_exception():
    """When session.run() raises, fallback to local data."""
    from knowledge.neo4j_kg import query_fault_kg

    bad_driver = MagicMock()
    bad_session = MagicMock()
    bad_session.__enter__ = lambda s: bad_session
    bad_session.__exit__ = MagicMock(return_value=False)
    bad_session.run.side_effect = RuntimeError("Neo4j query failed")
    bad_driver.session.return_value = bad_session

    with patch("neo4j_kg._get_kg_driver", return_value=bad_driver):
        result = query_fault_kg(4)

    assert result["fault_id"] == 4
    assert result.get("evidence", []) == []


def test_query_fault_kg_fallback_on_no_record():
    """When Neo4j returns None (fault node not found), fallback to local data."""
    from knowledge.neo4j_kg import query_fault_kg

    with patch("neo4j_kg._get_kg_driver", return_value=_mock_driver(record=None)):
        result = query_fault_kg(4)

    assert result["fault_id"] == 4
    assert result.get("evidence", []) == []


# ---------------------------------------------------------------------------
# Invalid fault_id
# ---------------------------------------------------------------------------

def test_query_fault_kg_invalid_fault_id():
    """fault_id outside 0-20 should return error dict."""
    from knowledge.neo4j_kg import query_fault_kg

    with patch("neo4j_kg._get_kg_driver", return_value=_mock_driver(_mock_record())):
        result = query_fault_kg(99)

    assert "error" in result


# ---------------------------------------------------------------------------
# kg_query_fault tool output format (pure logic, no me_tools import)
# ---------------------------------------------------------------------------

def test_query_fault_kg_output_is_json_serialisable():
    """query_fault_kg result should be JSON-serialisable (no non-serialisable objects)."""
    import json
    from knowledge.neo4j_kg import query_fault_kg

    with patch("neo4j_kg._get_kg_driver", return_value=_mock_driver(_mock_record())):
        result = query_fault_kg(4)

    # Should not raise
    serialised = json.dumps(result, ensure_ascii=False)
    parsed = json.loads(serialised)
    assert parsed["fault_id"] == 4
    assert "diagnostic_sensors" in parsed
