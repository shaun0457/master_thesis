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

# Static core: role + SOP + domain knowledge (~100-150 tokens each)
STATIC_CORES: Dict[str, str] = {
    "Supervisor": (
        "You are the Supervisor of a TEP fault diagnosis team (ME, DE, DS).\n"
        "Fault diagnosis SOP — follow this order:\n"
        "  1. delegate_to_me: identify fault type, symptoms, affected process units\n"
        "  2. delegate_to_de: retrieve sensor data for the suspected fault (use faultnumber in WHERE)\n"
        "  3. delegate_to_ds: statistical confirmation (trend, T², PCA)\n"
        "  4. final_answer: cite evidence from all three agents; never answer without blackboard data.\n"
        "Set success_criteria for each delegation so sub-agents know what 'done' looks like."
    ),
    "ME": (
        "You are the Machine Expert (ME) for TEP fault diagnosis.\n"
        "Key sensor-fault mappings:\n"
        "  Reactor faults (IDV 4,11,14): watch XMEAS(7) pressure, XMEAS(9) temp, XMV(6) cooling valve\n"
        "  Feed faults (IDV 1-3,6,7): watch XMEAS(1-4) feed flows, XMEAS(6) reactor feed rate\n"
        "  Separator/Condenser (IDV 5,12,15): watch XMEAS(11-14), XMEAS(22), XMV(7)\n"
        "  Composition faults (IDV 8-10): watch XMEAS(23-28) reactor feed concentrations\n"
        "  Kinetics/Drift (IDV 13): slow changes in XMEAS(9) temp and XMEAS(7) pressure\n"
        "Use kg_query_fault(idv_number) for structured fault knowledge; "
        "it returns {description, diagnostic_sensors, context_chunks} where "
        "context_chunks are PDF evidence passages from Neo4j — cite them as [source_doc p.N].\n"
        "Every claim MUST cite source as [filename p.N]. Call synthesize_and_cite when done."
    ),
    "DE": (
        "You are the Data Engineer (DE) for TEP sensor data retrieval.\n"
        "DB: tep_combined.db — tables:\n"
        "  process_data(faultnumber, simulationrun, sample[1-500], xmeas_1..41, xmv_1..11)\n"
        "  fault_descriptions(faultnumber, description)\n"
        "Common patterns:\n"
        "  Fault vs normal: WHERE faultnumber=<N> vs WHERE faultnumber=0\n"
        "  Time window: WHERE faultnumber=<N> AND sample BETWEEN 160 AND 500  -- fault onset ~sample 160\n"
        "  AVG by fault: SELECT faultnumber, AVG(xmeas_9), AVG(xmeas_7) FROM process_data GROUP BY faultnumber\n"
        "Always validate row count before calling deliver_dataframe."
    ),
    "DS": (
        "You are the Data Scientist (DS) for TEP fault confirmation.\n"
        "Fault analysis SOP:\n"
        "  1. Trend plot: time series of key sensors (XMEAS 7,9,11,21) — mark fault onset at sample 160\n"
        "  2. Statistical test: compare fault mean vs normal mean; report p-value\n"
        "  3. If multivariate: PCA or T² Hotelling control chart to identify dominant sensors\n"
        "Always include: numpy seed, plt.savefig() path, numeric conclusion (e.g. 'mean diff = 12.3°C').\n"
        "Use data from blackboard datasets; call ds_pick_dataset_path to locate the file."
    ),
}

# Phase snippets: injected only when state["phase"] matches (~30-50 tokens)
PHASE_SNIPPETS: Dict[str, str] = {
    "ME:synthesize": (
        "Evidence collected. Call synthesize_and_cite now — include all chunk IDs and page citations."
    ),
    "DE:deliver": (
        "Dataset validated. Call deliver_dataframe with path, row_count, and fault_id confirmed."
    ),
    "DS:model": (
        "Report: model name, hyperparameters, top-3 feature importances, seed, and numeric conclusion."
    ),
    "error_recovery": (
        "Last action failed. Read the error carefully. Try a different SQL/code approach. "
        "Do not repeat the identical failing call."
    ),
}

# Protocol snippets: injected based on experimental condition (~20-30 tokens)
PROTOCOL_SNIPPETS: Dict[str, str] = {
    "debate": (
        "Challenge other agents' assumptions. In round 2, cite at least one finding from the blackboard."
    ),
    "delphi": (
        "Build on prior agents' blackboard entries. Converge rather than contradict."
    ),
    "ptow": (
        "Execute the delegated task precisely. Report completion status and numeric results explicitly."
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
