from __future__ import annotations

import json
from pathlib import Path

from tep_pdf_kg.markdown_fusion import fuse_markdown_outputs, preclean_markdown


def test_preclean_markdown_removes_images_page_headers_and_promotes_real_headings():
    source = """![image 1](<foo.png>)
Page 1
246 J. J. DOWNS and E. F. VOGEL
INTRODUCTION
This is line one
line two
"""
    cleaned = preclean_markdown(source, "opendataloader-pdf")

    assert "![image" not in cleaned
    assert "Page 1" not in cleaned
    assert "246 J. J. DOWNS" not in cleaned
    assert "## Introduction" in cleaned
    assert "This is line one\nline two" in cleaned


def test_fuse_markdown_outputs_defers_noisy_tables_and_writes_review_candidates(tmp_path: Path):
    out_dir = tmp_path / "doc"
    odl_dir = out_dir / "opendataloader-pdf"
    docling_dir = out_dir / "docling"
    odl_dir.mkdir(parents=True)
    docling_dir.mkdir(parents=True)

    (odl_dir / "document.md").write_text(
        """INTRODUCTION

The process has 12 valves available for manipulation.

Table 1. Heat and material balance data
1 2 3 4 5
0.123 0.456 0.789
""",
        encoding="utf-8",
    )
    (docling_dir / "document.md").write_text(
        """## Introduction

The process has 12 valves available for manipulation and 41 measurements available for monitoring.
""",
        encoding="utf-8",
    )

    report = fuse_markdown_outputs(doc_id="DOWNS.pdf", output_dir=out_dir)

    fusion_dir = out_dir / "fusion"
    canonical = (fusion_dir / "canonical.cleaned.md").read_text(encoding="utf-8")
    alignment = [json.loads(line) for line in (fusion_dir / "alignment.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    review_candidates = [
        json.loads(line) for line in (fusion_dir / "review_candidates.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    assert report["doc_id"] == "DOWNS.pdf"
    assert "41 measurements available for monitoring" in canonical
    assert "Table 1. Heat and material balance data" not in canonical
    assert any(row["decision_type"] == "defer_table_review" for row in alignment)
    assert any(row["repair_candidate"] for row in review_candidates)
    assert report["deferred_table_count"] >= 1
    assert (fusion_dir / "review_candidates.jsonl").exists()


def test_fuse_markdown_outputs_keeps_docling_only_cleaner_prose(tmp_path: Path):
    out_dir = tmp_path / "doc"
    odl_dir = out_dir / "opendataloader-pdf"
    docling_dir = out_dir / "docling"
    odl_dir.mkdir(parents=True)
    docling_dir.mkdir(parents=True)

    (odl_dir / "document.md").write_text(
        """PROCESS DESCRIPTION

The process has five major unit operations.
""",
        encoding="utf-8",
    )
    (docling_dir / "document.md").write_text(
        """## Process Description

The process has five major unit operations.

Products G and H exit the stripper base and are separated in a downstream refining section.
""",
        encoding="utf-8",
    )

    report = fuse_markdown_outputs(doc_id="DOWNS.pdf", output_dir=out_dir)
    fusion_dir = out_dir / "fusion"
    canonical = (fusion_dir / "canonical.cleaned.md").read_text(encoding="utf-8")
    alignment = [json.loads(line) for line in (fusion_dir / "alignment.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    assert "Products G and H exit the stripper base" in canonical
    assert any(row["decision_type"] == "keep_docling_prose" for row in alignment)
    assert report["prose_blocks_from_docling"] >= 1
