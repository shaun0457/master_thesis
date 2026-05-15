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
FIGURE_RE = re.compile(r"^(fig(?:ure)?\.?|chart|flowchart)\b", re.I)
TABLE_RE = re.compile(r"^table\s+\d+", re.I)
UPPER_HEADING_RE = re.compile(r"^[A-Z][A-Z\s/&(),.'-]{4,}$")
PAGE_HEADER_RE = re.compile(
    r"^(?:\d+\s+)?(?:plant-?wide|j\.\s*j\.\s*downs|e\.\s*f\.\s*vogel|computers|engng|vol\.|pcrgamon|printed in great britain|0098-)",
    re.I,
)
FORMULA_PLACEHOLDER_RE = re.compile(r"^<!--\s*formula-not-decoded\s*-->$", re.I)
IMAGE_PLACEHOLDER_RE = re.compile(r"^<!--\s*image\s*-->$", re.I)
WHITESPACE_RE = re.compile(r"\s+")
NON_ALPHA_RE = re.compile(r"[^A-Za-z]+")
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

PROSE_TYPES = {"prose"}
DEFER_TYPES = {"table", "formula"}
SUPPRESS_TYPES = {"figure", "garbage"}


@dataclass(slots=True)
class MarkdownBlock:
    block_id: str
    section_id: str
    heading: str
    text: str
    order: float
    block_type: str
    parser_name: str
    quality_score: float
    token_count: int


@dataclass(slots=True)
class MarkdownSection:
    section_id: str
    heading: str
    order: int
    blocks: list[MarkdownBlock]


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
        if normalized:
            freq[normalized] = freq.get(normalized, 0) + 1
    return freq


def _alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    meaningful = [char for char in text if not char.isspace()]
    if not meaningful:
        return 0.0
    return sum(char.isalpha() for char in meaningful) / len(meaningful)


def _looks_like_page_header(line: str) -> bool:
    normalized = _normalize_line(line)
    if not normalized:
        return False
    if PAGE_HEADER_RE.match(normalized):
        return True
    if re.match(r"^\d+\s+[A-Z].{0,80}$", normalized) and _alpha_ratio(normalized) > 0.65:
        return True
    return False


def _should_promote_heading(line: str) -> bool:
    normalized = _normalize_line(line)
    if not normalized or _looks_like_page_header(normalized):
        return False
    if UPPER_HEADING_RE.match(normalized):
        return True
    return normalized in {"Introduction", "Process Description", "Summary", "References"}


def _normalize_for_similarity(text: str) -> str:
    text = text or ""
    text = text.replace("_", " ")
    text = re.sub(r"<!--\s*formula-not-decoded\s*-->", " formula ", text, flags=re.I)
    text = re.sub(r"<!--\s*image\s*-->", " image ", text, flags=re.I)
    return WHITESPACE_RE.sub(" ", text).strip().lower()


def _token_set(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text)}


