"""
LLMCallHarness — wraps all LLM invoke calls in the MAS.

Records per-call metrics (latency, token counts, context size) without
changing the LLM object or the calling code's interface.

SelfEvaluator — asks the LLM to rate its own last output (confidence,
completeness, issues). Non-blocking: returns None on any parse failure.
"""
from __future__ import annotations
import json
import re
import time
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage, HumanMessage

from core.structured_outputs import SelfEvalResult
from core.context_assembler import DynamicContextAssembler

_assembler = DynamicContextAssembler()


def _now_ms() -> float:
    return time.time() * 1000


def _ensure_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    m = state.setdefault("metrics", {})
    m.setdefault("llm_calls_total", 0)
    m.setdefault("tokens_in_total", 0)
    m.setdefault("tokens_out_total", 0)
    m.setdefault("llm_latency_ms_sum", 0.0)
    m.setdefault("context_tokens_est_max", 0)
    return m


def _extract_json(text: str) -> str:
    """Extract first JSON object from text, stripping markdown fences."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


class LLMCallHarness:
    """
    Thin wrapper around any LangChain LLM.
    Usage: replace llm.invoke(msgs) with harness.invoke(msgs, agent=..., state=state)
    """

    def __init__(self, llm: Any):
        self.llm = llm

    def invoke(
        self,
        messages: List[BaseMessage],
        *,
        agent: str,
        state: Dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        m = _ensure_metrics(state)

        t0 = _now_ms()
        response = self.llm.invoke(messages, **kwargs)
        latency = _now_ms() - t0

        m["llm_calls_total"] += 1
        m["llm_latency_ms_sum"] += latency

        # Token counting from response metadata (Gemini returns usage_metadata)
        usage = getattr(response, "usage_metadata", None) or {}
        m["tokens_in_total"] += usage.get("input_tokens", 0)
        m["tokens_out_total"] += usage.get("output_tokens", 0)

        # Track context window size
        est = _assembler.estimate_tokens(messages)
        m["context_tokens_est_max"] = max(m["context_tokens_est_max"], est)

        return response


class SelfEvaluator:
    """
    Asks the LLM to rate its own last output.
    Returns SelfEvalResult on success, None on any failure (never raises).
    """

    PROMPT = (
        "Evaluate your last output. Respond with JSON only, no explanation:\n"
        '{"confidence": 0.0-1.0, "completeness": 0.0-1.0, "issues": ["..."]}'
    )

    def evaluate(
        self,
        llm: Any,
        output_text: str,
        agent: str,
        state: Dict[str, Any],
    ) -> Optional[SelfEvalResult]:
        try:
            snippet = output_text[:600] if output_text else ""
            msgs = [HumanMessage(content=f"Output:\n{snippet}\n\n{self.PROMPT}")]
            raw = llm.invoke(msgs)
            result = SelfEvalResult.model_validate_json(_extract_json(raw.content))
            key = f"self_eval_confidence_{agent.lower()}"
            state.setdefault("metrics", {})[key] = result.confidence
            return result
        except Exception:
            return None
