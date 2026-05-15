from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .chunking import build_chunks
from .extraction import extract_claims
from .neo4j_import import import_claims
from .parsers import run_parser
from .schema import ChunkRecord, ClaimRecord, DocumentManifest, NormalizedDocument, ParserRunResult, ensure_parent
from .validation import validate_claims

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"


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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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

    payload = _read_json(path_obj)
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


def _chunk_from_row(row: dict[str, Any]) -> ChunkRecord:
    return ChunkRecord(**row)


def _document_from_cached_artifacts(manifest: DocumentManifest, output_dir: Path) -> tuple[NormalizedDocument, str]:
    metadata_payload = _read_json(output_dir / "canonical_document.json")
    document_md = (output_dir / "canonical_document.md").read_text(encoding="utf-8")
    canonical_source = str(metadata_payload.get("canonical_source", "parser_markdown"))
    parser_used = str(metadata_payload.get("parser_used", manifest.preferred_parser))
    metadata = metadata_payload.get("metadata", {})
    return (
        NormalizedDocument(
            doc_id=metadata_payload.get("doc_id", manifest.doc_id),
            source_path=manifest.pdf_path,
            parser_used=parser_used,
            parser_status="ok",
            selected_as_canonical=True,
            title=Path(manifest.pdf_path).stem.replace("_", " "),
            document_md=document_md,
            sections=[],
            pages=[],
            metadata=metadata,
        ),
        canonical_source,
    )


def _write_canonical_document_artifacts(output_dir: Path, document: NormalizedDocument, canonical_source: str) -> None:
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


def _load_cached_chunks(output_dir: Path) -> list[ChunkRecord]:
    return [_chunk_from_row(row) for row in _read_jsonl(output_dir / "chunks.jsonl")]


