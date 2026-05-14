from __future__ import annotations

from typing import Iterable

from .schema import ALLOWED_ENTITY_LABELS, ALLOWED_RELATIONS, CLAIM_TYPES, ClaimRecord

ENTITY_CANONICAL_MAP = {
    "reactor cooling water": "Reactor cooling water",
    "cooling water valve": "Cooling water valve",
    "separator": "Separator",
    "reactor": "Reactor",
    "stripper": "Stripper column",
}


def canonicalize_name(value: str) -> str:
    raw = " ".join(value.split()).strip()
    if not raw:
        return raw
    lowered = raw.lower()
    return ENTITY_CANONICAL_MAP.get(lowered, raw)


def validate_claims(claims: Iterable[ClaimRecord], min_confidence: float = 0.55) -> tuple[list[ClaimRecord], list[dict]]:
    accepted: list[ClaimRecord] = []
    rejected: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    for claim in claims:
        claim.subject = canonicalize_name(claim.subject)
        claim.object = canonicalize_name(claim.object)
        claim.normalized_subject = claim.subject.lower()
        claim.normalized_object = claim.object.lower()

        errors: list[str] = []
        if claim.subject_label not in ALLOWED_ENTITY_LABELS:
            errors.append(f"invalid subject label: {claim.subject_label}")
        if claim.object_label not in ALLOWED_ENTITY_LABELS:
            errors.append(f"invalid object label: {claim.object_label}")
        if claim.predicate not in ALLOWED_RELATIONS:
            errors.append(f"invalid predicate: {claim.predicate}")
        if claim.claim_type not in CLAIM_TYPES:
            errors.append(f"invalid claim type: {claim.claim_type}")
        if claim.extraction_confidence < min_confidence:
            errors.append(f"confidence below threshold: {claim.extraction_confidence}")
        if not claim.evidence_text.strip():
            errors.append("missing evidence text")

        dedupe_key = (
            claim.normalized_subject,
            claim.predicate,
            claim.normalized_object,
            claim.source_chunk_id,
        )
        if dedupe_key in seen:
            errors.append("duplicate claim")

        if errors:
            rejected.append({"claim": claim.to_dict(), "errors": errors})
            continue

        seen.add(dedupe_key)
        claim.review_status = "validated"
        accepted.append(claim)

    return accepted, rejected
