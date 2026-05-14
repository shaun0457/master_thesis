from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field


AgentName = Literal["Supervisor", "ME", "DE", "DS"]
DelegateTarget = Literal["ME", "DE", "DS"]
TicketStatus = Literal["ok", "blocked", "incomplete", "error"]


class HandoffArtifact(BaseModel):
    artifact_id: str = ""
    kind: str
    path: str = ""
    rowcount: int = 0
    columns: List[str] = Field(default_factory=list)
    producer: AgentName
    topic_id: str = ""
    ready_for: str = ""


class DelegateRequest(BaseModel):
    ticket_id: str
    from_agent: AgentName
    to_agent: DelegateTarget
    goal: str
    task_text: str
    required_inputs: List[str] = Field(default_factory=list)
    success_criteria: str = ""
    priority: Literal["low", "normal", "high"] = "normal"
    topic_id: str = ""
    owner: str = ""
    parent_ticket_id: Optional[str] = None
    depth: int = 0


class SubagentTaskTicket(BaseModel):
    ticket_id: str
    from_agent: AgentName
    to_agent: AgentName
    topic_id: str
    owner: str
    goal: str
    task_text: str
    success_criteria: str = ""
    inputs: Dict[str, Any] = Field(default_factory=dict)
    constraints: List[str] = Field(default_factory=list)
    handoff_type: str = "delegate"
    parent_ticket_id: Optional[str] = None
    depth: int = 0


class ContextPack(BaseModel):
    ticket_id: str
    role_prompt: str
    task_contract: str
    evidence_pack: str
    artifact_refs: List[HandoffArtifact] = Field(default_factory=list)
    history_tail: List[str] = Field(default_factory=list)
    runtime_limits: Dict[str, Any] = Field(default_factory=dict)


class SubagentResultEnvelope(BaseModel):
    ticket_id: str
    agent: AgentName
    status: TicketStatus
    summary: str
    artifacts: List[HandoffArtifact] = Field(default_factory=list)
    delegate_requests: List[DelegateRequest] = Field(default_factory=list)
    evidence_used: List[str] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    stop_reason: str = ""
    next_action: str = ""


class HandoffValidationResult(BaseModel):
    status: Literal["ready", "blocked", "incomplete"]
    reason: str = ""
    artifacts: List[HandoffArtifact] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)


def new_ticket_id(prefix: str = "ticket") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def ticket_signature(ticket: SubagentTaskTicket) -> str:
    normalized_inputs = json.dumps(ticket.inputs, ensure_ascii=False, sort_keys=True)
    base = "|".join(
        [
            ticket.to_agent,
            ticket.goal.strip().lower(),
            normalized_inputs,
            ticket.parent_ticket_id or "",
        ]
    )
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def normalize_delegate_request(
    payload: Dict[str, Any],
    *,
    from_agent: AgentName,
    topic_id: str,
    owner: str,
    parent_ticket_id: Optional[str],
    depth: int,
) -> DelegateRequest:
    to_agent = str(payload.get("to_agent") or payload.get("to") or "").strip().upper()
    if to_agent not in {"ME", "DE", "DS"}:
        raise ValueError("delegate target must be one of ME/DE/DS")
    task_text = str(payload.get("task_text") or payload.get("task") or "").strip()
    if not task_text:
        raise ValueError("delegate request task_text is required")
    goal = str(payload.get("goal") or task_text).strip()
    return DelegateRequest(
        ticket_id=str(payload.get("ticket_id") or new_ticket_id("req")),
        from_agent=from_agent,
        to_agent=to_agent,
        goal=goal,
        task_text=task_text,
        required_inputs=list(payload.get("required_inputs") or []),
        success_criteria=str(payload.get("success_criteria") or ""),
        priority=str(payload.get("priority") or "normal"),
        topic_id=str(payload.get("topic_id") or topic_id),
        owner=str(payload.get("owner") or owner),
        parent_ticket_id=payload.get("parent_ticket_id") or parent_ticket_id,
        depth=int(payload.get("depth", depth)),
    )


