import json
import os
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


def test_has_min_evidence_uses_state_run_id(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_ID", "evidence-source")

    from agents import bb_tools
    from agents.supervisor_workflow import _has_min_evidence

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

    from agents import bb_tools
    from agents import delegate_tools
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


def test_read_me_fault_facts_prefers_state_run_id_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_ID", "old-run")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))

    from agents import bb_tools
    from agents import delegate_tools
    bb_tools.bb_add_facts(
        run_id="old-run",
        facts=[{
            "agent": "ME",
            "source_tool": "kg_query_fault",
            "fault_id": 1,
            "description": "old run fact",
            "diagnostic_sensors": [{"column": "xmeas_old"}],
            "claim": "old run fact",
        }],
        agent="ME",
        source_tool="kg_query_fault",
    )
    bb_tools.bb_add_facts(
        run_id="current-run",
        facts=[{
            "agent": "ME",
            "source_tool": "kg_query_fault",
            "fault_id": 2,
            "description": "current run fact",
            "diagnostic_sensors": [{"column": "xmeas_current"}],
            "claim": "current run fact",
        }],
        agent="ME",
        source_tool="kg_query_fault",
    )

    result = delegate_tools._read_me_fault_facts({"run_id": "current-run"})
    assert "current run fact" in result
    assert "xmeas_current" in result
    assert "old run fact" not in result


def test_router_after_de_requires_actual_delivery_before_handoff():
    from agents.de_workflow import router_after_de

    state = {
        "messages": [AIMessage(content="I could not find a dataset.", tool_calls=[])],
        "metrics": {},
    }

    assert router_after_de(state) == "DataEngineer"


def test_router_after_de_hands_off_after_successful_delivery():
    from agents.de_workflow import router_after_de

    delivered = json.dumps({"status": "ok", "df_payload": {"path": "datasets/merged.parquet"}, "rowcount": 12})
    state = {
        "messages": [
            ToolMessage(content=delivered, name="deliver_dataframe", tool_call_id="deliver-1"),
            AIMessage(content="Dataset delivered.", tool_calls=[]),
        ],
        "metrics": {},
    }

    assert router_after_de(state) == "DataScientistValidator"


def test_router_after_tool_sql_query_is_not_ds_ready():
    from agents.de_workflow import router_after_tool

    state = {
        "messages": [
            ToolMessage(
                content=json.dumps({"status": "ok", "rowcount": 12, "rows": [{"x": 1}]}),
                name="sql_db_query",
                tool_call_id="sql-1",
            )
        ],
        "metrics": {},
    }

    assert router_after_tool(state) == "DataEngineer"
    assert state["metrics"].get("deliver_via") is None


def test_router_after_tool_deliver_dataframe_success_is_ds_ready():
    from agents.de_workflow import router_after_tool

    state = {
        "messages": [
            ToolMessage(
                content=json.dumps({
                    "status": "ok",
                    "df_payload": {"path": "datasets/ready.parquet"},
                    "rowcount": 12,
                }),
                name="deliver_dataframe",
                tool_call_id="deliver-1",
            )
        ],
        "metrics": {},
    }

    assert router_after_tool(state) == "DataScientistValidator"
    assert state["metrics"]["deliver_via"] == "deliver_dataframe"


def test_route_and_execute_returns_messages_without_mutating_state(monkeypatch):
    from agents import router
    monkeypatch.setattr(
        router,
        "_exec_one_tool",
        lambda name, args, state: {"agent": "DE", "summary": "done", "status": "ok"},
    )
    monkeypatch.setattr(router, "_consume_p2p_requests", lambda res, state: None)

    ai = AIMessage(
        content="",
        tool_calls=[{"name": "delegate_to_de", "args": {"task": "build data"}, "id": "call-1"}],
    )
    state = {"messages": [ai], "metrics": {}}

    result = router.route_and_execute(state)

    assert len(state["messages"]) == 1
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ToolMessage)


def test_invoke_stage1_rebuilds_graph_for_state_bound_tools(monkeypatch):
    from agents import de_tools
    from agents import de_workflow
    from agents import delegate_tools
    created_tool_names = []

    class FakeGraph:
        def __init__(self, tool_names):
            self.tool_names = list(tool_names)

        def invoke(self, sub_state):
            return {"messages": [], "run_id": sub_state["run_id"], "tool_names": self.tool_names}

    def fake_create_executor(mode, tools_for_agent, system_prompt=None):
        names = [getattr(t, "name", "") for t in tools_for_agent]
        created_tool_names.append(names)
        return object()

    def fake_build_graph(agent_state_cls, de_executor, tool_map):
        return FakeGraph(list(tool_map))

    monkeypatch.setattr(delegate_tools, "get_system_prompt", lambda agent, policy: "prompt")
    monkeypatch.setattr(de_tools, "get_de_tools", lambda mode: ([], {}))
    monkeypatch.setattr(de_workflow, "create_de_executor", fake_create_executor)
    monkeypatch.setattr(de_workflow, "build_graph", fake_build_graph)
    delegate_tools._GRAPH_CACHE.clear()

    first = delegate_tools._invoke_stage1(
        "DE",
        [],
        [SimpleNamespace(name="state_tool_a")],
        {"run_id": "run-a", "messages": [], "blackboard": {}},
    )
    second = delegate_tools._invoke_stage1(
        "DE",
        [],
        [SimpleNamespace(name="state_tool_b")],
        {"run_id": "run-b", "messages": [], "blackboard": {}},
    )

    assert first["tool_names"] == ["state_tool_a"]
    assert second["tool_names"] == ["state_tool_b"]
    assert created_tool_names == [["state_tool_a"], ["state_tool_b"]]
    assert delegate_tools._GRAPH_CACHE == {}


def test_router_root_defaults_to_workspace_runs(tmp_path, monkeypatch):
    monkeypatch.delenv("RUNS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    from agents.router import _root

    expected = os.path.join(str(tmp_path), "runs")
    assert _root() == expected
    assert os.path.isdir(expected)
