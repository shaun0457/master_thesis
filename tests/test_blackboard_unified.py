import json
import os
from pathlib import Path

os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


class _DummyToolExec:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def ok(self, value):
        return None


class _DummyLogger:
    def tool_exec(self, **kwargs):
        return _DummyToolExec()

    def artifact(self, **kwargs):
        return None

    def open_issue(self, **kwargs):
        return None


def test_bb_find_dataset_prefers_name_over_shared_topic(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_ID", "bb-unified-find")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))

    obs_path = tmp_path / "obs.parquet"
    base_path = tmp_path / "baseline.parquet"
    obs_path.write_text("obs", encoding="utf-8")
    base_path.write_text("baseline", encoding="utf-8")

    import bb_tools

    bb_tools.bb_register_dataset_path(
        run_id="bb-unified-find",
        name="obs_diag_demo",
        path=str(obs_path),
        meta={"kind": "observation", "role": "input", "aliases": ["observation"]},
        topic_id="diagnose",
        created_by="SYSTEM",
    )
    bb_tools.bb_register_dataset_path(
        run_id="bb-unified-find",
        name="baseline_stats",
        path=str(base_path),
        meta={"kind": "baseline", "role": "reference", "aliases": ["baseline"]},
        topic_id="diagnose",
        created_by="SYSTEM",
    )

    match = bb_tools.bb_find_dataset_py("bb-unified-find", prefer_name="obs_diag_demo", prefer_topic="obs_diag_demo")
    assert match is not None
    assert match["name"] == "obs_diag_demo"
    assert match["ref"] == str(obs_path)


def test_delegate_read_blackboard_reads_registry_and_syncs_state(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_ID", "bb-unified-read")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))

    dataset_path = tmp_path / "obs.parquet"
    dataset_path.write_text("obs", encoding="utf-8")

    import bb_tools
    bb_tools.bb_register_dataset_path(
        run_id="bb-unified-read",
        name="obs_diag_demo",
        path=str(dataset_path),
        meta={"kind": "observation", "role": "input"},
        topic_id="diagnose",
        created_by="SYSTEM",
    )

    import delegate_tools
    monkeypatch.setattr(delegate_tools, "get_run_logger", lambda: _DummyLogger())
    monkeypatch.setattr(delegate_tools, "emit_bb_read", lambda **kwargs: None)
    monkeypatch.setattr(delegate_tools, "note_tool_call", lambda **kwargs: None)
    monkeypatch.setattr(delegate_tools, "emit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(delegate_tools, "emit_compliance", lambda *args, **kwargs: None)

    state = {"run_id": "bb-unified-read", "blackboard": {"facts": [], "datasets": []}, "tool_events": [], "turn_counter": 0}
    tools, _ = delegate_tools.make_blackboard_tools(state, agent_name="DE")
    read_tool = next(t for t in tools if t.name == "read_blackboard")
    result = read_tool.invoke({"keys": ["datasets"], "limit": 5})

    assert result["datasets"][0]["name"] == "obs_diag_demo"
    assert state["blackboard"]["datasets"][0]["name"] == "obs_diag_demo"


def test_delegate_write_blackboard_dataset_uses_canonical_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_ID", "bb-unified-write")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))

    dataset_path = tmp_path / "merged.parquet"
    dataset_path.write_text("merged", encoding="utf-8")

    import delegate_tools
    monkeypatch.setattr(delegate_tools, "get_run_logger", lambda: _DummyLogger())
    monkeypatch.setattr(delegate_tools, "note_tool_call", lambda **kwargs: None)
    monkeypatch.setattr(delegate_tools, "emit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(delegate_tools, "emit_compliance", lambda *args, **kwargs: None)

    state = {"run_id": "bb-unified-write", "blackboard": {}, "tool_events": [], "turn_counter": 0}
    tools, _ = delegate_tools.make_blackboard_tools(state, agent_name="DE")
    write_tool = next(t for t in tools if t.name == "write_to_blackboard")

    message = write_tool.invoke({
        "section": "datasets",
        "summary": "Merged observation and baseline frame",
        "content": {
            "df_payload": {"name": "merged_frame", "path": str(dataset_path), "rows": 12, "format": "parquet"},
            "kind": "analysis_input",
            "role": "intermediate",
        },
    })

    assert "Successfully wrote" in message

    import bb_tools
    datasets = bb_tools.bb_list_datasets_py("bb-unified-write")
    assert datasets[-1]["name"] == "merged_frame"
    assert datasets[-1]["ref"] == str(dataset_path)
    assert state["blackboard"]["datasets"][-1]["name"] == "merged_frame"


def test_ds_prompt_includes_tool_boundary_and_windows_path_rules():
    from context_assembler import DynamicContextAssembler

    prompt = DynamicContextAssembler().assemble_system_prompt("DS")
    assert "write_to_blackboard" in prompt
    assert "raw strings" in prompt or "forward slashes" in prompt
