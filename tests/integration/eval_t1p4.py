"""Integration evaluator for T1-P4: compress_messages wired in _invoke_stage1.

Does NOT require API key.

Run with:
    KMP_DUPLICATE_LIB_OK=TRUE python tests/integration/eval_t1p4.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


def test_compress_messages_is_called():
    """Verify context_assembler.compress_messages is imported in delegate_tools."""
    import delegate_tools
    import inspect
    src = inspect.getsource(delegate_tools._invoke_stage1)
    assert "compress_messages" in src, (
        "compress_messages not found in _invoke_stage1 — T1-P4 not wired"
    )
    print("[PASS] compress_messages found in _invoke_stage1")


def test_long_history_is_compressed():
    """Long message history must be shortened before sub-state is built."""
    from context_assembler import DynamicContextAssembler
    from langchain_core.messages import HumanMessage, ToolMessage

    ca = DynamicContextAssembler()
    # ToolMessages with >800 chars each will be truncated by Layer 1
    big_msgs = [
        ToolMessage(content="x" * 5000, tool_call_id=f"tc_{i}")
        for i in range(5)
    ]
    compressed = ca.compress_messages(big_msgs, target_tokens=8000)
    total_chars = sum(len(str(m.content)) for m in compressed)
    original_chars = sum(len(str(m.content)) for m in big_msgs)
    assert total_chars < original_chars, (
        f"compress_messages had no effect: {total_chars} >= {original_chars}"
    )
    print(f"[PASS] compressed {original_chars} chars → {total_chars} chars")


if __name__ == "__main__":
    test_compress_messages_is_called()
    test_long_history_is_compressed()
    print("[eval_t1p4] ALL PASSED")
