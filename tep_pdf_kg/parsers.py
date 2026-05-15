from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .schema import DocumentManifest, NormalizedDocument, ParserRunResult, SectionElement

logger = logging.getLogger(__name__)


def _ensure_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _iter_dicts(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _iter_dicts(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_dicts(item)


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def _extract_bbox(node: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("bbox", "bounding_box", "box"):
        value = node.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and len(value) == 4:
            return {"x0": value[0], "y0": value[1], "x1": value[2], "y1": value[3]}
    return None


def _extract_page_range(node: dict[str, Any]) -> tuple[int | None, int | None]:
    page_start = None
    page_end = None
    for key in ("page_number", "page", "page_no", "page_num"):
        value = _coerce_int(node.get(key))
        if value is not None:
            page_start = value
            page_end = value
            break
    for key in ("page_start", "start_page"):
        value = _coerce_int(node.get(key))
        if value is not None:
            page_start = value
            break
    for key in ("page_end", "end_page"):
        value = _coerce_int(node.get(key))
        if value is not None:
            page_end = value
            break
    if page_start is not None and page_end is None:
        page_end = page_start
    if page_end is not None and page_start is None:
        page_start = page_end
    return page_start, page_end


def _extract_element_type(node: dict[str, Any]) -> str:
    for key in ("type", "label", "kind", "name", "category"):
        value = _ensure_text(node.get(key)).strip().lower()
        if value:
            return value
    return "paragraph"


def _extract_text(node: dict[str, Any]) -> str:
    for key in ("text", "content", "markdown", "md", "plain_text", "plaintext", "title"):
        value = _ensure_text(node.get(key)).strip()
        if value:
            return value
    return ""


def _extract_heading_level(node: dict[str, Any], element_type: str) -> int | None:
    for key in ("heading_level", "level"):
        value = _coerce_int(node.get(key))
        if value is not None:
            return value
    if "heading" in element_type or "title" in element_type:
        return 1
    return None


def _extract_elements(parser_json: Any) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    synthetic_id = 0

    for node in _iter_dicts(parser_json):
        text = _extract_text(node)
        element_type = _extract_element_type(node)
        page_start, page_end = _extract_page_range(node)
        bbox = _extract_bbox(node)
        heading_level = _extract_heading_level(node, element_type)
        element_ref = _ensure_text(node.get("id") or node.get("element_id") or node.get("ref")).strip()

        has_signal = bool(text or bbox or page_start is not None or heading_level is not None)
        if not has_signal:
            continue

        if not element_ref:
            synthetic_id += 1
            element_ref = f"element-{synthetic_id:05d}"
        if element_ref in seen_ids:
            continue
        seen_ids.add(element_ref)

        elements.append(
            {
                "element_ref": element_ref,
                "text": text,
                "element_type": element_type,
                "page_start": page_start,
                "page_end": page_end,
                "bbox": bbox,
                "heading_level": heading_level,
            }
        )

    return elements


def _build_sections(elements: list[dict[str, Any]]) -> tuple[list[SectionElement], list[dict[str, Any]]]:
    sections: list[SectionElement] = []
    page_lines: dict[int, list[str]] = defaultdict(list)
    heading_stack: list[str] = []

    for element in elements:
        page_start = element.get("page_start") or 1
        page_end = element.get("page_end") or page_start
        text = _ensure_text(element.get("text")).strip()
        if text:
            for page_no in range(page_start, page_end + 1):
                page_lines[page_no].append(text)

        heading_level = element.get("heading_level")
        element_type = _ensure_text(element.get("element_type")).lower()
        if heading_level is not None and text:
            level = max(1, int(heading_level))
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(text.lstrip("#").strip())
            continue

        if not text:
            continue

        sections.append(
            SectionElement(
                text_md=text,
                heading_path=heading_stack[:] or ["Document"],
                page_start=page_start,
                page_end=page_end,
                element_type=element_type or "paragraph",
                bbox=element.get("bbox"),
                element_ref=element.get("element_ref"),
            )
        )

    pages = [
        {"page_number": page_no, "text": "\n".join(lines).strip(), "block_count": len(lines)}
        for page_no, lines in sorted(page_lines.items())
    ]
    return sections, pages


def _build_document(
    *,
    manifest: DocumentManifest,
    pdf_path: str,
    parser_name: str,
    document_md: str,
    parser_json: Any,
    output_dir: Path,
) -> NormalizedDocument:
    elements = _extract_elements(parser_json)
    sections, pages = _build_sections(elements)
    return NormalizedDocument(
        doc_id=manifest.doc_id,
        source_path=pdf_path,
        parser_used=parser_name,
        parser_status="ok",
        selected_as_canonical=manifest.selected_parser == parser_name or (
            manifest.selected_parser is None and manifest.preferred_parser == parser_name
        ),
        title=Path(pdf_path).stem.replace("_", " "),
        document_md=document_md,
        sections=sections,
        pages=pages,
        metadata={
            "parser_candidates": manifest.parser_candidates,
            "parser_json": parser_json,
            "parser_output_dir": str(output_dir),
            "document_markdown_path": str(output_dir / "document.md"),
            "document_json_path": str(output_dir / "document.json"),
            "provenance_quality": "native" if elements else "weak",
        },
    )


def _read_first_matching(path: Path, suffix: str, exclude_names: set[str] | None = None) -> Path:
    exclude_names = exclude_names or set()
    candidates = sorted(item for item in path.rglob(f"*{suffix}") if item.name not in exclude_names)
    if not candidates:
        raise FileNotFoundError(f"No {suffix} artifact found in {path}")
    return candidates[0]


def _run_opendataloader(pdf_path: str, output_dir: Path) -> tuple[str, Any]:
    import opendataloader_pdf  # type: ignore

    opendataloader_pdf.convert(input_path=[pdf_path], output_dir=str(output_dir), format="markdown,json")
    markdown_path = _read_first_matching(output_dir, ".md")
    json_path = _read_first_matching(output_dir, ".json")
    return markdown_path.read_text(encoding="utf-8"), json.loads(json_path.read_text(encoding="utf-8"))


def _run_docling(pdf_path: str) -> tuple[str, Any]:
    from docling.document_converter import DocumentConverter  # type: ignore

    result = DocumentConverter().convert(pdf_path)
    return result.document.export_to_markdown(), result.document.export_to_dict()


def run_parser(pdf_path: str, manifest: DocumentManifest, parser_name: str, output_dir: str | Path) -> ParserRunResult:
    parser_dir = Path(output_dir)
    parser_dir.mkdir(parents=True, exist_ok=True)

    try:
        if parser_name == "opendataloader-pdf":
            document_md, parser_json = _run_opendataloader(pdf_path, parser_dir)
        elif parser_name == "docling":
            document_md, parser_json = _run_docling(pdf_path)
        else:
            raise ValueError(f"Unsupported parser: {parser_name}")

        (parser_dir / "document.md").write_text(document_md, encoding="utf-8")
        (parser_dir / "document.json").write_text(json.dumps(parser_json, ensure_ascii=False, indent=2), encoding="utf-8")

        document = _build_document(
            manifest=manifest,
            pdf_path=pdf_path,
            parser_name=parser_name,
            document_md=document_md,
            parser_json=parser_json,
            output_dir=parser_dir,
        )
        return ParserRunResult(parser_name=parser_name, status="ok", document=document)
    except Exception as exc:
        logger.info("Parser %s failed for %s: %s", parser_name, pdf_path, exc)
        placeholder = NormalizedDocument(
            doc_id=manifest.doc_id,
            source_path=pdf_path,
            parser_used=parser_name,
            parser_status="failed",
            selected_as_canonical=False,
            title=Path(pdf_path).stem.replace("_", " "),
            document_md="",
            sections=[],
            pages=[],
            metadata={
                "review_required": True,
                "error": str(exc),
                "parser_output_dir": str(parser_dir),
                "document_markdown_path": str(parser_dir / "document.md"),
                "document_json_path": str(parser_dir / "document.json"),
            },
        )
        return ParserRunResult(
            parser_name=parser_name,
            status="failed",
            document=placeholder,
            warnings=["parser output requires manual review"],
            error=str(exc),
        )
