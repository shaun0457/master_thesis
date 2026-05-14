from __future__ import annotations

from typing import Iterable

from .schema import ALLOWED_ENTITY_LABELS, ALLOWED_RELATIONS, ClaimRecord, ChunkRecord, NormalizedDocument

KG_ENTITY_KEYS = {
    "Fault": "name",
    "Symptom": "name",
    "Sensor": "name",
    "ProcessUnit": "name",
    "ControlAction": "name",
    "Actuator": "name",
    "Constraint": "name",
    "Risk": "name",
}

KG_SCHEMA_QUERIES = [
    "CREATE CONSTRAINT document_doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE",
    "CREATE CONSTRAINT chunk_chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
    "CREATE CONSTRAINT fault_idv_number IF NOT EXISTS FOR (f:Fault) REQUIRE f.idv_number IS UNIQUE",
    "CREATE INDEX sensor_name IF NOT EXISTS FOR (s:Sensor) ON (s.name)",
    "CREATE INDEX process_unit_name IF NOT EXISTS FOR (p:ProcessUnit) ON (p.name)",
    "CREATE INDEX control_action_name IF NOT EXISTS FOR (a:ControlAction) ON (a.name)",
    "CREATE INDEX constraint_name IF NOT EXISTS FOR (c:Constraint) ON (c.name)",
    "CREATE INDEX risk_name IF NOT EXISTS FOR (r:Risk) ON (r.name)",
]


def schema_queries() -> list[str]:
    return KG_SCHEMA_QUERIES[:]


def chunk_document_queries(document: NormalizedDocument, chunks: Iterable[ChunkRecord]) -> list[tuple[str, dict]]:
    queries: list[tuple[str, dict]] = []
    queries.append(
        (
            "MERGE (d:Document {doc_id: $doc_id}) "
            "SET d.filename = $filename, d.title = $title, d.parser_used = $parser_used, "
            "    d.parser_status = $parser_status, d.source_path = $source_path",
            {
                "doc_id": document.doc_id,
                "filename": document.doc_id,
                "title": document.title,
                "parser_used": document.parser_used,
                "parser_status": document.parser_status,
                "source_path": document.source_path,
            },
        )
    )
    for chunk in chunks:
        queries.append(
            (
                "MERGE (c:Chunk {chunk_id: $chunk_id}) "
                "SET c.doc_id = $doc_id, c.section_title = $section_title, c.page_start = $page_start, "
                "    c.page_end = $page_end, c.chunk_index = $chunk_index, c.content_md = $content_md, "
                "    c.chunk_type = $chunk_type, c.parser_used = $parser_used, c.review_status = $review_status "
                "WITH c "
                "MATCH (d:Document {doc_id: $doc_id}) "
                "MERGE (c)-[:PART_OF]->(d)",
                {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "section_title": chunk.section_title,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "chunk_index": chunk.chunk_index,
                    "content_md": chunk.text_md,
                    "chunk_type": chunk.chunk_type,
                    "parser_used": chunk.parser_used,
                    "review_status": chunk.review_status,
                },
            )
        )
    return queries


def claim_queries(claims: Iterable[ClaimRecord]) -> list[tuple[str, dict]]:
    queries: list[tuple[str, dict]] = []
    for claim in claims:
        if claim.subject_label not in ALLOWED_ENTITY_LABELS or claim.object_label not in ALLOWED_ENTITY_LABELS:
            continue
        if claim.predicate not in ALLOWED_RELATIONS:
            continue
        subject_key = KG_ENTITY_KEYS.get(claim.subject_label, "name")
        object_key = KG_ENTITY_KEYS.get(claim.object_label, "name")
        subject_labels = ":" + claim.subject_label
        object_labels = ":" + claim.object_label
        queries.append(
            (
                f"MERGE (s{subject_labels} {{{subject_key}: $subject_name}}) "
                f"MERGE (o{object_labels} {{{object_key}: $object_name}}) "
                f"MERGE (c:Chunk {{chunk_id: $chunk_id}}) "
                f"MERGE (s)-[r:{claim.predicate}]->(o) "
                "SET r.claim_id = $claim_id, r.claim_type = $claim_type, r.source_doc = $source_doc, "
                "    r.source_chunk_id = $chunk_id, r.page_start = $page_start, r.page_end = $page_end, "
                "    r.parser_used = $parser_used, r.extractor_version = $extractor_version, "
                "    r.review_status = $review_status, r.evidence_text = $evidence_text, "
                "    r.extraction_confidence = $extraction_confidence "
                "MERGE (s)-[:MENTIONED_IN]->(c) "
                "MERGE (o)-[:MENTIONED_IN]->(c)",
                {
                    "subject_name": claim.subject,
                    "object_name": claim.object,
                    "chunk_id": claim.source_chunk_id,
                    "claim_id": claim.claim_id,
                    "claim_type": claim.claim_type,
                    "source_doc": claim.source_doc,
                    "page_start": claim.page_start,
                    "page_end": claim.page_end,
                    "parser_used": claim.parser_used,
                    "extractor_version": claim.extractor_version,
                    "review_status": claim.review_status,
                    "evidence_text": claim.evidence_text,
                    "extraction_confidence": claim.extraction_confidence,
                },
            )
        )
    return queries


def import_claims(driver, document: NormalizedDocument, chunks: list[ChunkRecord], claims: list[ClaimRecord]) -> None:
    with driver.session() as session:
        for query in schema_queries():
            session.run(query)
        for query, params in chunk_document_queries(document, chunks):
            session.run(query, **params)
        for query, params in claim_queries(claims):
            session.run(query, **params)
