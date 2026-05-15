from __future__ import annotations

import json
import re
from typing import Any, Callable

from .schema import CLAIM_TYPES, ClaimRecord, ChunkRecord, utc_now_iso

EXTRACTOR_VERSION = "tep-pdf-kg-v1"

_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    (
        re.compile(r"(fault\s+\d+|idv[_\s]?\d+).{0,40}?(causes?|results? in|leads? to)\s+([^.;]+)", re.I),
        "CAUSES",
        "Fault",
        "Symptom",
    ),
    (
        re.compile(r"(symptom|increase|decrease|high|low)\s+([^.;]+).{0,40}?(observed by|measured by|seen in)\s+([^.;]+)", re.I),
        "OBSERVED_BY",
        "Symptom",
        "Sensor",
    ),
    (
        re.compile(r"(fault\s+\d+|idv[_\s]?\d+).{0,40}?(affects?|impacts?)\s+([^.;]+)", re.I),
        "AFFECTS_UNIT",
        "Fault",
        "ProcessUnit",
    ),
    (
        re.compile(r"(fault\s+\d+|idv[_\s]?\d+|condition).{0,40}?(suggests?|requires?|recommend[s]?)\s+([^.;]+)", re.I),
        "SUGGESTS_ACTION",
        "Fault",
        "ControlAction",
    ),
    (
        re.compile(r"(increase|decrease|adjust|open|close)\s+([^.;]+).{0,40}?(on|to)\s+([^.;]+valve|actuator|flow|cooling water)", re.I),
        "ACTS_ON",
        "ControlAction",
        "Actuator",
    ),
    (
        re.compile(r"(control action|adjustment|operation)\s+([^.;]+).{0,40}?(subject to|limited by|constrained by)\s+([^.;]+)", re.I),
        "SUBJECT_TO",
        "ControlAction",
        "Constraint",
    ),
    (
        re.compile(r"(control action|adjustment|operation)\s+([^.;]+).{0,40}?(risk|may cause|can cause)\s+([^.;]+)", re.I),
        "HAS_RISK",
        "ControlAction",
        "Risk",
    ),
]

_RELATION_TO_CLAIM_TYPE = {
    "CAUSES": "diagnosis",
    "OBSERVED_BY": "symptom_observation",
    "AFFECTS_UNIT": "process_unit_impact",
    "SUGGESTS_ACTION": "control_action",
    "ACTS_ON": "action_target",
    "SUBJECT_TO": "constraint",
    "HAS_RISK": "risk",
}

_DOCUMENT_METADATA_KEYS = {
    "doc_id",
    "title",
    "parser_used",
    "canonical_source",
    "provenance_quality",
    "parser_candidates",
}

_CHUNK_METADATA_KEYS = {
    "chunk_id",
    "chunk_index",
    "section_title",
    "heading_path",
    "page_start",
    "page_end",
    "parser_used",
    "review_status",
}


def _canonicalize_text(text: str) -> str:
    value = " ".join(text.replace("_", " ").split()).strip(" .;:,")
    return value


def build_slim_document_metadata(document_metadata: dict[str, Any] | None, chunk: ChunkRecord) -> dict[str, Any]:
    metadata = document_metadata or {}
    slim = {key: metadata[key] for key in _DOCUMENT_METADATA_KEYS if key in metadata}
    slim.setdefault("parser_used", chunk.parser_used)
    chunk_context = {key: getattr(chunk, key) for key in _CHUNK_METADATA_KEYS if hasattr(chunk, key)}
    chunk_context["has_bbox"] = chunk.bbox is not None
    chunk_context["element_ref_count"] = len(chunk.element_refs)
    if chunk.metadata and "provenance_quality" in chunk.metadata:
        chunk_context["provenance_quality"] = chunk.metadata["provenance_quality"]
    slim["chunk_context"] = chunk_context
    return slim


