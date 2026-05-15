from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, Field

from .schema import ALLOWED_ENTITY_LABELS, ALLOWED_RELATIONS, CLAIM_TYPES


class ExtractedClaim(BaseModel):
    subject: str = Field(..., min_length=1)
    subject_label: str
    predicate: str
    object: str = Field(..., min_length=1)
    object_label: str
    claim_type: str
    evidence_text: str = Field("", min_length=0)
    extraction_confidence: float = Field(0.5, ge=0.0, le=1.0)
    review_status: str = "pending"


class ExtractedClaimBatch(BaseModel):
    claims: list[ExtractedClaim] = []


def _extract_json_payload(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return {"claims": []}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    if "```" in text:
        for block in text.split("```"):
            candidate = block.strip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
            if not candidate:
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    start_positions = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
    if not start_positions:
        return {"claims": []}
    start = min(start_positions)
    for end in range(len(text), start, -1):
        candidate = text[start:end].strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return {"claims": []}


def _coerce_claim_batch(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, str):
        payload = _extract_json_payload(payload)
    if isinstance(payload, dict):
        claims = payload.get("claims", [])
    elif isinstance(payload, list):
        claims = payload
    else:
        claims = []

    accepted: list[dict[str, Any]] = []
    for raw in claims:
        if not isinstance(raw, dict):
            continue
        try:
            accepted.append(ExtractedClaim.model_validate(raw).model_dump())
        except Exception:
            continue
    return accepted


def _prompt_from_payload(payload: dict[str, Any]) -> str:
    chunk = payload.get("chunk") or {}
    metadata = payload.get("document_metadata") or {}
    allowed_relations = payload.get("allowed_relations") or sorted(ALLOWED_RELATIONS)
    return (
        "You extract semantic claims from Tennessee Eastman Process documents.\n"
        "Return only claims grounded in the provided chunk.\n"
        "Use only the allowed entity labels, relation labels, and claim types.\n"
        "Prefer omission over guessing. Keep evidence_text short and verbatim.\n\n"
        f"Allowed entity labels: {sorted(ALLOWED_ENTITY_LABELS)}\n"
        f"Allowed relation labels: {allowed_relations}\n"
        f"Allowed claim types: {sorted(CLAIM_TYPES)}\n\n"
        "Document metadata:\n"
        f"{json.dumps(metadata, ensure_ascii=False, indent=2)}\n\n"
        "Chunk:\n"
        f"{json.dumps(chunk, ensure_ascii=False, indent=2)}\n"
    )


def build_gemini_extractor(model: str | None = None, temperature: float | None = 0.0) -> Callable[[dict[str, Any]], Any]:
    from common import invoke_with_retry, llm

    active_llm = llm
    if model and hasattr(active_llm, "bind"):
        active_llm = active_llm.bind(model=model)
    if temperature is not None and hasattr(active_llm, "bind"):
        active_llm = active_llm.bind(temperature=temperature)

    if hasattr(active_llm, "with_structured_output"):
        structured = active_llm.with_structured_output(ExtractedClaimBatch)

        def extractor(payload: dict[str, Any]) -> list[dict[str, Any]]:
            prompt = _prompt_from_payload(payload)
            try:
                result = invoke_with_retry(structured.invoke, prompt)
                claims = getattr(result, "claims", []) or []
                return [claim.model_dump() for claim in claims]
            except OutputParserException:
                raw_prompt = (
                    prompt
                    + "\nReturn JSON with shape: "
                    + '{"claims":[{"subject":"","subject_label":"","predicate":"","object":"","object_label":"","claim_type":"","evidence_text":"","extraction_confidence":0.0,"review_status":"pending"}]}'
                )
                raw_result = invoke_with_retry(active_llm.invoke, raw_prompt)
                content = getattr(raw_result, "content", "")
                return _coerce_claim_batch(content)

        return extractor

    def extractor(payload: dict[str, Any]) -> list[dict[str, Any]]:
        prompt = (
            _prompt_from_payload(payload)
            + "\nReturn JSON with shape: "
            + '{"claims":[{"subject":"","subject_label":"","predicate":"","object":"","object_label":"","claim_type":"","evidence_text":"","extraction_confidence":0.0,"review_status":"pending"}]}'
        )
        result = invoke_with_retry(active_llm.invoke, prompt)
        content = getattr(result, "content", "")
        return _coerce_claim_batch(content)

    return extractor