def _jaccard_similarity(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_norm = _normalize_for_similarity(left)
    right_norm = _normalize_for_similarity(right)
    sequence = SequenceMatcher(None, left_norm[:1500], right_norm[:1500]).ratio()
    jaccard = _jaccard_similarity(left_norm, right_norm)
    return (sequence * 0.65) + (jaccard * 0.35)


def _normalize_heading(value: str) -> str:
    return NON_ALPHA_RE.sub(" ", value.lower()).strip()


def _quality_score(text: str, block_type: str) -> float:
    text = text.strip()
    if not text:
        return 0.0
    alpha_chars = sum(char.isalpha() for char in text)
    digit_chars = sum(char.isdigit() for char in text)
    symbol_chars = sum(not char.isalnum() and not char.isspace() for char in text)
    token_count = len(_token_set(text))
    score = float(alpha_chars + token_count * 4 - symbol_chars * 1.5)
    if block_type == "prose":
        score += 60
    elif block_type == "table":
        score -= 35
    elif block_type == "formula":
        score -= 25
    elif block_type in SUPPRESS_TYPES:
        score -= 120
    if digit_chars > alpha_chars:
        score -= 25
    return round(score, 2)


def _merge_text(base_text: str, other_text: str) -> str:
    if not base_text:
        return other_text
    if not other_text:
        return base_text
    if _normalize_for_similarity(other_text) in _normalize_for_similarity(base_text):
        return base_text
    if _normalize_for_similarity(base_text) in _normalize_for_similarity(other_text):
        return other_text

    base_sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", base_text) if part.strip()]
    other_sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", other_text) if part.strip()]
    merged = base_sentences[:]
    seen = {_normalize_for_similarity(sentence) for sentence in base_sentences}
    for sentence in other_sentences:
        normalized = _normalize_for_similarity(sentence)
        if normalized not in seen:
            merged.append(sentence)
            seen.add(normalized)
    return " ".join(merged).strip()


def _classify_block(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "garbage"
    if FORMULA_PLACEHOLDER_RE.match(stripped):
        return "formula"
    if IMAGE_PLACEHOLDER_RE.match(stripped):
        return "figure"
    if TABLE_RE.match(stripped):
        return "table"
    if FIGURE_RE.match(stripped):
        return "figure"
    if re.search(r"\b[A-Z]\(g\)|\(liq\)|arrhenius|raoult", stripped):
        return "formula"
    if "|" in stripped and stripped.count("|") >= 2:
        return "table"
    lines = [line for line in stripped.splitlines() if line.strip()]
    alpha = _alpha_ratio(stripped)
    digit_ratio = sum(char.isdigit() for char in stripped) / max(1, len(stripped))
    token_count = len(_token_set(stripped))
    if len(lines) > 3 and digit_ratio > 0.12 and alpha < 0.68:
        return "table"
    if stripped.count("<!-- formula-not-decoded -->") >= 1:
        return "formula"
    if alpha < 0.32 and token_count < 12:
        return "garbage"
    if any(line.startswith("- ") for line in lines) and digit_ratio > 0.10 and alpha < 0.72:
        return "table"
    if len(lines) == 1 and _should_promote_heading(stripped):
        return "headingish"
    if token_count < 5 and alpha < 0.72:
        return "garbage"
    return "prose"


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
        if _looks_like_page_header(line):
            continue
        if IMAGE_PLACEHOLDER_RE.match(line):
            cleaned_lines.append("")
            continue
        if frequencies.get(lowered, 0) >= 3 and len(line) <= 120 and not HEADING_RE.match(line):
            continue
        if _should_promote_heading(line) and not HEADING_RE.match(line):
            cleaned_lines.append(f"## {line.title() if line.isupper() else line}")
            continue
        cleaned_lines.append(line)

    paragraphs: list[str] = []
    pending: list[str] = []
    for line in cleaned_lines:
        heading_match = HEADING_RE.match(line)
        if heading_match:
            if pending:
                paragraphs.append("\n".join(pending).strip())
                pending = []
            heading_text = heading_match.group(2).strip()
            if _looks_like_page_header(heading_text):
                continue
            paragraphs.append(f"## {heading_text}")
            continue
        if not line:
            if pending:
                paragraphs.append("\n".join(pending).strip())
                pending = []
            continue
        pending.append(line)
    if pending:
        paragraphs.append("\n".join(pending).strip())

    output_lines: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            continue
        if HEADING_RE.match(paragraph):
            if output_lines and output_lines[-1] != "":
                output_lines.append("")
            output_lines.append(paragraph)
            output_lines.append("")
            continue
        block_type = _classify_block(paragraph)
        if block_type == "garbage":
            continue
        output_lines.append(paragraph)
        output_lines.append("")
    return "\n".join(output_lines).strip() + "\n"


def _split_sections(markdown_text: str, parser_name: str) -> list[MarkdownSection]:
    sections: list[MarkdownSection] = []
    current_heading = "Document"
    current_items: list[str] = []
    section_index = 0

    def flush() -> None:
        nonlocal current_items, section_index
        blocks: list[MarkdownBlock] = []
        block_index = 0
        for item in current_items:
            text = item.strip()
            if not text:
                continue
            block_type = _classify_block(text)
            if block_type == "headingish":
                block_type = "prose"
            block_id = f"{section_index:04d}_{block_index:03d}_{block_type}"
            blocks.append(
                MarkdownBlock(
                    block_id=block_id,
                    section_id=f"section_{section_index:04d}_{slugify(current_heading)}",
                    heading=current_heading,
                    text=text,
                    order=float(block_index),
                    block_type=block_type,
                    parser_name=parser_name,
                    quality_score=_quality_score(text, block_type),
                    token_count=len(_token_set(text)),
                )
            )
            block_index += 1
        if blocks:
            sections.append(
                MarkdownSection(
                    section_id=f"section_{section_index:04d}_{slugify(current_heading)}",
                    heading=current_heading,
                    order=section_index,
                    blocks=blocks,
                )
            )
            section_index += 1
        current_items = []

    for paragraph in [part.strip() for part in markdown_text.split("\n\n") if part.strip()]:
        match = HEADING_RE.match(paragraph)
        if match:
            flush()
            current_heading = match.group(2).strip()
            continue
        current_items.append(paragraph)
    flush()

    if not sections and markdown_text.strip():
        current_items = [markdown_text.strip()]
        flush()
    return sections


def _find_matching_section(
    base_section: MarkdownSection,
    secondary_sections: list[MarkdownSection],
    secondary_cursor: int,
) -> tuple[MarkdownSection | None, int, float]:
    best_section: MarkdownSection | None = None
    best_idx = secondary_cursor
    best_score = 0.0
    base_heading = _normalize_heading(base_section.heading)
    base_text = "\n".join(block.text for block in base_section.blocks if block.block_type in {"prose", "table"})

    for idx in range(secondary_cursor, min(len(secondary_sections), secondary_cursor + 6)):
        candidate = secondary_sections[idx]
        heading_score = 1.0 if base_heading and base_heading == _normalize_heading(candidate.heading) else 0.0
        candidate_text = "\n".join(block.text for block in candidate.blocks if block.block_type in {"prose", "table"})
        text_score = _similarity(base_text[:2000], candidate_text[:2000])
        block_type_overlap = 0.2 if {block.block_type for block in base_section.blocks} & {block.block_type for block in candidate.blocks} else 0.0
        score = max(heading_score, text_score) + block_type_overlap
        if score > best_score:
            best_score = score
            best_idx = idx
            best_section = candidate

    if best_section is None or best_score < 0.24:
        return None, secondary_cursor, 0.0
    return best_section, best_idx + 1, round(min(best_score, 1.0), 4)


def _find_matching_block(base_block: MarkdownBlock, secondary_blocks: list[MarkdownBlock], used: set[int]) -> tuple[int | None, float]:
    best_idx: int | None = None
    best_score = 0.0
    for idx, candidate in enumerate(secondary_blocks):
        if idx in used:
            continue
        if base_block.block_type in PROSE_TYPES and candidate.block_type not in PROSE_TYPES:
            continue
        if base_block.block_type in DEFER_TYPES and candidate.block_type in PROSE_TYPES:
            continue
        type_bonus = 0.15 if base_block.block_type == candidate.block_type else 0.0
        text_score = _similarity(base_block.text, candidate.text)
        order_penalty = abs(base_block.order - candidate.order) * 0.05
        score = text_score + type_bonus - order_penalty
        if score > best_score:
            best_score = score
            best_idx = idx
    if best_idx is None or best_score < 0.22:
        return None, 0.0
    return best_idx, round(min(best_score, 1.0), 4)


def _row_from_decision(
    *,
    section: MarkdownSection,
    order: float,
    odl_block: MarkdownBlock | None,
    docling_block: MarkdownBlock | None,
    decision_type: str,
    chosen_text: str,
    alignment_confidence: float,
    suppressed: bool,
    repair_candidate: bool,
    defer_reason: str | None,
) -> dict[str, Any]:
    odl_text = odl_block.text if odl_block is not None else ""
    docling_text = docling_block.text if docling_block is not None else ""
    block_type = odl_block.block_type if odl_block is not None else (docling_block.block_type if docling_block is not None else "garbage")
    review_required = repair_candidate or decision_type.startswith("review_required")
    return {
        "section_id": section.section_id,
        "heading": section.heading,
        "order": round(order, 3),
        "block_type": block_type,
        "odl_text": odl_text,
        "docling_text": docling_text,
        "chosen_text": chosen_text,
        "decision_type": decision_type,
        "similarity": round(_similarity(odl_text, docling_text), 4) if odl_text and docling_text else 0.0,
        "alignment_confidence": round(alignment_confidence, 4),
        "odl_quality": odl_block.quality_score if odl_block is not None else 0.0,
        "docling_quality": docling_block.quality_score if docling_block is not None else 0.0,
        "review_required": review_required,
        "suppressed": suppressed,
        "repair_candidate": repair_candidate,
        "defer_reason": defer_reason,
        "rule_tag": decision_type,
    }


def _merge_section_blocks(base_section: MarkdownSection, secondary_section: MarkdownSection | None) -> list[dict[str, Any]]:
    secondary_blocks = secondary_section.blocks if secondary_section is not None else []
    used_secondary: set[int] = set()
    rows: list[dict[str, Any]] = []

    for base_index, base_block in enumerate(base_section.blocks):
        sort_order = float(base_section.order) * 1000 + base_index

        if base_block.block_type in SUPPRESS_TYPES:
            rows.append(
                _row_from_decision(
                    section=base_section,
                    order=sort_order,
                    odl_block=base_block,
                    docling_block=None,
                    decision_type="suppress_noise",
                    chosen_text="",
                    alignment_confidence=1.0,
                    suppressed=True,
                    repair_candidate=False,
                    defer_reason="noise_block",
                )
            )
            continue

        if base_block.block_type in DEFER_TYPES:
            decision = "defer_table_review" if base_block.block_type == "table" else "defer_formula_review"
            rows.append(
                _row_from_decision(
                    section=base_section,
                    order=sort_order,
                    odl_block=base_block,
                    docling_block=None,
                    decision_type=decision,
                    chosen_text="",
                    alignment_confidence=0.2,
                    suppressed=True,
                    repair_candidate=True,
                    defer_reason=base_block.block_type,
                )
            )
            continue

        match_idx, match_confidence = _find_matching_block(base_block, secondary_blocks, used_secondary)
        secondary_block = secondary_blocks[match_idx] if match_idx is not None else None
        if match_idx is not None:
            used_secondary.add(match_idx)

        if secondary_block is None:
            rows.append(
                _row_from_decision(
                    section=base_section,
                    order=sort_order,
                    odl_block=base_block,
                    docling_block=None,
                    decision_type="keep_odl_prose",
                    chosen_text=base_block.text,
                    alignment_confidence=0.0,
                    suppressed=False,
                    repair_candidate=False,
                    defer_reason=None,
                )
            )
            continue

        if secondary_block.block_type in SUPPRESS_TYPES:
            rows.append(
                _row_from_decision(
                    section=base_section,
                    order=sort_order,
                    odl_block=base_block,
                    docling_block=secondary_block,
                    decision_type="keep_odl_prose",
                    chosen_text=base_block.text,
                    alignment_confidence=match_confidence,
                    suppressed=False,
                    repair_candidate=False,
                    defer_reason=None,
                )
            )
            continue

        similarity = _similarity(base_block.text, secondary_block.text)
        odl_quality = base_block.quality_score
        docling_quality = secondary_block.quality_score

        if similarity >= 0.82:
            if docling_quality > odl_quality * 1.05:
                decision = "keep_docling_prose"
                chosen_text = secondary_block.text
            else:
                decision = "keep_odl_prose"
                chosen_text = base_block.text
            rows.append(
                _row_from_decision(
                    section=base_section,
                    order=sort_order,
                    odl_block=base_block,
                    docling_block=secondary_block,
                    decision_type=decision,
                    chosen_text=chosen_text,
                    alignment_confidence=match_confidence,
                    suppressed=False,
                    repair_candidate=False,
                    defer_reason=None,
                )
            )
            continue

        if similarity >= 0.46 and docling_quality > odl_quality * 1.18:
            rows.append(
                _row_from_decision(
                    section=base_section,
                    order=sort_order,
                    odl_block=base_block,
                    docling_block=secondary_block,
                    decision_type="keep_docling_prose",
                    chosen_text=secondary_block.text,
                    alignment_confidence=match_confidence,
                    suppressed=False,
                    repair_candidate=False,
                    defer_reason=None,
                )
            )
            continue

        if similarity >= 0.50 and min(odl_quality, docling_quality) > 40:
            rows.append(
                _row_from_decision(
                    section=base_section,
                    order=sort_order,
                    odl_block=base_block,
                    docling_block=secondary_block,
                    decision_type="merge_prose",
                    chosen_text=_merge_text(base_block.text, secondary_block.text),
                    alignment_confidence=match_confidence,
                    suppressed=False,
                    repair_candidate=False,
                    defer_reason=None,
                )
            )
            continue

        if docling_quality > odl_quality * 1.35 and secondary_block.token_count >= max(8, base_block.token_count // 2):
            rows.append(
                _row_from_decision(
                    section=base_section,
                    order=sort_order,
                    odl_block=base_block,
                    docling_block=secondary_block,
                    decision_type="keep_docling_prose",
                    chosen_text=secondary_block.text,
                    alignment_confidence=match_confidence,
                    suppressed=False,
                    repair_candidate=True,
                    defer_reason="low_confidence_docling_override",
                )
            )
            continue

        rows.append(
            _row_from_decision(
                section=base_section,
                order=sort_order,
                odl_block=base_block,
                docling_block=secondary_block,
                decision_type="review_required_conflict",
                chosen_text=base_block.text if odl_quality >= docling_quality else secondary_block.text,
                alignment_confidence=match_confidence,
                suppressed=False,
                repair_candidate=True,
                defer_reason="prose_conflict",
            )
        )

    for idx, secondary_block in enumerate(secondary_blocks):
        if idx in used_secondary:
            continue
        if secondary_block.block_type not in PROSE_TYPES:
            continue
        rows.append(
            _row_from_decision(
                section=base_section,
                order=float(base_section.order) * 1000 + 800 + idx,
                odl_block=None,
                docling_block=secondary_block,
                decision_type="keep_docling_prose",
                chosen_text=secondary_block.text,
                alignment_confidence=0.25,
                suppressed=False,
                repair_candidate=True,
                defer_reason="docling_only_prose",
            )
        )

    return rows


def _align_sections(base_sections: list[MarkdownSection], secondary_sections: list[MarkdownSection]) -> list[dict[str, Any]]:
    alignments: list[dict[str, Any]] = []
    secondary_cursor = 0

    for base_section in base_sections:
        matched_section, secondary_cursor, _ = _find_matching_section(base_section, secondary_sections, secondary_cursor)
        alignments.extend(_merge_section_blocks(base_section, matched_section))

    return sorted(alignments, key=lambda item: item["order"])


def _render_canonical_markdown(alignments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    active_heading: str | None = None
    for row in alignments:
        heading = row["heading"]
        chosen_text = str(row["chosen_text"]).strip()
        if row.get("suppressed") and not row.get("repair_candidate"):
            continue
        should_render_text = bool(chosen_text)
        if row.get("decision_type") in {"defer_table_review", "defer_formula_review", "review_required_conflict"}:
            should_render_text = False
        if row.get("defer_reason") == "low_confidence_docling_override":
            should_render_text = False
        if row.get("defer_reason") == "docling_only_prose":
            if len(_token_set(chosen_text)) < 12 or not re.search(r"[.!?]", chosen_text):
                should_render_text = False
        if heading and heading != "Document" and heading != active_heading:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"## {heading}")
            lines.append("")
            active_heading = heading
        if row.get("repair_candidate"):
            reason = row.get("defer_reason") or row["decision_type"]
            lines.append(f"<!-- review_candidate: {row['section_id']} [{reason}] -->")
            if not should_render_text:
                lines.append("")
                continue
        if should_render_text:
            lines.append(chosen_text)
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

    base_sections = _split_sections(odl_preclean, base_parser)
    secondary_sections = _split_sections(docling_preclean, secondary_parser)
    alignments = _align_sections(base_sections, secondary_sections)
    canonical_md = _render_canonical_markdown(alignments)
    review_candidates = [row for row in alignments if row.get("repair_candidate")]

    _write_text(fusion_dir / "canonical.cleaned.md", canonical_md)
    _write_jsonl(fusion_dir / "alignment.jsonl", alignments)
    _write_jsonl(fusion_dir / "review_candidates.jsonl", review_candidates)

    report = {
        "doc_id": doc_id,
        "base_parser": base_parser,
        "secondary_parser": secondary_parser,
        "preclean_stats": {
            "odl_chars": len(odl_preclean),
            "docling_chars": len(docling_preclean),
        },
        "alignment_stats": {
            "section_count": len(base_sections),
            "block_alignment_count": len(alignments),
            "avg_similarity": round(
                sum(row["similarity"] for row in alignments if row["similarity"] > 0) / max(1, sum(1 for row in alignments if row["similarity"] > 0)),
                4,
            ),
        },
        "prose_blocks_from_odl": sum(1 for row in alignments if row["decision_type"] == "keep_odl_prose"),
        "prose_blocks_from_docling": sum(1 for row in alignments if row["decision_type"] == "keep_docling_prose"),
        "merged_prose_blocks": sum(1 for row in alignments if row["decision_type"] == "merge_prose"),
        "suppressed_noise_count": sum(1 for row in alignments if row["decision_type"] == "suppress_noise"),
        "deferred_table_count": sum(1 for row in alignments if row["decision_type"] == "defer_table_review"),
        "deferred_formula_count": sum(1 for row in alignments if row["decision_type"] == "defer_formula_review"),
        "low_confidence_alignment_count": sum(1 for row in alignments if row["repair_candidate"]),
        "sections_flagged_for_review": sum(1 for row in alignments if row["review_required"]),
        "canonical_markdown_path": str(fusion_dir / "canonical.cleaned.md"),
        "review_candidates_path": str(fusion_dir / "review_candidates.jsonl"),
    }
    _write_json(fusion_dir / "fusion_report.json", report)
    return report
