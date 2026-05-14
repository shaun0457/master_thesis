"""Generate an unlabeled observation by sampling rows from tep_combined.db.

Used for one-shot diagnosis testing. The faultnumber and simulationrun columns
are dropped so the MAS receives a truly unlabeled observation.

Usage:
    python scripts/simulate_observation.py --fault 4 --rows 50 --out datasets/obs_demo.parquet
    python scripts/simulate_observation.py --fault 4 --seed 42
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BASE, "tep_combined.db")
DEFAULT_OUT_DIR = os.path.join(BASE, "datasets", "observations")

DROP_COLS = {"faultnumber", "simulationrun"}


def sample_observation(
    db_path: str,
    fault: int,
    rows: int,
    seed: int,
    out_path: str,
) -> int:
    """Sample N consecutive rows for a fault, strip label, write parquet.

    Returns the true fault label (echoed for ground truth tracking, never persisted).
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Source DB not found: {db_path}")

    conn = sqlite3.connect(db_path)
    runs = pd.read_sql_query(
        "SELECT DISTINCT simulationrun FROM process_data WHERE faultnumber = ? ORDER BY simulationrun",
        conn,
        params=(fault,),
    )["simulationrun"].tolist()
    if not runs:
        conn.close()
        raise RuntimeError(f"No rows found for fault={fault}")

    rng = pd.Series(runs).sample(n=1, random_state=seed).iloc[0]
    df = pd.read_sql_query(
        "SELECT * FROM process_data WHERE faultnumber = ? AND simulationrun = ? "
        "ORDER BY sample LIMIT ?",
        conn,
        params=(fault, int(rng), rows),
    )
    conn.close()

    if df.empty:
        raise RuntimeError(f"No rows for fault={fault} run={rng}")

    keep_cols = [c for c in df.columns if c not in DROP_COLS]
    df_unlabeled = df[keep_cols].copy()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df_unlabeled.to_parquet(out_path, index=False)
    return int(fault)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--fault", type=int, required=True, help="Fault ID (0..20)")
    p.add_argument("--rows", type=int, default=50, help="Rows to sample (default 50)")
    p.add_argument("--seed", type=int, default=42, help="RNG seed (default 42)")
    p.add_argument("--db", type=str, default=DEFAULT_DB, help="Source DB path")
    p.add_argument("--out", type=str, default=None, help="Output parquet path")
    args = p.parse_args()

    out = args.out or os.path.join(DEFAULT_OUT_DIR, f"obs_fault{args.fault}_seed{args.seed}.parquet")
    try:
        true_label = sample_observation(args.db, args.fault, args.rows, args.seed, out)
        print(f"[ok] wrote {args.rows} unlabeled rows to {out}")
        print(f"[ground-truth] true_fault={true_label} (not persisted in parquet)")
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
