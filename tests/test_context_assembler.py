"""
TDD tests for context_assembler.py — written BEFORE implementation.
"""
import pytest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


def test_all_agents_have_static_core():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    for agent in ["Supervisor", "ME", "DE", "DS"]:
        prompt = a.assemble_system_prompt(agent)
        assert len(prompt) > 10, f"{agent} has empty static core"


def test_system_prompt_under_300_tokens_supervisor():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    prompt = a.assemble_system_prompt("Supervisor")
    tokens = len(prompt) // 4
    assert tokens <= 300, f"Supervisor prompt too long: {tokens} tokens"


def test_system_prompt_under_300_tokens_all_agents():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    for agent in ["Supervisor", "ME", "DE", "DS"]:
        for phase in ["default", "synthesize", "deliver", "error_recovery"]:
            prompt = a.assemble_system_prompt(agent, phase=phase)
            tokens = len(prompt) // 4
            assert tokens <= 300, f"{agent}:{phase} too long: {tokens} tokens"


def test_phase_snippet_me_synthesize():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    prompt = a.assemble_system_prompt("ME", phase="synthesize")
    assert "synthesize_and_cite" in prompt


def test_phase_snippet_de_deliver():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    prompt = a.assemble_system_prompt("DE", phase="deliver")
    assert "deliver_dataframe" in prompt


def test_error_recovery_snippet_injected():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    prompt = a.assemble_system_prompt("ME", phase="error_recovery")
    assert "failed" in prompt.lower() or "error" in prompt.lower()


def test_protocol_debate_injected():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    prompt = a.assemble_system_prompt("Supervisor", protocol="debate")
    assert "debate" in prompt.lower() or "challenge" in prompt.lower() or "cite" in prompt.lower()


def test_unknown_agent_raises():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    with pytest.raises(KeyError):
        a.assemble_system_prompt("UnknownAgent")


def test_estimate_tokens_nonzero():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    msgs = [HumanMessage(content="hello world, this is a test message")]
    tokens = a.estimate_tokens(msgs)
    assert tokens >= 1


def test_estimate_tokens_scales_with_length():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    short = [HumanMessage(content="hi")]
    long = [HumanMessage(content="x" * 1000)]
    assert a.estimate_tokens(long) > a.estimate_tokens(short)


def test_compress_reduces_token_count():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    msgs = [HumanMessage(content="x" * 4000) for _ in range(20)]
    original = a.estimate_tokens(msgs)
    compressed = a.compress_messages(msgs, target_tokens=2000)
    assert a.estimate_tokens(compressed) < original


def test_compress_preserves_first_human_message():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    first = HumanMessage(content="Original user question about TEP")
    msgs = [first] + [AIMessage(content="x" * 2000) for _ in range(15)]
    compressed = a.compress_messages(msgs, target_tokens=500)
    assert any(isinstance(m, HumanMessage) and "Original user question" in m.content
               for m in compressed)


def test_compress_truncates_tool_messages():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    long_tool_msg = ToolMessage(content="x" * 5000, tool_call_id="abc123")
    msgs = [long_tool_msg]
    compressed = a.compress_messages(msgs, target_tokens=10000)
    result_content = str(compressed[0].content)
    assert len(result_content) < 5000


def test_assemble_context_messages_includes_task():
    from core.context_assembler import DynamicContextAssembler
    a = DynamicContextAssembler()
    state = {"messages": [], "metrics": {}}
    result = a.assemble_context_messages(state, task_text="Analyze reactor temperature", agent="DE")
    combined = " ".join(str(m.content) for m in result)
    assert "Analyze reactor temperature" in combined
