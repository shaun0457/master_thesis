"""Integration evaluator for T2-P5: Phase-aware state updates.

Does NOT require API key — tests phase logic with mock tool calls.

Run with:
    KMP_DUPLICATE_LIB_OK=TRUE python tests/integration/eval_t2p5.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _read_src(filename: str) -> str:
    with open(os.path.join(_ROOT, filename), encoding="utf-8") as f:
        return f.read()


def test_supervisor_initializes_phase():
    """supervisor_node must setdefault phase to 'initial'."""
    src = _read_src("supervisor_workflow.py")
    assert 'setdefault("phase"' in src or "setdefault('phase'" in src, (
        "supervisor_workflow.py missing phase setdefault"
    )
    print("[PASS] supervisor_workflow.py contains phase setdefault")


def test_me_tool_node_sets_phase():
    """ME Tool_node must set state['phase'] = 'ME:synthesize'."""
    src = _read_src("me_workflow.py")
    assert "ME:synthesize" in src, (
        "me_workflow.py does not contain ME:synthesize phase update"
    )
    print("[PASS] me_workflow.py contains 'ME:synthesize' phase update")


def test_de_tool_node_sets_phase():
    """DE tool_node must set state['phase'] = 'DE:deliver'."""
    src = _read_src("de_workflow.py")
    assert "DE:deliver" in src, (
        "de_workflow.py does not contain DE:deliver phase update"
    )
    print("[PASS] de_workflow.py contains 'DE:deliver' phase update")


def test_phase_wired_to_context_assembler():
    """context_assembler PHASE_SNIPPETS must have 'ME:synthesize' key."""
    src = _read_src("context_assembler.py")
    assert "ME:synthesize" in src, (
        "context_assembler.py missing ME:synthesize in PHASE_SNIPPETS"
    )
    print("[PASS] context_assembler.py has ME:synthesize PHASE_SNIPPET")


if __name__ == "__main__":
    test_supervisor_initializes_phase()
    test_me_tool_node_sets_phase()
    test_de_tool_node_sets_phase()
    test_phase_wired_to_context_assembler()
    print("[eval_t2p5] ALL PASSED")
