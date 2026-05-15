from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

from tep_pdf_kg.chunking import build_chunks
from tep_pdf_kg.extraction import DEFAULT_LLM_EXTRACTION_CONFIDENCE, build_slim_document_metadata, extract_claims
from tep_pdf_kg.gemini_extractor import build_gemini_extractor
from tep_pdf_kg.neo4j_import import claim_queries, chunk_document_queries, schema_queries
from tep_pdf_kg.pipeline import run_document_pipeline
from tep_pdf_kg.schema import ClaimRecord, DocumentManifest, NormalizedDocument, utc_now_iso
from tep_pdf_kg.validation import validate_claims


def _sample_parser_json() -> dict:
    return {
        "elements": [
            {"id": "h1", "type": "heading", "text": "Fault 4", "page_number": 12, "heading_level": 2},
            {
                "id": "p1",
                "type": "paragraph",
                "text": (
                    "Fault 4 causes high reactor temperature. "
                    "High reactor temperature observed by xmeas_9. "
                    "Fault 4 affects Reactor."
                ),
                "page_number": 12,
                "bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4},
            },
            {
                "id": "p2",
                "type": "paragraph",
                "text": (
                    "Fault 4 suggests increase cooling water flow. "
                    "Increase cooling water flow on cooling water valve. "
                    "Control action increase cooling water flow subject to separator pressure limit. "
                    "Control action increase cooling water flow risk off-spec product."
                ),
                "page_number": 13,
            },
        ]
    }


def _sample_document() -> NormalizedDocument:
    return NormalizedDocument(
        doc_id="DOWNS.pdf",
        source_path="TEP_docs/DOWNS.pdf",
        parser_used="opendataloader-pdf",
        parser_status="ok",
        selected_as_canonical=True,
        title="DOWNS",
        document_md=(
            "## Fault 4\n\n"
            "Fault 4 causes high reactor temperature. "
            "High reactor temperature observed by xmeas_9. "
            "Fault 4 affects Reactor.\n\n"
            "Fault 4 suggests increase cooling water flow. "
            "Increase cooling water flow on cooling water valve. "
            "Control action increase cooling water flow subject to separator pressure limit. "
            "Control action increase cooling water flow risk off-spec product.\n"
        ),
        sections=[],
        pages=[{"page_number": 12, "text": "Fault 4...", "block_count": 2}],
        metadata={"parser_json": _sample_parser_json(), "provenance_quality": "native"},
    )


def test_chunk_builder_reads_markdown_and_preserves_traceability_fields():
    chunks = build_chunks(_sample_document(), min_chars=10, max_chars=220)

    assert len(chunks) == 2
    assert all(chunk.section_title == "Fault 4" for chunk in chunks)
    assert chunks[0].heading_path == ["Fault 4"]
    assert chunks[0].page_start == 12
    assert chunks[0].page_end == 13
    assert chunks[0].element_refs == ["p1", "p2"]
    assert chunks[0].metadata["provenance_quality"] == "native"
    assert chunks[0].prev_chunk_id is None
    assert chunks[0].next_chunk_id == chunks[1].chunk_id
    assert chunks[1].prev_chunk_id == chunks[0].chunk_id


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


def test_slim_document_metadata_excludes_full_parser_json():
    chunk = build_chunks(_sample_document(), min_chars=10, max_chars=1000)[0]
    metadata = {
        "doc_id": "DOWNS.pdf",
        "title": "DOWNS",
        "parser_used": "opendataloader-pdf",
        "canonical_source": "parser_markdown",
        "provenance_quality": "native",
        "parser_json": _sample_parser_json(),
        "document_json_path": "x.json",
    }

    slim = build_slim_document_metadata(metadata, chunk)

    assert "parser_json" not in slim
    assert slim["doc_id"] == "DOWNS.pdf"
    assert slim["chunk_context"]["chunk_id"] == chunk.chunk_id
    assert slim["chunk_context"]["element_ref_count"] == len(chunk.element_refs)


