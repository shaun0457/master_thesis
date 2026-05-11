"""Integration evaluator for T2-P6: Blackboard Provenance.

Does NOT require API key.

Run with:
    KMP_DUPLICATE_LIB_OK=TRUE python tests/integration/eval_t2p6.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


def test_fact_entry_helper():
    """_fact_entry must produce correct provenance dict."""
    from bb_tools import _fact_entry
    e = _fact_entry("Fault 4 is reactor cooling water", "ME", "synthesize_and_cite", 0.9)
    assert e["claim"] == "Fault 4 is reactor cooling water"
    assert e["agent"] == "ME"
    assert e["source_tool"] == "synthesize_and_cite"
    assert e["confidence"] == 0.9
    assert "turn" in e
    print(f"[PASS] _fact_entry: {e}")


def test_bb_add_facts_normalizes_strings():
    """bb_add_facts must wrap plain strings in provenance dict."""
    import os as _os
    _os.environ["RUN_ID"] = "test_t2p6_norm"
    from bb_tools import bb_add_facts, get_bb_snapshot
    bb_add_facts("test_t2p6_norm", ["Plain string fact"], agent="ME", source_tool="test_tool")
    snap = get_bb_snapshot("test_t2p6_norm")
    facts = snap.get("facts", [])
    assert facts, "No facts written"
    last = facts[-1]
    assert isinstance(last, dict), f"fact is not a dict: {last}"
    assert "claim" in last, f"fact missing 'claim' key: {last}"
    assert last["claim"] == "Plain string fact"
    assert last["agent"] == "ME"
    print(f"[PASS] bb_add_facts normalized string: {last}")


def test_has_min_evidence_with_provenance():
    """supervisor_workflow._has_min_evidence must work with provenance dict facts."""
    from supervisor_workflow import _has_min_evidence
    state = {"blackboard": {"facts": [
        {"claim": "Fault 4 is reactor cooling water step change",
         "agent": "ME", "confidence": 0.9, "source_tool": "retrieve_knowledge", "turn": 1}
    ]}}
    assert _has_min_evidence(state), "_has_min_evidence broken with provenance dicts"
    print("[PASS] _has_min_evidence works with provenance dict facts")


def test_no_direct_facts_append():
    """No file except bb_tools.py should use ["facts"].append directly."""
    import glob
    import re
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    # Match ["facts"].append or ['facts'].append as standalone (not as substr of "artifacts")
    _PATTERN = re.compile(r'\["facts"\]\.append|\'facts\'\]\.append')
    violations = []
    for path in glob.glob(os.path.join(root, "*.py")):
        fname = os.path.basename(path)
        if fname in ("bb_tools.py",) or "test_" in fname or "__pycache__" in path:
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            src = f.read()
        if _PATTERN.search(src):
            violations.append(fname)
    assert not violations, f'["facts"].append found outside bb_tools.py: {violations}'
    print("[PASS] No direct [\"facts\"].append outside bb_tools.py")


if __name__ == "__main__":
    test_fact_entry_helper()
    test_bb_add_facts_normalizes_strings()
    test_has_min_evidence_with_provenance()
    test_no_direct_facts_append()
    print("[eval_t2p6] ALL PASSED")
