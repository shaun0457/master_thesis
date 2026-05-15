from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .chunking import build_chunks
from .extraction import extract_claims
from .neo4j_import import import_claims
from .parsers import run_parser
from .schema import ClaimRecord, DocumentManifest, NormalizedDocument, ParserRunResult, ensure_parent
from .validation import validate_claims


def _write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_pilot_manifest(base_dir: str | Path = "TEP_docs", output_root: str | Path = "artifacts/tep_pdf_kg") -> list[DocumentManifest]:
    base_dir = Path(base_dir)
    output_root = Path(output_root)
    return [
        DocumentManifest(
            doc_id="DOWNS.pdf",
            pdf_path=str(base_dir / "DOWNS.pdf"),
            output_dir=str(output_root / "DOWNS"),
        ),
        DocumentManifest(
            doc_id="Decentralized_control_of_the_Tennessee_E.pdf",
            pdf_path=str(base_dir / "Decentralized_control_of_the_Tennessee_E.pdf"),
            output_dir=str(output_root / "Decentralized_control_of_the_Tennessee_E"),
        ),
    ]


def _select_canonical_result(results: list[ParserRunResult], manifest: DocumentManifest) -> ParserRunResult:
    by_name = {result.parser_name: result for result in results if result.status == "ok" and result.document is not None}
    preferred = manifest.selected_parser or manifest.preferred_parser
    if preferred in by_name:
        selected = by_name[preferred]
    elif by_name:
        selected = next(iter(by_name.values()))
    else:
        raise RuntimeError(f"No parser produced a document for {manifest.doc_id}")
    selected.document.selected_as_canonical = True
    return selected


def _load_reviewed_markdown(path: str, fallback: NormalizedDocument) -> NormalizedDocument:
    reviewed_md = Path(path).read_text(encoding="utf-8")
    metadata = dict(fallback.metadata)
    metadata["reviewed_markdown_path"] = path
    metadata["canonical_source"] = "reviewed_markdown"
    return NormalizedDocument(
        doc_id=fallback.doc_id,
        source_path=fallback.source_path,
        parser_used=fallback.parser_used,
        parser_status=fallback.parser_status,
        selected_as_canonical=True,
        title=fallback.title,
        document_md=reviewed_md,
        sections=fallback.sections,
        pages=fallback.pages,
        metadata=metadata,
    )


def _load_reviewed_document(path: str, fallback: NormalizedDocument) -> NormalizedDocument:
    path_obj = Path(path)
    if path_obj.suffix.lower() == ".md":
        return _load_reviewed_markdown(path, fallback)

    payload = json.loads(path_obj.read_text(encoding="utf-8"))
    metadata = dict(fallback.metadata)
    metadata.update(payload.get("metadata", {}))
    metadata["canonical_source"] = "reviewed_document"
    return NormalizedDocument(
        doc_id=payload["doc_id"],
        source_path=payload["source_path"],
        parser_used=payload["parser_used"],
        parser_status=payload["parser_status"],
        selected_as_canonical=True,
        title=payload["title"],
        document_md=payload["document_md"],
        sections=fallback.sections,
        pages=payload.get("pages", fallback.pages),
        metadata=metadata,
    )


def _claim_from_row(row: dict[str, Any]) -> ClaimRecord:
    return ClaimRecord(**row)


def run_document_pipeline(
    manifest: DocumentManifest,
    extractor: Callable[[dict[str, Any]], Any] | None = None,
    neo4j_driver=None,
    start_chunk: int = 0,
    max_chunks: int | None = None,
    append_claims: bool = False,
) -> dict[str, Any]:
    output_dir = Path(manifest.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    parser_results = []
    for parser_name in manifest.parser_candidates:
        parser_dir = output_dir / parser_name
        result = run_parser(manifest.pdf_path, manifest, parser_name, parser_dir)
        parser_results.append(result)
        _write_json(parser_dir / "parser_report.json", result.to_dict())
        if result.status != "ok" or result.document is None:
            (parser_dir / "document.md").write_text("", encoding="utf-8")
            _write_json(parser_dir / "document.json", {"error": result.error, "parser_name": parser_name})

    selected = _select_canonical_result(parser_results, manifest)
    document = selected.document

    reviewed_markdown_path = manifest.reviewed_markdown_path
    if reviewed_markdown_path:
        document = _load_reviewed_markdown(reviewed_markdown_path, document)
    elif manifest.reviewed_document_path:
        document = _load_reviewed_document(manifest.reviewed_document_path, document)

    canonical_source = document.metadata.get("canonical_source", "parser_markdown")
    (output_dir / "canonical_document.md").write_text(document.document_md, encoding="utf-8")
    _write_json(
        output_dir / "canonical_document.json",
        {
            "doc_id": document.doc_id,
            "parser_used": document.parser_used,
            "canonical_source": canonical_source,
            "document_markdown_path": str(output_dir / "canonical_document.md"),
            "parser_json_path": document.metadata.get("document_json_path"),
            "metadata": document.metadata,
        },
    )

    chunks = build_chunks(document)
    if manifest.reviewed_chunks_path:
        reviewed_chunks = []
        for line in Path(manifest.reviewed_chunks_path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                reviewed_chunks.append(json.loads(line))
        if reviewed_chunks:
            for idx, row in enumerate(reviewed_chunks):
                if idx < len(chunks):
                    chunks[idx].text_md = row.get("text_md", chunks[idx].text_md)
                    chunks[idx].review_status = row.get("review_status", "reviewed")

    chunk_rows = [chunk.to_dict() for chunk in chunks]
    _write_jsonl(output_dir / "chunks.jsonl", chunk_rows)

    chunk_slice = chunks[start_chunk:]
    if max_chunks is not None:
        chunk_slice = chunk_slice[:max_chunks]

    raw_claim_path = output_dir / "claims.raw.jsonl"
    if not append_claims:
        raw_claim_path.write_text("", encoding="utf-8")

    raw_claim_count = 0
    for chunk in chunk_slice:
        chunk_claims = extract_claims(chunk, extractor=extractor, document_metadata=document.metadata)
        rows = [claim.to_dict() for claim in chunk_claims]
        _append_jsonl(raw_claim_path, rows)
        raw_claim_count += len(rows)

    persisted_raw_claims = [_claim_from_row(row) for row in _read_jsonl(raw_claim_path)]
    validated_claims, rejected_claims = validate_claims(persisted_raw_claims)
    _write_jsonl(output_dir / "claims.validated.jsonl", [claim.to_dict() for claim in validated_claims])
    _write_json(output_dir / "claims.rejected.json", rejected_claims)

    if neo4j_driver is not None:
        import_claims(neo4j_driver, document, chunks, validated_claims)

    summary = {
        "doc_id": manifest.doc_id,
        "selected_parser": document.parser_used,
        "parser_candidates": manifest.parser_candidates,
        "canonical_source": canonical_source,
        "chunk_count": len(chunks),
        "processed_chunk_count": len(chunk_slice),
        "start_chunk": start_chunk,
        "max_chunks": max_chunks,
        "raw_claim_count": len(persisted_raw_claims),
        "raw_claims_written_this_run": raw_claim_count,
        "validated_claim_count": len(validated_claims),
        "rejected_claim_count": len(rejected_claims),
        "output_dir": str(output_dir),
    }
    _write_json(output_dir / "pipeline_summary.json", summary)
    return summary
