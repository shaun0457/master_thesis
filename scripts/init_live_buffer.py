"""Initialize live_observations.db — the rolling buffer for streamed sensor data.

Schema:
    observations(obs_id, ts, source, true_fault_hidden, payload_json)
    diagnoses(run_id, ts, obs_ids_json, predicted_fault, confidence,
              evidence_json, summary, true_fault_optional)

Indices on ts and obs_id for fast recent-window queries.

Usage:
    python scripts/init_live_buffer.py [--reset]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BASE, "live_observations.db")

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS observations (
        obs_id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts                  REAL NOT NULL,
        source              TEXT NOT NULL DEFAULT 'unknown',
        true_fault_hidden   INTEGER,
        payload_json        TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_obs_ts ON observations(ts)",
    """
    CREATE TABLE IF NOT EXISTS diagnoses (
        run_id              TEXT PRIMARY KEY,
        ts                  REAL NOT NULL,
        obs_ids_json        TEXT NOT NULL,
        predicted_fault     INTEGER,
        confidence          REAL,
        evidence_json       TEXT,
        summary             TEXT,
        true_fault_optional INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_diag_ts ON diagnoses(ts)",
]


def init(db_path: str = DEFAULT_DB, reset: bool = False) -> str:
    if reset and os.path.exists(db_path):
        os.remove(db_path)
        print(f"[reset] removed existing {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        for stmt in SCHEMA:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()

    print(f"[ok] live buffer ready at {db_path}")
    return db_path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", type=str, default=DEFAULT_DB, help="Live buffer DB path")
    p.add_argument("--reset", action="store_true", help="Delete and recreate")
    args = p.parse_args()
    try:
        init(args.db, args.reset)
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
