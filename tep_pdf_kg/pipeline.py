from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .chunking import build_chunks
from .extraction import extract_claims
from .neo4j_import import import_claims
from .parsers import run_parser
from .schema import DocumentManifest, NormalizedDocument, ParserRunResult, ensure_parent
from .validation import validate_claims


def _write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


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
    by_name = {result.parser_name: result for result in results}
    preferred = manifest.selected_parser or manifest.preferred_parser
    if preferred in by_name and by_name[preferred].document is not None:
        selected = by_name[preferred]
    else:
        selected = next(result for result in results if result.document is not None)
    if selected.document is not None:
        selected.document.selected_as_canonical = True
    return selected


def _load_reviewed_document(path: str, fallback: NormalizedDocument) -> NormalizedDocument:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return NormalizedDocument(
        doc_id=payload["doc_id"],
        source_path=payload["source_path"],
        parser_used=payload["parser_used"],
        parser_status=payload["parser_status"],
        selected_as_canonical=True,
        title=payload["title"],
        document_md=payload["document_md"],
        sections=[] if not payload.get("sections") else fallback.sections,
        pages=payload.get("pages", fallback.pages),
        metadata=payload.get("metadata", fallback.metadata),
    )


def run_document_pipeline(
    manifest: DocumentManifest,
    extractor: Callable[[dict[str, Any]], Any] | None = None,
    neo4j_driver=None,
) -> dict[str, Any]:
    output_dir = Path(manifest.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    parser_results = [run_parser(manifest.pdf_path, manifest, parser_name) for parser_name in manifest.parser_candidates]
    for result in parser_results:
        parser_dir = output_dir / result.parser_name
        parser_dir.mkdir(parents=True, exist_ok=True)
        _write_json(parser_dir / "parser_report.json", result.to_dict())
        document_payload = result.document.to_dict() if result.document is not None else {}
        _write_json(parser_dir / "document.json", document_payload)
        Path(parser_dir / "document.md").write_text(
            result.document.document_md if result.document is not None else "",
            encoding="utf-8",
        )

    selected = _select_canonical_result(parser_results, manifest)
    if selected.document is None:
        raise RuntimeError(f"No parser produced a document for {manifest.doc_id}")

    document = selected.document
    if manifest.reviewed_document_path:
        document = _load_reviewed_document(manifest.reviewed_document_path, document)

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

    raw_claims = []
    for chunk in chunks:
        raw_claims.extend(extract_claims(chunk, extractor=extractor, document_metadata=document.metadata))
    _write_jsonl(output_dir / "claims.raw.jsonl", [claim.to_dict() for claim in raw_claims])

    validated_claims, rejected_claims = validate_claims(raw_claims)
    _write_jsonl(output_dir / "claims.validated.jsonl", [claim.to_dict() for claim in validated_claims])
    _write_json(output_dir / "claims.rejected.json", rejected_claims)

    if neo4j_driver is not None:
        import_claims(neo4j_driver, document, chunks, validated_claims)

    summary = {
        "doc_id": manifest.doc_id,
        "selected_parser": document.parser_used,
        "parser_candidates": manifest.parser_candidates,
        "chunk_count": len(chunks),
        "raw_claim_count": len(raw_claims),
        "validated_claim_count": len(validated_claims),
        "rejected_claim_count": len(rejected_claims),
        "output_dir": str(output_dir),
    }
    _write_json(output_dir / "pipeline_summary.json", summary)
    return summary