def build_ticket(
    *,
    from_agent: AgentName,
    to_agent: AgentName,
    topic_id: str,
    owner: str,
    goal: str,
    task_text: str,
    success_criteria: str = "",
    inputs: Optional[Dict[str, Any]] = None,
    constraints: Optional[List[str]] = None,
    handoff_type: str = "delegate",
    parent_ticket_id: Optional[str] = None,
    depth: int = 0,
    ticket_id: Optional[str] = None,
) -> SubagentTaskTicket:
    return SubagentTaskTicket(
        ticket_id=ticket_id or new_ticket_id(to_agent.lower()),
        from_agent=from_agent,
        to_agent=to_agent,
        topic_id=topic_id or f"topic_{uuid.uuid4().hex[:8]}",
        owner=owner or to_agent,
        goal=goal.strip() or task_text.strip(),
        task_text=task_text.strip(),
        success_criteria=success_criteria.strip(),
        inputs=inputs or {},
        constraints=constraints or [],
        handoff_type=handoff_type,
        parent_ticket_id=parent_ticket_id,
        depth=depth,
    )


def render_task_contract(ticket: SubagentTaskTicket) -> str:
    lines = [
        "[TASK CONTRACT]",
        f"Ticket: {ticket.ticket_id}",
        f"From: {ticket.from_agent}",
        f"To: {ticket.to_agent}",
        f"Topic: {ticket.topic_id}",
        f"Owner: {ticket.owner}",
        f"Goal: {ticket.goal}",
        f"Task: {ticket.task_text}",
    ]
    if ticket.success_criteria:
        lines.append(f"Success criteria: {ticket.success_criteria}")
    if ticket.constraints:
        lines.append("Constraints:")
        lines.extend(f"- {c}" for c in ticket.constraints)
    if ticket.inputs:
        lines.append("Inputs:")
        lines.extend(f"- {k}: {v}" for k, v in ticket.inputs.items())
    return "\n".join(lines)


def summarize_history_tail(messages: List[BaseMessage], limit: int = 4) -> List[str]:
    tail = []
    for msg in messages[-limit:]:
        role = msg.__class__.__name__.replace("Message", "")
        content = str(getattr(msg, "content", "") or "").replace("\n", " ").strip()
        name = getattr(msg, "name", "") or ""
        label = f"{role}:{name}" if name else role
        tail.append(f"{label} {content[:220]}".strip())
    return tail


def evidence_strings_from_blackboard(blackboard: Dict[str, Any], topic_id: str = "") -> List[str]:
    out: List[str] = []
    bb = blackboard or {}
    for fact in bb.get("facts", []) or []:
        if isinstance(fact, dict):
            claim = str(fact.get("claim") or fact.get("description") or "").strip()
            if claim:
                out.append(claim)
    for citation in bb.get("citations", []) or []:
        if isinstance(citation, dict):
            label = str(citation.get("source") or citation.get("doc_id") or "citation")
            page = citation.get("page")
            snippet = str(citation.get("snippet") or citation.get("claim") or "").strip()
            out.append(f"{label} p.{page}: {snippet}" if page else f"{label}: {snippet}")
    return out[:12]


def artifact_refs_from_blackboard(blackboard: Dict[str, Any], *, ready_for: Optional[str] = None) -> List[HandoffArtifact]:
    refs: List[HandoffArtifact] = []
    for dataset in (blackboard or {}).get("datasets", []) or []:
        if not isinstance(dataset, dict):
            continue
        meta = dataset.get("meta") or {}
        target = dataset.get("ready_for") or meta.get("ready_for") or meta.get("intended_owner") or ""
        if ready_for and target != ready_for:
            continue
        refs.append(
            HandoffArtifact(
                artifact_id=str(dataset.get("artifact_id") or ""),
                kind=str(dataset.get("kind") or meta.get("kind") or "dataset"),
                path=str(dataset.get("path") or dataset.get("uri") or ""),
                rowcount=int(dataset.get("rowcount") or dataset.get("rows") or 0),
                columns=list(dataset.get("columns") or []),
                producer=str(dataset.get("created_by") or dataset.get("producer") or "DE"),
                topic_id=str(dataset.get("topic_id") or meta.get("workflow_topic") or ""),
                ready_for=str(target),
            )
        )
    return refs


