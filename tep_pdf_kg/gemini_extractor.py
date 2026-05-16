from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .llm_json import extract_json_payload
from .schema import ALLOWED_ENTITY_LABELS, ALLOWED_RELATIONS, CLAIM_TYPES

DEFAULT_EXTRACTION_CONFIDENCE = 0.7
RELATION_ROLE_GUIDANCE = [
    "OBSERVED_BY only when the subject is a Symptom and the object is a Sensor.",
    "ACTS_ON only when the subject is a ControlAction and the object is an Actuator.",
    "CAUSES should prefer Fault -> Symptom.",
    "AFFECTS_UNIT should prefer Fault -> ProcessUnit.",
    "SUGGESTS_ACTION only when the subject is a Fault and the object is a ControlAction.",
    "SUBJECT_TO only when the subject is a ControlAction and the object is a Constraint.",
    "HAS_RISK only when the subject is a ControlAction and the object is a Risk.",
    "HAS_CAPABILITY only when the subject is a ProcessUnit and the object is a Capability.",
]
NEGATIVE_EXTRACTION_RULES = [
    "Do not convert counts, inventories, configuration lists, section titles, or headings into fault or symptom claims.",
    "Do not force capability or inventory text into ACTS_ON or OBSERVED_BY.",
    "If the chunk only states what the process or unit has available, emit a capability claim or omit it.",
]
CONFIDENCE_CALIBRATION_RULES = [
    "Use 0.80 or higher when the claim is explicit and semantically precise.",
    "Use 0.65 to 0.79 when the claim is supported but needs light normalization or mapping.",
    "Prefer omission over speculative claims. Do not default to 0.50 for uncertain items.",
]


class ExtractedClaim(BaseModel):
    subject: str = Field(..., min_length=1)
    subject_label: str
    predicate: str
    object: str = Field(..., min_length=1)
    object_label: str
    claim_type: str
    evidence_text: str = Field("", min_length=0)
    extraction_confidence: float = Field(DEFAULT_EXTRACTION_CONFIDENCE, ge=0.0, le=1.0)
    review_status: str = "pending"


class ExtractedClaimBatch(BaseModel):
    claims: list[ExtractedClaim] = []

def _coerce_claim_batch(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, str):
        payload = extract_json_payload(payload)
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


def _system_prompt() -> str:
    relation_rules = "\n".join(f"- {rule}" for rule in RELATION_ROLE_GUIDANCE)
    negative_rules = "\n".join(f"- {rule}" for rule in NEGATIVE_EXTRACTION_RULES)
    confidence_rules = "\n".join(f"- {rule}" for rule in CONFIDENCE_CALIBRATION_RULES)
    return (
        "You are a Tennessee Eastman Process knowledge graph extractor.\n"
        "Extract only claims explicitly supported by the provided chunk.\n"
        "Use only the allowed entity labels, relation labels, and claim types.\n"
        "Do not infer beyond the chunk. Prefer omission over guessing.\n"
        "Keep evidence_text short and verbatim.\n"
        "Relation-role rules:\n"
        f"{relation_rules}\n"
        "Negative rules:\n"
        f"{negative_rules}\n"
        "Confidence calibration:\n"
        f"{confidence_rules}\n"
    )


def _user_prompt_from_payload(payload: dict[str, Any]) -> str:
    chunk = payload.get("chunk") or {}
    metadata = payload.get("document_metadata") or {}
    allowed_relations = payload.get("allowed_relations") or sorted(ALLOWED_RELATIONS)
    return (
        f"Allowed entity labels: {sorted(ALLOWED_ENTITY_LABELS)}\n"
        f"Allowed relation labels: {allowed_relations}\n"
        f"Allowed claim types: {sorted(CLAIM_TYPES)}\n\n"
        "Document metadata:\n"
        f"{json.dumps(metadata, ensure_ascii=False, indent=2)}\n\n"
        "Chunk:\n"
        f"{json.dumps(chunk, ensure_ascii=False, indent=2)}\n"
    )


def _messages_from_payload(payload: dict[str, Any], *, require_json_shape: bool) -> list[Any]:
    user_prompt = _user_prompt_from_payload(payload)
    if require_json_shape:
        user_prompt += (
            "\nReturn JSON with shape: "
            + '{"claims":[{"subject":"","subject_label":"","predicate":"","object":"","object_label":"","claim_type":"","evidence_text":"","extraction_confidence":0.0,"review_status":"pending"}]}'
        )
    return [
        SystemMessage(content=_system_prompt()),
        HumanMessage(content=user_prompt),
    ]


def build_gemini_extractor(model: str | None = None, temperature: float | None = 0.0) -> Callable[[dict[str, Any]], Any]:
    from langchain_google_genai import ChatGoogleGenerativeAI

    from core.common import invoke_with_retry, llm

    active_llm = llm
    if model:
        active_llm = ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature if temperature is not None else getattr(llm, "temperature", 0.0),
            max_output_tokens=getattr(llm, "max_output_tokens", 8192),
        )
    elif temperature is not None and hasattr(active_llm, "bind"):
        active_llm = active_llm.bind(temperature=temperature)

    if hasattr(active_llm, "with_structured_output"):
        structured = active_llm.with_structured_output(ExtractedClaimBatch)

        def extractor(payload: dict[str, Any]) -> list[dict[str, Any]]:
            messages = _messages_from_payload(payload, require_json_shape=False)
            try:
                result = invoke_with_retry(structured.invoke, messages)
                claims = getattr(result, "claims", []) or []
                return [claim.model_dump() for claim in claims]
            except OutputParserException:
                raw_result = invoke_with_retry(active_llm.invoke, _messages_from_payload(payload, require_json_shape=True))
                content = getattr(raw_result, "content", "")
                return _coerce_claim_batch(content)

        return extractor

    def extractor(payload: dict[str, Any]) -> list[dict[str, Any]]:
        result = invoke_with_retry(active_llm.invoke, _messages_from_payload(payload, require_json_shape=True))
        content = getattr(result, "content", "")
        return _coerce_claim_batch(content)

    return extractor
