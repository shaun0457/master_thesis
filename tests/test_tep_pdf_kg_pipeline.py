from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from tep_pdf_kg.chunking import build_chunks
from tep_pdf_kg.extraction import extract_claims
from tep_pdf_kg.neo4j_import import claim_queries, chunk_document_queries, schema_queries
from tep_pdf_kg.pipeline import run_document_pipeline
from tep_pdf_kg.schema import ChunkRecord, DocumentManifest, NormalizedDocument, SectionElement
from tep_pdf_kg.validation import validate_claims


def _sample_document() -> NormalizedDocument:
    return NormalizedDocument(
        doc_id="DOWNS.pdf",
        source_path="TEP_docs/DOWNS.pdf",
        parser_used="opendataloader-pdf",
        parser_status="ok",
        selected_as_canonical=True,
        title="DOWNS",
        document_md=(
            "## Fault 4\n"
            "Fault 4 causes high reactor temperature. "
            "High reactor temperature observed by xmeas_9. "
            "Fault 4 affects Reactor. "
            "Fault 4 suggests increase cooling water flow. "
            "Increase cooling water flow on cooling water valve. "
            "Control action increase cooling water flow subject to separator pressure limit. "
            "Control action increase cooling water flow risk off-spec product.\n"
        ),
        sections=[
            SectionElement(
                text_md=(
                    "Fault 4 causes high reactor temperature. "
                    "High reactor temperature observed by xmeas_9. "
                    "Fault 4 affects Reactor. "
                    "Fault 4 suggests increase cooling water flow. "
                    "Increase cooling water flow on cooling water valve. "
                    "Control action increase cooling water flow subject to separator pressure limit. "
                    "Control action increase cooling water flow risk off-spec product."
                ),
                heading_path=["Fault 4"],
                page_start=12,
                page_end=12,
                element_ref="page-12-line-1",
            )
        ],
        pages=[{"page_number": 12, "text": "Fault 4...", "block_count": 1}],
        metadata={},
    )


def test_chunk_builder_preserves_traceability_fields():
    chunks = build_chunks(_sample_document(), min_chars=10, max_chars=1000)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.doc_id == "DOWNS.pdf"
    assert chunk.page_start == 12
    assert chunk.page_end == 12
    assert chunk.section_title == "Fault 4"
    assert chunk.prev_chunk_id is None
    assert chunk.next_chunk_id is None
    assert chunk.element_refs == ["page-12-line-1"]


def test_extract_validate_and_prepare_claim_queries():
    chunk = build_chunks(_sample_document(), min_chars=10, max_chars=1000)[0]

    raw_claims = extract_claims(chunk)
    validated, rejected = validate_claims(raw_claims)
    queries = claim_queries(validated)

    predicates = {claim.predicate for claim in validated}
    assert {"CAUSES", "OBSERVED_BY", "AFFECTS_UNIT", "SUGGESTS_ACTION", "ACTS_ON", "SUBJECT_TO", "HAS_RISK"} <= predicates
    assert rejected == []
    assert queries
    assert all("source_chunk_id" not in params for _, params in queries)
    assert all("MERGE (c:Chunk {chunk_id: $chunk_id})" in query for query, _ in queries)


def test_schema_and_chunk_document_queries_cover_v1_entities():
    document = _sample_document()
    chunks = build_chunks(document, min_chars=10, max_chars=1000)

    schema = schema_queries()
    query_pairs = chunk_document_queries(document, chunks)

    assert any("fault_idv_number" in query for query in schema)
    assert any("Document" in query for query in schema)
    assert any("MERGE (d:Document" in query for query, _ in query_pairs)
    assert any("MERGE (c:Chunk" in query for query, _ in query_pairs)


def test_pipeline_writes_all_stage_artifacts(tmp_path: Path, monkeypatch):
    document = _sample_document()

    def fake_run_parser(pdf_path, manifest, parser_name):
        clone = NormalizedDocument(
            doc_id=document.doc_id,
            source_path=pdf_path,
            parser_used=parser_name,
            parser_status="ok",
            selected_as_canonical=parser_name == manifest.preferred_parser,
            title=document.title,
            document_md=document.document_md,
            sections=document.sections,
            pages=document.pages,
            metadata=document.metadata,
        )
        return MagicMock(
            parser_name=parser_name,
            status="ok",
            document=clone,
            to_dict=lambda: {
                "parser_name": parser_name,
                "status": "ok",
                "document": clone.to_dict(),
                "warnings": [],
                "error": None,
            },
        )

    monkeypatch.setattr("tep_pdf_kg.pipeline.run_parser", fake_run_parser)
    manifest = DocumentManifest(
        doc_id="DOWNS.pdf",
        pdf_path=str(tmp_path / "DOWNS.pdf"),
        output_dir=str(tmp_path / "out"),
    )
    Path(manifest.pdf_path).write_bytes(b"%PDF-1.4\n")

    summary = run_document_pipeline(manifest)

    out_dir = Path(summary["output_dir"])
    assert summary["selected_parser"] == "opendataloader-pdf"
    assert (out_dir / "chunks.jsonl").exists()
    assert (out_dir / "claims.raw.jsonl").exists()
    assert (out_dir / "claims.validated.jsonl").exists()
    assert (out_dir / "claims.rejected.json").exists()
    assert (out_dir / "pipeline_summary.json").exists()
    assert (out_dir / "opendataloader-pdf" / "document.md").exists()
    assert (out_dir / "docling" / "parser_report.json").exists()

    validated = [
        json.loads(line)
        for line in (out_dir / "claims.validated.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert validated
