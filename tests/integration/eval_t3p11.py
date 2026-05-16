"""Integration evaluator for T3-P11: Cost Tracking + Run Report.

Does NOT require API key.

Run with:
    KMP_DUPLICATE_LIB_OK=TRUE python tests/integration/eval_t3p11.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


def test_compute_cost_usd_with_real_tokens():
    """cost_usd must be a positive float when tokens > 0."""
    from core.run_logger import _compute_cost_usd
    cost = _compute_cost_usd(10_000, 2_000)
    assert cost is not None, "Expected float, got None"
    assert cost > 0, f"Expected positive cost, got {cost}"
    # Sanity: 10K in × $1.25/M + 2K out × $10/M = $0.0125 + $0.020 = $0.0325
    assert abs(cost - 0.0325) < 0.0001, f"Unexpected cost value: {cost}"
    print(f"[PASS] compute_cost_usd(10K, 2K) = ${cost:.6f}")


def test_compute_cost_usd_returns_none_for_zero_tokens():
    """cost_usd must be None (not 0.0) when no tokens captured — avoids fake $0.0000."""
    from core.run_logger import _compute_cost_usd
    cost = _compute_cost_usd(0, 0)
    assert cost is None, f"Expected None for zero tokens, got {cost}"
    print("[PASS] compute_cost_usd(0, 0) = None (correctly signals no data)")


def test_extract_tokens_path1_llm_output():
    """_extract_tokens must read from llm_output.usage_metadata (primary path)."""
    from unittest.mock import MagicMock
    from core.harness_callback import _extract_tokens
    response = MagicMock()
    response.llm_output = {"usage_metadata": {"prompt_token_count": 500, "candidates_token_count": 150}}
    response.generations = []
    t_in, t_out = _extract_tokens(response)
    assert t_in == 500 and t_out == 150, f"Path 1 failed: {t_in}, {t_out}"
    print(f"[PASS] _extract_tokens path1: in={t_in} out={t_out}")


def test_extract_tokens_path2_generation_info():
    """_extract_tokens must fall back to generation_info.usage_metadata."""
    from unittest.mock import MagicMock
    from core.harness_callback import _extract_tokens
    response = MagicMock()
    response.llm_output = {}
    gen = MagicMock()
    gen.generation_info = {"usage_metadata": {"prompt_token_count": 300, "candidates_token_count": 80}}
    response.generations = [[gen]]
    t_in, t_out = _extract_tokens(response)
    assert t_in == 300 and t_out == 80, f"Path 2 failed: {t_in}, {t_out}"
    print(f"[PASS] _extract_tokens path2: in={t_in} out={t_out}")


def test_extract_tokens_path3_message_usage_metadata():
    """_extract_tokens must fall back to AIMessage.usage_metadata (new LangChain standard)."""
    from unittest.mock import MagicMock
    from core.harness_callback import _extract_tokens
    response = MagicMock()
    response.llm_output = {}
    gen = MagicMock()
    gen.generation_info = {}
    gen.message.usage_metadata = {"input_tokens": 400, "output_tokens": 120}
    response.generations = [[gen]]
    t_in, t_out = _extract_tokens(response)
    assert t_in == 400 and t_out == 120, f"Path 3 failed: {t_in}, {t_out}"
    print(f"[PASS] _extract_tokens path3: in={t_in} out={t_out}")


def test_write_run_report_creates_markdown():
    """_write_run_report must create a run_report.md with cost and quality sections."""
    import tempfile
    from pathlib import Path
    from core.run_logger import _write_run_report
    with tempfile.TemporaryDirectory() as tmp:
        summary = {
            "run_id": "test-run-001",
            "cost_usd": 0.0325,
            "tokens_in_total": 10_000,
            "tokens_out_total": 2_000,
            "llm_calls_total": 3,
            "llm_latency_ms_sum": 4500.0,
            "judge_triggered": True,
            "judge_factual_grounding": 3,
            "judge_completeness": 2,
            "judge_coherence": 3,
        }
        data = {"error_events": [], "metrics": {"evidence_utilization": 0.75}}
        _write_run_report(tmp, summary, data)
        report = Path(tmp) / "run_report.md"
        assert report.exists(), "run_report.md not created"
        content = report.read_text(encoding="utf-8")
        assert "$0.0325" in content, "Cost not in report"
        assert "10,000" in content, "tokens_in not in report"
        assert "3/3" in content or "3" in content, "Judge score not in report"
        print(f"[PASS] run_report.md created ({len(content)} chars)")


if __name__ == "__main__":
    test_compute_cost_usd_with_real_tokens()
    test_compute_cost_usd_returns_none_for_zero_tokens()
    test_extract_tokens_path1_llm_output()
    test_extract_tokens_path2_generation_info()
    test_extract_tokens_path3_message_usage_metadata()
    test_write_run_report_creates_markdown()
    print("[eval_t3p11] ALL PASSED")