def test_schema_and_chunk_document_queries_cover_v1_entities():
    document = _sample_document()
    chunks = build_chunks(document, min_chars=10, max_chars=1000)

    schema = schema_queries()
    query_pairs = chunk_document_queries(document, chunks)

    assert any("fault_idv_number" in query for query in schema)
    assert any("capability_name" in query for query in schema)
    assert any("Document" in query for query in schema)
    assert any("MERGE (d:Document" in query for query, _ in query_pairs)
    assert any("MERGE (c:Chunk" in query for query, _ in query_pairs)


def test_extract_claims_llm_fallback_confidence_defaults_to_validation_aligned_value():
    chunk = build_chunks(_sample_document(), min_chars=10, max_chars=1000)[0]

    claims = extract_claims(
        chunk,
        extractor=lambda payload: [
            {
                "subject": "Fault 4",
                "subject_label": "Fault",
                "predicate": "CAUSES",
                "object": "High reactor temperature",
                "object_label": "Symptom",
                "claim_type": "diagnosis",
                "evidence_text": "Fault 4 causes high reactor temperature.",
            }
        ],
    )

    assert len(claims) == 1
    assert claims[0].extraction_confidence == DEFAULT_LLM_EXTRACTION_CONFIDENCE


def test_validate_claims_rejects_relation_role_mismatch():
    claim = ClaimRecord(
        claim_id="c1",
        subject="Cooling water valve",
        subject_label="Actuator",
        predicate="OBSERVED_BY",
        object="Reactor",
        object_label="ProcessUnit",
        claim_type="symptom_observation",
        normalized_subject="cooling water valve",
        normalized_object="reactor",
        source_chunk_id="chunk-1",
        source_doc="DOWNS.pdf",
        page_start=1,
        page_end=1,
        evidence_text="Cooling water valve observed by reactor.",
        extractor_version="tep-pdf-kg-v1",
        extraction_confidence=0.9,
        review_status="pending",
        extraction_timestamp=utc_now_iso(),
        parser_used="opendataloader-pdf",
    )

    validated, rejected = validate_claims([claim])

    assert validated == []
    assert len(rejected) == 1
    assert any("relation-role mismatch" in error for error in rejected[0]["errors"])


def test_validate_claims_accepts_capability_claim_and_import_query():
    claim = ClaimRecord(
        claim_id="c2",
        subject="Tennessee Eastman process",
        subject_label="ProcessUnit",
        predicate="HAS_CAPABILITY",
        object="12 valves available for manipulation",
        object_label="Capability",
        claim_type="capability",
        normalized_subject="tennessee eastman process",
        normalized_object="12 valves available for manipulation",
        source_chunk_id="chunk-2",
        source_doc="DOWNS.pdf",
        page_start=1,
        page_end=1,
        evidence_text="The process has 12 valves available for manipulation.",
        extractor_version="tep-pdf-kg-v1",
        extraction_confidence=0.7,
        review_status="pending",
        extraction_timestamp=utc_now_iso(),
        parser_used="opendataloader-pdf",
    )

    validated, rejected = validate_claims([claim])
    queries = claim_queries(validated)

    assert rejected == []
    assert len(validated) == 1
    assert len(queries) == 1
    assert "HAS_CAPABILITY" in queries[0][0]


def test_validate_claims_still_rejects_low_confidence():
    claim = ClaimRecord(
        claim_id="c3",
        subject="Fault 4",
        subject_label="Fault",
        predicate="CAUSES",
        object="High reactor temperature",
        object_label="Symptom",
        claim_type="diagnosis",
        normalized_subject="fault 4",
        normalized_object="high reactor temperature",
        source_chunk_id="chunk-3",
        source_doc="DOWNS.pdf",
        page_start=1,
        page_end=1,
        evidence_text="Fault 4 causes high reactor temperature.",
        extractor_version="tep-pdf-kg-v1",
        extraction_confidence=0.4,
        review_status="pending",
        extraction_timestamp=utc_now_iso(),
        parser_used="opendataloader-pdf",
    )

    validated, rejected = validate_claims([claim])

    assert validated == []
    assert any("confidence below threshold" in error for error in rejected[0]["errors"])


