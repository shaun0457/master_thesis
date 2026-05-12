"""Integration evaluator for T3-P9: tenacity retry wrapper for Gemini 503/429.

Does NOT require API key.

Run with:
    KMP_DUPLICATE_LIB_OK=TRUE python tests/integration/eval_t3p9.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


def test_invoke_with_retry_succeeds_after_transient_error():
    """Function should retry on ServiceUnavailable and succeed on second call."""
    from unittest.mock import MagicMock, patch
    from google.api_core.exceptions import ServiceUnavailable
    from common import invoke_with_retry

    call_count = 0
    def fake_invoke(inputs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ServiceUnavailable("transient error")
        return {"output": "ok"}

    result = invoke_with_retry(fake_invoke, {"question": "test"})
    assert result == {"output": "ok"}, f"Expected success result, got {result}"
    assert call_count == 2, f"Expected 2 calls (1 fail + 1 success), got {call_count}"
    print(f"[PASS] retry succeeded on attempt 2: call_count={call_count}")


def test_invoke_with_retry_raises_after_max_attempts():
    """Function should reraise after 3 failed attempts."""
    from unittest.mock import MagicMock
    from google.api_core.exceptions import ServiceUnavailable
    from common import invoke_with_retry

    call_count = 0
    def always_fail(inputs):
        nonlocal call_count
        call_count += 1
        raise ServiceUnavailable("persistent error")

    try:
        invoke_with_retry(always_fail, {})
        assert False, "Should have raised"
    except ServiceUnavailable:
        pass
    assert call_count == 3, f"Expected 3 attempts, got {call_count}"
    print(f"[PASS] reraise after {call_count} attempts")


def test_invoke_with_retry_retries_on_resource_exhausted():
    """Function should also retry on ResourceExhausted (429)."""
    from google.api_core.exceptions import ResourceExhausted
    from common import invoke_with_retry

    call_count = 0
    def fail_once(inputs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ResourceExhausted("quota exceeded")
        return "done"

    result = invoke_with_retry(fail_once, {})
    assert result == "done"
    assert call_count == 2
    print(f"[PASS] ResourceExhausted retry works: call_count={call_count}")


def test_invoke_with_retry_no_retry_on_other_errors():
    """Non-retriable errors should propagate immediately without retry."""
    from common import invoke_with_retry

    call_count = 0
    def fail_value(inputs):
        nonlocal call_count
        call_count += 1
        raise ValueError("bad input")

    try:
        invoke_with_retry(fail_value, {})
        assert False, "Should have raised"
    except ValueError:
        pass
    assert call_count == 1, f"Expected 1 call (no retry), got {call_count}"
    print(f"[PASS] ValueError not retried: call_count={call_count}")


def test_invoke_with_retry_in_source():
    """common.py must export invoke_with_retry and use tenacity."""
    import inspect
    import common
    src = inspect.getsource(common)
    assert "invoke_with_retry" in src, "common.py missing invoke_with_retry"
    assert "tenacity" in src or "retry" in src.lower(), "common.py missing retry logic"
    print("[PASS] invoke_with_retry present in common.py")


if __name__ == "__main__":
    test_invoke_with_retry_succeeds_after_transient_error()
    test_invoke_with_retry_raises_after_max_attempts()
    test_invoke_with_retry_retries_on_resource_exhausted()
    test_invoke_with_retry_no_retry_on_other_errors()
    test_invoke_with_retry_in_source()
    print("[eval_t3p9] ALL PASSED")
