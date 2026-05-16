"""Diagnosis orchestrator — wraps the LangGraph supervisor for unlabeled observations.

Public API:
    diagnose(observation_path, true_fault=None) -> DiagnosisResult

Flow:
    1. Initialise a run-scoped state mirroring chat_cli.py
    2. Register the observation parquet + baseline_stats on the blackboard
    3. Seed a HumanMessage that frames the diagnosis task
    4. Invoke the LangGraph supervisor
    5. Parse final_answer for fault_id + evidence sensors
    6. Persist DiagnosisResult to live_observations.db (diagnoses table)
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BUFFER_DB = os.path.join(BASE, "live_observations.db")
DEFAULT_BASELINE = os.path.join(BASE, "datasets", "baseline_stats.parquet")
PDF_DOCS_PATH = os.path.join(BASE, "TEP_docs")
SQLITE_DB_PATH = "sqlite:///tep_combined.db"

_FAULT_PATTERNS = [
    re.compile(r"\bIDV[_\s-]?(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bfault[_\s-]?(?:id\s*=?\s*)?(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bidv_number[\":\s]+(\d{1,2})", re.IGNORECASE),
]


@dataclass
class DiagnosisResult:
    run_id: str
    ts: float
    observation_path: str
    predicted_fault: Optional[int]
    fault_name: Optional[str]
    confidence: Optional[float]
    evidence_sensors: list[str]
    top_candidates: list[dict]
    summary: str
    true_fault: Optional[int] = None
    tool_events_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_final_answer(state: dict[str, Any]) -> str:
    """Pull the supervisor's final_answer text from the message log."""
    from langchain_core.messages import AIMessage

    for msg in reversed(state.get("messages", []) or []):
        if isinstance(msg, AIMessage):
            tcs = getattr(msg, "tool_calls", None) or []
            if tcs and tcs[0].get("name") == "final_answer":
                return tcs[0].get("args", {}).get("answer", "") or ""
            if not tcs and getattr(msg, "content", None):
                return msg.content
    return ""


def _parse_fault_id(text: str) -> Optional[int]:
    if not text:
        return None
    for pat in _FAULT_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                fid = int(m.group(1))
                if 0 <= fid <= 20:
                    return fid
            except (ValueError, IndexError):
                continue
    return None


def _scan_blackboard_for_candidates(state: dict[str, Any]) -> list[dict]:
    """Find the last kg_match_fault_by_sensors result on the blackboard / events."""
    for ev in reversed(state.get("tool_events", []) or []):
        if ev.get("tool") == "kg_match_fault_by_sensors" and ev.get("ok"):
            result = ev.get("result") or ev.get("output")
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    continue
            elif isinstance(result, list):
                return result
    return []


def _scan_evidence_sensors(state: dict[str, Any], top_candidates: list[dict]) -> list[str]:
    """Get the matched sensors from the top candidate; fall back to any seen list."""
    if top_candidates:
        return list(top_candidates[0].get("matched") or [])
    return []


def _weighted_confidence(
    candidates: list[dict],
    predicted: Optional[int],
) -> Optional[float]:
    """Phase 6: confidence weighted by margin over the runner-up.

    base = candidate's Jaccard score
    margin = base − second_best_score (or base if only one)
    confidence = base * (0.5 + 0.5 * margin)  → in [base/2, base]

    A tight top-1 with no runner-up gets full base; a close second-place
    drops confidence proportionally. Caps at 1.0, floors at 0.
    """
    if not candidates or predicted is None:
        return None
    chosen = next(
        (c for c in candidates if c.get("fault_id") == predicted),
        candidates[0],
    )
    base = float(chosen.get("score") or 0.0)
    if base <= 0:
        return 0.0
    others = [c for c in candidates if c is not chosen]
    second = max((float(c.get("score") or 0.0) for c in others), default=0.0)
    margin = max(0.0, base - second)
    confidence = base * (0.5 + 0.5 * margin)
    return max(0.0, min(1.0, round(confidence, 4)))


