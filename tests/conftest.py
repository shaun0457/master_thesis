"""
Shared pytest fixtures for MAS 2026 refactor tests.
All fixtures use mocks — no real Gemini API calls.
"""
import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage


class MockUsageMetadata:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def _make_ai_message(content: str, with_usage: bool = False) -> AIMessage:
    msg = AIMessage(content=content)
    if with_usage:
        msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
    return msg


@pytest.fixture
def mock_llm():
    """LLM that returns a fixed AIMessage, no API call."""
    m = MagicMock()
    m.invoke.return_value = _make_ai_message("mock response")
    return m


@pytest.fixture
def mock_llm_with_usage():
    """LLM whose response includes usage_metadata."""
    m = MagicMock()
    resp = _make_ai_message("mock response")
    resp.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
    m.invoke.return_value = resp
    return m


@pytest.fixture
def mock_llm_returning_json():
    """LLM that returns valid self-eval JSON."""
    m = MagicMock()
    m.invoke.return_value = _make_ai_message(
        '{"confidence": 0.8, "completeness": 0.9, "issues": []}'
    )
    return m


@pytest.fixture
def mock_llm_returning_judge_json():
    """LLM that returns valid judge score JSON."""
    m = MagicMock()
    m.invoke.return_value = _make_ai_message(
        '{"factual_grounding": 2, "completeness": 2, "coherence": 3, "critique": "Good answer."}'
    )
    return m


@pytest.fixture
def mock_llm_returning_garbage():
    """LLM that returns unparseable content."""
    m = MagicMock()
    m.invoke.return_value = _make_ai_message("Sorry I cannot help with that.")
    return m


@pytest.fixture
def mock_state():
    """Clean AgentState-like dict with empty metrics."""
    return {
        "messages": [],
        "metrics": {},
        "tool_events": [],
    }