def test_pipeline_writes_all_stage_artifacts_and_prefers_reviewed_markdown(tmp_path: Path, monkeypatch):
    document = _sample_document()

    def fake_run_parser(pdf_path, manifest, parser_name, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
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
            metadata={
                "parser_json": _sample_parser_json(),
                "document_json_path": str(Path(output_dir) / "document.json"),
                "document_markdown_path": str(Path(output_dir) / "document.md"),
            },
        )
        (Path(output_dir) / "document.md").write_text(clone.document_md, encoding="utf-8")
        (Path(output_dir) / "document.json").write_text(json.dumps(_sample_parser_json()), encoding="utf-8")
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
    reviewed_md = tmp_path / "reviewed.md"
    reviewed_md.write_text(
        "## Fault 4\n\nFault 4 causes high reactor temperature. Fault 4 affects Reactor.\n",
        encoding="utf-8",
    )
    manifest = DocumentManifest(
        doc_id="DOWNS.pdf",
        pdf_path=str(tmp_path / "DOWNS.pdf"),
        output_dir=str(tmp_path / "out"),
        reviewed_markdown_path=str(reviewed_md),
    )
    Path(manifest.pdf_path).write_bytes(b"%PDF-1.4\n")

    summary = run_document_pipeline(manifest, start_chunk=0, max_chunks=1, max_workers=1)

    out_dir = Path(summary["output_dir"])
    assert summary["selected_parser"] == "opendataloader-pdf"
    assert summary["canonical_source"] == "reviewed_markdown"
    assert summary["processed_chunk_count"] == 1
    assert summary["chunk_status_counts"]["succeeded"] == 1
    assert (out_dir / "chunks.jsonl").exists()
    assert (out_dir / "extract_status.jsonl").exists()
    assert (out_dir / "claims.raw.jsonl").exists()
    assert (out_dir / "claims.validated.jsonl").exists()
    assert (out_dir / "claims.rejected.json").exists()
    assert (out_dir / "pipeline_summary.json").exists()
    assert any((out_dir / "chunk_claims").glob("*.json"))
    assert (out_dir / "canonical_document.md").read_text(encoding="utf-8") == reviewed_md.read_text(encoding="utf-8")
    assert (out_dir / "opendataloader-pdf" / "document.md").exists()
    assert (out_dir / "docling" / "parser_report.json").exists()

    validated = [
        json.loads(line)
        for line in (out_dir / "claims.validated.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert validated


def test_pipeline_resume_skips_succeeded_and_retries_failed_chunks(tmp_path: Path, monkeypatch):
    document = _sample_document()
    attempts: dict[str, int] = {}

    def fake_run_parser(pdf_path, manifest, parser_name, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
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
            metadata={
                "parser_json": _sample_parser_json(),
                "document_json_path": str(Path(output_dir) / "document.json"),
                "document_markdown_path": str(Path(output_dir) / "document.md"),
            },
        )
        return MagicMock(
            parser_name=parser_name,
            status="ok",
            document=clone,
            to_dict=lambda: {"parser_name": parser_name, "status": "ok", "document": clone.to_dict(), "warnings": [], "error": None},
        )

    monkeypatch.setattr("tep_pdf_kg.pipeline.run_parser", fake_run_parser)
    monkeypatch.setattr("tep_pdf_kg.pipeline.build_chunks", lambda doc: build_chunks(doc, min_chars=10, max_chars=220))
    original_extract = extract_claims

    def fake_extract(chunk, extractor=None, document_metadata=None):
        attempts[chunk.chunk_id] = attempts.get(chunk.chunk_id, 0) + 1
        if chunk.chunk_index == 1 and attempts[chunk.chunk_id] == 1:
            raise RuntimeError("chunk failed once")
        return original_extract(chunk, extractor=extractor, document_metadata=document_metadata)

    monkeypatch.setattr("tep_pdf_kg.pipeline.extract_claims", fake_extract)
    manifest = DocumentManifest(
        doc_id="DOWNS.pdf",
        pdf_path=str(tmp_path / "DOWNS.pdf"),
        output_dir=str(tmp_path / "out"),
    )
    Path(manifest.pdf_path).write_bytes(b"%PDF-1.4\n")

    first = run_document_pipeline(manifest, resume=False, max_workers=1)
    second = run_document_pipeline(manifest, resume=True, max_workers=1)

    out_dir = Path(first["output_dir"])
    raw_claims = [
        json.loads(line)
        for line in (out_dir / "claims.raw.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert first["failed_chunk_count"] == 1
    assert first["succeeded_chunk_count"] == 1
    assert second["processed_chunk_count"] == 1
    assert second["skipped_chunk_count"] == 1
    assert second["failed_chunk_count"] == 0
    assert len(raw_claims) >= 2
    assert second["raw_claim_count"] == len(raw_claims)
    assert sorted(attempts.values()) == [1, 2]


def test_pipeline_parallel_merge_preserves_chunk_order(tmp_path: Path, monkeypatch):
    document = _sample_document()
    original_extract_claims = extract_claims

    def fake_run_parser(pdf_path, manifest, parser_name, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
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
            metadata={
                "parser_json": _sample_parser_json(),
                "document_json_path": str(Path(output_dir) / "document.json"),
                "document_markdown_path": str(Path(output_dir) / "document.md"),
            },
        )
        return MagicMock(
            parser_name=parser_name,
            status="ok",
            document=clone,
            to_dict=lambda: {"parser_name": parser_name, "status": "ok", "document": clone.to_dict(), "warnings": [], "error": None},
        )

    def fake_llm_extractor(payload):
        chunk = payload["chunk"]
        chunk_index = int(chunk["chunk_index"])
        if chunk_index == 0:
            time.sleep(0.05)
        return [
            {
                "subject": f"Fault {chunk_index}",
                "subject_label": "Fault",
                "predicate": "CAUSES",
                "object": f"Symptom {chunk_index}",
                "object_label": "Symptom",
                "claim_type": "diagnosis",
                "evidence_text": str(chunk["text_md"])[:80],
                "extraction_confidence": 0.9,
                "review_status": "pending",
            }
        ]

    def fake_extract(chunk, extractor=None, document_metadata=None):
        return original_extract_claims(chunk, extractor=fake_llm_extractor, document_metadata=document_metadata)

    monkeypatch.setattr("tep_pdf_kg.pipeline.run_parser", fake_run_parser)
    monkeypatch.setattr("tep_pdf_kg.pipeline.build_chunks", lambda doc: build_chunks(doc, min_chars=10, max_chars=220))
    monkeypatch.setattr("tep_pdf_kg.pipeline.extract_claims", fake_extract)
    manifest = DocumentManifest(
        doc_id="DOWNS.pdf",
        pdf_path=str(tmp_path / "DOWNS.pdf"),
        output_dir=str(tmp_path / "out"),
    )
    Path(manifest.pdf_path).write_bytes(b"%PDF-1.4\n")

    summary = run_document_pipeline(manifest, max_workers=2)

    out_dir = Path(summary["output_dir"])
    raw_claims = [
        json.loads(line)
        for line in (out_dir / "claims.raw.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert summary["succeeded_chunk_count"] == 2
    assert [row["source_chunk_id"] for row in raw_claims] == [
        "DOWNS.pdf__chunk_0000_fault-4",
        "DOWNS.pdf__chunk_0001_fault-4",
    ]


def test_pipeline_prefers_fusion_repaired_markdown_when_present(tmp_path: Path, monkeypatch):
    document = _sample_document()

    def fake_run_parser(pdf_path, manifest, parser_name, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
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
            metadata={
                "parser_json": _sample_parser_json(),
                "document_json_path": str(Path(output_dir) / "document.json"),
                "document_markdown_path": str(Path(output_dir) / "document.md"),
            },
        )
        (Path(output_dir) / "document.md").write_text(clone.document_md, encoding="utf-8")
        (Path(output_dir) / "document.json").write_text(json.dumps(_sample_parser_json()), encoding="utf-8")
        return MagicMock(
            parser_name=parser_name,
            status="ok",
            document=clone,
            to_dict=lambda: {"parser_name": parser_name, "status": "ok", "document": clone.to_dict(), "warnings": [], "error": None},
        )

    monkeypatch.setattr("tep_pdf_kg.pipeline.run_parser", fake_run_parser)
    manifest = DocumentManifest(
        doc_id="DOWNS.pdf",
        pdf_path=str(tmp_path / "DOWNS.pdf"),
        output_dir=str(tmp_path / "out"),
    )
    Path(manifest.pdf_path).write_bytes(b"%PDF-1.4\n")
    fusion_dir = Path(manifest.output_dir) / "fusion"
    fusion_dir.mkdir(parents=True, exist_ok=True)
    repaired_md = "## Fault 4\n\nRepaired markdown should win.\n"
    (fusion_dir / "canonical.repaired.md").write_text(repaired_md, encoding="utf-8")

    summary = run_document_pipeline(manifest, max_workers=1)

    out_dir = Path(summary["output_dir"])
    assert summary["canonical_source"] == "fusion_repaired_markdown"
    assert (out_dir / "canonical_document.md").read_text(encoding="utf-8") == repaired_md


def test_pipeline_resume_rebuilds_chunks_when_repaired_markdown_appears(tmp_path: Path, monkeypatch):
    document = _sample_document()

    def fake_run_parser(pdf_path, manifest, parser_name, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
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
            metadata={
                "parser_json": _sample_parser_json(),
                "document_json_path": str(Path(output_dir) / "document.json"),
                "document_markdown_path": str(Path(output_dir) / "document.md"),
            },
        )
        (Path(output_dir) / "document.md").write_text(clone.document_md, encoding="utf-8")
        (Path(output_dir) / "document.json").write_text(json.dumps(_sample_parser_json()), encoding="utf-8")
        return MagicMock(
            parser_name=parser_name,
            status="ok",
            document=clone,
            to_dict=lambda: {"parser_name": parser_name, "status": "ok", "document": clone.to_dict(), "warnings": [], "error": None},
        )

    monkeypatch.setattr("tep_pdf_kg.pipeline.run_parser", fake_run_parser)
    manifest = DocumentManifest(
        doc_id="DOWNS.pdf",
        pdf_path=str(tmp_path / "DOWNS.pdf"),
        output_dir=str(tmp_path / "out"),
    )
    Path(manifest.pdf_path).write_bytes(b"%PDF-1.4\n")

    first = run_document_pipeline(manifest, max_workers=1)
    fusion_dir = Path(manifest.output_dir) / "fusion"
    fusion_dir.mkdir(parents=True, exist_ok=True)
    (fusion_dir / "canonical.repaired.md").write_text("## Fault 4\n\nFresh repaired markdown.\n", encoding="utf-8")

    second = run_document_pipeline(manifest, resume=True, max_workers=1)

    out_dir = Path(first["output_dir"])
    assert first["canonical_source"] == "parser_markdown"
    assert second["canonical_source"] == "fusion_repaired_markdown"
    assert second["canonical_changed"] is True
    assert second["resume_used"] is False
    assert (out_dir / "canonical_document.md").read_text(encoding="utf-8") == "## Fault 4\n\nFresh repaired markdown.\n"


def test_gemini_extractor_uses_structured_output(monkeypatch):
    import importlib

    seen_prompt = {}

    class FakeClaim:
        def __init__(self, payload):
            self._payload = payload

        def model_dump(self):
            return dict(self._payload)

    class FakeBatch:
        def __init__(self):
            self.claims = [
                FakeClaim(
                    {
                        "subject": "Fault 4",
                        "subject_label": "Fault",
                        "predicate": "CAUSES",
                        "object": "High reactor temperature",
                        "object_label": "Symptom",
                        "claim_type": "diagnosis",
                        "evidence_text": "Fault 4 causes high reactor temperature.",
                        "extraction_confidence": 0.88,
                        "review_status": "pending",
                    }
                )
            ]

    class FakeStructured:
        def invoke(self, prompt):
            seen_prompt["value"] = prompt
            return FakeBatch()

    class FakeLLM:
        def bind(self, **kwargs):
            return self

        def with_structured_output(self, schema):
            return FakeStructured()

    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-for-unit-test")
    common = importlib.import_module("common")
    monkeypatch.setattr(common, "llm", FakeLLM())
    monkeypatch.setattr(common, "invoke_with_retry", lambda fn, prompt: fn(prompt))

    extractor = build_gemini_extractor()
    claims = extractor(
        {
            "chunk": {
                "chunk_id": "c1",
                "text_md": "Fault 4 causes high reactor temperature.",
                "page_start": 1,
                "page_end": 1,
            },
            "document_metadata": {},
            "allowed_relations": ["CAUSES"],
        }
    )

    assert claims
    assert claims[0]["predicate"] == "CAUSES"
    assert claims[0]["subject_label"] == "Fault"
    assert isinstance(seen_prompt["value"], list)
    assert len(seen_prompt["value"]) == 2
    assert "parser_json" not in str(seen_prompt["value"][1].content)
    assert "HAS_CAPABILITY only when the subject is a ProcessUnit and the object is a Capability." in str(seen_prompt["value"][0].content)
    assert "Do not force capability or inventory text into ACTS_ON or OBSERVED_BY." in str(seen_prompt["value"][0].content)


def test_gemini_extractor_drops_invalid_claims_after_structured_parse_failure(monkeypatch):
    import importlib
    from langchain_core.exceptions import OutputParserException

    class FakeStructured:
        def invoke(self, prompt):
            raise OutputParserException("structured parse failed")

    class FakeInvokeResult:
        def __init__(self, content):
            self.content = content

    class FakeLLM:
        def bind(self, **kwargs):
            return self

        def with_structured_output(self, schema):
            return FakeStructured()

        def invoke(self, prompt):
            return FakeInvokeResult(
                json.dumps(
                    {
                        "claims": [
                            {
                                "subject": "Fault 4",
                                "subject_label": "Fault",
                                "predicate": "CAUSES",
                                "object": "High reactor temperature",
                                "object_label": "Symptom",
                                "claim_type": "diagnosis",
                                "evidence_text": "Fault 4 causes high reactor temperature.",
                                "extraction_confidence": 0.88,
                                "review_status": "pending",
                            },
                            {
                                "subject": "Broken claim",
                                "subject_label": "Fault",
                            },
                        ]
                    }
                )
            )

    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-for-unit-test")
    common = importlib.import_module("common")
    monkeypatch.setattr(common, "llm", FakeLLM())
    monkeypatch.setattr(common, "invoke_with_retry", lambda fn, prompt: fn(prompt))

    extractor = build_gemini_extractor()
    claims = extractor(
        {
            "chunk": {
                "chunk_id": "c1",
                "text_md": "Fault 4 causes high reactor temperature.",
                "page_start": 1,
                "page_end": 1,
            },
            "document_metadata": {},
            "allowed_relations": ["CAUSES"],
        }
    )

    assert len(claims) == 1
    assert claims[0]["predicate"] == "CAUSES"


def test_gemini_extractor_tolerates_fenced_json_fallback(monkeypatch):
    import importlib
    from langchain_core.exceptions import OutputParserException

    class FakeStructured:
        def invoke(self, prompt):
            raise OutputParserException("structured parse failed")

    class FakeInvokeResult:
        def __init__(self, content):
            self.content = content

    class FakeLLM:
        def bind(self, **kwargs):
            return self

        def with_structured_output(self, schema):
            return FakeStructured()

        def invoke(self, prompt):
            return FakeInvokeResult(
                """```json
                {"claims":[{"subject":"Fault 4","subject_label":"Fault","predicate":"CAUSES","object":"High reactor temperature","object_label":"Symptom","claim_type":"diagnosis","evidence_text":"Fault 4 causes high reactor temperature.","extraction_confidence":0.88,"review_status":"pending"}]}
                ```"""
            )

    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-for-unit-test")
    common = importlib.import_module("common")
    monkeypatch.setattr(common, "llm", FakeLLM())
    monkeypatch.setattr(common, "invoke_with_retry", lambda fn, prompt: fn(prompt))

    extractor = build_gemini_extractor()
    claims = extractor(
        {
            "chunk": {
                "chunk_id": "c1",
                "text_md": "Fault 4 causes high reactor temperature.",
                "page_start": 1,
                "page_end": 1,
            },
            "document_metadata": {},
            "allowed_relations": ["CAUSES"],
        }
    )

    assert len(claims) == 1
    assert claims[0]["predicate"] == "CAUSES"


def test_gemini_extractor_defaults_missing_confidence_after_structured_parse_failure(monkeypatch):
    import importlib
    from langchain_core.exceptions import OutputParserException

    class FakeStructured:
        def invoke(self, prompt):
            raise OutputParserException("structured parse failed")

    class FakeInvokeResult:
        def __init__(self, content):
            self.content = content

    class FakeLLM:
        def bind(self, **kwargs):
            return self

        def with_structured_output(self, schema):
            return FakeStructured()

        def invoke(self, prompt):
            return FakeInvokeResult(
                json.dumps(
                    {
                        "claims": [
                            {
                                "subject": "Fault 4",
                                "subject_label": "Fault",
                                "predicate": "CAUSES",
                                "object": "High reactor temperature",
                                "object_label": "Symptom",
                                "claim_type": "diagnosis",
                                "evidence_text": "Fault 4 causes high reactor temperature.",
                                "review_status": "pending",
                            }
                        ]
                    }
                )
            )

    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-for-unit-test")
    common = importlib.import_module("common")
    monkeypatch.setattr(common, "llm", FakeLLM())
    monkeypatch.setattr(common, "invoke_with_retry", lambda fn, prompt: fn(prompt))

    extractor = build_gemini_extractor()
    claims = extractor(
        {
            "chunk": {
                "chunk_id": "c1",
                "text_md": "Fault 4 causes high reactor temperature.",
                "page_start": 1,
                "page_end": 1,
            },
            "document_metadata": {},
            "allowed_relations": ["CAUSES"],
        }
    )

    assert len(claims) == 1
    assert claims[0]["extraction_confidence"] == DEFAULT_LLM_EXTRACTION_CONFIDENCE


def test_gemini_extractor_model_override_builds_new_client(monkeypatch):
    import importlib
    import langchain_google_genai

    seen = {}

    class FakeClaim:
        def __init__(self, payload):
            self._payload = payload

        def model_dump(self):
            return dict(self._payload)

    class FakeBatch:
        def __init__(self):
            self.claims = [
                FakeClaim(
                    {
                        "subject": "Fault 4",
                        "subject_label": "Fault",
                        "predicate": "CAUSES",
                        "object": "High reactor temperature",
                        "object_label": "Symptom",
                        "claim_type": "diagnosis",
                        "evidence_text": "Fault 4 causes high reactor temperature.",
                        "extraction_confidence": 0.88,
                        "review_status": "pending",
                    }
                )
            ]

    class FakeInvokeResult:
        def __init__(self, content):
            self.content = content

    class FakeStructured:
        def invoke(self, prompt):
            return FakeBatch()

    class FakeOverrideLLM:
        def __init__(self, **kwargs):
            seen["kwargs"] = kwargs

        def with_structured_output(self, schema):
            return FakeStructured()

        def invoke(self, prompt):
            return FakeInvokeResult("")

    class FakeBaseLLM:
        temperature = 0.25
        max_output_tokens = 8192

    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-for-unit-test")
    common = importlib.import_module("common")
    monkeypatch.setattr(common, "llm", FakeBaseLLM())
    monkeypatch.setattr(common, "invoke_with_retry", lambda fn, prompt: fn(prompt))
    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", FakeOverrideLLM)

    extractor = build_gemini_extractor(model="gemini-2.0-flash-lite")
    claims = extractor(
        {
            "chunk": {"chunk_id": "c1", "text_md": "Fault 4 causes high reactor temperature.", "page_start": 1, "page_end": 1},
            "document_metadata": {},
            "allowed_relations": ["CAUSES"],
        }
    )

    assert seen["kwargs"]["model"] == "gemini-2.0-flash-lite"
    assert claims[0]["predicate"] == "CAUSES"


def test_pipeline_writes_capability_claims_and_rejects_relation_role_mismatch(tmp_path: Path, monkeypatch):
    document = _sample_document()

    def fake_run_parser(pdf_path, manifest, parser_name, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
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
            metadata={
                "parser_json": _sample_parser_json(),
                "document_json_path": str(Path(output_dir) / "document.json"),
                "document_markdown_path": str(Path(output_dir) / "document.md"),
            },
        )
        return MagicMock(
            parser_name=parser_name,
            status="ok",
            document=clone,
            to_dict=lambda: {"parser_name": parser_name, "status": "ok", "document": clone.to_dict(), "warnings": [], "error": None},
        )

    def fake_extract(chunk, extractor=None, document_metadata=None):
        return extract_claims(
            chunk,
            extractor=lambda payload: [
                {
                    "subject": "Tennessee Eastman process",
                    "subject_label": "ProcessUnit",
                    "predicate": "HAS_CAPABILITY",
                    "object": "41 measurements available for monitoring or control",
                    "object_label": "Capability",
                    "claim_type": "capability",
                    "evidence_text": "41 measurements available for monitoring or control.",
                    "extraction_confidence": 0.74,
                    "review_status": "pending",
                },
                {
                    "subject": "xmeas_9",
                    "subject_label": "Sensor",
                    "predicate": "ACTS_ON",
                    "object": "Reactor",
                    "object_label": "ProcessUnit",
                    "claim_type": "action_target",
                    "evidence_text": "Bad relation-role mapping.",
                    "extraction_confidence": 0.91,
                    "review_status": "pending",
                },
            ],
            document_metadata=document_metadata,
        )

    monkeypatch.setattr("tep_pdf_kg.pipeline.run_parser", fake_run_parser)
    monkeypatch.setattr("tep_pdf_kg.pipeline.build_chunks", lambda doc: build_chunks(doc, min_chars=10, max_chars=1000)[:1])
    monkeypatch.setattr("tep_pdf_kg.pipeline.extract_claims", fake_extract)
    manifest = DocumentManifest(
        doc_id="DOWNS.pdf",
        pdf_path=str(tmp_path / "DOWNS.pdf"),
        output_dir=str(tmp_path / "out"),
    )
    Path(manifest.pdf_path).write_bytes(b"%PDF-1.4\n")

    summary = run_document_pipeline(manifest, max_workers=1)

    out_dir = Path(summary["output_dir"])
    validated = [
        json.loads(line)
        for line in (out_dir / "claims.validated.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rejected = json.loads((out_dir / "claims.rejected.json").read_text(encoding="utf-8"))

    assert summary["raw_claim_count"] == 2
    assert summary["validated_claim_count"] == 1
    assert summary["rejected_claim_count"] == 1
    assert validated[0]["predicate"] == "HAS_CAPABILITY"
    assert validated[0]["object_label"] == "Capability"
    assert rejected[0]["claim"]["predicate"] == "ACTS_ON"
    assert any("relation-role mismatch" in error for error in rejected[0]["errors"])
