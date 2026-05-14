"""Compute baseline statistics from normal operation data (faultnumber=0).

Output: datasets/baseline_stats.parquet
Schema: one row per sensor with mean, std, p01, p50, p99, n.

Usage:
    python scripts/build_baseline_stats.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DB = os.path.join(BASE, "tep_combined.db")
OUT_DIR = os.path.join(BASE, "datasets")
OUT_PATH = os.path.join(OUT_DIR, "baseline_stats.parquet")

SENSOR_PREFIXES = ("xmeas_", "xmv_")


def build(db_path: str = SRC_DB, out_path: str = OUT_PATH) -> str:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Source DB not found: {db_path}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    t0 = time.time()

    conn = sqlite3.connect(db_path)
    cols_info = conn.execute("PRAGMA table_info(process_data)").fetchall()
    all_cols = [c[1] for c in cols_info]
    sensor_cols = [c for c in all_cols if c.startswith(SENSOR_PREFIXES)]
    if not sensor_cols:
        raise RuntimeError("No xmeas_/xmv_ columns found in process_data")

    select_list = ", ".join(sensor_cols)
    df = pd.read_sql_query(
        f"SELECT {select_list} FROM process_data WHERE faultnumber = 0",
        conn,
    )
    conn.close()

    if df.empty:
        raise RuntimeError("No baseline (faultnumber=0) rows found")

    rows = []
    for col in sensor_cols:
        arr = df[col].to_numpy(dtype=float)
        rows.append({
            "sensor": col,
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr, ddof=1)),
            "p01": float(np.percentile(arr, 1)),
            "p50": float(np.percentile(arr, 50)),
            "p99": float(np.percentile(arr, 99)),
            "n": int(arr.shape[0]),
        })

    stats = pd.DataFrame(rows)
    stats.to_parquet(out_path, index=False)

    elapsed = time.time() - t0
    print(f"[ok] {len(rows)} sensors → {out_path}  ({elapsed:.1f}s, n={stats['n'].iloc[0]} baseline rows)")
    return out_path


if __name__ == "__main__":
    try:
        build()
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
