"""Stream simulator — replays tep_combined.db as a synthetic SCADA feed.

**Time-series semantics (Phase TS):**
A `RunCursor` walks a single `simulationrun` sample-by-sample. When a phase
transition occurs, the cursor switches to a fresh run of the new fault, but
the wallclock keeps advancing. This preserves TEP's sample-axis ordering and
mimics the real plant pattern (samples arrive one at a time, faults are
introduced at a specific moment in the trajectory).

Each POST to /observations carries `sample_idx` + `simulationrun` so the
buffer can be queried as a time-ordered window.

Usage:
    python stream_simulator.py --url http://localhost:8000 --interval 5
    python stream_simulator.py --pattern "normal:60,fault4:30,fault8:30"
    python stream_simulator.py --once --fault 4 --rows 10 --start-sample 161
"""
from __future__ import annotations

import argparse
import os
import random
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE, "tep_combined.db")

DROP_COLS = {"faultnumber", "simulationrun"}
MAX_SAMPLE = 500  # TEP convention: each run has 500 samples


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


@dataclass
class RunCursor:
    """Stateful pointer into a single simulationrun's sample axis."""
    fault: int
    run_idx: int
    next_sample: int = 1
    end_sample: int = MAX_SAMPLE
    available_runs: list[int] = field(default_factory=list)

    def is_exhausted(self) -> bool:
        return self.next_sample > self.end_sample


def parse_pattern(pattern: str) -> list[Phase]:
    return [Phase.parse(p.strip()) for p in pattern.split(",") if p.strip()]


def _list_runs(conn: sqlite3.Connection, fault: int) -> list[int]:
    rows = conn.execute(
        "SELECT DISTINCT simulationrun FROM process_data WHERE faultnumber = ? "
        "ORDER BY simulationrun",
        (fault,),
    ).fetchall()
    return [int(r[0]) for r in rows]


def _build_cursor(
    conn: sqlite3.Connection,
    fault: int,
    *,
    seed: int,
    run_idx: Optional[int] = None,
    start_sample: int = 1,
) -> Optional[RunCursor]:
    runs = _list_runs(conn, fault)
    if not runs:
        return None
    rng = random.Random(seed)
    chosen = run_idx if run_idx is not None else rng.choice(runs)
    if chosen not in runs:
        chosen = runs[0]
    return RunCursor(
        fault=fault,
        run_idx=int(chosen),
        next_sample=max(1, int(start_sample)),
        end_sample=MAX_SAMPLE,
        available_runs=runs,
    )


