"""Integration evaluator for T1-P1: HarnessCallback.

Requires a real GOOGLE_API_KEY. Run with:
    KMP_DUPLICATE_LIB_OK=TRUE python tests/integration/eval_t1p1.py

Acceptance criteria (from production plan):
  - metrics["llm_calls_total"] >= 1  (callback triggered)
  - metrics["llm_latency_ms_sum"] > 0  (on_llm_start wired)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def test_callback_metrics():
    from core.common import llm
    from core.harness_callback import HarnessCallback

    state: dict = {"messages": [], "metrics": {}}
    llm.invoke("Say 'ok'", config={"callbacks": [HarnessCallback(state, "test")]})
    m = state["metrics"]

    assert m.get("llm_calls_total", 0) >= 1, f"callback not triggered: {m}"
    assert m.get("llm_latency_ms_sum", 0) > 0, (
        f"latency not measured (on_llm_start missing?): {m}"
    )
    print(
        f"[PASS] llm_calls_total={m['llm_calls_total']} "
        f"latency={m['llm_latency_ms_sum']:.0f}ms "
        f"tokens_in={m.get('tokens_in_total', 0)}"
    )


if __name__ == "__main__":
    test_callback_metrics()
    print("[eval_t1p1] ALL PASSED")
