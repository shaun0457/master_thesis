"""
TDD tests for llm_cache.py — written BEFORE implementation.
"""
import time
import pytest
from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage


# ─── ExactMatchCache ─────────────────────────────────────────────────────────

def test_cache_hit_returns_cached_response(mock_llm, mock_state):
    from llm_cache import ExactMatchCache
    cache = ExactMatchCache(mock_llm)
    msgs = [HumanMessage(content="What is TEP fault 4?")]
    cache.invoke(msgs, state=mock_state)
    cache.invoke(msgs, state=mock_state)
    assert mock_llm.invoke.call_count == 1  # second call served from cache


def test_cache_miss_calls_llm(mock_llm, mock_state):
    from llm_cache import ExactMatchCache
    cache = ExactMatchCache(mock_llm)
    msgs_a = [HumanMessage(content="question A")]
    msgs_b = [HumanMessage(content="question B")]
    cache.invoke(msgs_a, state=mock_state)
    cache.invoke(msgs_b, state=mock_state)
    assert mock_llm.invoke.call_count == 2


def test_cache_hit_increments_metric(mock_llm, mock_state):
    from llm_cache import ExactMatchCache
    cache = ExactMatchCache(mock_llm)
    msgs = [HumanMessage(content="repeat question")]
    cache.invoke(msgs, state=mock_state)
    cache.invoke(msgs, state=mock_state)
    assert mock_state["metrics"].get("cache_hits", 0) == 1


def test_cache_miss_does_not_increment_hit_counter(mock_llm, mock_state):
    from llm_cache import ExactMatchCache
    cache = ExactMatchCache(mock_llm)
    cache.invoke([HumanMessage(content="unique Q1")], state=mock_state)
    assert mock_state["metrics"].get("cache_hits", 0) == 0


def test_cache_respects_ttl(mock_llm, mock_state):
    from llm_cache import ExactMatchCache
    cache = ExactMatchCache(mock_llm, ttl_seconds=0.05)
    msgs = [HumanMessage(content="ttl test")]
    cache.invoke(msgs, state=mock_state)
    time.sleep(0.1)
    cache.invoke(msgs, state=mock_state)
    assert mock_llm.invoke.call_count == 2  # TTL expired → cache miss


def test_cache_respects_max_size(mock_llm, mock_state):
    from llm_cache import ExactMatchCache
    cache = ExactMatchCache(mock_llm, max_size=2)
    cache.invoke([HumanMessage(content="q1")], state=mock_state)
    cache.invoke([HumanMessage(content="q2")], state=mock_state)
    cache.invoke([HumanMessage(content="q3")], state=mock_state)  # evicts q1
    # Re-request q1 — should be a cache miss (evicted)
    cache.invoke([HumanMessage(content="q1")], state=mock_state)
    assert mock_llm.invoke.call_count == 4


def test_cache_hit_does_not_increment_llm_calls_total(mock_llm, mock_state):
    from llm_cache import ExactMatchCache
    cache = ExactMatchCache(mock_llm)
    msgs = [HumanMessage(content="cached question")]
    mock_state["metrics"]["llm_calls_total"] = 0
    cache.invoke(msgs, state=mock_state)
    first_count = mock_state["metrics"]["llm_calls_total"]
    cache.invoke(msgs, state=mock_state)
    second_count = mock_state["metrics"]["llm_calls_total"]
    assert second_count == first_count  # cache hit → no new LLM call counted


# ─── PrefixStabilizer ────────────────────────────────────────────────────────

def test_prefix_stabilizer_puts_system_first():
    from llm_cache import PrefixStabilizer
    ps = PrefixStabilizer()
    msgs = [
        HumanMessage(content="hi"),
        SystemMessage(content="You are an expert"),
    ]
    result = ps.stabilize(msgs)
    assert isinstance(result[0], SystemMessage)


def test_prefix_stabilizer_keeps_system_content():
    from llm_cache import PrefixStabilizer
    ps = PrefixStabilizer()
    system_text = "You are the Machine Expert."
    msgs = [HumanMessage(content="question"), SystemMessage(content=system_text)]
    result = ps.stabilize(msgs)
    assert result[0].content == system_text


def test_prefix_stabilizer_no_system_message_unchanged():
    from llm_cache import PrefixStabilizer
    ps = PrefixStabilizer()
    msgs = [HumanMessage(content="a"), HumanMessage(content="b")]
    result = ps.stabilize(msgs)
    assert len(result) == 2
    assert isinstance(result[0], HumanMessage)


def test_prefix_stabilizer_multiple_system_messages_deduped():
    from llm_cache import PrefixStabilizer
    ps = PrefixStabilizer()
    msgs = [
        SystemMessage(content="first"),
        HumanMessage(content="q"),
        SystemMessage(content="second"),
    ]
    result = ps.stabilize(msgs)
    system_msgs = [m for m in result if isinstance(m, SystemMessage)]
    assert len(system_msgs) == 1  # duplicates merged/dropped


# ─── GeminiContextCacheManager ───────────────────────────────────────────────

def test_gemini_cache_manager_rejects_small_corpus():
    from llm_cache import GeminiContextCacheManager
    mgr = GeminiContextCacheManager(min_tokens=32000)
    small_docs = ["short document"]
    result = mgr.create_cache(small_docs, model="gemini-2.5-pro")
    assert result is None  # too small, no cache created


def test_gemini_cache_manager_accepts_large_corpus():
    from llm_cache import GeminiContextCacheManager
    mgr = GeminiContextCacheManager(min_tokens=100)  # low threshold for test
    # Each word ≈ 1 token in rough estimate; 400-char doc ≈ 100 tokens
    large_docs = ["word " * 500]
    result = mgr.create_cache(large_docs, model="gemini-2.5-pro")
    assert result is not None  # returns cache handle or marker dict


def test_gemini_cache_manager_cache_handle_has_token_count():
    from llm_cache import GeminiContextCacheManager
    mgr = GeminiContextCacheManager(min_tokens=100)
    large_docs = ["word " * 500]
    result = mgr.create_cache(large_docs, model="gemini-2.5-pro")
    assert "token_count" in result
