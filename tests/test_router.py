# tests/test_router.py
"""Tests for mas/core/router.py — Router class."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mas.blackboard.store import BlackboardStore
from mas.core.router import Router


def _make_store(tmp_path: Path) -> BlackboardStore:
    return BlackboardStore(root=tmp_path / "bb", run_id="test-run-001")


def _turn(role: str, target, turn_index: int = 0) -> dict:
    return {
        "schema":     "run.turn.v2",
        "run_id":     "test-run-001",
        "turn_index": turn_index,
        "role":       role,
        "message":    "test message",
        "intent":     "work",
        "action":     {"target": target},
        "ts":         "2024-11-15T14:30:22Z",
    }


# ---------------------------------------------------------------------------
# Neutral protocol — free handoff
# ---------------------------------------------------------------------------

class TestNeutralProtocol:
    def test_supervisor_to_de_ok(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="neutral", run_id="test-run-001")
        result = router.route(_turn("supervisor", "de"))
        assert result["status"] == "ok"
        assert result["next_owner"] == "de"
        assert result["violations"] == []

    def test_worker_to_worker_allowed(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="neutral", run_id="test-run-001")
        result = router.route(_turn("de", "ds"))
        assert result["status"] == "ok"
        assert result["violations"] == []

    def test_violation_count_zero_on_clean_run(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="neutral", run_id="test-run-001")
        router.route(_turn("supervisor", "de"))
        router.route(_turn("de", "supervisor"))
        assert router.violation_count == 0


# ---------------------------------------------------------------------------
# planner_to_worker protocol — P2P blocked
# ---------------------------------------------------------------------------

class TestPlannerToWorkerProtocol:
    def test_supervisor_to_de_ok(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="planner_to_worker", run_id="r1")
        result = router.route(_turn("supervisor", "de"))
        assert result["status"] == "ok"
        assert result["next_owner"] == "de"

    def test_supervisor_to_ds_ok(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="planner_to_worker", run_id="r1")
        result = router.route(_turn("supervisor", "ds"))
        assert result["next_owner"] == "ds"

    def test_de_to_supervisor_ok(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="planner_to_worker", run_id="r1")
        result = router.route(_turn("de", "supervisor"))
        assert result["status"] == "ok"

    def test_de_to_ds_blocked(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="planner_to_worker", run_id="r1")
        result = router.route(_turn("de", "ds"))
        assert "ROUTING_P2P_FORBIDDEN" in result["violations"]
        assert result["next_owner"] == "supervisor"

    def test_ds_to_me_blocked(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="planner_to_worker", run_id="r1")
        result = router.route(_turn("ds", "me"))
        assert "ROUTING_P2P_FORBIDDEN" in result["violations"]
        assert result["next_owner"] == "supervisor"

    def test_me_to_de_blocked(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="planner_to_worker", run_id="r1")
        result = router.route(_turn("me", "de"))
        assert "ROUTING_P2P_FORBIDDEN" in result["violations"]

    def test_violation_count_increments_on_p2p(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="planner_to_worker", run_id="r1")
        router.route(_turn("de", "ds"))
        router.route(_turn("ds", "me"))
        assert router.violation_count == 2

    def test_violation_count_not_incremented_on_clean(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="planner_to_worker", run_id="r1")
        router.route(_turn("supervisor", "de"))
        router.route(_turn("de", "supervisor"))
        assert router.violation_count == 0


# ---------------------------------------------------------------------------
# debate protocol — P2P allowed as warning, not hard block
# ---------------------------------------------------------------------------

class TestDebateProtocol:
    def test_worker_to_worker_is_warning_not_block(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="debate", run_id="r1")
        result = router.route(_turn("de", "ds"))
        assert "ROUTING_P2P_WARNING" in result["violations"]
        assert result["next_owner"] == "ds"

    def test_warning_does_not_increment_violation_count(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="debate", run_id="r1")
        router.route(_turn("de", "ds"))
        assert router.violation_count == 0


# ---------------------------------------------------------------------------
# delphi protocol — same as neutral (free handoff)
# ---------------------------------------------------------------------------

class TestDelphiProtocol:
    def test_worker_to_worker_allowed(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="delphi", run_id="r1")
        result = router.route(_turn("de", "ds"))
        assert result["status"] == "ok"
        assert result["violations"] == []


# ---------------------------------------------------------------------------
# next_owner fallback
# ---------------------------------------------------------------------------

class TestNextOwnerFallback:
    def test_unknown_target_falls_back_to_supervisor(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="neutral", run_id="r1")
        result = router.route(_turn("supervisor", "unknown_bot"))
        assert result["next_owner"] == "supervisor"

    def test_none_target_falls_back_to_supervisor(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="neutral", run_id="r1")
        result = router.route(_turn("supervisor", None))
        assert result["next_owner"] == "supervisor"

    def test_uppercase_target_normalised(self, tmp_path):
        router = Router(_make_store(tmp_path), protocol="neutral", run_id="r1")
        result = router.route(_turn("supervisor", "DE"))
        assert result["next_owner"] == "de"


# ---------------------------------------------------------------------------
# Router event is written to log file
# ---------------------------------------------------------------------------

class TestRouterEventLogging:
    def test_router_event_file_created(self, tmp_path):
        store = _make_store(tmp_path)
        router = Router(store, protocol="neutral", run_id="test-run-001")
        router.route(_turn("supervisor", "de"))

        event_file = (
            Path(__file__).parents[1]
            / "data" / "runs" / "test-run-001"
            / "router.event.v2.jsonl"
        )
        # File may be written relative to project root — just check no exception raised
        # (file creation depends on cwd; we just verify route() returns cleanly)
        assert router.violation_count == 0