def _apply_reviewed_chunks(chunks: list[ChunkRecord], reviewed_chunks_path: str | None) -> list[ChunkRecord]:
    if not reviewed_chunks_path:
        return chunks
    reviewed_chunks = []
    for line in Path(reviewed_chunks_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            reviewed_chunks.append(json.loads(line))
    if reviewed_chunks:
        for idx, row in enumerate(reviewed_chunks):
            if idx < len(chunks):
                chunks[idx].text_md = row.get("text_md", chunks[idx].text_md)
                chunks[idx].review_status = row.get("review_status", "reviewed")
    return chunks


def _load_fusion_repaired_markdown(output_dir: Path, fallback: NormalizedDocument) -> NormalizedDocument | None:
    repaired_path = output_dir / "fusion" / "canonical.repaired.md"
    if not repaired_path.exists():
        return None
    metadata = dict(fallback.metadata)
    metadata["fusion_repaired_markdown_path"] = str(repaired_path)
    metadata["canonical_source"] = "fusion_repaired_markdown"
    return NormalizedDocument(
        doc_id=fallback.doc_id,
        source_path=fallback.source_path,
        parser_used=fallback.parser_used,
        parser_status=fallback.parser_status,
        selected_as_canonical=True,
        title=fallback.title,
        document_md=repaired_path.read_text(encoding="utf-8"),
        sections=fallback.sections,
        pages=fallback.pages,
        metadata=metadata,
    )


def _apply_available_canonical_override(manifest: DocumentManifest, output_dir: Path, fallback: NormalizedDocument) -> NormalizedDocument:
    repaired = _load_fusion_repaired_markdown(output_dir, fallback)
    if repaired is not None:
        return repaired
    if manifest.reviewed_markdown_path:
        return _load_reviewed_markdown(manifest.reviewed_markdown_path, fallback)
    if manifest.reviewed_document_path:
        return _load_reviewed_document(manifest.reviewed_document_path, fallback)
    return fallback


def _materialize_document_and_chunks(manifest: DocumentManifest, output_dir: Path, resume: bool) -> tuple[NormalizedDocument, list[ChunkRecord], str, bool]:
    chunk_path = output_dir / "chunks.jsonl"
    canonical_md_path = output_dir / "canonical_document.md"
    canonical_json_path = output_dir / "canonical_document.json"

    if resume and chunk_path.exists() and canonical_md_path.exists() and canonical_json_path.exists():
        cached_document, cached_source = _document_from_cached_artifacts(manifest, output_dir)
        preferred_document = _apply_available_canonical_override(manifest, output_dir, cached_document)
        preferred_source = str(preferred_document.metadata.get("canonical_source", cached_source))
        if preferred_source == cached_source and preferred_document.document_md == cached_document.document_md:
            chunks = _load_cached_chunks(output_dir)
            return preferred_document, chunks, preferred_source, False
        _write_canonical_document_artifacts(output_dir, preferred_document, preferred_source)
        chunks = build_chunks(preferred_document)
        chunks = _apply_reviewed_chunks(chunks, manifest.reviewed_chunks_path)
        _write_jsonl(output_dir / "chunks.jsonl", [chunk.to_dict() for chunk in chunks])
        return preferred_document, chunks, preferred_source, True

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

    document = _apply_available_canonical_override(manifest, output_dir, document)

    canonical_source = document.metadata.get("canonical_source", "parser_markdown")
    _write_canonical_document_artifacts(output_dir, document, canonical_source)

    chunks = build_chunks(document)
    chunks = _apply_reviewed_chunks(chunks, manifest.reviewed_chunks_path)
    _write_jsonl(output_dir / "chunks.jsonl", [chunk.to_dict() for chunk in chunks])
    return document, chunks, canonical_source, False


def _status_ledger_path(output_dir: Path) -> Path:
    return output_dir / "extract_status.jsonl"


def _chunk_claim_dir(output_dir: Path) -> Path:
    return output_dir / "chunk_claims"


def _chunk_claim_path(output_dir: Path, chunk: ChunkRecord) -> Path:
    return _chunk_claim_dir(output_dir) / f"chunk_{chunk.chunk_index:04d}.json"


def _latest_status_by_chunk(output_dir: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(_status_ledger_path(output_dir)):
        chunk_id = row.get("chunk_id")
        if chunk_id:
            latest[str(chunk_id)] = row
    return latest


def _existing_chunk_artifact(output_dir: Path, chunk: ChunkRecord) -> dict[str, Any] | None:
    path = _chunk_claim_path(output_dir, chunk)
    if not path.exists():
        return None
    return _read_json(path)


def _append_status_event(output_dir: Path, chunk: ChunkRecord, status: str, attempt_count: int, **extra: Any) -> dict[str, Any]:
    payload = {
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "status": status,
        "attempt_count": attempt_count,
        "timestamp": _claim_timestamp(),
    }
    payload.update(extra)
    _append_jsonl(_status_ledger_path(output_dir), [payload])
    return payload


def _claim_timestamp() -> str:
    from .schema import utc_now_iso

    return utc_now_iso()


def _reset_extraction_artifacts(output_dir: Path) -> None:
    chunk_dir = _chunk_claim_dir(output_dir)
    if chunk_dir.exists():
        shutil.rmtree(chunk_dir)
    for filename in ("extract_status.jsonl", "claims.raw.jsonl", "claims.validated.jsonl", "claims.rejected.json", "pipeline_summary.json"):
        path = output_dir / filename
        if path.exists():
            path.unlink()


def _chunk_execution_targets(
    chunks: list[ChunkRecord],
    output_dir: Path,
    *,
    start_chunk: int,
    max_chunks: int | None,
    resume: bool,
) -> tuple[list[ChunkRecord], int]:
    chunk_slice = chunks[start_chunk:]
    if max_chunks is not None:
        chunk_slice = chunk_slice[:max_chunks]

    if not resume:
        return chunk_slice, 0

    latest = _latest_status_by_chunk(output_dir)
    targets: list[ChunkRecord] = []
    skipped = 0
    for chunk in chunk_slice:
        row = latest.get(chunk.chunk_id)
        artifact = _existing_chunk_artifact(output_dir, chunk)
        if row and row.get("status") == STATUS_SUCCEEDED and artifact and artifact.get("status") == STATUS_SUCCEEDED:
            skipped += 1
            continue
        targets.append(chunk)
    return targets, skipped


def _extract_chunk_worker(
    chunk: ChunkRecord,
    *,
    extractor: Callable[[dict[str, Any]], Any] | None,
    document_metadata: dict[str, Any],
) -> list[ClaimRecord]:
    return extract_claims(chunk, extractor=extractor, document_metadata=document_metadata)


def _write_chunk_artifact(
    output_dir: Path,
    chunk: ChunkRecord,
    *,
    status: str,
    attempt_count: int,
    claims: list[ClaimRecord],
    error: str | None,
    extractor_name: str,
) -> dict[str, Any]:
    payload = {
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "status": status,
        "attempt_count": attempt_count,
        "extractor": extractor_name,
        "updated_at": _claim_timestamp(),
        "error": error,
        "claims": [claim.to_dict() for claim in claims],
    }
    _write_json(_chunk_claim_path(output_dir, chunk), payload)
    return payload


def _existing_attempt_count(output_dir: Path, chunk: ChunkRecord) -> int:
    artifact = _existing_chunk_artifact(output_dir, chunk)
    if not artifact:
        return 0
    try:
        return int(artifact.get("attempt_count", 0))
    except Exception:
        return 0


def _run_chunk_extraction(
    output_dir: Path,
    chunks: list[ChunkRecord],
    *,
    extractor: Callable[[dict[str, Any]], Any] | None,
    document_metadata: dict[str, Any],
    max_workers: int,
) -> dict[str, int]:
    counts = {
        STATUS_SUCCEEDED: 0,
        STATUS_FAILED: 0,
    }
    if not chunks:
        return counts

    worker_count = max(1, max_workers)
    extractor_name = "gemini" if extractor is not None else "heuristic"

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_map = {}
        for chunk in chunks:
            attempt_count = _existing_attempt_count(output_dir, chunk) + 1
            _append_status_event(output_dir, chunk, STATUS_RUNNING, attempt_count)
            future = pool.submit(
                _extract_chunk_worker,
                chunk,
                extractor=extractor,
                document_metadata=document_metadata,
            )
            future_map[future] = (chunk, attempt_count)

        for future in as_completed(future_map):
            chunk, attempt_count = future_map[future]
            try:
                claims = future.result()
                _write_chunk_artifact(
                    output_dir,
                    chunk,
                    status=STATUS_SUCCEEDED,
                    attempt_count=attempt_count,
                    claims=claims,
                    error=None,
                    extractor_name=extractor_name,
                )
                _append_status_event(
                    output_dir,
                    chunk,
                    STATUS_SUCCEEDED,
                    attempt_count,
                    claim_count=len(claims),
                    claims_path=str(_chunk_claim_path(output_dir, chunk)),
                )
                counts[STATUS_SUCCEEDED] += 1
            except Exception as exc:
                _write_chunk_artifact(
                    output_dir,
                    chunk,
                    status=STATUS_FAILED,
                    attempt_count=attempt_count,
                    claims=[],
                    error=str(exc),
                    extractor_name=extractor_name,
                )
                _append_status_event(
                    output_dir,
                    chunk,
                    STATUS_FAILED,
                    attempt_count,
                    error=str(exc),
                    claims_path=str(_chunk_claim_path(output_dir, chunk)),
                )
                counts[STATUS_FAILED] += 1

    return counts


def _merge_succeeded_chunk_claims(output_dir: Path, chunks: list[ChunkRecord]) -> list[ClaimRecord]:
    merged: list[ClaimRecord] = []
    for chunk in sorted(chunks, key=lambda item: item.chunk_index):
        artifact = _existing_chunk_artifact(output_dir, chunk)
        if not artifact or artifact.get("status") != STATUS_SUCCEEDED:
            continue
        for row in artifact.get("claims", []):
            merged.append(_claim_from_row(row))
    return merged


def _status_counts_for_chunks(output_dir: Path, chunks: list[ChunkRecord]) -> dict[str, int]:
    latest = _latest_status_by_chunk(output_dir)
    counts = {
        STATUS_PENDING: 0,
        STATUS_RUNNING: 0,
        STATUS_SUCCEEDED: 0,
        STATUS_FAILED: 0,
    }
    for chunk in chunks:
        row = latest.get(chunk.chunk_id)
        artifact = _existing_chunk_artifact(output_dir, chunk)
        status = STATUS_PENDING
        if row and str(row.get("status")) in counts:
            status = str(row.get("status"))
        if artifact and artifact.get("status") == STATUS_SUCCEEDED:
            status = STATUS_SUCCEEDED
        counts[status] += 1
    return counts


def run_document_pipeline(
    manifest: DocumentManifest,
    extractor: Callable[[dict[str, Any]], Any] | None = None,
    neo4j_driver=None,
    start_chunk: int = 0,
    max_chunks: int | None = None,
    append_claims: bool = False,
    resume: bool = False,
    max_workers: int = 1,
) -> dict[str, Any]:
    output_dir = Path(manifest.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if append_claims:
        resume = True

    document, chunks, canonical_source, canonical_changed = _materialize_document_and_chunks(manifest, output_dir, resume=resume)

    effective_resume = resume and not canonical_changed

    if not effective_resume:
        _reset_extraction_artifacts(output_dir)

    target_chunks, skipped_chunk_count = _chunk_execution_targets(
        chunks,
        output_dir,
        start_chunk=start_chunk,
        max_chunks=max_chunks,
        resume=effective_resume,
    )

    execution_counts = _run_chunk_extraction(
        output_dir,
        target_chunks,
        extractor=extractor,
        document_metadata=document.metadata,
        max_workers=max_workers,
    )

    persisted_raw_claims = _merge_succeeded_chunk_claims(output_dir, chunks)
    _write_jsonl(output_dir / "claims.raw.jsonl", [claim.to_dict() for claim in persisted_raw_claims])

    validated_claims, rejected_claims = validate_claims(persisted_raw_claims)
    _write_jsonl(output_dir / "claims.validated.jsonl", [claim.to_dict() for claim in validated_claims])
    _write_json(output_dir / "claims.rejected.json", rejected_claims)

    if neo4j_driver is not None:
        import_claims(neo4j_driver, document, chunks, validated_claims)

    chunk_status_counts = _status_counts_for_chunks(output_dir, chunks)
    summary = {
        "doc_id": manifest.doc_id,
        "selected_parser": document.parser_used,
        "parser_candidates": manifest.parser_candidates,
        "canonical_source": canonical_source,
        "chunk_count": len(chunks),
        "processed_chunk_count": len(target_chunks),
        "skipped_chunk_count": skipped_chunk_count,
        "start_chunk": start_chunk,
        "max_chunks": max_chunks,
        "resume_used": effective_resume,
        "canonical_changed": canonical_changed,
        "max_workers": max(1, max_workers),
        "raw_claim_count": len(persisted_raw_claims),
        "validated_claim_count": len(validated_claims),
        "rejected_claim_count": len(rejected_claims),
        "chunk_status_counts": chunk_status_counts,
        "succeeded_chunk_count": chunk_status_counts[STATUS_SUCCEEDED],
        "failed_chunk_count": chunk_status_counts[STATUS_FAILED],
        "merge_completed": True,
        "execution_succeeded_this_run": execution_counts[STATUS_SUCCEEDED],
        "execution_failed_this_run": execution_counts[STATUS_FAILED],
        "output_dir": str(output_dir),
    }
    _write_json(output_dir / "pipeline_summary.json", summary)
    return summary
