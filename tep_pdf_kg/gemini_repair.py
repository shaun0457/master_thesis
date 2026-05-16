from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from .llm_json import extract_json_payload
from .markdown_fusion import _assign_candidate_ids, _render_canonical_markdown
from .schema import ensure_parent, utc_now_iso

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

ALLOWED_REPAIR_CANDIDATE_TYPES = {
    "review_required_conflict",
    "low_confidence_docling_override",
    "docling_only_prose",
    "defer_table_review",
    "defer_formula_review",
}


class MarkdownRepairDecision(BaseModel):
    candidate_id: str = Field(..., min_length=1)
    action: str = Field(..., pattern="^(replace|append_after|omit|keep_deferred)$")
    repaired_text: str = ""
    content_type: str = Field(..., pattern="^(prose|bullet_list|table_summary|formula_note)$")
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    notes: str = ""


def _write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    ensure_parent(path)
    path.write_text(content, encoding="utf-8")


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fusion_dir(output_dir: Path) -> Path:
    return output_dir / "fusion"


def _repair_dir(output_dir: Path) -> Path:
    return output_dir / "fusion_repair"


def _repair_status_path(output_dir: Path) -> Path:
    return _repair_dir(output_dir) / "fusion_repair_status.jsonl"


def _candidate_artifact_path(output_dir: Path, candidate_id: str) -> Path:
    return _repair_dir(output_dir) / f"{candidate_id}.json"


