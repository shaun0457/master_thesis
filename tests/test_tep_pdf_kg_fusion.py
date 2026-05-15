from __future__ import annotations

import json
from pathlib import Path

from tep_pdf_kg.markdown_fusion import fuse_markdown_outputs, preclean_markdown


def test_preclean_markdown_removes_images_and_repeated_noise():
    source = """![image 1](<foo.png>)
Page 1
Repeated Header

Repeated Header

## Intro
This is line one
line two
"""
    cleaned = preclean_markdown(source, "opendataloader-pdf")

    assert "![image" not in cleaned
    assert "Page 1" not in cleaned
    assert "Repeated Header" in cleaned
    assert "This is line one line two" in cleaned


def test_fuse_markdown_outputs_writes_canonical_and_alignment(tmp_path: Path):
    out_dir = tmp_path / "doc"
    odl_dir = out_dir / "opendataloader-pdf"
    docling_dir = out_dir / "docling"
    odl_dir.mkdir(parents=True)
    docling_dir.mkdir(parents=True)

    (odl_dir / "document.md").write_text(
        """## Intro

![image 1](<foo.png>)
The process has 12 valves available for manipulation.

## Notes

Repeated Header
Repeated Header
Noisy OCR line.
""",
        encoding="utf-8",
    )
    (docling_dir / "document.md").write_text(
        """## Intro

The process has 12 valves available for manipulation and 41 measurements available for monitoring.

## Notes

Cleaner note line.
""",
        encoding="utf-8",
    )

    report = fuse_markdown_outputs(doc_id="DOWNS.pdf", output_dir=out_dir)

    fusion_dir = out_dir / "fusion"
    canonical = (fusion_dir / "canonical.cleaned.md").read_text(encoding="utf-8")
    alignment = [json.loads(line) for line in (fusion_dir / "alignment.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    stored_report = json.loads((fusion_dir / "fusion_report.json").read_text(encoding="utf-8"))

    assert report["doc_id"] == "DOWNS.pdf"
    assert "41 measurements available for monitoring" in canonical
    assert "![image" not in canonical
    assert any(row["decision_type"] in {"keep_docling", "merge_docling_into_odl"} for row in alignment)
    assert stored_report["canonical_markdown_path"].endswith("canonical.cleaned.md")
    assert (fusion_dir / "odl.preclean.md").exists()
    assert (fusion_dir / "docling.preclean.md").exists()
