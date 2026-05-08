"""
DynamicContextAssembler — replaces the entire prompt/ folder and prompt_builder.py.

System prompt target: ≤300 tokens per agent (vs ~1,700 tokens with old .md cards).
Dynamic context (blackboard snapshot, task) is injected as HumanMessage, not system prompt.
"""
from __future__ import annotations
from typing import List, Dict, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage

CONTEXT_WARN_TOKENS = 12_000
MAX_TOOL_MSG_CHARS = 800

# Static core: role + single most-critical rule (~50 tokens each)
STATIC_CORES: Dict[str, str] = {
    "Supervisor": (
        "You are the Supervisor of a 3-agent team (ME, DE, DS) analyzing "
        "the Tennessee Eastman chemical process (TEP).\n"
        "Your only actions: delegate_to_me | delegate_to_de | delegate_to_ds | final_answer.\n"
        "Never call final_answer without blackboard evidence from at least one expert."
    ),
    "ME": (
        "You are the Machine Expert (ME). Answer questions using TEP technical documents.\n"
        "Every factual claim MUST cite its source as [filename.pdf p.N].\n"
        "When you have sufficient evidence, call synthesize_and_cite."
    ),
    "DE": (
        "You are the Data Engineer (DE). Query the TEP SQLite database to extract sensor data.\n"
        "Validate query results before delivering. "
        "When the dataset is ready, call deliver_dataframe."
    ),
    "DS": (
        "You are the Data Scientist (DS). Analyze data from the blackboard using Python.\n"
        "Include: reproducible code, a seed value, and at least one figure per analysis."
    ),
}

# Phase snippets: injected only when relevant (~30-50 tokens)
PHASE_SNIPPETS: Dict[str, str] = {
    "ME:synthesize": (
        "You have sufficient evidence. Call synthesize_and_cite now with all collected chunks."
    ),
    "DE:deliver": (
        "The dataset is validated and ready. Call deliver_dataframe with path and row_count."
    ),
    "DS:model": (
        "Report: model name, hyperparameters, feature importances, and a reproducibility seed."
    ),
    "error_recovery": (
        "Your last action failed. Read the error message carefully and try a different approach. "
        "Do not repeat the same failing call."
    ),
}

# Protocol snippets: injected based on experimental condition (~20-30 tokens)
PROTOCOL_SNIPPETS: Dict[str, str] = {
    "debate": (
        "Challenge assumptions. In round 2, cite at least one finding from another agent."
    ),
    "delphi": (
        "Converge on consensus. Build on previous agents' findings rather than contradicting."
    ),
    "ptow": (
        "Execute the planner's instructions precisely. Report completion status explicitly."
    ),
}


class DynamicContextAssembler:
    """
    Assembles minimal system prompts and dynamic context messages.

    Usage:
        assembler = DynamicContextAssembler()
        sys_prompt = assembler.assemble_system_prompt("ME", phase="synthesize", protocol="debate")
        ctx_msgs = assembler.assemble_context_messages(state, task_text="...", agent="ME")
    """

    def assemble_system_prompt(
        self,
        agent: str,
        phase: str = "default",
        protocol: str = "debate",
    ) -> str:
        core = STATIC_CORES[agent]  # raises KeyError for unknown agents
        parts = [core]

        # Agent-specific phase snippet
        agent_phase_key = f"{agent}:{phase}"
        if agent_phase_key in PHASE_SNIPPETS:
            parts.append(PHASE_SNIPPETS[agent_phase_key])
        elif phase in PHASE_SNIPPETS:
            parts.append(PHASE_SNIPPETS[phase])

        # Protocol snippet
        if protocol in PROTOCOL_SNIPPETS:
            parts.append(PROTOCOL_SNIPPETS[protocol])

        return "\n\n".join(parts)

    def assemble_context_messages(
        self,
        state: Dict[str, Any],
        task_text: str,
        agent: str,
    ) -> List[BaseMessage]:
        """Build dynamic HumanMessage(s) with blackboard snapshot + task."""
        parts: List[str] = []

        # Blackboard snapshot (if available)
        try:
            from common import bb_snapshot_text
            bb_snap = bb_snapshot_text(state, max_items=5)
            if bb_snap and bb_snap.strip():
                parts.append(f"[Blackboard]\n{bb_snap}")
        except Exception:
            pass

        parts.append(f"[Task]\n{task_text}")
        return [HumanMessage(content="\n\n".join(parts))]

    def estimate_tokens(self, messages: List[BaseMessage]) -> int:
        """Fast token estimate: chars / 4. No API call."""
        return sum(len(str(getattr(m, "content", ""))) for m in messages) // 4

    def compress_messages(
        self,
        messages: List[BaseMessage],
        target_tokens: int,
    ) -> List[BaseMessage]:
        """
        Three-layer compression to fit within target_tokens:
          1. Truncate ToolMessage content to MAX_TOOL_MSG_CHARS
          2. Summarize old middle messages (keep first HumanMessage + last 5)
          3. Returns compressed list (never raises)
        """
        if not messages:
            return messages

        # Layer 1: truncate long ToolMessages
        result: List[BaseMessage] = []
        for m in messages:
            if isinstance(m, ToolMessage) and len(str(m.content)) > MAX_TOOL_MSG_CHARS:
                truncated = str(m.content)[:MAX_TOOL_MSG_CHARS] + "…[truncated]"
                m = ToolMessage(content=truncated, tool_call_id=getattr(m, "tool_call_id", ""))
            result.append(m)

        if self.estimate_tokens(result) <= target_tokens:
            return result

        # Layer 2: keep first HumanMessage + last 5 messages, summarize the middle
        head = [m for m in result if isinstance(m, HumanMessage)][:1]
        tail = result[-5:]
        mid = result[len(head):-5] if len(result) > len(head) + 5 else []
        if mid:
            summary = HumanMessage(
                content=f"[{len(mid)} earlier messages compressed to save context]"
            )
            return head + [summary] + tail
        return head + tail