def _claim_from_match(chunk: ChunkRecord, predicate: str, subject_label: str, object_label: str, subject: str, obj: str) -> ClaimRecord:
    claim_type = _RELATION_TO_CLAIM_TYPE[predicate]
    subject_norm = _canonicalize_text(subject)
    object_norm = _canonicalize_text(obj)
    return ClaimRecord(
        claim_id=f"{chunk.chunk_id}::{predicate}::{len(subject_norm)}::{len(object_norm)}",
        subject=subject_norm,
        subject_label=subject_label,
        predicate=predicate,
        object=object_norm,
        object_label=object_label,
        claim_type=claim_type,
        normalized_subject=subject_norm.lower(),
        normalized_object=object_norm.lower(),
        source_chunk_id=chunk.chunk_id,
        source_doc=chunk.doc_id,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        evidence_text=chunk.text_md[:400],
        extractor_version=EXTRACTOR_VERSION,
        extraction_confidence=0.72,
        review_status="pending",
        extraction_timestamp=utc_now_iso(),
        parser_used=chunk.parser_used,
        metadata={"section_title": chunk.section_title},
    )


def _heuristic_extract(chunk: ChunkRecord) -> list[ClaimRecord]:
    claims: list[ClaimRecord] = []
    text = chunk.text_md
    for pattern, predicate, subject_label, object_label in _PATTERNS:
        for match in pattern.finditer(text):
            groups = [grp for grp in match.groups() if grp]
            if predicate == "OBSERVED_BY":
                subject = f"{groups[0]} {groups[1]}"
                obj = groups[-1]
            elif predicate in {"ACTS_ON", "SUBJECT_TO", "HAS_RISK"}:
                subject = f"{groups[0]} {groups[1]}".strip()
                obj = groups[-1]
            else:
                subject = groups[0]
                obj = groups[-1]
            claims.append(_claim_from_match(chunk, predicate, subject_label, object_label, subject, obj))
    return claims


def _parse_llm_claims(payload: Any, chunk: ChunkRecord) -> list[ClaimRecord]:
    if isinstance(payload, str):
        payload = json.loads(payload)
    claims: list[ClaimRecord] = []
    for idx, raw in enumerate(payload or []):
        predicate = str(raw.get("predicate", "")).upper().strip()
        claim_type = str(raw.get("claim_type", "")).strip().lower()
        if predicate not in _RELATION_TO_CLAIM_TYPE or claim_type not in CLAIM_TYPES:
            continue
        subject = _canonicalize_text(str(raw.get("subject", "")))
        obj = _canonicalize_text(str(raw.get("object", "")))
        if not subject or not obj:
            continue
        claims.append(
            ClaimRecord(
                claim_id=f"{chunk.chunk_id}::llm::{idx}",
                subject=subject,
                subject_label=str(raw.get("subject_label", "")).strip(),
                predicate=predicate,
                object=obj,
                object_label=str(raw.get("object_label", "")).strip(),
                claim_type=claim_type,
                normalized_subject=subject.lower(),
                normalized_object=obj.lower(),
                source_chunk_id=chunk.chunk_id,
                source_doc=chunk.doc_id,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                evidence_text=str(raw.get("evidence_text", "")).strip() or chunk.text_md[:400],
                extractor_version=EXTRACTOR_VERSION,
                extraction_confidence=float(raw.get("extraction_confidence", 0.5)),
                review_status=str(raw.get("review_status", "pending")),
                extraction_timestamp=utc_now_iso(),
                parser_used=chunk.parser_used,
                metadata={"section_title": chunk.section_title, "source": "llm"},
            )
        )
    return claims


def extract_claims(
    chunk: ChunkRecord,
    extractor: Callable[[dict[str, Any]], Any] | None = None,
    document_metadata: dict[str, Any] | None = None,
) -> list[ClaimRecord]:
    if extractor is None:
        return _heuristic_extract(chunk)
    payload = {
        "chunk": chunk.to_dict(),
        "document_metadata": build_slim_document_metadata(document_metadata, chunk),
        "task": "Extract semantic TEP claims into the controlled schema.",
        "allowed_relations": sorted(_RELATION_TO_CLAIM_TYPE),
    }
    result = extractor(payload)
    return _parse_llm_claims(result, chunk)
