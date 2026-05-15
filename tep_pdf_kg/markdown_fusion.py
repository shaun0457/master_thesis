from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .schema import ensure_parent, slugify

IMAGE_RE = re.compile(r"!\[[^\]]*]\(<[^>]+>\)|!\[[^\]]*]\([^)]+\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
PAGE_NOISE_RE = re.compile(r"^\s*(page\s+\d+|\d+)\s*$", re.I)
WHITESPACE_RE = re.compile(r"\s+")
NON_ALPHA_RE = re.compile(r"[^A-Za-z]+")


@dataclass(slots=True)
class MarkdownSection:
    section_id: str
    heading: str
    body: str
    order: int


def _write_text(path: Path, content: str) -> None:
    ensure_parent(path)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _normalize_line(line: str) -> str:
    return WHITESPACE_RE.sub(" ", line.strip())


def _line_frequencies(lines: list[str]) -> dict[str, int]:
    freq: dict[str, int] = {}
    for line in lines:
        normalized = _normalize_line(line).lower()
        if not normalized:
            continue
        freq[normalized] = freq.get(normalized, 0) + 1
    return freq


def preclean_markdown(text: str, parser_name: str) -> str:
    del parser_name
    text = IMAGE_RE.sub("", text or "")
    raw_lines = text.splitlines()
    frequencies = _line_frequencies(raw_lines)
    cleaned_lines: list[str] = []

    for raw_line in raw_lines:
        line = _normalize_line(raw_line)
        if not line:
            cleaned_lines.append("")
            continue
        lowered = line.lower()
        if PAGE_NOISE_RE.match(line):
            continue
        if frequencies.get(lowered, 0) >= 3 and len(line) <= 120:
            continue
        cleaned_lines.append(line)

    paragraphs: list[str] = []
    pending: list[str] = []
    for line in cleaned_lines:
        heading_match = HEADING_RE.match(line)
        if heading_match:
            if pending:
                paragraphs.append(" ".join(pending).strip())
                pending = []
            paragraphs.append(line)
            continue
        if not line:
            if pending:
                paragraphs.append(" ".join(pending).strip())
                pending = []
            continue
        pending.append(line)
    if pending:
        paragraphs.append(" ".join(pending).strip())

    output_lines: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            continue
        if HEADING_RE.match(paragraph):
            if output_lines and output_lines[-1] != "":
                output_lines.append("")
            output_lines.append(paragraph)
            output_lines.append("")
        else:
            output_lines.append(paragraph)
            output_lines.append("")
    return "\n".join(output_lines).strip() + "\n"


def _split_sections(markdown_text: str) -> list[MarkdownSection]:
    sections: list[MarkdownSection] = []
    current_heading = "Document"
    current_lines: list[str] = []
    section_index = 0

    def flush() -> None:
        nonlocal current_lines, section_index
        body = "\n".join(line for line in current_lines if line.strip()).strip()
        if not body:
            current_lines = []
            return
        section_id = f"section_{section_index:04d}_{slugify(current_heading)}"
        sections.append(MarkdownSection(section_id=section_id, heading=current_heading, body=body, order=section_index))
        section_index += 1
        current_lines = []

    for line in markdown_text.splitlines():
        match = HEADING_RE.match(line.strip())
        if match:
            flush()
            current_heading = match.group(2).strip()
            continue
        current_lines.append(line)
    flush()

    if not sections and markdown_text.strip():
        sections.append(MarkdownSection(section_id="section_0000_document", heading="Document", body=markdown_text.strip(), order=0))
    return sections


def _normalize_heading(value: str) -> str:
    return NON_ALPHA_RE.sub(" ", value.lower()).strip()


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _quality_score(text: str) -> float:
    if not text.strip():
        return 0.0
    words = text.split()
    alpha_chars = sum(ch.isalpha() for ch in text)
    bad_chars = text.count("�") + text.count("ˇ")
    unique_words = len({word.lower() for word in words})
    return alpha_chars - (bad_chars * 20) + (unique_words * 2)


def _merge_text(base_text: str, other_text: str) -> str:
    if not base_text:
        return other_text
    if not other_text:
        return base_text
    if other_text in base_text:
        return base_text
    if base_text in other_text:
        return other_text

    base_sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", base_text) if sentence.strip()]
    other_sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", other_text) if sentence.strip()]
    merged = base_sentences[:]
    seen = {sentence.lower() for sentence in base_sentences}
    for sentence in other_sentences:
        if sentence.lower() not in seen:
            merged.append(sentence)
            seen.add(sentence.lower())
    return " ".join(merged).strip()


def _align_sections(base_sections: list[MarkdownSection], secondary_sections: list[MarkdownSection]) -> list[dict[str, Any]]:
    alignments: list[dict[str, Any]] = []
    secondary_cursor = 0

    for base in base_sections:
        best_idx: int | None = None
        best_score = 0.0
        base_heading = _normalize_heading(base.heading)
        window_end = min(len(secondary_sections), secondary_cursor + 4)
        for idx in range(secondary_cursor, window_end):
            candidate = secondary_sections[idx]
            heading_score = 1.0 if base_heading and base_heading == _normalize_heading(candidate.heading) else 0.0
            score = max(heading_score, _similarity(base.body[:600], candidate.body[:600]))
            if score > best_score:
                best_score = score
                best_idx = idx

        secondary = secondary_sections[best_idx] if best_idx is not None and best_score >= 0.35 else None
        if secondary is not None:
            secondary_cursor = best_idx + 1

        odl_text = base.body
        docling_text = secondary.body if secondary is not None else ""
        similarity = _similarity(odl_text[:1000], docling_text[:1000]) if docling_text else 0.0
        odl_quality = _quality_score(odl_text)
        docling_quality = _quality_score(docling_text)
        decision = "keep_odl"
        review_required = False
        chosen_text = odl_text

        if not docling_text:
            decision = "keep_odl"
        elif similarity >= 0.82:
            if docling_quality > odl_quality * 1.05:
                decision = "keep_docling"
                chosen_text = docling_text
            else:
                decision = "keep_odl"
        elif docling_quality > odl_quality * 1.15 and similarity >= 0.45:
            decision = "keep_docling"
            chosen_text = docling_text
        elif similarity >= 0.55:
            decision = "merge_docling_into_odl"
            chosen_text = _merge_text(odl_text, docling_text)
        else:
            decision = "review_required"
            review_required = True
            chosen_text = odl_text if odl_quality >= docling_quality else docling_text

        alignments.append(
            {
                "section_id": base.section_id,
                "heading": base.heading,
                "order": base.order,
                "odl_text": odl_text,
                "docling_text": docling_text,
                "chosen_text": chosen_text,
                "decision_type": decision,
                "similarity": round(similarity, 4),
                "odl_quality": round(odl_quality, 2),
                "docling_quality": round(docling_quality, 2),
                "review_required": review_required,
                "rule_tag": decision,
            }
        )

    return alignments


def _render_canonical_markdown(alignments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in sorted(alignments, key=lambda item: item["order"]):
        heading = row["heading"]
        text = row["chosen_text"].strip()
        if heading and heading != "Document":
            if lines:
                lines.append("")
            lines.append(f"## {heading}")
            lines.append("")
        if row.get("review_required"):
            lines.append(f"<!-- review_required: {row['section_id']} -->")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def fuse_markdown_outputs(
    *,
    doc_id: str,
    output_dir: str | Path,
    base_parser: str = "opendataloader-pdf",
    secondary_parser: str = "docling",
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    base_md_path = output_dir / base_parser / "document.md"
    secondary_md_path = output_dir / secondary_parser / "document.md"
    if not base_md_path.exists():
        raise FileNotFoundError(f"Missing base markdown: {base_md_path}")
    if not secondary_md_path.exists():
        raise FileNotFoundError(f"Missing secondary markdown: {secondary_md_path}")

    fusion_dir = output_dir / "fusion"
    odl_preclean = preclean_markdown(base_md_path.read_text(encoding="utf-8"), base_parser)
    docling_preclean = preclean_markdown(secondary_md_path.read_text(encoding="utf-8"), secondary_parser)
    _write_text(fusion_dir / "odl.preclean.md", odl_preclean)
    _write_text(fusion_dir / "docling.preclean.md", docling_preclean)

    base_sections = _split_sections(odl_preclean)
    secondary_sections = _split_sections(docling_preclean)
    alignments = _align_sections(base_sections, secondary_sections)
    canonical_md = _render_canonical_markdown(alignments)
    _write_text(fusion_dir / "canonical.cleaned.md", canonical_md)
    _write_jsonl(fusion_dir / "alignment.jsonl", alignments)

    report = {
        "doc_id": doc_id,
        "base_parser": base_parser,
        "secondary_parser": secondary_parser,
        "preclean_stats": {
            "odl_chars": len(odl_preclean),
            "docling_chars": len(docling_preclean),
        },
        "alignment_stats": {
            "section_count": len(alignments),
            "avg_similarity": round(sum(row["similarity"] for row in alignments) / len(alignments), 4) if alignments else 0.0,
        },
        "sections_from_odl": sum(1 for row in alignments if row["decision_type"] == "keep_odl"),
        "sections_from_docling": sum(1 for row in alignments if row["decision_type"] == "keep_docling"),
        "sections_merged": sum(1 for row in alignments if row["decision_type"] == "merge_docling_into_odl"),
        "sections_flagged_for_review": sum(1 for row in alignments if row["review_required"]),
        "canonical_markdown_path": str(fusion_dir / "canonical.cleaned.md"),
    }
    _write_json(fusion_dir / "fusion_report.json", report)
    return report
