import json
import os

from langchain_core.messages import AIMessage, ToolMessage

os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


def test_has_min_evidence_uses_state_run_id(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_ID", "evidence-source")

    import bb_tools
    from supervisor_workflow import _has_min_evidence

    bb_tools.bb_add_facts(
        run_id="evidence-source",
        facts=[{"claim": "source run fact", "agent": "ME", "source_tool": "test"}],
        agent="ME",
        source_tool="test",
    )

    assert _has_min_evidence({"run_id": "evidence-source", "blackboard": {"facts": [], "datasets": []}})
    assert not _has_min_evidence({"run_id": "evidence-empty", "blackboard": {"facts": [], "datasets": []}})


def test_read_me_fault_facts_diagnose_mode_avoids_faultnumber_leak(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_ID", "diag-me-facts")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))

    import bb_tools
    import delegate_tools

    bb_tools.bb_add_facts(
        run_id="diag-me-facts",
        facts=[{
            "agent": "ME",
            "source_tool": "kg_query_fault",
            "fault_id": 4,
            "description": "Reactor cooling water inlet temperature step change",
            "diagnostic_sensors": [{"column": "xmeas_9"}, {"column": "xmeas_7"}],
            "claim": "IDV_4 candidate",
        }],
        agent="ME",
        source_tool="kg_query_fault",
    )

    result = delegate_tools._read_me_fault_facts({"phase": "diagnose", "topic_ctx": {"mode": "diagnose"}})
    assert "xmeas_9" in result
    assert "xmeas_7" in result
    assert "faultnumber=" not in result
    assert "already-registered datasets" in result


def test_router_after_de_requires_actual_delivery_before_handoff():
    from de_workflow import router_after_de

    state = {
        "messages": [AIMessage(content="I could not find a dataset.", tool_calls=[])],
        "metrics": {},
    }

    assert router_after_de(state) == "DataEngineer"


def test_router_after_de_hands_off_after_successful_delivery():
    from de_workflow import router_after_de

    delivered = json.dumps({"status": "ok", "df_payload": {"name": "merged_frame"}, "rowcount": 12})
    state = {
        "messages": [
            ToolMessage(content=delivered, name="deliver_dataframe", tool_call_id="deliver-1"),
            AIMessage(content="Dataset delivered.", tool_calls=[]),
        ],
        "metrics": {},
    }

    assert router_after_de(state) == "DataScientistValidator"


def test_router_root_defaults_to_workspace_runs(tmp_path, monkeypatch):
    monkeypatch.delenv("RUNS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    from router import _root

    expected = os.path.join(str(tmp_path), "runs")
    assert _root() == expected
    assert os.path.isdir(expected)
