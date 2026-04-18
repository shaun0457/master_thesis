# tests/test_base_agent.py
"""Tests for agents/base.py — BaseAgent."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mas.blackboard.store import BlackboardStore


def _make_store(tmp_path: Path, run_id: str = "agent-run") -> BlackboardStore:
    return BlackboardStore(root=tmp_path / "bb", run_id=run_id)


def _make_agent(store, protocol="neutral"):
    """Build a BaseAgent with a mocked Gemini model."""
    with patch("google.generativeai.configure"), \
         patch("google.generativeai.GenerativeModel") as mock_model_cls:
        mock_model_cls.return_value = MagicMock()
        from agents.base import BaseAgent
        agent = BaseAgent(
            role="supervisor",
            bb_store=store,
            router=MagicMock(),
            protocol=protocol,
            model_name="gemini-2.5-pro",
            temperature=0.25,
        )
        agent._model = mock_model_cls.return_value
    return agent


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def _agent(self, tmp_path):
        return _make_agent(_make_store(tmp_path))

    def _ctx(self, run_id="agent-run"):
        return {
            "run_id": run_id,
            "history": [],
            "query": "test task",
        }

    def test_extracts_json_block(self, tmp_path):
        agent = self._agent(tmp_path)
        text = '```json\n{"intent": "delegate", "message": "Go DE", "action": {"target": "de"}}\n```'
        result = agent._parse_response(text, self._ctx(), 100, {"input": 10, "output": 20})
        assert result["intent"] == "delegate"
        assert result["message"] == "Go DE"

    def test_fallback_on_no_json_block(self, tmp_path):
        agent = self._agent(tmp_path)
        text = "I will now delegate to the data engineer."
        result = agent._parse_response(text, self._ctx(), 50, {"input": 5, "output": 10})
        assert result["intent"] == "work"
        assert text in result["message"]

    def test_role_always_set_to_agent_role(self, tmp_path):
        agent = self._agent(tmp_path)
        text = '```json\n{"intent": "work", "message": "hi", "action": {}, "role": "de"}\n```'
        result = agent._parse_response(text, self._ctx(), 10, {})
        assert result["role"] == "supervisor"

    def test_turn_index_reflects_history_length(self, tmp_path):
        agent = self._agent(tmp_path)
        ctx = {"run_id": "agent-run", "history": [{}, {}], "query": ""}
        result = agent._parse_response("hello", ctx, 0, {})
        assert result["turn_index"] == 2

    def test_metrics_trace_populated(self, tmp_path):
        agent = self._agent(tmp_path)
        result = agent._parse_response("hi", self._ctx(), 123, {"input": 50, "output": 80})
        assert result["metrics_trace"]["latency_ms"] == 123
        assert result["metrics_trace"]["tokens_input"] == 50
        assert result["metrics_trace"]["tokens_output"] == 80

    def test_schema_field_defaults_to_run_turn_v2(self, tmp_path):
        agent = self._agent(tmp_path)
        result = agent._parse_response("hello", self._ctx(), 0, {})
        assert result["schema"] == "run.turn.v2"

    def test_broken_json_block_falls_back_gracefully(self, tmp_path):
        agent = self._agent(tmp_path)
        text = "```json\n{broken json\n```"
        result = agent._parse_response(text, self._ctx(), 0, {})
        assert result["intent"] == "work"

    def test_blackboard_refs_defaults_to_empty_list(self, tmp_path):
        agent = self._agent(tmp_path)
        result = agent._parse_response("hello", self._ctx(), 0, {})
        assert result["blackboard_refs"] == []

    def test_write_event_true_when_refs_present(self, tmp_path):
        agent = self._agent(tmp_path)
        text = '```json\n{"intent":"work","message":"x","action":{},"blackboard_refs":["bb://a/b"]}\n```'
        result = agent._parse_response(text, self._ctx(), 0, {})
        assert result["metrics_trace"]["write_event"] is True

    def test_write_event_false_when_no_refs(self, tmp_path):
        agent = self._agent(tmp_path)
        result = agent._parse_response("plain text", self._ctx(), 0, {})
        assert result["metrics_trace"]["write_event"] is False


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_includes_query(self, tmp_path):
        agent = _make_agent(_make_store(tmp_path))
        ctx = {"run_id": "r", "history": [], "query": "Diagnose fault X"}
        prompt = agent._build_prompt(ctx)
        assert "Diagnose fault X" in prompt

    def test_includes_history_excerpt(self, tmp_path):
        agent = _make_agent(_make_store(tmp_path))
        ctx = {
            "run_id": "r",
            "history": [{"role": "de", "message": "I found anomaly"}],
            "query": "",
        }
        prompt = agent._build_prompt(ctx)
        assert "I found anomaly" in prompt

    def test_includes_output_format_instruction(self, tmp_path):
        agent = _make_agent(_make_store(tmp_path))
        ctx = {"run_id": "r", "history": [], "query": ""}
        prompt = agent._build_prompt(ctx)
        assert "Output Format" in prompt

    def test_history_limited_to_last_10(self, tmp_path):
        agent = _make_agent(_make_store(tmp_path))
        history = [{"role": "de", "message": f"msg{i}"} for i in range(15)]
        ctx = {"run_id": "r", "history": history, "query": ""}
        prompt = agent._build_prompt(ctx)
        # Should have msg14 (last) but NOT msg0 (too old)
        assert "msg14" in prompt
        assert "msg0" not in prompt


# ---------------------------------------------------------------------------
# write_to_blackboard
# ---------------------------------------------------------------------------

class TestWriteToBlackboard:
    def test_returns_bb_uri_and_event(self, tmp_path):
        store = _make_store(tmp_path)
        agent = _make_agent(store)
        uri, event = agent.write_to_blackboard(
            intent="analyze",
            content={"result": 42},
            task_id="task-001",
        )
        assert uri.startswith("bb://")
        assert "analysis" in uri
        assert event["schema"] == "bb.write.v1"

    def test_intent_to_topic_mapping(self, tmp_path):
        store = _make_store(tmp_path)
        agent = _make_agent(store)
        for intent, expected_topic in [("analyze", "analysis"), ("report", "reports"), ("data", "datasets")]:
            uri, _ = agent.write_to_blackboard(intent=intent, content={}, task_id="t")
            assert expected_topic in uri

    def test_unknown_intent_defaults_to_artifacts(self, tmp_path):
        store = _make_store(tmp_path)
        agent = _make_agent(store)
        uri, _ = agent.write_to_blackboard(intent="work", content={}, task_id="t")
        assert "artifacts" in uri

    def test_write_event_has_correct_writer_role(self, tmp_path):
        store = _make_store(tmp_path)
        agent = _make_agent(store)
        _, event = agent.write_to_blackboard(intent="analyze", content={}, task_id="t")
        assert event["writer_role"] == "supervisor"

    def test_file_actually_written_to_disk(self, tmp_path):
        store = _make_store(tmp_path)
        agent = _make_agent(store)
        uri, _ = agent.write_to_blackboard(intent="analyze", content={"x": 1}, task_id="t")
        path = store.resolve(uri)
        assert path.exists()
        assert json.loads(path.read_text())["x"] == 1


# ---------------------------------------------------------------------------
# read_from_blackboard
# ---------------------------------------------------------------------------

class TestReadFromBlackboard:
    def test_reads_json_artifact(self, tmp_path):
        store = _make_store(tmp_path)
        store.write_json("bb://analysis/test.json", {"answer": 99})
        agent = _make_agent(store)
        result = agent.read_from_blackboard("bb://analysis/test.json")
        assert result["answer"] == 99

    def test_reads_parquet_artifact(self, tmp_path):
        import pandas as pd

        store = _make_store(tmp_path)
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        path = store.resolve("bb://data/test.parquet")
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(str(path), index=False, engine="pyarrow")

        agent = _make_agent(store)
        result = agent.read_from_blackboard("bb://data/test.parquet")
        assert "columns" in result
        assert "data" in result


# ---------------------------------------------------------------------------
# act — integration with mocked LLM
# ---------------------------------------------------------------------------

class TestAct:
    def test_act_returns_structured_dict(self, tmp_path):
        store = _make_store(tmp_path)
        agent = _make_agent(store)

        mock_response = MagicMock()
        mock_response.text = (
            '```json\n'
            '{"intent":"delegate","message":"Go DE","action":{"target":"de"},'
            '"blackboard_refs":[]}\n'
            '```'
        )
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=10, candidates_token_count=20
        )
        agent._model.generate_content.return_value = mock_response

        ctx = {"run_id": "agent-run", "history": [], "query": "diagnose fault"}
        result = agent.act(ctx)

        assert result["role"] == "supervisor"
        assert result["intent"] == "delegate"
        assert "latency_ms" in result["metrics_trace"]

    def test_act_calls_model_generate_content(self, tmp_path):
        store = _make_store(tmp_path)
        agent = _make_agent(store)

        mock_response = MagicMock()
        mock_response.text = "plain text response"
        mock_response.usage_metadata = None
        agent._model.generate_content.return_value = mock_response

        ctx = {"run_id": "agent-run", "history": [], "query": "task"}
        agent.act(ctx)

        agent._model.generate_content.assert_called_once()
