"""Stream simulator — replays tep_combined.db as a synthetic SCADA feed.

Reads rows from process_data, strips faultnumber + simulationrun, and POSTs to
the FastAPI /observations endpoint at a configurable cadence. Optionally
schedules a fault-injection pattern (e.g. normal -> fault 4 -> fault 8).

Usage:
    python stream_simulator.py --url http://localhost:8000 --interval 5
    python stream_simulator.py --pattern "normal:60,fault4:30,fault8:30"
    python stream_simulator.py --once --fault 4 --rows 10

The true label is sent to /observations as true_fault_hidden so accuracy can
be computed downstream; the MAS itself never sees it.
"""
from __future__ import annotations

import argparse
import os
import random
import sqlite3
import sys
import time
from dataclasses import dataclass
from typing import Optional

import httpx

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE, "tep_combined.db")

DROP_COLS = {"faultnumber", "simulationrun"}


@dataclass
class Phase:
    fault: int
    duration_s: float

    @classmethod
    def parse(cls, spec: str) -> "Phase":
        name, _, dur = spec.partition(":")
        name = name.strip().lower()
        if name == "normal":
            fid = 0
        elif name.startswith("fault"):
            fid = int(name.replace("fault", "").strip())
        else:
            raise ValueError(f"Bad phase spec: {spec!r}")
        return cls(fault=fid, duration_s=float(dur or 30))


def parse_pattern(pattern: str) -> list[Phase]:
    return [Phase.parse(p.strip()) for p in pattern.split(",") if p.strip()]


def _fetch_rows(conn: sqlite3.Connection, fault: int, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    runs = [r[0] for r in conn.execute(
        "SELECT DISTINCT simulationrun FROM process_data WHERE faultnumber = ?",
        (fault,),
    ).fetchall()]
    if not runs:
        return []
    run = rng.choice(runs)
    cur = conn.execute(
        "SELECT * FROM process_data WHERE faultnumber = ? AND simulationrun = ? "
        "ORDER BY sample LIMIT ?",
        (fault, run, n),
    )
    cols = [d[0] for d in cur.description]
    rows = []
    for vals in cur.fetchall():
        row = {c: v for c, v in zip(cols, vals) if c not in DROP_COLS}
        rows.append(row)
    return rows


def _post_observations(client: httpx.Client, url: str, rows: list[dict],
                       fault: int, source: str) -> bool:
    try:
        r = client.post(f"{url.rstrip('/')}/observations", json={
            "source": source,
            "true_fault_hidden": int(fault),
            "rows": rows,
        }, timeout=30.0)
        if r.status_code != 200:
            print(f"[warn] {r.status_code} {r.text[:200]}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[error] post failed: {e}", file=sys.stderr)
        return False


def run_pattern(url: str, db_path: str, phases: list[Phase],
                interval_s: float, rows_per_tick: int, seed: int) -> int:
    if not os.path.exists(db_path):
        print(f"[error] DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    sent_total = 0
    try:
        with httpx.Client() as client:
            for phase in phases:
                deadline = time.time() + phase.duration_s
                ticks = 0
                while time.time() < deadline:
                    rows = _fetch_rows(conn, phase.fault, rows_per_tick, seed + ticks)
                    if not rows:
                        print(f"[warn] no rows for fault={phase.fault}", file=sys.stderr)
                        break
                    ok = _post_observations(client, url, rows, phase.fault, "simulator")
                    if ok:
                        sent_total += len(rows)
                        print(f"[tick] fault={phase.fault} rows={len(rows)} total_sent={sent_total}")
                    ticks += 1
                    time.sleep(interval_s)
    finally:
        conn.close()
    print(f"[done] total observations sent: {sent_total}")
    return 0


def run_once(url: str, db_path: str, fault: int, rows: int, seed: int) -> int:
    conn = sqlite3.connect(db_path)
    try:
        observations = _fetch_rows(conn, fault, rows, seed)
    finally:
        conn.close()
    if not observations:
        print(f"[error] no rows for fault={fault}", file=sys.stderr)
        return 1
    with httpx.Client() as client:
        ok = _post_observations(client, url, observations, fault, "simulator-once")
    print(f"[ok] sent {len(observations)} rows (fault={fault})" if ok else "[fail]")
    return 0 if ok else 1


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--url", default="http://localhost:8000",
                   help="FastAPI server base URL")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--interval", type=float, default=5.0, help="Seconds between ticks")
    p.add_argument("--rows", type=int, default=5, help="Rows per tick / one-shot")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pattern", default="normal:30,fault4:30,fault8:30",
                   help='Comma-separated phases, e.g. "normal:60,fault4:30"')
    p.add_argument("--once", action="store_true",
                   help="Send a single batch and exit (uses --fault)")
    p.add_argument("--fault", type=int, default=4, help="Fault ID for --once mode")
    args = p.parse_args()

    if args.once:
        sys.exit(run_once(args.url, args.db, args.fault, args.rows, args.seed))
    phases = parse_pattern(args.pattern)
    sys.exit(run_pattern(args.url, args.db, phases, args.interval, args.rows, args.seed))


if __name__ == "__main__":
    main()
