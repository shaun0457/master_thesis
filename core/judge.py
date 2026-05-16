"""
JudgeLLM — evaluates final_answer quality against the original question.

judge_sync() is synchronous, called at the end of each turn in chat_cli.py.
Returns JudgeScore on success, None on any failure (never raises).
"""
from __future__ import annotations
import json
import re
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage

from core.structured_outputs import JudgeScore


def _extract_json(text: str) -> str:
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def _first_question(state: Dict[str, Any]) -> str:
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            return msg.content
    return "unknown question"


class JudgeLLM:
    PROMPT_TEMPLATE = (
        "You are an impartial judge. Score the answer to the question below.\n\n"
        "Question: {question}\n\n"
        "Answer: {answer}\n\n"
        "Respond with JSON only, no explanation:\n"
        '{{"factual_grounding": 0-3, "completeness": 0-3, "coherence": 0-3, "critique": "..."}}'
    )

    def judge_sync(
        self,
        llm: Any,
        state: Dict[str, Any],
        final_answer: str,
    ) -> Optional[JudgeScore]:
        try:
            question = _first_question(state)
            prompt = self.PROMPT_TEMPLATE.format(
                question=question,
                answer=final_answer,
            )
            msgs = [HumanMessage(content=prompt)]
            raw = llm.invoke(msgs)
            score = JudgeScore.model_validate_json(_extract_json(raw.content))

            m = state.setdefault("metrics", {})
            m["judge_triggered"] = True
            m["judge_factual_grounding"] = score.factual_grounding
            m["judge_completeness"] = score.completeness
            m["judge_coherence"] = score.coherence
            return score
        except Exception:
            return None
