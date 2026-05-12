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


def _extract_tokens(response: LLMResult) -> tuple:
    """Extract (tokens_in, tokens_out) from LLMResult, trying multiple locations.

    langchain-google-genai places token counts in different locations depending
    on version:
      Path 1: response.llm_output["usage_metadata"] — prompt_token_count / candidates_token_count
      Path 2: response.generations[0][0].generation_info["usage_metadata"] — same keys
      Path 3: response.generations[0][0].message.usage_metadata — input_tokens / output_tokens
                (newer LangChain AIMessage standard)
    Returns (0, 0) only if all three paths yield nothing.
    """
    # Path 1: llm_output (most common for Google models)
    llm_out = (getattr(response, "llm_output", None) or {})
    meta = (llm_out.get("usage_metadata") or {})
    t_in  = meta.get("prompt_token_count", 0)
    t_out = meta.get("candidates_token_count", 0)
    if t_in or t_out:
        return t_in, t_out

    # Path 2: generation_info inside the first generation
    try:
        gen_info = (response.generations[0][0].generation_info or {})
        meta2 = (gen_info.get("usage_metadata") or {})
        t_in  = meta2.get("prompt_token_count", 0)
        t_out = meta2.get("candidates_token_count", 0)
        if t_in or t_out:
            return t_in, t_out
    except (IndexError, AttributeError, TypeError):
        pass

    # Path 3: AIMessage.usage_metadata (LangChain >= 0.2 standard)
    try:
        msg_meta = (response.generations[0][0].message.usage_metadata or {})
        t_in  = msg_meta.get("input_tokens", 0)
        t_out = msg_meta.get("output_tokens", 0)
        if t_in or t_out:
            return t_in, t_out
    except (IndexError, AttributeError, TypeError):
        pass

    return 0, 0


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
        tokens_in, tokens_out = _extract_tokens(response)
        m["tokens_in_total"] = m.get("tokens_in_total", 0) + tokens_in
        m["tokens_out_total"] = m.get("tokens_out_total", 0) + tokens_out