def _walk_one_tick(conn: sqlite3.Connection, cursor: RunCursor, n: int) -> list[dict]:
    """Fetch up to n rows from the cursor's run starting at next_sample.

    Rolls to the next run of the same fault when the current run is exhausted.
    Mutates `cursor.next_sample` / `cursor.run_idx` in place.
    """
    collected: list[dict] = []
    while len(collected) < n:
        if cursor.is_exhausted():
            # roll to next run of same fault
            try:
                idx = cursor.available_runs.index(cursor.run_idx)
                cursor.run_idx = cursor.available_runs[(idx + 1) % len(cursor.available_runs)]
            except (ValueError, IndexError):
                if not cursor.available_runs:
                    break
                cursor.run_idx = cursor.available_runs[0]
            cursor.next_sample = 1

        remaining = n - len(collected)
        end = min(cursor.end_sample, cursor.next_sample + remaining - 1)
        cur = conn.execute(
            "SELECT * FROM process_data "
            "WHERE faultnumber = ? AND simulationrun = ? "
            "AND sample BETWEEN ? AND ? ORDER BY sample",
            (cursor.fault, cursor.run_idx, cursor.next_sample, end),
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        if not rows:
            cursor.next_sample = cursor.end_sample + 1
            continue
        for vals in rows:
            row = {c: v for c, v in zip(cols, vals)}
            sample_v = row.get("sample")
            run_v = row.get("simulationrun")
            payload = {c: v for c, v in row.items() if c not in DROP_COLS}
            collected.append({
                "payload": payload,
                "sample_idx": int(sample_v) if sample_v is not None else None,
                "simulationrun": int(run_v) if run_v is not None else None,
            })
        cursor.next_sample = end + 1
    return collected


def _post_observations(
    client: httpx.Client,
    url: str,
    rows_with_meta: list[dict],
    fault: int,
    source: str,
) -> bool:
    """Send a batch to /observations. Each item has payload + sample_idx + simulationrun."""
    try:
        r = client.post(
            f"{url.rstrip('/')}/observations",
            json={
                "source": source,
                "true_fault_hidden": int(fault),
                "rows": [r["payload"] for r in rows_with_meta],
                "sample_indices": [r["sample_idx"] for r in rows_with_meta],
                "simulationruns": [r["simulationrun"] for r in rows_with_meta],
            },
            timeout=30.0,
        )
        if r.status_code != 200:
            print(f"[warn] {r.status_code} {r.text[:200]}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[error] post failed: {e}", file=sys.stderr)
        return False


def run_pattern(
    url: str,
    db_path: str,
    phases: list[Phase],
    interval_s: float,
    rows_per_tick: int,
    seed: int,
    *,
    start_sample: int = 1,
    run_idx: Optional[int] = None,
) -> int:
    if not os.path.exists(db_path):
        print(f"[error] DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    sent_total = 0
    try:
        with httpx.Client() as client:
            for phase_i, phase in enumerate(phases):
                cursor = _build_cursor(
                    conn, phase.fault, seed=seed + phase_i,
                    run_idx=run_idx if phase_i == 0 else None,
                    start_sample=start_sample if phase_i == 0 else 1,
                )
                if cursor is None:
                    print(f"[warn] no runs for fault={phase.fault}", file=sys.stderr)
                    continue
                deadline = time.time() + phase.duration_s
                while time.time() < deadline:
                    batch = _walk_one_tick(conn, cursor, rows_per_tick)
                    if not batch:
                        print(f"[warn] cursor exhausted for fault={phase.fault}",
                              file=sys.stderr)
                        break
                    ok = _post_observations(client, url, batch, phase.fault, "simulator")
                    if ok:
                        sent_total += len(batch)
                        last_idx = batch[-1]["sample_idx"]
                        print(f"[tick] fault={phase.fault} run={cursor.run_idx} "
                              f"sample_idx<={last_idx} n={len(batch)} total={sent_total}")
                    time.sleep(interval_s)
    finally:
        conn.close()
    print(f"[done] total observations sent: {sent_total}")
    return 0


def run_once(
    url: str,
    db_path: str,
    fault: int,
    rows: int,
    seed: int,
    *,
    start_sample: int = 1,
    run_idx: Optional[int] = None,
) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cursor = _build_cursor(
            conn, fault, seed=seed, run_idx=run_idx, start_sample=start_sample
        )
        if cursor is None:
            print(f"[error] no runs for fault={fault}", file=sys.stderr)
            return 1
        batch = _walk_one_tick(conn, cursor, rows)
    finally:
        conn.close()
    if not batch:
        print(f"[error] no rows produced for fault={fault}", file=sys.stderr)
        return 1
    with httpx.Client() as client:
        ok = _post_observations(client, url, batch, fault, "simulator-once")
    if ok:
        first = batch[0]["sample_idx"]
        last = batch[-1]["sample_idx"]
        print(f"[ok] sent {len(batch)} rows (fault={fault}, "
              f"run={cursor.run_idx}, sample {first}..{last})")
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
    p.add_argument("--start-sample", type=int, default=1,
                   help="Starting sample_idx within the first run (TEP fault onset = 161)")
    p.add_argument("--run-idx", type=int, default=None,
                   help="Specific simulationrun id (else random)")
    p.add_argument("--once", action="store_true",
                   help="Send a single batch and exit (uses --fault)")
    p.add_argument("--fault", type=int, default=4, help="Fault ID for --once mode")
    args = p.parse_args()

    if args.once:
        sys.exit(run_once(
            args.url, args.db, args.fault, args.rows, args.seed,
            start_sample=args.start_sample, run_idx=args.run_idx,
        ))
    phases = parse_pattern(args.pattern)
    sys.exit(run_pattern(
        args.url, args.db, phases, args.interval, args.rows, args.seed,
        start_sample=args.start_sample, run_idx=args.run_idx,
    ))


if __name__ == "__main__":
    main()
