"""Initialize live_observations.db — the rolling buffer for streamed sensor data.

Schema:
    observations(obs_id, ts, source, true_fault_hidden, payload_json,
                 sample_idx, simulationrun)
    diagnoses(run_id, ts, obs_ids_json, predicted_fault, confidence,
              evidence_json, summary, true_fault_optional)

`sample_idx` and `simulationrun` are populated by the stream simulator so
window queries can preserve TEP sample-axis ordering.

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

TABLES = [
    """
    CREATE TABLE IF NOT EXISTS observations (
        obs_id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts                  REAL NOT NULL,
        source              TEXT NOT NULL DEFAULT 'unknown',
        true_fault_hidden   INTEGER,
        payload_json        TEXT NOT NULL,
        sample_idx          INTEGER,
        simulationrun       INTEGER
    )
    """,
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
]

INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_obs_ts ON observations(ts)",
    "CREATE INDEX IF NOT EXISTS idx_obs_sample ON observations(sample_idx)",
    "CREATE INDEX IF NOT EXISTS idx_diag_ts ON diagnoses(ts)",
]

MIGRATIONS = [
    "ALTER TABLE observations ADD COLUMN sample_idx INTEGER",
    "ALTER TABLE observations ADD COLUMN simulationrun INTEGER",
]


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> int:
    """Add new columns to existing observations tables. Idempotent."""
    if not _table_columns(conn, "observations"):
        return 0
    applied = 0
    for stmt in MIGRATIONS:
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            # column already exists — that's fine
            if "duplicate column" not in str(e).lower():
                raise
    return applied


def init(db_path: str = DEFAULT_DB, reset: bool = False) -> str:
    if reset and os.path.exists(db_path):
        os.remove(db_path)
        print(f"[reset] removed existing {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        for stmt in TABLES:
            conn.execute(stmt)
        applied = _migrate(conn)
        for stmt in INDICES:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()

    suffix = f" (migrations: {applied})" if applied else ""
    print(f"[ok] live buffer ready at {db_path}{suffix}")
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
