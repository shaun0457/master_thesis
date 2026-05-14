from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Callable

import fitz

from .schema import DocumentManifest, NormalizedDocument, ParserRunResult, SectionElement

logger = logging.getLogger(__name__)


HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+(.+)$")


def _extract_with_pymupdf(pdf_path: str) -> tuple[list[dict], list[SectionElement], str]:
    pdf = fitz.open(pdf_path)
    pages: list[dict] = []
    sections: list[SectionElement] = []
    full_lines: list[str] = []
    heading_path: list[str] = []

    for page_idx, page in enumerate(pdf, start=1):
        blocks = page.get_text("blocks")
        page_lines: list[str] = []
        page_text = page.get_text("text")
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = HEADING_RE.match(line)
            if match and len(line.split()) <= 12:
                heading_text = match.group(2).strip()
                heading_path = [heading_text]
                full_lines.append(f"\n## {heading_text}\n")
                page_lines.append(line)
                continue
            full_lines.append(line)
            page_lines.append(line)
            sections.append(
                SectionElement(
                    text_md=line,
                    heading_path=heading_path[:] or ["Document"],
                    page_start=page_idx,
                    page_end=page_idx,
                    element_type="paragraph",
                    bbox=None,
                    element_ref=f"page-{page_idx}-line-{len(page_lines)}",
                )
            )
        pages.append(
            {
                "page_number": page_idx,
                "text": "\n".join(page_lines),
                "block_count": len(blocks),
            }
        )
    title = Path(pdf_path).stem.replace("_", " ")
    return pages, sections, "\n".join(full_lines).strip() + "\n"


def _build_parser_adapter(parser_name: str) -> Callable[[str], tuple[list[dict], list[SectionElement], str]]:
    parser_name = parser_name.lower()

    def adapter(pdf_path: str) -> tuple[list[dict], list[SectionElement], str]:
        native_enabled = os.environ.get("TEP_KG_ENABLE_NATIVE_PARSERS", "").strip() == "1"
        if not native_enabled:
            return _extract_with_pymupdf(pdf_path)

        if parser_name == "opendataloader-pdf":
            try:
                import opendataloader_pdf  # type: ignore  # pragma: no cover

                loader = getattr(opendataloader_pdf, "load_pdf", None)
                if callable(loader):
                    result = loader(pdf_path)
                    raise NotImplementedError(
                        "opendataloader-pdf native output mapping not implemented yet; "
                        "fallback to PyMuPDF normalization."
                    )
            except Exception as exc:
                logger.info("Parser %s unavailable or unsupported (%s); using PyMuPDF fallback", parser_name, exc)
            return _extract_with_pymupdf(pdf_path)

        if parser_name == "docling":
            try:
                from docling.document_converter import DocumentConverter  # type: ignore  # pragma: no cover

                converter = DocumentConverter()
                result = converter.convert(pdf_path)
                raise NotImplementedError(
                    "Docling native output mapping not implemented yet; fallback to PyMuPDF normalization."
                )
            except Exception as exc:
                logger.info("Parser %s unavailable or unsupported (%s); using PyMuPDF fallback", parser_name, exc)
            return _extract_with_pymupdf(pdf_path)

        raise ValueError(f"Unsupported parser: {parser_name}")

    return adapter


def run_parser(pdf_path: str, manifest: DocumentManifest, parser_name: str) -> ParserRunResult:
    adapter = _build_parser_adapter(parser_name)
    try:
        pages, sections, document_md = adapter(pdf_path)
        document = NormalizedDocument(
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
            metadata={"parser_candidates": manifest.parser_candidates},
        )
        return ParserRunResult(parser_name=parser_name, status="ok", document=document)
    except Exception as exc:
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
            metadata={"review_required": True, "error": str(exc)},
        )
        return ParserRunResult(
            parser_name=parser_name,
            status="failed",
            document=placeholder,
            warnings=["parser output requires manual review"],
            error=str(exc),
        )
