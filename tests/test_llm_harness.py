"""
TDD tests for llm_harness.py — written BEFORE implementation.
"""
import pytest
from langchain_core.messages import HumanMessage


def test_harness_increments_llm_calls(mock_llm, mock_state):
    from llm_harness import LLMCallHarness
    harness = LLMCallHarness(mock_llm)
    harness.invoke([HumanMessage(content="test")], agent="ME", state=mock_state)
    assert mock_state["metrics"]["llm_calls_total"] == 1


def test_harness_increments_on_multiple_calls(mock_llm, mock_state):
    from llm_harness import LLMCallHarness
    harness = LLMCallHarness(mock_llm)
    harness.invoke([HumanMessage(content="q1")], agent="ME", state=mock_state)
    harness.invoke([HumanMessage(content="q2")], agent="DE", state=mock_state)
    assert mock_state["metrics"]["llm_calls_total"] == 2


def test_harness_records_positive_latency(mock_llm, mock_state):
    from llm_harness import LLMCallHarness
    harness = LLMCallHarness(mock_llm)
    harness.invoke([HumanMessage(content="test")], agent="ME", state=mock_state)
    assert mock_state["metrics"]["llm_latency_ms_sum"] >= 0


def test_harness_extracts_tokens_from_usage_metadata(mock_llm_with_usage, mock_state):
    from llm_harness import LLMCallHarness
    harness = LLMCallHarness(mock_llm_with_usage)
    harness.invoke([HumanMessage(content="test")], agent="ME", state=mock_state)
    assert mock_state["metrics"]["tokens_in_total"] == 100
    assert mock_state["metrics"]["tokens_out_total"] == 50


def test_harness_handles_missing_usage_metadata_gracefully(mock_llm, mock_state):
    from llm_harness import LLMCallHarness
    harness = LLMCallHarness(mock_llm)
    harness.invoke([HumanMessage(content="test")], agent="ME", state=mock_state)
    # Should not crash, tokens just stay 0
    assert mock_state["metrics"]["tokens_in_total"] == 0
    assert mock_state["metrics"]["tokens_out_total"] == 0


def test_harness_returns_llm_response(mock_llm, mock_state):
    from llm_harness import LLMCallHarness
    harness = LLMCallHarness(mock_llm)
    response = harness.invoke([HumanMessage(content="test")], agent="ME", state=mock_state)
    assert response is not None
    assert response.content == "mock response"


def test_harness_tracks_context_token_estimate(mock_llm, mock_state):
    from llm_harness import LLMCallHarness
    harness = LLMCallHarness(mock_llm)
    msgs = [HumanMessage(content="x" * 400)]  # ~100 tokens
    harness.invoke(msgs, agent="ME", state=mock_state)
    assert mock_state["metrics"]["context_tokens_est_max"] > 0


def test_self_evaluator_parses_valid_json(mock_llm_returning_json, mock_state):
    from llm_harness import SelfEvaluator
    evaluator = SelfEvaluator()
    result = evaluator.evaluate(mock_llm_returning_json, "test output text", "ME", mock_state)
    assert result is not None
    assert result.confidence == 0.8
    assert result.completeness == 0.9


def test_self_evaluator_writes_to_state(mock_llm_returning_json, mock_state):
    from llm_harness import SelfEvaluator
    evaluator = SelfEvaluator()
    evaluator.evaluate(mock_llm_returning_json, "test output text", "ME", mock_state)
    assert mock_state["metrics"].get("self_eval_confidence_me") == 0.8


def test_self_evaluator_returns_none_on_garbage(mock_llm_returning_garbage, mock_state):
    from llm_harness import SelfEvaluator
    evaluator = SelfEvaluator()
    result = evaluator.evaluate(mock_llm_returning_garbage, "test output", "ME", mock_state)
    assert result is None


def test_self_evaluator_does_not_crash_on_garbage(mock_llm_returning_garbage, mock_state):
    from llm_harness import SelfEvaluator
    evaluator = SelfEvaluator()
    # Must not raise any exception
    try:
        evaluator.evaluate(mock_llm_returning_garbage, "output", "DS", mock_state)
    except Exception as e:
        pytest.fail(f"SelfEvaluator raised unexpectedly: {e}")


def test_self_evaluator_agent_name_lowercased_in_key(mock_llm_returning_json, mock_state):
    from llm_harness import SelfEvaluator
    evaluator = SelfEvaluator()
    evaluator.evaluate(mock_llm_returning_json, "output text here", "DS", mock_state)
    assert "self_eval_confidence_ds" in mock_state["metrics"]
