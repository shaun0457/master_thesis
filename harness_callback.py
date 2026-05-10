"""
HarnessCallback — LangChain BaseCallbackHandler that records per-LLM-call
metrics (count, latency, token usage) into the agent state dict.

Usage:
    res = executor.invoke(input, config={"callbacks": [HarnessCallback(state, "ME")]})

The callback is bound at invoke time (not module load time) so it always
holds a reference to the current state, not a stale snapshot.
"""
import time
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


class HarnessCallback(BaseCallbackHandler):
    def __init__(self, state: dict, agent_tag: str):
        self.state = state
        self.agent_tag = agent_tag
        self._t0: float = 0.0

    def on_llm_start(self, serialized, messages, **kwargs):
        self._t0 = time.time() * 1000

    def on_llm_end(self, response: LLMResult, **kwargs):
        latency = time.time() * 1000 - self._t0
        from metrics import _ensure_metrics
        m = _ensure_metrics(self.state)
        m["llm_calls_total"] = m.get("llm_calls_total", 0) + 1
        m["llm_latency_ms_sum"] = m.get("llm_latency_ms_sum", 0.0) + latency
        usage = (getattr(response, "llm_output", {}) or {})
        token_meta = usage.get("usage_metadata") or {}
        m["tokens_in_total"] = m.get("tokens_in_total", 0) + token_meta.get("prompt_token_count", 0)
        m["tokens_out_total"] = m.get("tokens_out_total", 0) + token_meta.get("candidates_token_count", 0)
