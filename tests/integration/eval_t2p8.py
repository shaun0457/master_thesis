"""Integration evaluator for T2-P8: DS Python code sandbox.

Does NOT require API key.

Run with:
    KMP_DUPLICATE_LIB_OK=TRUE python tests/integration/eval_t2p8.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


def test_basic_execution():
    """Simple code must produce expected stdout."""
    from ds_tools import _execute_python_subprocess
    result = _execute_python_subprocess("print('hello sandbox')", timeout=10)
    assert "hello sandbox" in result.get("stdout", ""), f"Expected stdout, got {result}"
    assert result.get("returncode") == 0
    print(f"[PASS] basic exec: {result}")


def test_timeout():
    """Code that runs forever must return timeout error after timeout seconds."""
    from ds_tools import _execute_python_subprocess
    result = _execute_python_subprocess("import time; time.sleep(999)", timeout=3)
    assert "error" in result or "Timeout" in str(result.get("error", "")), (
        f"Expected timeout error, got {result}"
    )
    print(f"[PASS] timeout: {result}")


def test_syntax_error():
    """Code with syntax error must return stderr, not crash."""
    from ds_tools import _execute_python_subprocess
    result = _execute_python_subprocess("def foo(: pass", timeout=10)
    assert result.get("returncode") != 0 or "error" in result.get("stderr", "").lower() or "error" in result
    print(f"[PASS] syntax error handled: {result}")


def test_execute_python_code_tool():
    """The @tool function must still be callable and return a string."""
    from ds_tools import execute_python_code
    result = execute_python_code.invoke({"code": "print(1+1)"})
    assert isinstance(result, str), f"Expected str, got {type(result)}"
    print(f"[PASS] execute_python_code tool returns string: {result!r}")


if __name__ == "__main__":
    test_basic_execution()
    test_timeout()
    test_syntax_error()
    test_execute_python_code_tool()
    print("[eval_t2p8] ALL PASSED")
