"""Integration evaluator for T2-P7: evidence_utilization metric.

Does NOT require API key.

Run with:
    KMP_DUPLICATE_LIB_OK=TRUE python tests/integration/eval_t2p7.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


def test_evidence_utilization_basic():
    """Keyword from blackboard fact must be found in answer → score > 0."""
    from core.metrics import compute_evidence_utilization
    state = {"blackboard": {"facts": [
        {"claim": "Fault 4 is reactor cooling water step change",
         "agent": "ME", "confidence": 0.9}
    ]}}
    score = compute_evidence_utilization(state, "Fault 4 involves reactor cooling water temperature.")
    assert 0 < score <= 1.0, f"Expected score > 0, got {score}"
    assert state["metrics"].get("evidence_utilization") == score
    print(f"[PASS] evidence_utilization = {score:.2f}")


def test_evidence_utilization_no_match():
    """Completely unrelated answer must score 0."""
    from core.metrics import compute_evidence_utilization
    state = {"blackboard": {"facts": [
        {"claim": "reactor cooling water fault", "agent": "ME", "confidence": 0.9}
    ]}}
    score = compute_evidence_utilization(state, "The weather today is sunny and pleasant.")
    assert score == 0.0, f"Expected 0, got {score}"
    print(f"[PASS] no match → score = {score}")


def test_stop_words_do_not_inflate():
    """Fact containing only stop words must score 0 against a stop-word-only answer."""
    from core.metrics import compute_evidence_utilization
    state = {"blackboard": {"facts": [
        {"claim": "The reactor is a hot unit", "agent": "ME", "confidence": 0.9}
    ]}}
    score = compute_evidence_utilization(state, "The is a an or and to it")
    assert score == 0.0, f"Stop words inflated score to {score}"
    print(f"[PASS] stop words → score = {score}")


def test_empty_blackboard_returns_zero():
    """Empty blackboard must return 0.0."""
    from core.metrics import compute_evidence_utilization
    state = {"blackboard": {"facts": []}}
    score = compute_evidence_utilization(state, "Some answer text here.")
    assert score == 0.0
    print("[PASS] empty blackboard → 0.0")


def test_string_fact_also_handled():
    """Legacy string facts (pre-T2-P6) must still be handled gracefully."""
    from core.metrics import compute_evidence_utilization
    state = {"blackboard": {"facts": ["reactor cooling water fault 4"]}}
    score = compute_evidence_utilization(state, "reactor cooling water caused fault 4.")
    assert score > 0.0, f"String fact not handled, score={score}"
    print(f"[PASS] string fact handled → score = {score:.2f}")


if __name__ == "__main__":
    test_evidence_utilization_basic()
    test_evidence_utilization_no_match()
    test_stop_words_do_not_inflate()
    test_empty_blackboard_returns_zero()
    test_string_fact_also_handled()
    print("[eval_t2p7] ALL PASSED")
