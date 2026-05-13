"""TDD: Plan B + D — BB-mediated ME→DE context injection.

Tests verify:
  D1. After delegate_to_me, kg_query_fault results are written to BB as structured facts.
  D2. Multiple kg_query_fault calls each produce one BB fact entry.
  B1. delegate_to_de injects ME facts into task when BB has ME fault facts.
  B2. delegate_to_de leaves task unchanged when BB has no ME fault facts.
  B3. Injection is skipped gracefully when RUN_ID is unset.

All tests are unit-level — no real subgraph or LLM calls.
"""
import os
# delegate_tools imports common which instantiates ChatGoogleGenerativeAI at module load
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")

import json
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import ToolMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_kg_tool_msg(fault_id: int, description: str, sensors: list) -> ToolMessage:
    payload = {
        "fault_id": fault_id,
        "fault_name": f"IDV_{fault_id}",
        "description": description,
        "diagnostic_sensors": sensors,
        "source": "tep_knowledge",
    }
    return ToolMessage(
        content=json.dumps(payload, ensure_ascii=False),
        name="kg_query_fault",
        tool_call_id=f"call_{fault_id}",
    )


def _make_out_state(tool_msgs: list) -> dict:
    return {"messages": tool_msgs, "metrics": {}, "tool_events": []}


# ---------------------------------------------------------------------------
# Plan D: _extract_and_write_me_fault_facts
# ---------------------------------------------------------------------------

class TestExtractAndWriteMeFaultFacts:
    def test_d1_writes_structured_fact_to_bb(self, tmp_path, monkeypatch):
        """D1: A kg_query_fault ToolMessage in out_state → one structured fact in BB."""
        monkeypatch.setenv("RUN_ID", "test-d1")
        monkeypatch.setenv("RUNS_DIR", str(tmp_path))

        import bb_tools
        import importlib, delegate_tools
        importlib.reload(bb_tools)

        sensors = [{"column": "xmeas_9", "process_unit": "Reactor"}]
        msg = _make_kg_tool_msg(4, "Reactor cooling water inlet temperature step change", sensors)
        out_state = _make_out_state([msg])

        delegate_tools._extract_and_write_me_fault_facts(out_state)

        reg = bb_tools._load("test-d1")
        me_facts = [f for f in reg["facts"] if isinstance(f, dict) and f.get("agent") == "ME"]
        assert len(me_facts) == 1
        assert me_facts[0]["fault_id"] == 4
        assert me_facts[0]["source_tool"] == "kg_query_fault"
        assert "xmeas_9" in me_facts[0]["claim"]

    def test_d2_multiple_kg_calls_write_multiple_facts(self, tmp_path, monkeypatch):
        """D2: Two kg_query_fault ToolMessages → two separate BB fact entries."""
        monkeypatch.setenv("RUN_ID", "test-d2")
        monkeypatch.setenv("RUNS_DIR", str(tmp_path))

        import bb_tools
        import delegate_tools

        msgs = [
            _make_kg_tool_msg(4, "Reactor cooling water step change",
                              [{"column": "xmeas_9", "process_unit": "Reactor"}]),
            _make_kg_tool_msg(1, "A/C feed ratio step change",
                              [{"column": "xmeas_1", "process_unit": "Separator"}]),
        ]
        delegate_tools._extract_and_write_me_fault_facts(_make_out_state(msgs))

        reg = bb_tools._load("test-d2")
        me_facts = [f for f in reg["facts"] if isinstance(f, dict) and f.get("agent") == "ME"]
        assert len(me_facts) == 2
        fault_ids = {f["fault_id"] for f in me_facts}
        assert fault_ids == {1, 4}

    def test_d3_no_kg_msg_writes_nothing(self, tmp_path, monkeypatch):
        """D3: out_state with no kg_query_fault ToolMessages → BB facts unchanged."""
        monkeypatch.setenv("RUN_ID", "test-d3")
        monkeypatch.setenv("RUNS_DIR", str(tmp_path))

        import bb_tools
        import delegate_tools

        out_state = _make_out_state([])
        delegate_tools._extract_and_write_me_fault_facts(out_state)

        reg = bb_tools._load("test-d3")
        assert reg["facts"] == []


# ---------------------------------------------------------------------------
# Plan B: _read_me_fault_facts + delegate_to_de injection
# ---------------------------------------------------------------------------