def extract_handoff_artifacts(out_state: Dict[str, Any], *, agent: AgentName, topic_id: str) -> List[HandoffArtifact]:
    artifacts: List[HandoffArtifact] = []
    for msg in out_state.get("messages", []) or []:
        if not isinstance(msg, ToolMessage):
            continue
        name = getattr(msg, "name", "") or ""
        if name != "deliver_dataframe":
            continue
        try:
            payload = json.loads(msg.content)
        except Exception:
            payload = {}
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            continue
        df_payload = payload.get("df_payload") or {}
        if not isinstance(df_payload, dict):
            continue
        artifacts.append(
            HandoffArtifact(
                artifact_id=str(payload.get("artifact_id") or df_payload.get("artifact_id") or ""),
                kind="dataset",
                path=str(df_payload.get("path") or ""),
                rowcount=int(payload.get("rowcount") or 0),
                columns=list(payload.get("columns") or df_payload.get("columns") or []),
                producer=agent,
                topic_id=topic_id,
                ready_for="DS",
            )
        )
    return artifacts


def ds_has_numeric_conclusion(out_state: Dict[str, Any]) -> bool:
    for msg in reversed(out_state.get("messages", []) or []):
        if isinstance(msg, AIMessage):
            text = str(getattr(msg, "content", "") or "")
            if any(ch.isdigit() for ch in text):
                return True
    return False


def validate_me_to_de(out_state: Dict[str, Any], *, topic_id: str) -> HandoffValidationResult:
    blackboard = out_state.get("blackboard") or {}
    facts = [f for f in (blackboard.get("facts") or []) if isinstance(f, dict)]
    normalized = [
        f for f in facts
        if f.get("fault_id") is not None or f.get("diagnostic_sensors") or "sensor" in str(f.get("claim", "")).lower()
    ]
    if not normalized:
        for msg in out_state.get("messages", []) or []:
            if not isinstance(msg, ToolMessage) or (getattr(msg, "name", "") or "") != "kg_query_fault":
                continue
            try:
                payload = json.loads(msg.content)
            except Exception:
                payload = {}
            if payload.get("fault_id") is not None or payload.get("diagnostic_sensors"):
                normalized.append(payload)
    if normalized:
        return HandoffValidationResult(status="ready", reason="ME produced normalized fault facts")
    return HandoffValidationResult(status="blocked", reason="ME handoff requires normalized fault facts or sensor hypotheses")


def validate_de_to_ds(out_state: Dict[str, Any], *, topic_id: str) -> HandoffValidationResult:
    artifacts = extract_handoff_artifacts(out_state, agent="DE", topic_id=topic_id)
    ready = [
        art for art in artifacts
        if art.path and art.rowcount >= 1 and art.columns
    ]
    if ready:
        return HandoffValidationResult(status="ready", reason="DE produced a DS-ready dataset", artifacts=ready)
    return HandoffValidationResult(status="blocked", reason="DE handoff requires a deliver_dataframe artifact with path, rowcount, and columns")


def validate_ds_to_supervisor(out_state: Dict[str, Any], *, topic_id: str) -> HandoffValidationResult:
    artifacts: List[HandoffArtifact] = []
    for entry in (out_state.get("tool_events") or []):
        if entry.get("tool") == "execute_python_code" and entry.get("ok", True):
            args = entry.get("args") or {}
            path = str(args.get("save_path") or args.get("path") or "")
            artifacts.append(
                HandoffArtifact(
                    artifact_id="",
                    kind="analysis",
                    path=path,
                    rowcount=0,
                    columns=[],
                    producer="DS",
                    topic_id=topic_id,
                    ready_for="Supervisor",
                )
            )
    if artifacts or ds_has_numeric_conclusion(out_state):
        return HandoffValidationResult(status="ready", reason="DS produced analysis output", artifacts=artifacts)
    return HandoffValidationResult(status="blocked", reason="DS handoff requires an analysis artifact or numeric conclusion")


def render_context_pack(pack: ContextPack) -> str:
    parts = [pack.task_contract]
    if pack.evidence_pack:
        parts.append(f"[EVIDENCE PACK]\n{pack.evidence_pack}")
    if pack.artifact_refs:
        lines = ["[ARTIFACT REFS]"]
        for art in pack.artifact_refs:
            cols = ", ".join(art.columns[:8])
            lines.append(
                f"- {art.kind} id={art.artifact_id or '?'} ready_for={art.ready_for or '?'} path={art.path} rows={art.rowcount} cols={cols}"
            )
        parts.append("\n".join(lines))
    if pack.history_tail:
        parts.append("[HISTORY TAIL]\n" + "\n".join(f"- {line}" for line in pack.history_tail))
    parts.append("[RUNTIME LIMITS]\n" + json.dumps(pack.runtime_limits, ensure_ascii=False, sort_keys=True))
    return "\n\n".join(parts)
