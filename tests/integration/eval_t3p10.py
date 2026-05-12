"""Integration evaluator for T3-P10: Golden Dataset Eval Pipeline.

Does NOT require API key — uses --dry-run mode.

Run with:
    KMP_DUPLICATE_LIB_OK=TRUE python tests/integration/eval_t3p10.py
"""
import os
import sys
import json
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")

EVAL_DIR = Path(__file__).parent.parent.parent / "eval"


def test_golden_qa_json_exists_and_valid():
    """golden_qa.json must exist and contain at least 5 questions."""
    path = EVAL_DIR / "golden_qa.json"
    assert path.exists(), f"golden_qa.json not found at {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list), "golden_qa.json must be a list"
    assert len(data) >= 5, f"Expected >= 5 questions, got {len(data)}"
    for item in data:
        assert "id" in item, f"Missing 'id' in item: {item}"
        assert "question" in item
        assert "expected_keywords" in item
        assert "agent_path" in item
    print(f"[PASS] golden_qa.json: {len(data)} questions, all fields present")


def test_run_eval_dry_run():
    """run_eval.py --dry-run must succeed and write results.json."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_eval", EVAL_DIR / "run_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    results = mod.run_eval(dry_run=True)
    assert isinstance(results, list), "run_eval must return list"
    assert len(results) >= 5, f"Expected >= 5 results, got {len(results)}"
    for r in results:
        assert "id" in r
        assert "keyword_hit_rate" in r
        assert r["dry_run"] is True
    print(f"[PASS] run_eval dry-run: {len(results)} results written")


def test_results_json_written():
    """results.json must exist after dry-run."""
    path = EVAL_DIR / "results.json"
    assert path.exists(), f"results.json not found — run eval first"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) >= 5
    print(f"[PASS] results.json: {len(data)} entries")


def test_regression_gate_passes_on_dry_run():
    """regression_gate.py must exit 0 on dry-run results."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("regression_gate", EVAL_DIR / "regression_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    results_path = EVAL_DIR / "results.json"
    golden_path  = EVAL_DIR / "golden_qa.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    golden  = json.loads(golden_path.read_text(encoding="utf-8"))

    ok, failures = mod.gate(results, golden)
    assert ok, f"Regression gate failed: {failures}"
    print(f"[PASS] regression_gate: all checks passed")


def test_regression_gate_catches_low_hit_rate():
    """Gate must fail when keyword_hit_rate is 0 for all questions."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("regression_gate", EVAL_DIR / "regression_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    golden_path = EVAL_DIR / "golden_qa.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    bad_results = [
        {"id": item["id"], "keyword_hit_rate": 0.0, "keyword_hits": 0,
         "ds_verdict": None, "me_citation_coverage": None}
        for item in golden
    ]
    ok, failures = mod.gate(bad_results, golden)
    assert not ok, "Gate should have failed on 0% hit rate"
    assert any("pass rate" in f.lower() or "keyword" in f.lower() for f in failures)
    print(f"[PASS] regression_gate correctly caught low hit rate: {failures[0]}")


if __name__ == "__main__":
    test_golden_qa_json_exists_and_valid()
    test_run_eval_dry_run()
    test_results_json_written()
    test_regression_gate_passes_on_dry_run()
    test_regression_gate_catches_low_hit_rate()
    print("[eval_t3p10] ALL PASSED")