def _read_alignment_rows(output_dir: Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(_fusion_dir(output_dir) / "alignment.jsonl")
    return _assign_candidate_ids(rows)


def _read_review_candidates(output_dir: Path) -> list[dict[str, Any]]:
    rows = [row for row in _read_alignment_rows(output_dir) if row.get("repair_candidate")]
    return [row for row in rows if row.get("decision_type") in ALLOWED_REPAIR_CANDIDATE_TYPES]


def _latest_status_by_candidate(output_dir: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(_repair_status_path(output_dir)):
        candidate_id = str(row.get("candidate_id", "")).strip()
        if candidate_id:
            latest[candidate_id] = row
    return latest


def _existing_candidate_artifact(output_dir: Path, candidate_id: str) -> dict[str, Any] | None:
    path = _candidate_artifact_path(output_dir, candidate_id)
    if not path.exists():
        return None
    return _read_json(path)


def _append_status_event(output_dir: Path, candidate: dict[str, Any], status: str, attempt_count: int, **extra: Any) -> dict[str, Any]:
    payload = {
        "candidate_id": candidate["candidate_id"],
        "candidate_index": int(str(candidate["candidate_id"]).split("_")[-1]),
        "decision_type": candidate.get("decision_type"),
        "status": status,
        "attempt_count": attempt_count,
        "timestamp": utc_now_iso(),
    }
    payload.update(extra)
    _append_jsonl(_repair_status_path(output_dir), [payload])
    return payload


def _existing_attempt_count(output_dir: Path, candidate_id: str) -> int:
    artifact = _existing_candidate_artifact(output_dir, candidate_id)
    if not artifact:
        return 0
    try:
        return int(artifact.get("attempt_count", 0))
    except Exception:
        return 0


def _neighboring_context(alignments: list[dict[str, Any]], candidate_index: int) -> dict[str, str]:
    previous_text = ""
    next_text = ""
    for idx in range(candidate_index - 1, -1, -1):
        row = alignments[idx]
        if row.get("repair_candidate") or row.get("suppressed"):
            continue
        chosen_text = str(row.get("chosen_text", "")).strip()
        if chosen_text:
            previous_text = chosen_text
            break
    for idx in range(candidate_index + 1, len(alignments)):
        row = alignments[idx]
        if row.get("repair_candidate") or row.get("suppressed"):
            continue
        chosen_text = str(row.get("chosen_text", "")).strip()
        if chosen_text:
            next_text = chosen_text
            break
    return {
        "previous_accepted_prose": previous_text,
        "next_accepted_prose": next_text,
    }


def _payload_for_candidate(candidate: dict[str, Any], alignments: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_pos = next((idx for idx, row in enumerate(alignments) if row.get("candidate_id") == candidate["candidate_id"]), -1)
    neighbor_context = _neighboring_context(alignments, candidate_pos) if candidate_pos >= 0 else {
        "previous_accepted_prose": "",
        "next_accepted_prose": "",
    }
    return {
        "task": "Repair or defer one markdown fusion candidate using only the provided parser-native evidence.",
        "candidate": {
            "candidate_id": candidate["candidate_id"],
            "decision_type": candidate.get("decision_type"),
            "defer_reason": candidate.get("defer_reason"),
            "heading": candidate.get("heading"),
            "section_id": candidate.get("section_id"),
            "block_type": candidate.get("block_type"),
            "odl_text": candidate.get("odl_text", ""),
            "docling_text": candidate.get("docling_text", ""),
            "chosen_text": candidate.get("chosen_text", ""),
            "alignment_confidence": candidate.get("alignment_confidence"),
            "similarity": candidate.get("similarity"),
        },
        "local_context": neighbor_context,
    }


def _candidate_guidance(payload: dict[str, Any]) -> str:
    candidate = payload.get("candidate") or {}
    decision_type = str(candidate.get("decision_type", "")).strip()
    if decision_type == "keep_docling_prose":
        return (
            "Candidate-specific rule for docling_only_prose:\n"
            "- This text appears only in Docling, so decide whether it is real body prose or parser noise.\n"
            "- Use 'replace' only when the repaired text is a complete, standalone sentence or paragraph that can be inserted directly into canonical markdown.\n"
            "- If the text is only a short fragment, affiliation stub, caption stub, header fragment, or isolated noun phrase, prefer 'keep_deferred'.\n"
            "- You may correct obvious OCR mistakes, punctuation, spacing, hyphenation, and casing, but do not add facts.\n"
        )
    if decision_type == "review_required_conflict":
        return (
            "Candidate-specific rule for prose_conflict:\n"
            "- ODL and Docling disagree, so your job is to choose or reconstruct the smallest grounded prose block that reads as a coherent paragraph.\n"
            "- Optimize for chunk readability over maximum information retention.\n"
            "- Prefer the version that is semantically complete, locally consistent with neighboring accepted prose, and least contaminated by table headers or OCR debris.\n"
            "- Treat equipment/process-flow narration, mode/list descriptions, captions, and table/header material as different discourse units.\n"
            "- Never merge two different discourse units into one repaired paragraph.\n"
            "- If one side ends with a dangling connector or incomplete lead-in such as 'the', 'and', 'for', 'to', or 'from there to a', treat that side as incomplete.\n"
            "- If the candidate mixes process-flow prose with mode/list prose such as 'Mode 1 is the base case', prefer only the complete standalone sub-paragraph or keep_deferred.\n"
            "- You may keep only one coherent sub-paragraph from the evidence. You do not need to preserve every fragment.\n"
            "- Do not splice unrelated sentence fragments together just to make something longer.\n"
            "- If neither side supports a clean standalone prose block, return 'keep_deferred'.\n"
        )
    if decision_type == "defer_table_review":
        return (
            "Candidate-specific rule for deferred table review:\n"
            "- Treat this as table-like content.\n"
            "- Use 'replace' only if you can recover a short human-readable table summary grounded in the provided text.\n"
            "- If the semantics are unclear or the content is mostly numeric/header noise, return 'keep_deferred'.\n"
        )
    if decision_type == "defer_formula_review":
        return (
            "Candidate-specific rule for deferred formula review:\n"
            "- Treat this as formula-like content.\n"
            "- Use 'replace' only if you can restate the formula region as a short grounded note without inventing chemistry details.\n"
            "- If the formula text is partial or ambiguous, return 'keep_deferred'.\n"
        )
    return (
        "Candidate-specific rule for low_confidence_docling_override:\n"
        "- Docling may be cleaner than ODL but confidence is low.\n"
        "- Use 'replace' only when Docling clearly yields a better complete prose block.\n"
        "- Otherwise prefer 'keep_deferred' over risky normalization.\n"
    )


def _system_prompt() -> str:
    return (
        "You repair parser-fused markdown for downstream chunking.\n"
        "Work only from the provided ODL text, Docling text, and local heading context.\n"
        "Your goal is to produce the smallest grounded markdown block that can be inserted directly into the canonical document.\n"
        "Optimize for chunk readability and local coherence, not for preserving every possible token.\n"
        "Do not invent facts. Do not rewrite the whole document. Do not summarize unless the candidate is table-like or formula-like.\n"
        "Return one machine-safe action for the candidate only.\n"
        "Use 'replace' for a grounded repaired block that is complete enough to stand alone in markdown.\n"
        "Use 'append_after' only when the base chosen text should remain and the candidate adds a clearly separate grounded follow-on block.\n"
        "Use 'omit' only for obvious parser noise.\n"
        "Use 'keep_deferred' whenever the evidence is too fragmentary, contradictory, or noisy to produce a reliable standalone block.\n"
        "For prose candidates, prefer omission/defer over half-sentences, labels, column names, captions, affiliations, or OCR debris.\n"
        "For mixed prose candidates, never join process narration with list-like or mode-like fragments unless the combined result is clearly a natural paragraph in the source evidence.\n"
        "You may correct obvious OCR typos, spacing, punctuation, and broken words, but only inside text already supported by the supplied parser evidence.\n"
        "If you choose 'replace', 'repaired_text' must be a complete readable sentence or paragraph, not a keyword fragment.\n"
    )


def _user_prompt_from_payload(payload: dict[str, Any]) -> str:
    return (
        f"{_candidate_guidance(payload)}\n"
        "Local decision checklist:\n"
        "- Is the output a complete standalone prose block?\n"
        "- Is it grounded only in ODL/Docling text provided here?\n"
        "- Does it avoid mixing different discourse units such as narrative prose and mode/list prose?\n"
        "- Does it avoid dangling lead-ins like 'from there to a' or similar incomplete transitions?\n"
        "- Is it free of table headers, affiliation fragments, or parser junk?\n"
        "- If not, prefer keep_deferred.\n\n"
        "Repair candidate payload:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with shape: "
        '{"candidate_id":"","action":"replace","repaired_text":"","content_type":"prose","confidence":0.0,"notes":""}'
    )


def _messages_from_payload(payload: dict[str, Any]) -> list[Any]:
    return [
        SystemMessage(content=_system_prompt()),
        HumanMessage(content=_user_prompt_from_payload(payload)),
    ]


def _coerce_repair_decision(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        payload = extract_json_payload(payload)
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    return MarkdownRepairDecision.model_validate(payload).model_dump()


def build_gemini_repair_extractor(model: str | None = None, temperature: float | None = 0.0) -> Callable[[dict[str, Any]], dict[str, Any]]:
    from langchain_google_genai import ChatGoogleGenerativeAI

    from core.common import invoke_with_retry, llm

    active_llm = llm
    if model:
        active_llm = ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature if temperature is not None else getattr(llm, "temperature", 0.0),
            max_output_tokens=getattr(llm, "max_output_tokens", 8192),
        )
    elif temperature is not None and hasattr(active_llm, "bind"):
        active_llm = active_llm.bind(temperature=temperature)

    if hasattr(active_llm, "with_structured_output"):
        structured = active_llm.with_structured_output(MarkdownRepairDecision)

        def extractor(payload: dict[str, Any]) -> dict[str, Any]:
            messages = _messages_from_payload(payload)
            try:
                result = invoke_with_retry(structured.invoke, messages)
                return _coerce_repair_decision(result)
            except (OutputParserException, ValidationError, TypeError):
                raw_result = invoke_with_retry(active_llm.invoke, messages)
                return _coerce_repair_decision(getattr(raw_result, "content", ""))

        return extractor

    def extractor(payload: dict[str, Any]) -> dict[str, Any]:
        result = invoke_with_retry(active_llm.invoke, _messages_from_payload(payload))
        return _coerce_repair_decision(getattr(result, "content", ""))

    return extractor


def _write_candidate_artifact(
    output_dir: Path,
    candidate: dict[str, Any],
    *,
    status: str,
    attempt_count: int,
    decision: dict[str, Any] | None,
    error: str | None,
) -> dict[str, Any]:
    payload = {
        "candidate_id": candidate["candidate_id"],
        "candidate_index": int(str(candidate["candidate_id"]).split("_")[-1]),
        "status": status,
        "attempt_count": attempt_count,
        "updated_at": utc_now_iso(),
        "decision_type": candidate.get("decision_type"),
        "defer_reason": candidate.get("defer_reason"),
        "heading": candidate.get("heading"),
        "section_id": candidate.get("section_id"),
        "error": error,
        "repair_decision": decision,
    }
    _write_json(_candidate_artifact_path(output_dir, candidate["candidate_id"]), payload)
    return payload


def _repair_candidate_worker(candidate: dict[str, Any], *, extractor: Callable[[dict[str, Any]], dict[str, Any]], alignments: list[dict[str, Any]]) -> dict[str, Any]:
    decision = extractor(_payload_for_candidate(candidate, alignments))
    return MarkdownRepairDecision.model_validate(decision).model_dump()


def _candidate_execution_targets(
    candidates: list[dict[str, Any]],
    output_dir: Path,
    *,
    start_candidate: int,
    max_candidates: int | None,
    resume: bool,
) -> tuple[list[dict[str, Any]], int]:
    candidate_slice = candidates[start_candidate:]
    if max_candidates is not None:
        candidate_slice = candidate_slice[:max_candidates]
    if not resume:
        return candidate_slice, 0

    latest = _latest_status_by_candidate(output_dir)
    targets: list[dict[str, Any]] = []
    skipped = 0
    for candidate in candidate_slice:
        row = latest.get(candidate["candidate_id"])
        artifact = _existing_candidate_artifact(output_dir, candidate["candidate_id"])
        if row and row.get("status") == STATUS_SUCCEEDED and artifact and artifact.get("status") == STATUS_SUCCEEDED:
            skipped += 1
            continue
        targets.append(candidate)
    return targets, skipped


def _run_candidate_repairs(
    output_dir: Path,
    candidates: list[dict[str, Any]],
    *,
    extractor: Callable[[dict[str, Any]], dict[str, Any]],
    alignments: list[dict[str, Any]],
    max_workers: int,
) -> dict[str, int]:
    counts = {STATUS_SUCCEEDED: 0, STATUS_FAILED: 0}
    if not candidates:
        return counts

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        future_map = {}
        for candidate in candidates:
            attempt_count = _existing_attempt_count(output_dir, candidate["candidate_id"]) + 1
            _append_status_event(output_dir, candidate, STATUS_RUNNING, attempt_count)
            future = pool.submit(_repair_candidate_worker, candidate, extractor=extractor, alignments=alignments)
            future_map[future] = (candidate, attempt_count)

        for future in as_completed(future_map):
            candidate, attempt_count = future_map[future]
            try:
                decision = future.result()
                if decision.get("candidate_id") != candidate["candidate_id"]:
                    raise ValueError("candidate_id mismatch in repair response")
                _write_candidate_artifact(
                    output_dir,
                    candidate,
                    status=STATUS_SUCCEEDED,
                    attempt_count=attempt_count,
                    decision=decision,
                    error=None,
                )
                _append_status_event(
                    output_dir,
                    candidate,
                    STATUS_SUCCEEDED,
                    attempt_count,
                    action=decision.get("action"),
                    artifact_path=str(_candidate_artifact_path(output_dir, candidate["candidate_id"])),
                )
                counts[STATUS_SUCCEEDED] += 1
            except Exception as exc:
                _write_candidate_artifact(
                    output_dir,
                    candidate,
                    status=STATUS_FAILED,
                    attempt_count=attempt_count,
                    decision=None,
                    error=str(exc),
                )
                _append_status_event(
                    output_dir,
                    candidate,
                    STATUS_FAILED,
                    attempt_count,
                    error=str(exc),
                    artifact_path=str(_candidate_artifact_path(output_dir, candidate["candidate_id"])),
                )
                counts[STATUS_FAILED] += 1
    return counts


def _repair_overrides_from_artifacts(output_dir: Path, candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    overrides: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        artifact = _existing_candidate_artifact(output_dir, candidate["candidate_id"])
        if artifact and artifact.get("status") == STATUS_SUCCEEDED and isinstance(artifact.get("repair_decision"), dict):
            overrides[candidate["candidate_id"]] = artifact["repair_decision"]
    return overrides


def _status_counts(output_dir: Path, candidates: list[dict[str, Any]]) -> dict[str, int]:
    latest = _latest_status_by_candidate(output_dir)
    counts = {
        STATUS_PENDING: 0,
        STATUS_RUNNING: 0,
        STATUS_SUCCEEDED: 0,
        STATUS_FAILED: 0,
    }
    for candidate in candidates:
        row = latest.get(candidate["candidate_id"])
        artifact = _existing_candidate_artifact(output_dir, candidate["candidate_id"])
        status = STATUS_PENDING
        if row and str(row.get("status")) in counts:
            status = str(row.get("status"))
        if artifact and artifact.get("status") == STATUS_SUCCEEDED:
            status = STATUS_SUCCEEDED
        counts[status] += 1
    return counts


def rebuild_repaired_markdown(doc_id: str, output_dir: str | Path) -> dict[str, Any]:
    output_dir = Path(output_dir)
    alignments = _read_alignment_rows(output_dir)
    candidates = [row for row in alignments if row.get("repair_candidate")]
    repair_overrides = _repair_overrides_from_artifacts(output_dir, candidates)
    repaired_markdown = _render_canonical_markdown(alignments, repair_overrides=repair_overrides)
    repaired_path = _fusion_dir(output_dir) / "canonical.repaired.md"
    report_path = _fusion_dir(output_dir) / "canonical.repaired.report.json"

    action_counts: dict[str, int] = {}
    for decision in repair_overrides.values():
        action = str(decision.get("action", "")).strip() or "unknown"
        action_counts[action] = action_counts.get(action, 0) + 1

    report = {
        "doc_id": doc_id,
        "candidate_count": len(candidates),
        "applied_repair_count": len(repair_overrides),
        "status_counts": _status_counts(output_dir, candidates),
        "action_counts": action_counts,
        "canonical_cleaned_path": str(_fusion_dir(output_dir) / "canonical.cleaned.md"),
        "canonical_repaired_path": str(repaired_path),
    }
    _write_text(repaired_path, repaired_markdown)
    _write_json(report_path, report)
    return report


def run_fusion_repair(
    *,
    doc_id: str,
    output_dir: str | Path,
    extractor: Callable[[dict[str, Any]], dict[str, Any]],
    start_candidate: int = 0,
    max_candidates: int | None = None,
    resume: bool = False,
    max_workers: int = 1,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    alignments = _read_alignment_rows(output_dir)
    candidates = [row for row in alignments if row.get("repair_candidate")]
    targets, skipped_count = _candidate_execution_targets(
        candidates,
        output_dir,
        start_candidate=start_candidate,
        max_candidates=max_candidates,
        resume=resume,
    )
    execution_counts = _run_candidate_repairs(
        output_dir,
        targets,
        extractor=extractor,
        alignments=alignments,
        max_workers=max_workers,
    )
    report = rebuild_repaired_markdown(doc_id, output_dir)
    report.update(
        {
            "processed_candidate_count": len(targets),
            "skipped_candidate_count": skipped_count,
            "start_candidate": start_candidate,
            "max_candidates": max_candidates,
            "resume_used": resume,
            "max_workers": max(1, max_workers),
            "execution_succeeded_this_run": execution_counts[STATUS_SUCCEEDED],
            "execution_failed_this_run": execution_counts[STATUS_FAILED],
            "repair_status_path": str(_repair_status_path(output_dir)),
            "repair_dir": str(_repair_dir(output_dir)),
        }
    )
    return report
