from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .schema import ChunkRecord, NormalizedDocument, slugify

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(slots=True)
class MarkdownSection:
    heading_path: list[str]
    section_title: str
    body_md: str


@dataclass(slots=True)
class SectionProvenance:
    heading_path: list[str]
    section_title: str
    page_start: int
    page_end: int
    bbox: dict[str, Any] | None
    element_refs: list[str]
    provenance_quality: str


def _split_markdown_sections(document_md: str) -> list[MarkdownSection]:
    sections: list[MarkdownSection] = []
    heading_stack: list[str] = []
    current_heading_path = ["Document"]
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal body_lines
        body = "\n".join(body_lines).strip()
        if body:
            sections.append(
                MarkdownSection(
                    heading_path=current_heading_path[:],
                    section_title=current_heading_path[-1],
                    body_md=body,
                )
            )
        body_lines = []

    for raw_line in document_md.splitlines():
        match = HEADING_RE.match(raw_line.strip())
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(title)
            current_heading_path = heading_stack[:] or ["Document"]
            continue
        body_lines.append(raw_line)

    flush()
    if not sections and document_md.strip():
        sections.append(MarkdownSection(heading_path=["Document"], section_title="Document", body_md=document_md.strip()))
    return sections


def _iter_provenance_elements(parser_json: Any) -> list[dict[str, Any]]:
    if not parser_json:
        return []

    def walk(payload: Any):
        if isinstance(payload, dict):
            yield payload
            for value in payload.values():
                yield from walk(value)
        elif isinstance(payload, list):
            for item in payload:
                yield from walk(item)

    def pick_text(node: dict[str, Any]) -> str:
        for key in ("text", "content", "markdown", "md", "plain_text", "plaintext", "title"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def pick_type(node: dict[str, Any]) -> str:
        for key in ("type", "label", "kind", "name", "category"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return "paragraph"

    def pick_int(node: dict[str, Any], *keys: str) -> int | None:
        for key in keys:
            value = node.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str) and value.strip().isdigit():
                return int(value.strip())
        return None

    elements: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    synthetic = 0
    for node in walk(parser_json):
        text = pick_text(node)
        element_type = pick_type(node)
        page_start = pick_int(node, "page_start", "start_page", "page_number", "page", "page_no", "page_num")
        page_end = pick_int(node, "page_end", "end_page") or page_start
        heading_level = pick_int(node, "heading_level", "level")
        if heading_level is None and ("heading" in element_type or "title" in element_type):
            heading_level = 1
        bbox = node.get("bbox") if isinstance(node.get("bbox"), dict) else None
        if bbox is None and isinstance(node.get("bounding_box"), dict):
            bbox = node.get("bounding_box")
        element_ref = node.get("id") or node.get("element_id") or node.get("ref")
        if not isinstance(element_ref, str) or not element_ref.strip():
            synthetic += 1
            element_ref = f"element-{synthetic:05d}"
        if element_ref in seen_refs:
            continue
        if not any([text, page_start is not None, bbox, heading_level is not None]):
            continue
        seen_refs.add(element_ref)
        elements.append(
            {
                "text": text,
                "element_type": element_type,
                "page_start": page_start or 1,
                "page_end": page_end or page_start or 1,
                "heading_level": heading_level,
                "bbox": bbox,
                "element_ref": element_ref,
            }
        )
    return elements


def _build_section_provenance(document: NormalizedDocument) -> list[SectionProvenance]:
    parser_json = document.metadata.get("parser_json") if document.metadata else None
    elements = _iter_provenance_elements(parser_json)
    if not elements:
        if document.sections:
            grouped: dict[tuple[str, ...], list[Any]] = {}
            for section in document.sections:
                key = tuple(section.heading_path or ["Document"])
                grouped.setdefault(key, []).append(section)
            provenance: list[SectionProvenance] = []
            for key, group in grouped.items():
                provenance.append(
                    SectionProvenance(
                        heading_path=list(key),
                        section_title=key[-1],
                        page_start=min(item.page_start for item in group),
                        page_end=max(item.page_end for item in group),
                        bbox=next((item.bbox for item in group if item.bbox is not None), None),
                        element_refs=[item.element_ref for item in group if item.element_ref],
                        provenance_quality="section-fallback",
                    )
                )
            return provenance
        return [
            SectionProvenance(
                heading_path=["Document"],
                section_title="Document",
                page_start=1,
                page_end=max(1, len(document.pages) or 1),
                bbox=None,
                element_refs=[],
                provenance_quality="missing",
            )
        ]

    provenance: list[SectionProvenance] = []
    heading_stack: list[str] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        provenance.append(
            SectionProvenance(
                heading_path=current["heading_path"][:],
                section_title=current["heading_path"][-1],
                page_start=current["page_start"],
                page_end=current["page_end"],
                bbox=current["bbox"],
                element_refs=current["element_refs"][:],
                provenance_quality=current["provenance_quality"],
            )
        )
        current = None

    for element in elements:
        text = str(element.get("text", "")).strip()
        heading_level = element.get("heading_level")
        if heading_level is not None and text:
            flush()
            heading_stack = heading_stack[: max(0, int(heading_level) - 1)]
            heading_stack.append(text.lstrip("#").strip())
            continue

        if current is None:
            current = {
                "heading_path": heading_stack[:] or ["Document"],
                "page_start": element["page_start"],
                "page_end": element["page_end"],
                "bbox": element.get("bbox"),
                "element_refs": [],
                "provenance_quality": "native",
            }
        else:
            current["page_start"] = min(current["page_start"], element["page_start"])
            current["page_end"] = max(current["page_end"], element["page_end"])
            if current["bbox"] is None and element.get("bbox") is not None:
                current["bbox"] = element["bbox"]
        if element.get("element_ref"):
            current["element_refs"].append(element["element_ref"])

    flush()
    return provenance or [
        SectionProvenance(
            heading_path=["Document"],
            section_title="Document",
            page_start=1,
            page_end=max(1, len(document.pages) or 1),
            bbox=None,
            element_refs=[],
            provenance_quality="missing",
        )
    ]


def _match_provenance(section: MarkdownSection, candidates: list[SectionProvenance], cursor: int) -> tuple[SectionProvenance, int]:
    normalized_title = section.section_title.strip().lower()
    normalized_path = [part.strip().lower() for part in section.heading_path]
    for idx in range(cursor, len(candidates)):
        candidate = candidates[idx]
        if candidate.section_title.strip().lower() == normalized_title:
            return candidate, idx + 1
        if [part.strip().lower() for part in candidate.heading_path] == normalized_path:
            return candidate, idx + 1
    fallback = candidates[min(cursor, len(candidates) - 1)] if candidates else SectionProvenance(
        heading_path=section.heading_path[:],
        section_title=section.section_title,
        page_start=1,
        page_end=1,
        bbox=None,
        element_refs=[],
        provenance_quality="missing",
    )
    return fallback, cursor


def _paragraphs(body_md: str) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", body_md) if block.strip()]
    return blocks or ([body_md.strip()] if body_md.strip() else [])


def build_chunks(document: NormalizedDocument, min_chars: int = 80, max_chars: int = 900) -> list[ChunkRecord]:
    markdown_sections = _split_markdown_sections(document.document_md)
    provenance_sections = _build_section_provenance(document)
    chunks: list[ChunkRecord] = []
    provenance_cursor = 0

    for section in markdown_sections:
        provenance, provenance_cursor = _match_provenance(section, provenance_sections, provenance_cursor)
        paragraphs = _paragraphs(section.body_md)
        pending: list[str] = []

        def flush_pending() -> None:
            nonlocal pending
            text = "\n\n".join(pending).strip()
            if not text:
                pending = []
                return
            if len(text) < min_chars and chunks and chunks[-1].section_title == section.section_title:
                chunks[-1].text_md = f"{chunks[-1].text_md}\n\n{text}".strip()
                chunks[-1].page_start = min(chunks[-1].page_start, provenance.page_start)
                chunks[-1].page_end = max(chunks[-1].page_end, provenance.page_end)
                chunks[-1].element_refs = list(dict.fromkeys(chunks[-1].element_refs + provenance.element_refs))
            else:
                chunk_index = len(chunks)
                chunk_id = f"{document.doc_id}__chunk_{chunk_index:04d}_{slugify(section.section_title)}"
                chunks.append(
                    ChunkRecord(
                        doc_id=document.doc_id,
                        chunk_id=chunk_id,
                        section_title=section.section_title,
                        page_start=provenance.page_start,
                        page_end=provenance.page_end,
                        chunk_index=chunk_index,
                        text_md=text,
                        chunk_type="markdown_section",
                        parser_used=document.parser_used,
                        prev_chunk_id=chunks[-1].chunk_id if chunks else None,
                        next_chunk_id=None,
                        bbox=provenance.bbox,
                        element_refs=provenance.element_refs[:],
                        heading_path=section.heading_path[:],
                        review_status="pending",
                        metadata={"provenance_quality": provenance.provenance_quality},
                    )
                )
            pending = []

        for paragraph in paragraphs:
            projected = "\n\n".join(pending + [paragraph]).strip()
            if pending and len(projected) > max_chars:
                flush_pending()
            pending.append(paragraph)
            if len(projected) > max_chars:
                flush_pending()

        flush_pending()

    for idx, chunk in enumerate(chunks):
        chunk.prev_chunk_id = chunks[idx - 1].chunk_id if idx > 0 else None
        chunk.next_chunk_id = chunks[idx + 1].chunk_id if idx + 1 < len(chunks) else None

    return chunks
