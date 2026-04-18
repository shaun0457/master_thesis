# tests/test_event_writer.py
"""Tests for mas/logging/event_writer.py."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mas.blackboard.store import BlackboardStore
from mas.logging import event_writer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path, run_id: str = "test-run") -> BlackboardStore:
    return BlackboardStore(root=tmp_path / "bb", run_id=run_id)


def _event_file(base: Path, run_id: str, name: str) -> Path:
    """Return path that event_writer writes to (relative to project root)."""
    project_root = Path(__file__).parents[1]
    return project_root / "data" / "runs" / run_id / name


def _minimal_turn(run_id="test-run") -> dict:
    return {
        "schema":     "run.turn.v2",
        "run_id":     run_id,
        "turn_index": 0,
        "role":       "supervisor",
        "message":    "hello",
        "intent":     "delegate",
        "action":     {"target": "de"},
        "ts":         "2024-11-15T14:30:22Z",
    }


def _minimal_router(run_id="test-run") -> dict:
    return {
        "schema":     "router.event.v2",
        "run_id":     run_id,
        "turn_index": 0,
        "sender":     "supervisor",
        "status":     "ok",
        "violations": [],
        "next_owner": "de",
        "ts":         "2024-11-15T14:30:22Z",
    }


def _minimal_write(run_id="test-run") -> dict:
    return {
        "schema":        "bb.write.v1",
        "run_id":        run_id,
        "write_id":      "w1",
        "turn_index":    1,
        "writer_role":   "de",
        "topic_id":      "analysis",
        "artifact":      "bb://analysis/x.json",
        "artifact_kind": "json",
        "ts":            "2024-11-15T14:30:22Z",
    }


def _minimal_read(run_id="test-run") -> dict:
    return {
        "schema":        "run.read.v1",
        "run_id":        run_id,
        "read_id":       "r1",
        "turn_index":    2,
        "reader_role":   "ds",
        "artifact":      "bb://analysis/x.json",
        "artifact_kind": "json",
        "write_ref":     {"event_id": "w1", "turn_index": 1, "writer_role": "de"},
        "ts":            "2024-11-15T14:30:22Z",
    }


# ---------------------------------------------------------------------------
# _runs_dir helper
# ---------------------------------------------------------------------------

class TestRunsDir:
    def test_returns_correct_path(self, tmp_path):
        store = _make_store(tmp_path, "my-run")
        result = event_writer._runs_dir(store)
        project_root = Path(__file__).parents[1]
        assert result == project_root / "data" / "runs" / "my-run"

    def test_different_run_ids_give_different_paths(self, tmp_path):
        s1 = _make_store(tmp_path, "run-a")
        s2 = _make_store(tmp_path, "run-b")
        assert event_writer._runs_dir(s1) != event_writer._runs_dir(s2)


# ---------------------------------------------------------------------------
# Schema cache
# ---------------------------------------------------------------------------

class TestSchemaCache:
    def setup_method(self):
        event_writer._SCHEMA_CACHE.clear()

    def test_cache_populated_after_first_validate(self):
        event_writer.validate_against_schema(_minimal_turn(), "run.turn.v2")
        assert "run.turn.v2" in event_writer._SCHEMA_CACHE

    def test_cache_reused_on_second_call(self):
        event_writer.validate_against_schema(_minimal_turn(), "run.turn.v2")
        schema_ref = event_writer._SCHEMA_CACHE["run.turn.v2"]
        event_writer.validate_against_schema(_minimal_turn(), "run.turn.v2")
        assert event_writer._SCHEMA_CACHE["run.turn.v2"] is schema_ref

    def test_missing_schema_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            event_writer.validate_against_schema({}, "nonexistent.schema.xyz")


# ---------------------------------------------------------------------------
# Anti-contamination filter
# ---------------------------------------------------------------------------

class TestContaminationFilter:
    def test_http_url_blocked(self):
        with pytest.raises(ValueError, match="Anti-contamination"):
            event_writer._check_contamination({"msg": "see http://example.com"})

    def test_https_url_blocked(self):
        with pytest.raises(ValueError, match="Anti-contamination"):
            event_writer._check_contamination({"msg": "check https://example.com/page"})

    def test_dotcom_alone_is_allowed(self):
        # .com in filenames/paths should NOT be blocked (only https?:// pattern)
        event_writer._check_contamination({"path": "bb://data/result.com.json"})

    def test_dotorg_alone_is_allowed(self):
        event_writer._check_contamination({"note": "reference.org file"})

    def test_www_alone_is_allowed(self):
        event_writer._check_contamination({"note": "www_config.json"})

    def test_clean_event_passes(self):
        event_writer._check_contamination({"message": "all clear", "role": "supervisor"})


# ---------------------------------------------------------------------------
# write_turn
# ---------------------------------------------------------------------------

class TestWriteTurn:
    def test_creates_jsonl_file(self, tmp_path):
        store = _make_store(tmp_path, "wt-run")
        ev = _minimal_turn("wt-run")
        with patch.object(event_writer, "_runs_dir", return_value=tmp_path / "runs" / "wt-run"):
            event_writer.write_turn(store, ev)
            out = tmp_path / "runs" / "wt-run" / "run.turn.v2.jsonl"
            assert out.exists()

    def test_appends_valid_json_line(self, tmp_path):
        store = _make_store(tmp_path, "wt-run")
        ev = _minimal_turn("wt-run")
        with patch.object(event_writer, "_runs_dir", return_value=tmp_path / "runs" / "wt-run"):
            event_writer.write_turn(store, ev)
            event_writer.write_turn(store, _minimal_turn("wt-run"))
            out = tmp_path / "runs" / "wt-run" / "run.turn.v2.jsonl"
            lines = [json.loads(l) for l in out.read_text().strip().splitlines()]
            assert len(lines) == 2

    def test_auto_fills_run_id_if_missing(self, tmp_path):
        store = _make_store(tmp_path, "wt-run")
        ev = _minimal_turn("wt-run")
        del ev["run_id"]
        with patch.object(event_writer, "_runs_dir", return_value=tmp_path / "runs" / "wt-run"):
            event_writer.write_turn(store, ev)
            out = tmp_path / "runs" / "wt-run" / "run.turn.v2.jsonl"
            written = json.loads(out.read_text().strip())
            assert written["run_id"] == "wt-run"

    def test_run_id_mismatch_raises(self, tmp_path):
        store = _make_store(tmp_path, "wt-run")
        ev = _minimal_turn("other-run")
        with pytest.raises(ValueError, match="run_id mismatch"):
            event_writer.write_turn(store, ev)

    def test_https_url_in_message_raises(self, tmp_path):
        store = _make_store(tmp_path, "wt-run")
        ev = _minimal_turn("wt-run")
        ev["message"] = "see https://example.com"
        with pytest.raises(ValueError, match="Anti-contamination"):
            event_writer.write_turn(store, ev)

    def test_role_normalised_to_lowercase(self, tmp_path):
        store = _make_store(tmp_path, "wt-run")
        ev = _minimal_turn("wt-run")
        ev["role"] = "Supervisor"
        with patch.object(event_writer, "_runs_dir", return_value=tmp_path / "runs" / "wt-run"):
            event_writer.write_turn(store, ev)
            out = tmp_path / "runs" / "wt-run" / "run.turn.v2.jsonl"
            written = json.loads(out.read_text().strip())
            assert written["role"] == "supervisor"


# ---------------------------------------------------------------------------
# write_router
# ---------------------------------------------------------------------------

class TestWriteRouter:
    def test_creates_router_jsonl(self, tmp_path):
        store = _make_store(tmp_path, "wr-run")
        ev = _minimal_router("wr-run")
        with patch.object(event_writer, "_runs_dir", return_value=tmp_path / "runs" / "wr-run"):
            event_writer.write_router(store, ev)
            out = tmp_path / "runs" / "wr-run" / "router.event.v2.jsonl"
            assert out.exists()
            written = json.loads(out.read_text().strip())
            assert written["schema"] == "router.event.v2"


# ---------------------------------------------------------------------------
# write_bb_write
# ---------------------------------------------------------------------------

class TestWriteBbWrite:
    def test_creates_write_jsonl(self, tmp_path):
        store = _make_store(tmp_path, "bb-run")
        ev = _minimal_write("bb-run")
        with patch.object(event_writer, "_runs_dir", return_value=tmp_path / "runs" / "bb-run"):
            event_writer.write_bb_write(store, ev)
            out = tmp_path / "runs" / "bb-run" / "bb.write.v1.jsonl"
            assert out.exists()

    def test_writer_role_normalised(self, tmp_path):
        store = _make_store(tmp_path, "bb-run")
        ev = _minimal_write("bb-run")
        ev["writer_role"] = "DE"
        with patch.object(event_writer, "_runs_dir", return_value=tmp_path / "runs" / "bb-run"):
            event_writer.write_bb_write(store, ev)
            out = tmp_path / "runs" / "bb-run" / "bb.write.v1.jsonl"
            written = json.loads(out.read_text().strip())
            assert written["writer_role"] == "de"


# ---------------------------------------------------------------------------
# write_read
# ---------------------------------------------------------------------------

class TestWriteRead:
    def test_creates_read_jsonl(self, tmp_path):
        store = _make_store(tmp_path, "rd-run")
        ev = _minimal_read("rd-run")
        with patch.object(event_writer, "_runs_dir", return_value=tmp_path / "runs" / "rd-run"):
            event_writer.write_read(store, ev)
            out = tmp_path / "runs" / "rd-run" / "run.read.v1.jsonl"
            assert out.exists()

    def test_reader_role_normalised(self, tmp_path):
        store = _make_store(tmp_path, "rd-run")
        ev = _minimal_read("rd-run")
        ev["reader_role"] = "DS"
        with patch.object(event_writer, "_runs_dir", return_value=tmp_path / "runs" / "rd-run"):
            event_writer.write_read(store, ev)
            out = tmp_path / "runs" / "rd-run" / "run.read.v1.jsonl"
            written = json.loads(out.read_text().strip())
            assert written["reader_role"] == "ds"
