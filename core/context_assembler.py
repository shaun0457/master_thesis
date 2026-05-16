"""
DynamicContextAssembler — replaces the entire prompt/ folder and prompt_builder.py.

System prompt target: ≤300 tokens per agent (vs ~1,700 tokens with old .md cards).
Dynamic context (blackboard snapshot, task) is injected as HumanMessage, not system prompt.
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from agents.subagent_contracts import (
    ContextPack,
    SubagentTaskTicket,
    artifact_refs_from_blackboard,
    evidence_strings_from_blackboard,
    render_context_pack,
    render_task_contract,
    summarize_history_tail,
)

CONTEXT_WARN_TOKENS = 12_000
MAX_TOOL_MSG_CHARS = 800

# Static core: role + SOP + domain knowledge (~100-150 tokens each)
STATIC_CORES: Dict[str, str] = {
    "Supervisor": (
        "You are the Supervisor of a TEP fault diagnosis team (ME, DE, DS).\n"
        "Fault diagnosis SOP:\n"
        "  1. delegate_to_me: identify fault type, symptoms, affected sensors\n"
        "  2. delegate_to_de: retrieve sensor data (use faultnumber in WHERE)\n"
        "     Tip: call ME+DE in the SAME message for parallel execution.\n"
        "  3. delegate_to_ds: statistical confirmation (trend, T², PCA)\n"
        "  4. final_answer: cite evidence; never answer without blackboard data.\n"
        "     Skip DS for knowledge-only questions (fault definition, sensor tags).\n"
        "     Skip DS for simple aggregates (average, count, %) — DE result is enough.\n"
        "Set success_criteria for each delegation."
    ),
    "ME": (
        "You are the Machine Expert (ME) for TEP fault diagnosis.\n"
        "TEP has 21 process disturbances (IDV 1-21). Key sensors:\n"
        "  IDV 4,11,14 → XMEAS(7,9), XMV(6)  |  IDV 1-3,6,7 → XMEAS(1-4,6)\n"
        "  IDV 5,12,15 → XMEAS(11-14,22)      |  IDV 8-10   → XMEAS(23-28)\n"
        "Workflow: (1) kg_query_fault(N) — returns {description, context_chunks, evidence}.\n"
        "  (2) synthesize_and_cite(question=<q>, hits=<context_chunks from step 1>).\n"
        "Pass context_chunks DIRECTLY as hits. Description alone answers root-cause questions.\n"
        "Every claim MUST cite [filename p.N]. Call synthesize_and_cite when done."
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
        "MANDATORY: always end with deliver_dataframe(). Do NOT end your turn with only sql_db_query.\n"
        "deliver_dataframe is the ONLY way to share data with DS — a bare sql_db_query result is invisible to DS."
    ),
    "DS": (
        "You are the Data Scientist (DS) for TEP fault confirmation.\n"
        "Fault analysis SOP:\n"
        "  1. Trend plot: time series of key sensors (XMEAS 7,9,11,21) — mark fault onset at sample 160\n"
        "  2. Statistical test: compare fault mean vs normal mean; report p-value\n"
        "  3. If multivariate: PCA or T² Hotelling control chart to identify dominant sensors\n"
        "Always include: numpy seed, plt.savefig() path, numeric conclusion (e.g. 'mean diff = 12.3°C').\n"
        "Use data from blackboard datasets; call ds_pick_dataset_path to locate the file.\n"
        "Hard rules: never call tool APIs such as write_to_blackboard from inside execute_python_code.\n"
        "Treat tools as separate outer tool calls only. On Windows, file paths must use raw strings "
        "(r'...') or forward slashes."
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
    "Supervisor:diagnose": (
        "DIAGNOSIS MODE — an unlabeled sensor observation has been pre-registered on the "
        "blackboard as dataset `obs_<run_id>` together with `baseline_stats` (per-sensor "
        "mean/std over faultnumber=0). The faultnumber column is HIDDEN from the observation.\n"
        "Hard rules (must follow):\n"
        "  - DO NOT instruct DE to filter by faultnumber — that would be cheating (the label "
        "    is exactly what you must infer).\n"
        "  - The observation parquet is already on the blackboard. DE should inspect "
        "    read_blackboard(keys=['datasets']) and load the named datasets, not re-query SQL.\n"
        "  - ME MUST call kg_match_fault_by_sensors before final_answer so candidate scores "
        "    are logged (used for accuracy and confidence).\n"
        "Recommended chain:\n"
        "  1) delegate_to_de — load `obs_<run_id>` and `baseline_stats` and deliver a merged frame.\n"
        "  2) delegate_to_ds — compute per-sensor z = (obs.mean - baseline.mean) / baseline.std; "
        "     report top-5 sensors by |z|.\n"
        "  3) delegate_to_me — call kg_match_fault_by_sensors with those sensors, then "
        "     kg_query_fault on the top candidate for context.\n"
        "  4) final_answer — state predicted fault as 'IDV_N', list evidence sensors, "
        "     one-paragraph rationale. If ambiguous between sensor-family siblings (e.g. "
        "     {4,11,14}), report the family and the most likely member."
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
            from core.common import bb_snapshot_text
            bb_snap = bb_snapshot_text(state, max_items=5)
            if bb_snap and bb_snap.strip():
                parts.append(f"[Blackboard]\n{bb_snap}")
        except Exception:
            pass

        parts.append(f"[Task]\n{task_text}")
        return [HumanMessage(content="\n\n".join(parts))]

    def build_context_pack(
        self,
        *,
        state: Dict[str, Any],
        ticket: SubagentTaskTicket,
        role_prompt: str,
        runtime_limits: Optional[Dict[str, Any]] = None,
        history_tail_limit: int = 4,
    ) -> ContextPack:
        blackboard = state.get("blackboard") or {}
        evidence_lines = evidence_strings_from_blackboard(blackboard, topic_id=ticket.topic_id)
        ready_for = "DS" if ticket.to_agent == "DS" else None
        artifact_refs = artifact_refs_from_blackboard(blackboard, ready_for=ready_for)
        return ContextPack(
            ticket_id=ticket.ticket_id,
            role_prompt=role_prompt,
            task_contract=render_task_contract(ticket),
            evidence_pack="\n".join(f"- {line}" for line in evidence_lines) if evidence_lines else "",
            artifact_refs=artifact_refs,
            history_tail=summarize_history_tail(state.get("messages", []) or [], limit=history_tail_limit),
            runtime_limits=runtime_limits or {},
        )

    def assemble_contract_messages(self, pack: ContextPack) -> List[BaseMessage]:
        return [HumanMessage(content=render_context_pack(pack))]

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
