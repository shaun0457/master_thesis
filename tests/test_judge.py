"""
TDD tests for judge.py — written BEFORE implementation.
"""
import pytest
from langchain_core.messages import HumanMessage


def test_judge_sync_returns_score(mock_llm_returning_judge_json, mock_state):
    from judge import JudgeLLM
    mock_state["messages"] = [HumanMessage(content="What causes fault 4 in TEP?")]
    judge = JudgeLLM()
    score = judge.judge_sync(mock_llm_returning_judge_json, mock_state, "The answer is X.")
    assert score is not None
    assert 0 <= score.factual_grounding <= 3
    assert 0 <= score.completeness <= 3
    assert 0 <= score.coherence <= 3
    assert isinstance(score.critique, str)
    assert len(score.critique) > 0


def test_judge_sync_sets_triggered_flag(mock_llm_returning_judge_json, mock_state):
    from judge import JudgeLLM
    mock_state["messages"] = [HumanMessage(content="test question")]
    judge = JudgeLLM()
    judge.judge_sync(mock_llm_returning_judge_json, mock_state, "some answer")
    assert mock_state["metrics"].get("judge_triggered") is True


def test_judge_sync_writes_scores_to_metrics(mock_llm_returning_judge_json, mock_state):
    from judge import JudgeLLM
    mock_state["messages"] = [HumanMessage(content="test question")]
    judge = JudgeLLM()
    judge.judge_sync(mock_llm_returning_judge_json, mock_state, "some answer")
    m = mock_state["metrics"]
    assert m.get("judge_factual_grounding") == 2
    assert m.get("judge_completeness") == 2
    assert m.get("judge_coherence") == 3


def test_judge_sync_returns_none_on_garbage(mock_llm_returning_garbage, mock_state):
    from judge import JudgeLLM
    mock_state["messages"] = [HumanMessage(content="test question")]
    judge = JudgeLLM()
    result = judge.judge_sync(mock_llm_returning_garbage, mock_state, "some answer")
    assert result is None


def test_judge_sync_does_not_crash_on_garbage(mock_llm_returning_garbage, mock_state):
    from judge import JudgeLLM
    mock_state["messages"] = [HumanMessage(content="test question")]
    judge = JudgeLLM()
    try:
        judge.judge_sync(mock_llm_returning_garbage, mock_state, "some answer")
    except Exception as e:
        pytest.fail(f"JudgeLLM raised unexpectedly: {e}")


def test_judge_does_not_set_triggered_on_failure(mock_llm_returning_garbage, mock_state):
    from judge import JudgeLLM
    mock_state["messages"] = [HumanMessage(content="test question")]
    judge = JudgeLLM()
    judge.judge_sync(mock_llm_returning_garbage, mock_state, "some answer")
    assert mock_state["metrics"].get("judge_triggered") is not True


def test_judge_prompt_includes_question(mock_llm_returning_judge_json, mock_state):
    from judge import JudgeLLM
    question = "What is the reactor feed ratio in TEP?"
    mock_state["messages"] = [HumanMessage(content=question)]
    judge = JudgeLLM()
    judge.judge_sync(mock_llm_returning_judge_json, mock_state, "The feed ratio is 0.5.")
    call_args = mock_llm_returning_judge_json.invoke.call_args
    prompt_text = str(call_args)
    assert question[:30] in prompt_text


def test_judge_prompt_includes_answer(mock_llm_returning_judge_json, mock_state):
    from judge import JudgeLLM
    mock_state["messages"] = [HumanMessage(content="question")]
    judge = JudgeLLM()
    answer = "The separator pressure is 2700 kPa."
    judge.judge_sync(mock_llm_returning_judge_json, mock_state, answer)
    call_args = mock_llm_returning_judge_json.invoke.call_args
    prompt_text = str(call_args)
    assert "separator pressure" in prompt_text


def test_judge_works_with_empty_message_history(mock_llm_returning_judge_json, mock_state):
    from judge import JudgeLLM
    mock_state["messages"] = []  # no messages
    judge = JudgeLLM()
    score = judge.judge_sync(mock_llm_returning_judge_json, mock_state, "some answer")
    assert score is not None  # should still work, uses fallback question text