def _persist_diagnosis(
    db_path: str,
    result: DiagnosisResult,
    obs_ids: Optional[list[int]] = None,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO diagnoses
            (run_id, ts, obs_ids_json, predicted_fault, confidence,
             evidence_json, summary, true_fault_optional)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.run_id,
                result.ts,
                json.dumps(obs_ids or []),
                result.predicted_fault,
                result.confidence,
                json.dumps({
                    "sensors": result.evidence_sensors,
                    "top_candidates": result.top_candidates,
                }, ensure_ascii=False),
                result.summary,
                result.true_fault,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _build_seed_message(obs_dataset: str, baseline_dataset: str, n_rows: int) -> str:
    return (
        f"An unlabeled TEP sensor observation ({n_rows} consecutive samples) has been "
        f"registered on the blackboard as dataset `{obs_dataset}`. "
        f"The normal-operation baseline statistics are registered as `{baseline_dataset}` "
        f"(per-sensor mean / std / percentiles computed from faultnumber=0).\n\n"
        "Do NOT re-query SQL — the datasets are already on the blackboard.\n\n"
        "Workflow:\n"
        "1. delegate_to_de to inspect read_blackboard(keys=['datasets']) and load both named datasets.\n"
        "2. delegate_to_ds to compute per-sensor z-score = (obs.mean - baseline.mean) / baseline.std "
        "and report the top-5 sensors by |z-score|.\n"
        "3. delegate_to_me with kg_match_fault_by_sensors using those top sensors, then "
        "kg_query_fault on the top candidate for context.\n"
        "4. final_answer with the predicted fault ID (e.g. IDV_4), the evidence sensors, "
        "and a one-paragraph explanation of why that fault matches."
    )


def diagnose(
    observation_path: str,
    true_fault: Optional[int] = None,
    *,
    baseline_path: str = DEFAULT_BASELINE,
    buffer_db: str = DEFAULT_BUFFER_DB,
    recursion_limit: int = 60,
    obs_ids: Optional[list[int]] = None,
) -> DiagnosisResult:
    """Run a single diagnosis on an unlabeled observation parquet."""
    # Lazy imports — these trigger GOOGLE_API_KEY validation
    from langchain_core.messages import HumanMessage
    from core.common import ensure_run_id
    from core.metrics import init_metrics
    from agents.bb_tools import bb_register_dataset_path, sync_blackboard_state
    from agents.supervisor_workflow import build_team_graph

    run_id = f"diag_{uuid.uuid4().hex[:10]}"
    ts = time.time()

    if not os.path.exists(observation_path):
        return DiagnosisResult(
            run_id=run_id, ts=ts, observation_path=observation_path,
            predicted_fault=None, fault_name=None, confidence=None,
            evidence_sensors=[], top_candidates=[], summary="",
            true_fault=true_fault,
            error=f"observation_path not found: {observation_path}",
        )

    try:
        obs_df = pd.read_parquet(observation_path)
    except Exception as e:
        return DiagnosisResult(
            run_id=run_id, ts=ts, observation_path=observation_path,
            predicted_fault=None, fault_name=None, confidence=None,
            evidence_sensors=[], top_candidates=[], summary="",
            true_fault=true_fault, error=f"failed to load observation: {e}",
        )

    obs_dataset_name = f"obs_{run_id}"
    baseline_dataset_name = "baseline_stats"

    state: dict[str, Any] = {
        "messages": [],
        "blackboard": {"facts": [], "datasets": [], "citations": [], "open_issues": [], "artifacts": []},
        "tool_events": [],
        "violations": [],
        "pdf_dir": PDF_DOCS_PATH,
        "db_url": SQLITE_DB_PATH,
        "run_id": run_id,
        "policy": "gentle",
        "turn_counter": 0,
        "seed": 42,
        "task_id": run_id,
        "prompt_condition": "diagnose",
        "phase": "diagnose",  # triggers Supervisor:diagnose PHASE_SNIPPET
        "topic_ctx": {
            "mode": "diagnose",
            "obs_dataset": obs_dataset_name,
            "baseline_dataset": baseline_dataset_name,
        },
    }
    ensure_run_id(state)
    init_metrics(state)

    try:
        bb_register_dataset_path(
            run_id=run_id,
            name=obs_dataset_name,
            path=os.path.abspath(observation_path),
            fmt="parquet",
            rows=len(obs_df),
            columns=list(obs_df.columns),
            meta={
                "source": "diagnose_flow",
                "unlabeled": True,
                "intended_owner": "DS",
                "kind": "observation",
                "role": "input",
                "aliases": [obs_dataset_name, "observation"],
            },
            topic_id="diagnose",
            created_by="SYSTEM",
            state=state,
        )
        if os.path.exists(baseline_path):
            base_df = pd.read_parquet(baseline_path)
            bb_register_dataset_path(
                run_id=run_id,
                name=baseline_dataset_name,
                path=os.path.abspath(baseline_path),
                fmt="parquet",
                rows=len(base_df),
                columns=list(base_df.columns),
                meta={
                    "source": "build_baseline_stats",
                    "intended_owner": "DS",
                    "kind": "baseline",
                    "role": "reference",
                    "aliases": [baseline_dataset_name, "baseline"],
                },
                topic_id="diagnose",
                created_by="SYSTEM",
                state=state,
            )
        sync_blackboard_state(state, run_id)
    except Exception as e:
        return DiagnosisResult(
            run_id=run_id, ts=ts, observation_path=observation_path,
            predicted_fault=None, fault_name=None, confidence=None,
            evidence_sensors=[], top_candidates=[], summary="",
            true_fault=true_fault, error=f"blackboard register failed: {e}",
        )

    seed_text = _build_seed_message(obs_dataset_name, baseline_dataset_name, len(obs_df))
    state["messages"].append(HumanMessage(content=seed_text))

    graph = build_team_graph()
    try:
        out_state = graph.invoke(state, {"recursion_limit": recursion_limit})
        state.update(out_state or {})
    except Exception as e:
        return DiagnosisResult(
            run_id=run_id, ts=ts, observation_path=observation_path,
            predicted_fault=None, fault_name=None, confidence=None,
            evidence_sensors=[], top_candidates=[], summary="",
            true_fault=true_fault, error=f"graph invoke failed: {e}",
        )

    final_text = _extract_final_answer(state)
    predicted = _parse_fault_id(final_text)
    candidates = _scan_blackboard_for_candidates(state)
    evidence = _scan_evidence_sensors(state, candidates)

    fault_name = f"IDV_{predicted}" if predicted is not None else None
    confidence = _weighted_confidence(candidates, predicted)

    result = DiagnosisResult(
        run_id=run_id,
        ts=ts,
        observation_path=observation_path,
        predicted_fault=predicted,
        fault_name=fault_name,
        confidence=confidence,
        evidence_sensors=evidence,
        top_candidates=candidates,
        summary=final_text,
        true_fault=true_fault,
        tool_events_count=len(state.get("tool_events", []) or []),
    )

    try:
        _persist_diagnosis(buffer_db, result, obs_ids=obs_ids)
    except Exception:
        pass

    return result
