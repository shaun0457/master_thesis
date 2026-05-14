"""FastAPI server — production entry for the TEP fault diagnosis MAS.

Endpoints:
    POST /diagnose            run diagnosis on an observation (path or inline rows)
    POST /observations        ingest sensor row(s) to the live buffer
    GET  /observations        list recent buffered rows
    GET  /diagnoses           list recent diagnosis results
    POST /admin/baseline      trigger baseline recompute (async)
    GET  /health              Neo4j + SQLite + Gemini reachability
    GET  /                    minimal index

Run:
    uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import uuid
from typing import Any, Optional

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

BASE = os.path.dirname(os.path.abspath(__file__))
BUFFER_DB = os.path.join(BASE, "live_observations.db")
BASELINE_PARQUET = os.path.join(BASE, "datasets", "baseline_stats.parquet")
TEP_DB = os.path.join(BASE, "tep_combined.db")
INBOX_DIR = os.path.join(BASE, "inbox")
os.makedirs(INBOX_DIR, exist_ok=True)

app = FastAPI(title="TEP Fault Diagnosis MAS", version="0.1.0")


# ----------------------- Models ----------------------- #

class ObservationRow(BaseModel):
    """A single sensor reading; keys are sensor names (xmeas_*, xmv_*)."""
    model_config = {"extra": "allow"}


class IngestRequest(BaseModel):
    source: str = Field(default="manual", description="Source label (simulator, scada, manual)")
    true_fault_hidden: Optional[int] = Field(default=None, description="Ground truth (for QA only)")
    rows: list[dict[str, Any]] = Field(..., description="One or more sensor rows")


class IngestResponse(BaseModel):
    inserted: int
    obs_ids: list[int]


class DiagnoseRequest(BaseModel):
    observation_path: Optional[str] = Field(default=None, description="Path to parquet/csv")
    rows: Optional[list[dict[str, Any]]] = Field(default=None, description="Inline rows")
    true_fault: Optional[int] = Field(default=None, description="Ground truth (QA only)")
    recursion_limit: int = 60


class DiagnoseResponse(BaseModel):
    run_id: str
    ts: float
    predicted_fault: Optional[int]
    fault_name: Optional[str]
    confidence: Optional[float]
    evidence_sensors: list[str]
    top_candidates: list[dict[str, Any]]
    summary: str
    true_fault: Optional[int]
    tool_events_count: int
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    sqlite_ok: bool
    neo4j_ok: bool
    gemini_key_present: bool
    baseline_present: bool


# ----------------------- Helpers ----------------------- #

def _ensure_buffer() -> None:
    if not os.path.exists(BUFFER_DB):
        from scripts.init_live_buffer import init  # type: ignore
        init(BUFFER_DB)


def _persist_observations(rows: list[dict], source: str, true_fault: Optional[int]) -> list[int]:
    _ensure_buffer()
    ts = time.time()
    ids: list[int] = []
    conn = sqlite3.connect(BUFFER_DB)
    try:
        cur = conn.cursor()
        for row in rows:
            cur.execute(
                "INSERT INTO observations (ts, source, true_fault_hidden, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (ts, source, true_fault, json.dumps(row, ensure_ascii=False)),
            )
            ids.append(int(cur.lastrowid))
        conn.commit()
    finally:
        conn.close()
    return ids


def _materialise_observation(req: DiagnoseRequest) -> tuple[str, list[int] | None]:
    """Return a parquet path for the observation, materialising rows if needed."""
    if req.observation_path:
        if not os.path.exists(req.observation_path):
            raise HTTPException(status_code=400, detail=f"observation_path not found: {req.observation_path}")
        return req.observation_path, None

    if req.rows:
        df = pd.DataFrame(req.rows)
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        tmp.close()
        df.to_parquet(tmp.name, index=False)
        ids = _persist_observations(req.rows, source="diagnose_inline",
                                    true_fault=req.true_fault)
        return tmp.name, ids

    raise HTTPException(status_code=400, detail="Provide either observation_path or rows")


# ----------------------- Endpoints ----------------------- #

@app.get("/")
def index() -> dict[str, Any]:
    return {
        "name": "TEP Fault Diagnosis MAS",
        "endpoints": [
            "POST /diagnose", "POST /observations", "GET /observations",
            "GET /diagnoses", "POST /admin/baseline", "GET /health",
        ],
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    sqlite_ok = os.path.exists(TEP_DB)
    neo4j_ok = bool(os.environ.get("NEO4J_URI"))
    if neo4j_ok:
        try:
            from neo4j_kg import _get_kg_driver
            driver = _get_kg_driver()
            with driver.session() as session:
                session.run("RETURN 1").consume()
        except Exception:
            neo4j_ok = False
    gemini_ok = bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    baseline_ok = os.path.exists(BASELINE_PARQUET)
    status = "ok" if (sqlite_ok and gemini_ok and baseline_ok) else "degraded"
    return HealthResponse(
        status=status, sqlite_ok=sqlite_ok, neo4j_ok=neo4j_ok,
        gemini_key_present=gemini_ok, baseline_present=baseline_ok,
    )


@app.post("/observations", response_model=IngestResponse)
def ingest_observations(req: IngestRequest) -> IngestResponse:
    if not req.rows:
        raise HTTPException(status_code=400, detail="rows must be non-empty")
    ids = _persist_observations(req.rows, source=req.source,
                                true_fault=req.true_fault_hidden)
    return IngestResponse(inserted=len(ids), obs_ids=ids)


@app.get("/observations")
def list_observations(limit: int = 50) -> dict[str, Any]:
    _ensure_buffer()
    conn = sqlite3.connect(BUFFER_DB)
    try:
        rows = conn.execute(
            "SELECT obs_id, ts, source, true_fault_hidden, payload_json "
            "FROM observations ORDER BY obs_id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()
    return {
        "count": len(rows),
        "items": [
            {
                "obs_id": r[0], "ts": r[1], "source": r[2],
                "true_fault_hidden": r[3], "payload": json.loads(r[4]),
            }
            for r in rows
        ],
    }


@app.get("/diagnoses")
def list_diagnoses(limit: int = 20) -> dict[str, Any]:
    _ensure_buffer()
    conn = sqlite3.connect(BUFFER_DB)
    try:
        rows = conn.execute(
            "SELECT run_id, ts, obs_ids_json, predicted_fault, confidence, "
            "evidence_json, summary, true_fault_optional "
            "FROM diagnoses ORDER BY ts DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()
    items = []
    correct = 0
    total_with_truth = 0
    for r in rows:
        true_f = r[7]
        pred = r[3]
        if true_f is not None:
            total_with_truth += 1
            if pred is not None and int(pred) == int(true_f):
                correct += 1
        items.append({
            "run_id": r[0], "ts": r[1], "obs_ids": json.loads(r[2] or "[]"),
            "predicted_fault": pred, "confidence": r[4],
            "evidence": json.loads(r[5] or "{}"),
            "summary": r[6], "true_fault": true_f,
        })
    accuracy = (correct / total_with_truth) if total_with_truth else None
    return {"count": len(items), "accuracy": accuracy, "items": items}


@app.post("/diagnose", response_model=DiagnoseResponse)
def diagnose_endpoint(req: DiagnoseRequest) -> DiagnoseResponse:
    obs_path, obs_ids = _materialise_observation(req)
    from diagnose_flow import diagnose as run_diagnose
    result = run_diagnose(
        observation_path=obs_path,
        true_fault=req.true_fault,
        buffer_db=BUFFER_DB,
        recursion_limit=req.recursion_limit,
        obs_ids=obs_ids,
    )
    return DiagnoseResponse(**result.to_dict())


@app.post("/admin/baseline")
def recompute_baseline(bg: BackgroundTasks) -> dict[str, str]:
    def _run() -> None:
        from scripts.build_baseline_stats import build  # type: ignore
        build()
    bg.add_task(_run)
    return {"status": "scheduled", "output": BASELINE_PARQUET}
