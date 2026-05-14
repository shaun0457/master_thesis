from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED_ENTITY_LABELS = {
    "Fault",
    "Symptom",
    "Sensor",
    "ProcessUnit",
    "ControlAction",
    "Actuator",
    "Constraint",
    "Risk",
    "Document",
    "Chunk",
}

ALLOWED_RELATIONS = {
    "CAUSES",
    "OBSERVED_BY",
    "AFFECTS_UNIT",
    "SUGGESTS_ACTION",
    "ACTS_ON",
    "SUBJECT_TO",
    "HAS_RISK",
    "MENTIONED_IN",
    "PART_OF",
}

CLAIM_TYPES = {
    "diagnosis",
    "causal_mechanism",
    "symptom_observation",
    "process_unit_impact",
    "control_action",
    "action_target",
    "constraint",
    "risk",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed or "unknown"


@dataclass(slots=True)
class DocumentManifest:
    doc_id: str
    pdf_path: str
    output_dir: str
    parser_candidates: list[str] = field(default_factory=lambda: ["opendataloader-pdf", "docling"])
    preferred_parser: str = "opendataloader-pdf"
    selected_parser: str | None = None
    reviewed_document_path: str | None = None
    reviewed_chunks_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SectionElement:
    text_md: str
    heading_path: list[str]
    page_start: int
    page_end: int
    element_type: str = "paragraph"
    bbox: dict[str, Any] | None = None
    element_ref: str | None = None


@dataclass(slots=True)
class NormalizedDocument:
    doc_id: str
    source_path: str
    parser_used: str
    parser_status: str
    selected_as_canonical: bool
    title: str
    document_md: str
    sections: list[SectionElement]
    pages: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


@dataclass(slots=True)
class ChunkRecord:
    doc_id: str
    chunk_id: str
    section_title: str
    page_start: int
    page_end: int
    chunk_index: int
    text_md: str
    chunk_type: str
    parser_used: str
    prev_chunk_id: str | None
    next_chunk_id: str | None
    bbox: dict[str, Any] | None = None
    element_refs: list[str] = field(default_factory=list)
    heading_path: list[str] = field(default_factory=list)
    review_status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ClaimRecord:
    claim_id: str
    subject: str
    subject_label: str
    predicate: str
    object: str
    object_label: str
    claim_type: str
    normalized_subject: str
    normalized_object: str
    source_chunk_id: str
    source_doc: str
    page_start: int
    page_end: int
    evidence_text: str
    extractor_version: str
    extraction_confidence: float
    review_status: str
    extraction_timestamp: str
    parser_used: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ParserRunResult:
    parser_name: str
    status: str
    document: NormalizedDocument | None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


def ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
