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

from dotenv import load_dotenv
load_dotenv()
import tempfile
import time
import uuid
from typing import Any, Optional

import pandas as pd
import threading
from collections import deque
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

BASE = os.path.dirname(os.path.abspath(__file__))
BUFFER_DB = os.path.join(BASE, "live_observations.db")
BASELINE_PARQUET = os.path.join(BASE, "datasets", "baseline_stats.parquet")
TEP_DB = os.path.join(BASE, "tep_combined.db")
INBOX_DIR = os.path.join(BASE, "inbox")
os.makedirs(INBOX_DIR, exist_ok=True)

app = FastAPI(title="TEP Fault Diagnosis MAS", version="0.1.0")


# ----------------------- Rate limiting (Phase 6) ----------------------- #
RATE_LIMIT_ENABLED = os.environ.get("API_RATE_LIMIT_ENABLED", "0") == "1"
RATE_LIMIT_RPM = int(os.environ.get("API_RATE_LIMIT_RPM", "60"))
RATE_LIMIT_PATHS = {"/diagnose", "/diagnose/window", "/admin/baseline"}
_rate_buckets: dict[str, deque] = {}
_rate_lock = threading.Lock()


@app.middleware("http")
async def _rate_limit_middleware(request: Request, call_next):
    if RATE_LIMIT_ENABLED and request.url.path in RATE_LIMIT_PATHS:
        client = (request.client.host if request.client else "unknown")
        bucket_key = f"{client}:{request.url.path}"
        now = time.time()
        cutoff = now - 60.0
        with _rate_lock:
            bucket = _rate_buckets.setdefault(bucket_key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= RATE_LIMIT_RPM:
                retry_after = max(1, int(60 - (now - bucket[0])))
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"rate limit {RATE_LIMIT_RPM}/min exceeded",
                             "retry_after_s": retry_after},
                )
            bucket.append(now)
    return await call_next(request)


# ----------------------- Models ----------------------- #

class ObservationRow(BaseModel):
    """A single sensor reading; keys are sensor names (xmeas_*, xmv_*)."""
    model_config = {"extra": "allow"}


class IngestRequest(BaseModel):
    source: str = Field(default="manual", description="Source label (simulator, scada, manual)")
    true_fault_hidden: Optional[int] = Field(default=None, description="Ground truth (for QA only)")
    rows: list[dict[str, Any]] = Field(..., description="One or more sensor rows")
    sample_indices: Optional[list[Optional[int]]] = Field(default=None,
                                                          description="Per-row sample_idx (TS)")
    simulationruns: Optional[list[Optional[int]]] = Field(default=None,
                                                         description="Per-row simulationrun (TS)")


class IngestResponse(BaseModel):
    inserted: int
    obs_ids: list[int]


class WindowDiagnoseRequest(BaseModel):
    window_size: int = Field(default=50, ge=1, le=1000, description="Recent rows to diagnose")
    source: Optional[str] = Field(default=None, description="Filter buffer by source label")
    true_fault: Optional[int] = Field(default=None,
                                      description="Override true_fault; else inferred from majority of buffered rows")
    recursion_limit: int = 60


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

_buffer_init_lock = threading.Lock()
_buffer_initialised: set[str] = set()


def _ensure_buffer() -> None:
    """Thread-safe lazy init. Idempotent + cached per DB path."""
    if BUFFER_DB in _buffer_initialised:
        return
    with _buffer_init_lock:
        if BUFFER_DB in _buffer_initialised:
            return
        from scripts.init_live_buffer import init  # type: ignore
        init(BUFFER_DB)
        _buffer_initialised.add(BUFFER_DB)


def _persist_observations(
    rows: list[dict],
    source: str,
    true_fault: Optional[int],
    sample_indices: Optional[list[Optional[int]]] = None,
    simulationruns: Optional[list[Optional[int]]] = None,
) -> list[int]:
    _ensure_buffer()
    ts = time.time()
    ids: list[int] = []
    conn = sqlite3.connect(BUFFER_DB)
    try:
        cur = conn.cursor()
        for i, row in enumerate(rows):
            s_idx = (sample_indices[i] if sample_indices and i < len(sample_indices) else
                     row.get("sample"))
            sr = simulationruns[i] if simulationruns and i < len(simulationruns) else None
            cur.execute(
                "INSERT INTO observations "
                "(ts, source, true_fault_hidden, payload_json, sample_idx, simulationrun) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, source, true_fault, json.dumps(row, ensure_ascii=False),
                 int(s_idx) if s_idx is not None else None,
                 int(sr) if sr is not None else None),
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
            "POST /diagnose", "POST /diagnose/window",
            "POST /observations", "GET /observations",
            "GET /diagnoses", "POST /admin/baseline",
            "GET /health", "GET /dashboard",
        ],
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    sqlite_ok = os.path.exists(TEP_DB)
    neo4j_ok = bool(os.environ.get("NEO4J_URI"))
    if neo4j_ok:
        try:
            from knowledge.neo4j_kg import _get_kg_driver
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
    ids = _persist_observations(
        req.rows,
        source=req.source,
        true_fault=req.true_fault_hidden,
        sample_indices=req.sample_indices,
        simulationruns=req.simulationruns,
    )
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
    from simulation.diagnose_flow import diagnose as run_diagnose
    result = run_diagnose(
        observation_path=obs_path,
        true_fault=req.true_fault,
        buffer_db=BUFFER_DB,
        recursion_limit=req.recursion_limit,
        obs_ids=obs_ids,
    )
    return DiagnoseResponse(**result.to_dict())


@app.post("/diagnose/window", response_model=DiagnoseResponse)
def diagnose_window(req: WindowDiagnoseRequest) -> DiagnoseResponse:
    """Pull the last N observations from the buffer and diagnose them as a batch."""
    _ensure_buffer()
    conn = sqlite3.connect(BUFFER_DB)
    try:
        if req.source:
            rows = conn.execute(
                "SELECT obs_id, payload_json, true_fault_hidden, sample_idx "
                "FROM observations WHERE source = ? ORDER BY obs_id DESC LIMIT ?",
                (req.source, int(req.window_size)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT obs_id, payload_json, true_fault_hidden, sample_idx "
                "FROM observations ORDER BY obs_id DESC LIMIT ?",
                (int(req.window_size),),
            ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail="no observations in buffer")

    # Chronological order
    rows = list(reversed(rows))
    obs_ids = [int(r[0]) for r in rows]
    payloads = [json.loads(r[1]) for r in rows]
    truth_labels = [r[2] for r in rows if r[2] is not None]

    inferred_truth = req.true_fault
    if inferred_truth is None and truth_labels:
        inferred_truth = max(set(truth_labels), key=truth_labels.count)

    df = pd.DataFrame(payloads)
    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    tmp.close()
    df.to_parquet(tmp.name, index=False)

    from simulation.diagnose_flow import diagnose as run_diagnose
    result = run_diagnose(
        observation_path=tmp.name,
        true_fault=inferred_truth,
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


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(limit: int = 50) -> HTMLResponse:
    from monitoring.dashboard import render_dashboard
    return HTMLResponse(render_dashboard(BUFFER_DB, limit=limit))
