"""Integration evaluator for T3-P12: Delegation Contract.

Does NOT require API key.

Run with:
    KMP_DUPLICATE_LIB_OK=TRUE python tests/integration/eval_t3p12.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


def test_format_task_contract_with_criteria():
    """Contract block must contain both task and success_criteria."""
    from delegate_tools import _format_task_contract
    block = _format_task_contract(
        "Compute mean of XMEAS_1",
        "Returns a float value and explains the unit"
    )
    assert "[TASK CONTRACT]" in block
    assert "Compute mean of XMEAS_1" in block
    assert "Returns a float value" in block
    print(f"[PASS] contract with criteria:\n{block}")


def test_format_task_contract_without_criteria():
    """Contract block must still work when no criteria provided."""
    from delegate_tools import _format_task_contract
    block = _format_task_contract("List all fault types")
    assert "[TASK CONTRACT]" in block
    assert "List all fault types" in block
    assert "Success criteria" not in block
    print(f"[PASS] contract without criteria:\n{block}")


def test_invoke_stage1_source_uses_format_task_contract():
    """_invoke_stage1 must use _format_task_contract in anchor construction."""
    import inspect
    import delegate_tools
    src = inspect.getsource(delegate_tools._invoke_stage1)
    assert "_format_task_contract" in src, "_invoke_stage1 missing _format_task_contract call"
    assert "success_criteria" in src, "_invoke_stage1 missing success_criteria param"
    print("[PASS] _invoke_stage1 uses _format_task_contract and success_criteria")


def test_supervisor_tools_have_success_criteria():
    """All three delegate tool schemas must include success_criteria field."""
    from supervisor_tools import DelegateMEArgs, DelegateDEArgs, DelegateDSArgs
    for cls in (DelegateMEArgs, DelegateDEArgs, DelegateDSArgs):
        fields = cls.model_fields
        assert "success_criteria" in fields, f"{cls.__name__} missing success_criteria field"
        field = fields["success_criteria"]
        assert not field.is_required(), f"{cls.__name__}.success_criteria must be optional"
    print("[PASS] all delegate tool schemas have optional success_criteria")


def test_anchor_contains_contract_block():
    """After _format_task_contract + _format_bb_index, anchor content must have both sections."""
    from delegate_tools import _format_task_contract, _format_bb_index
    from langchain_core.messages import HumanMessage

    bb = {"facts": [{"claim": "Fault 4 is cooling water", "agent": "ME", "confidence": 0.9}]}
    task = "What is the root cause of Fault 4?"
    criteria = "Answer cites the exact fault mechanism with evidence"

    bb_index = _format_bb_index(bb)
    contract = _format_task_contract(task, criteria)
    anchor = HumanMessage(content=f"{bb_index}\n\n{contract}")

    assert "[BLACKBOARD INDEX]" in anchor.content
    assert "[TASK CONTRACT]" in anchor.content
    assert "Success criteria:" in anchor.content
    assert "Fault 4 is cooling water" in anchor.content
    print(f"[PASS] anchor contains both BLACKBOARD INDEX and TASK CONTRACT sections")


if __name__ == "__main__":
    test_format_task_contract_with_criteria()
    test_format_task_contract_without_criteria()
    test_invoke_stage1_source_uses_format_task_contract()
    test_supervisor_tools_have_success_criteria()
    test_anchor_contains_contract_block()
    print("[eval_t3p12] ALL PASSED")