class TestReadMeFaultFacts:
    def test_b1_returns_formatted_string_when_facts_exist(self, tmp_path, monkeypatch):
        """B1: BB has ME fact → _read_me_fault_facts returns non-empty string with sensor names."""
        monkeypatch.setenv("RUN_ID", "test-b1")
        monkeypatch.setenv("RUNS_DIR", str(tmp_path))

        import bb_tools
        import delegate_tools

        sensors = [{"column": "xmeas_9", "process_unit": "Reactor"},
                   {"column": "xmeas_7", "process_unit": "Reactor"}]
        fact = {
            "agent": "ME",
            "source_tool": "kg_query_fault",
            "fault_id": 4,
            "description": "Reactor cooling water inlet temperature step change",
            "diagnostic_sensors": sensors,
            "claim": "IDV_4: Reactor cooling water... Diagnostic sensors: xmeas_9, xmeas_7",
        }
        bb_tools.bb_add_facts(run_id="test-b1", facts=[fact], agent="ME", source_tool="kg_query_fault")

        result = delegate_tools._read_me_fault_facts()
        assert "xmeas_9" in result
        assert "xmeas_7" in result
        assert "IDV_4" in result
        assert "deliver_dataframe" in result

    def test_b2_returns_empty_when_no_me_facts(self, tmp_path, monkeypatch):
        """B2: BB has no ME facts → _read_me_fault_facts returns empty string."""
        monkeypatch.setenv("RUN_ID", "test-b2")
        monkeypatch.setenv("RUNS_DIR", str(tmp_path))

        import delegate_tools
        result = delegate_tools._read_me_fault_facts()
        assert result == ""

    def test_b3_returns_empty_when_no_run_id(self, monkeypatch):
        """B3: RUN_ID not set → _read_me_fault_facts returns '' without error."""
        monkeypatch.delenv("RUN_ID", raising=False)

        import delegate_tools
        result = delegate_tools._read_me_fault_facts()
        assert result == ""


class TestDelegateToDeInjection:
    def test_b4_task_prepended_with_me_context_when_facts_exist(self, tmp_path, monkeypatch):
        """B4: delegate_to_de injects [Context from ME] when BB has ME fault facts."""
        monkeypatch.setenv("RUN_ID", "test-b4")
        monkeypatch.setenv("RUNS_DIR", str(tmp_path))

        import bb_tools
        sensors = [{"column": "xmeas_9", "process_unit": "Reactor"}]
        fact = {
            "agent": "ME", "source_tool": "kg_query_fault", "fault_id": 4,
            "description": "Reactor cooling step change", "diagnostic_sensors": sensors,
            "claim": "IDV_4: Reactor...",
        }
        bb_tools.bb_add_facts(run_id="test-b4", facts=[fact], agent="ME", source_tool="kg_query_fault")

        captured_task = {}

        def fake_run_subgraph(agent_name, state, task, intro, **kwargs):
            captured_task["task"] = task
            return {"messages": [], "metrics": {}, "tool_events": []}

        import delegate_tools
        with patch.object(delegate_tools, "_run_subgraph", side_effect=fake_run_subgraph), \
             patch.object(delegate_tools, "make_blackboard_tools", return_value=([], [])):
            delegate_tools.delegate_to_de("Retrieve sensor data.", {"metrics": {}, "blackboard": {}})

        assert "[Context from ME]" in captured_task["task"]
        assert "xmeas_9" in captured_task["task"]

    def test_b5_task_unchanged_when_no_me_facts(self, tmp_path, monkeypatch):
        """B5: delegate_to_de does NOT prepend when BB has no ME facts."""
        monkeypatch.setenv("RUN_ID", "test-b5")
        monkeypatch.setenv("RUNS_DIR", str(tmp_path))

        captured_task = {}

        def fake_run_subgraph(agent_name, state, task, intro, **kwargs):
            captured_task["task"] = task
            return {"messages": [], "metrics": {}, "tool_events": []}

        import delegate_tools
        with patch.object(delegate_tools, "_run_subgraph", side_effect=fake_run_subgraph), \
             patch.object(delegate_tools, "make_blackboard_tools", return_value=([], [])):
            delegate_tools.delegate_to_de("Retrieve sensor data.", {"metrics": {}, "blackboard": {}})

        assert "[Context from ME]" not in captured_task["task"]
        assert captured_task["task"] == "Retrieve sensor data."


# ---------------------------------------------------------------------------
# Plan A: Parallel Router — metrics race condition guard
# ---------------------------------------------------------------------------

class TestParallelMetricsSafety:
    def test_a1_concurrent_increments_are_safe(self):
        """A1: 20 threads incrementing global_tool_calls with lock → final value == 20."""
        import threading
        from router import _metrics_lock  # will fail until router.py exposes it

        state = {"metrics": {"global_tool_calls": 0}}
        errors = []

        def increment():
            try:
                with _metrics_lock:
                    state["metrics"]["global_tool_calls"] += 1
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=increment) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during parallel increment: {errors}"
        assert state["metrics"]["global_tool_calls"] == 20
