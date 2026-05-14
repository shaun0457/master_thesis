import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def test_build_context_pack_uses_contract_evidence_and_short_tail():
    from context_assembler import DynamicContextAssembler
    from subagent_contracts import build_ticket

    state = {
        "messages": [
            HumanMessage(content="user question"),
            AIMessage(content="first answer"),
            ToolMessage(content="x" * 4000, tool_call_id="tool-1", name="sql_db_query"),
            AIMessage(content="latest agent note"),
        ],
        "blackboard": {
            "facts": [{"claim": "IDV_4 affects xmeas_9", "agent": "ME"}],
            "datasets": [
                {
                    "artifact_id": "ds-1",
                    "kind": "dataset",
                    "path": "datasets/ready.parquet",
                    "rowcount": 12,
                    "columns": ["xmeas_9", "xmeas_7"],
                    "created_by": "DE",
                    "ready_for": "DS",
                }
            ],
        },
    }
    ticket = build_ticket(
        from_agent="Supervisor",
        to_agent="DS",
        topic_id="topic-1",
        owner="DS",
        goal="Analyze dataset",
        task_text="Analyze dataset",
    )
    assembler = DynamicContextAssembler()
    pack = assembler.build_context_pack(
        state=state,
        ticket=ticket,
        role_prompt="role",
        runtime_limits={"max_context_tokens": 5000},
    )

    assert "Ticket:" in pack.task_contract
    assert "IDV_4 affects xmeas_9" in pack.evidence_pack
    assert len(pack.artifact_refs) == 1
    assert len(pack.history_tail) <= 4


def test_validate_de_to_ds_requires_columns_and_path():
    from subagent_contracts import validate_de_to_ds

    good = {
        "messages": [
            ToolMessage(
                content=json.dumps(
                    {
                        "status": "ok",
                        "artifact_id": "a1",
                        "df_payload": {"path": "datasets/ready.parquet"},
                        "rowcount": 3,
                        "columns": ["x", "y"],
                    }
                ),
                tool_call_id="deliver-1",
                name="deliver_dataframe",
            )
        ]
    }
    bad = {
        "messages": [
            ToolMessage(
                content=json.dumps({"status": "ok", "df_payload": {"path": ""}, "rowcount": 3}),
                tool_call_id="deliver-2",
                name="deliver_dataframe",
            )
        ]
    }

    assert validate_de_to_ds(good, topic_id="t1").status == "ready"
    assert validate_de_to_ds(bad, topic_id="t1").status == "blocked"


def test_validate_ds_to_supervisor_accepts_numeric_conclusion_without_artifact():
    from subagent_contracts import validate_ds_to_supervisor

    out_state = {"messages": [AIMessage(content="mean diff = 12.3 and p-value = 0.01")], "tool_events": []}
    assert validate_ds_to_supervisor(out_state, topic_id="t1").status == "ready"


def test_run_subgraph_blocks_before_invoke_when_context_cap_exceeded(monkeypatch):
    import delegate_tools
    from subagent_contracts import build_ticket

    monkeypatch.setattr(
        delegate_tools,
        "_invoke_stage1",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not invoke")),
    )
    state = {
        "messages": [HumanMessage(content="x" * 5000)],
        "blackboard": {},
        "runtime_limits": {"max_context_tokens": 10},
    }
    ticket = build_ticket(
        from_agent="Supervisor",
        to_agent="DE",
        topic_id="topic-1",
        owner="DE",
        goal="Fetch data",
        task_text="Fetch data",
    )
    result = delegate_tools._run_subgraph(
        "DE",
        state,
        "Fetch data",
        "intro",
        topic_id="topic-1",
        owner="DE",
        ticket=ticket,
    )

    assert result["status"] == "blocked"
    assert result["stop_reason"] == "context_cap_exceeded"


def test_route_and_execute_serializes_result_envelope(monkeypatch):
    import router

    monkeypatch.setattr(
        router,
        "_exec_one_tool",
        lambda name, args, state: {
            "ticket_id": "ticket-1",
            "agent": "DE",
            "status": "ok",
            "summary": "done",
            "metrics": {"context_tokens_est": 12},
            "delegate_requests": [],
        },
    )
    monkeypatch.setattr(router, "_consume_p2p_requests", lambda res, state: None)
    ai = AIMessage(content="", tool_calls=[{"name": "delegate_to_de", "args": {"task": "build data"}, "id": "call-1"}])
    result = router.route_and_execute({"messages": [ai], "metrics": {}})
    payload = json.loads(result["messages"][0].content)

    assert payload["ticket_id"] == "ticket-1"
    assert payload["status"] == "ok"
    assert "metrics" in payload
