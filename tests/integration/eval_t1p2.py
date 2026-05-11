"""Integration evaluator for T1-P2: additive metrics merge.

Does NOT require API key — purely tests the _merge_metrics helper logic.

Run with:
    python tests/integration/eval_t1p2.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# delegate_tools imports common which requires GOOGLE_API_KEY at module load;
# set a dummy value so the import succeeds without a real key.
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


def test_additive_merge():
    from delegate_tools import _merge_metrics

    parent = {"llm_calls_total": 2, "tokens_in_total": 100, "some_string": "old"}
    child = {"llm_calls_total": 3, "tokens_in_total": 50, "some_string": "new", "cache_hits": 1}

    _merge_metrics(parent, child)

    assert parent["llm_calls_total"] == 5, f"Expected 5, got {parent['llm_calls_total']}"
    assert parent["tokens_in_total"] == 150, f"Expected 150, got {parent['tokens_in_total']}"
    assert parent["cache_hits"] == 1, f"Expected 1, got {parent['cache_hits']}"
    assert parent["some_string"] == "new", f"Non-additive key should be overwritten"
    print(f"[PASS] additive merge: {parent}")


def test_merge_does_not_overwrite_parent_calls():
    from delegate_tools import _merge_metrics

    # Simulates supervisor(2 calls) + ME subgraph(3 calls): total must be 5
    parent = {"llm_calls_total": 2, "llm_latency_ms_sum": 500.0}
    child = {"llm_calls_total": 3, "llm_latency_ms_sum": 800.0}

    _merge_metrics(parent, child)

    assert parent["llm_calls_total"] == 5, (
        f"Overwrite bug! Expected 5, got {parent['llm_calls_total']}"
    )
    assert parent["llm_latency_ms_sum"] == 1300.0, (
        f"Expected 1300.0, got {parent['llm_latency_ms_sum']}"
    )
    print(f"[PASS] no overwrite: {parent}")


if __name__ == "__main__":
    test_additive_merge()
    test_merge_does_not_overwrite_parent_calls()
    print("[eval_t1p2] ALL PASSED")
