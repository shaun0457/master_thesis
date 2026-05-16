"""
Application-level caching layer for LLM calls.

ExactMatchCache      — LRU + TTL cache keyed by sha256(messages)
PrefixStabilizer     — ensures SystemMessage is always first (maximizes
                       implicit Gemini KV cache hits on stable prefixes)
GeminiContextCacheManager — stub for Gemini Context Caching API (ME corpus only)
                             Real API requires ≥32K tokens; this class enforces
                             that minimum and returns a cache-handle dict.
"""
from __future__ import annotations
import hashlib
import json
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage, SystemMessage


# ─── helpers ─────────────────────────────────────────────────────────────────

def _messages_key(messages: List[BaseMessage]) -> str:
    parts = [f"{type(m).__name__}:{getattr(m, 'content', '')}" for m in messages]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def _estimate_tokens(docs: List[str]) -> int:
    return sum(len(d) for d in docs) // 4


# ─── ExactMatchCache ─────────────────────────────────────────────────────────

class ExactMatchCache:
    """
    Wraps a LangChain LLM and caches responses by message fingerprint.
    Cache hit: returns stored response without calling the LLM.
    Cache miss: calls LLM, stores response, returns response.
    """

    def __init__(self, llm: Any, *, max_size: int = 256, ttl_seconds: float = 300.0):
        self.llm = llm
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()

    def _is_fresh(self, ts: float) -> bool:
        return (time.time() - ts) < self.ttl

    def _evict_stale(self) -> None:
        stale = [k for k, (_, ts) in self._store.items() if not self._is_fresh(ts)]
        for k in stale:
            del self._store[k]

    def invoke(self, messages: List[BaseMessage], *, state: Dict[str, Any], **kwargs: Any) -> Any:
        m = state.setdefault("metrics", {})
        key = _messages_key(messages)

        self._evict_stale()
        if key in self._store:
            response, _ = self._store[key]
            if self._is_fresh(_):
                m["cache_hits"] = m.get("cache_hits", 0) + 1
                # Move to end (LRU access)
                self._store.move_to_end(key)
                return response

        # Cache miss — call LLM
        response = self.llm.invoke(messages, **kwargs)
        m["llm_calls_total"] = m.get("llm_calls_total", 0) + 1

        # Evict oldest if at capacity
        while len(self._store) >= self.max_size:
            self._store.popitem(last=False)

        self._store[key] = (response, time.time())
        self._store.move_to_end(key)
        return response


# ─── PrefixStabilizer ────────────────────────────────────────────────────────

class PrefixStabilizer:
    """
    Reorders messages so the SystemMessage always appears first.
    When multiple SystemMessages exist, keeps only the last one (most specific).
    Stable prefix → better implicit Gemini KV cache hit rate.
    """

    def stabilize(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        if not system_msgs:
            return list(messages)

        # Keep last SystemMessage (most specific / most recently injected)
        canonical_system = system_msgs[-1]
        return [canonical_system] + non_system


# ─── GeminiContextCacheManager ───────────────────────────────────────────────

class GeminiContextCacheManager:
    """
    Manages Gemini Context Caching API for large, stable corpora (e.g. ME's
    TEP document set).  The real API requires ≥32K tokens; this class enforces
    min_tokens and returns a stub cache-handle dict.

    In production, swap the stub body with google.generativeai cache calls.
    """

    def __init__(self, *, min_tokens: int = 32_000):
        self.min_tokens = min_tokens

    def create_cache(self, docs: List[str], *, model: str) -> Optional[Dict[str, Any]]:
        token_count = _estimate_tokens(docs)
        if token_count < self.min_tokens:
            return None
        return {
            "model": model,
            "token_count": token_count,
            "status": "stub",
        }
