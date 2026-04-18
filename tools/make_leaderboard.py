#!/usr/bin/env python3
# tools/make_leaderboard.py
"""
Aggregate result.json records into a thesis-ready leaderboard.

Inputs (under --results_dir):
  - EITHER many .../result.json files
  - OR a single results.jsonl
Outputs (under --out):
  - results.parquet  (falls back to results.csv if pyarrow not available)
  - LEADERBOARD.md   (Task x Strategy macro view)
"""

import argparse, json, sys
from pathlib import Path
from typing import List, Dict, Any, Tuple

import math
import statistics as stats

try:
    import pandas as pd
except Exception as e:
    print("ERROR: pandas is required. Install with `pip install pandas`.", file=sys.stderr)
    raise

REQUIRED_TOP_LEVEL = [
    "run_id", "dataset_id", "task_type", "strategy",
    "model", "seed", "outcome"
]
# optional but helpful
OPTIONAL_SETS = {
    "cost": ["tokens_total"],
    "behavior": ["turn_count", "tool_call_count", "loop_count"]
}

def find_result_files(results_dir: Path) -> List[Path]:
    files = []
    # 1) results.jsonl (preferred single-file format)
    jsl = results_dir / "results.jsonl"
    if jsl.exists():
        files.append(jsl)
        return files
    # 2) any result.json under the directory
    for p in results_dir.rglob("result.json"):
        files.append(p)
    return files

def load_records(path: Path) -> List[Dict[str, Any]]:
    recs = []
    if path.suffix == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"WARNING: bad JSON line in {path}: {e}", file=sys.stderr)
    else:
        try:
            recs.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            print(f"WARNING: bad JSON file {path}: {e}", file=sys.stderr)
    return recs

def validate_minimal_schema(r: Dict[str, Any]) -> Tuple[bool, str]:
    for k in REQUIRED_TOP_LEVEL:
        if k not in r:
            return False, f"missing field: {k}"
    oc = r.get("outcome") or {}
    if not isinstance(oc.get("final_quality_score"), (int, float)):
        return False, "outcome.final_quality_score must be numeric"
    # nested optional checks do not hard-fail
    return True, ""

def to_rows(records: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for r in records:
        ok, why = validate_minimal_schema(r)
        if not ok:
            print(f"SKIP run {r.get('run_id','?')}: {why}", file=sys.stderr)
            continue
        row = {
            "run_id": r["run_id"],
            "dataset_id": r["dataset_id"],
            "task_type": r["task_type"],
            "strategy": r["strategy"],
            "model_name": (r.get("model") or {}).get("name", None),
            "model_provider": (r.get("model") or {}).get("provider", None),
            "model_version": (r.get("model") or {}).get("version", None),
            "seed": r["seed"],
            "final_quality_score": float((r.get("outcome") or {}).get("final_quality_score")),
        }
        # cost
        cost = r.get("cost") or {}
        row["tokens_total"] = cost.get("tokens_total", None)
        row["tokens_prompt"] = cost.get("tokens_prompt", None)
        row["tokens_completion"] = cost.get("tokens_completion", None)
        # outcome counts (turns/tools/loops)
        beh = r.get("outcome") or {}
        row["turn_count"] = beh.get("turn_count", None)
        row["tool_call_count"] = beh.get("tool_call_count", None)
        row["loop_count"] = beh.get("loop_count", None)

        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=[
            "run_id","dataset_id","task_type","strategy","model_name","model_provider","model_version",
            "seed","final_quality_score","tokens_total","tokens_prompt","tokens_completion",
            "turn_count","tool_call_count","loop_count"
        ])
    return pd.DataFrame(rows)

def ci95(series: List[float]) -> Tuple[float, float]:
    """
    Normal-approx 95% CI; bootstrap can be added later in run_models.py
    """
    n = len(series)
    if n == 0:
        return (math.nan, math.nan)
    mean = sum(series)/n
    if n == 1:
        return (mean, math.nan)
    sd = stats.pstdev(series) if n > 1 else 0.0
    se = sd / math.sqrt(n)
    lo = mean - 1.96*se
    hi = mean + 1.96*se
    return (lo, hi)

def efficiency_q_per_1k(mean_q: float, mean_tokens: float) -> float:
    if mean_tokens is None or mean_tokens == 0:
        return math.nan
    return float(mean_q) / (float(mean_tokens)/1000.0)

def make_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[
            "task_type","strategy","N","mean_quality","ci95_lo","ci95_hi",
            "mean_tokens","eff_q_per_1k"
        ])

    groups = []
    for (task, strat), g in df.groupby(["task_type","strategy"], dropna=False):
        qual = g["final_quality_score"].dropna().tolist()
        lo, hi = ci95(qual)
        mean_q = float(sum(qual)/len(qual)) if qual else math.nan
        tokens = g["tokens_total"].dropna().tolist()
        mean_tokens = float(sum(tokens)/len(tokens)) if tokens else math.nan
        eff = efficiency_q_per_1k(mean_q, mean_tokens)
        groups.append({
            "task_type": task,
            "strategy": strat,
            "N": int(len(g)),
            "mean_quality": round(mean_q, 4) if not math.isnan(mean_q) else math.nan,
            "ci95_lo": round(lo, 4) if not math.isnan(lo) else math.nan,
            "ci95_hi": round(hi, 4) if not math.isnan(hi) else math.nan,
            "mean_tokens": round(mean_tokens, 1) if mean_tokens == mean_tokens else math.nan,
            "eff_q_per_1k": round(eff, 4) if eff == eff else math.nan
        })
    lb = pd.DataFrame(groups).sort_values(["task_type","strategy"]).reset_index(drop=True)
    return lb

def write_outputs(df_all: pd.DataFrame, lb: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # table file
    parquet_path = out_dir / "results.parquet"
    csv_path = out_dir / "results.csv"
    try:
        df_all.to_parquet(parquet_path, index=False)
        results_path_str = str(parquet_path)
    except Exception:
        df_all.to_csv(csv_path, index=False)
        results_path_str = str(csv_path)

    # markdown leaderboard
    md = ["# Leaderboard (Task × Strategy)",
          "",
          f"- Source rows: **{len(df_all)}**",
          f"- Results table: `{results_path_str}`",
          ""]
    if lb.empty:
        md.append("_No records found._")
    else:
        # pretty table
        header = "| Task | Strategy | N | Mean Q | 95% CI | Mean Tokens | Eff(Q/1k) |"
        sep    = "|---|---:|---:|---:|---:|---:|---:|"
        md.append(header)
        md.append(sep)
        for _, r in lb.iterrows():
            ci = f"[{r['ci95_lo']}, {r['ci95_hi']}]" if r['ci95_lo'] == r['ci95_lo'] else "NA"
            md.append(f"| {r['task_type']} | {r['strategy']} | {r['N']} | {r['mean_quality']} | {ci} | {r['mean_tokens']} | {r['eff_q_per_1k']} |")
    (out_dir / "LEADERBOARD.md").write_text("\n".join(md), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results_dir", type=str, required=True, help="Directory containing result.json files or results.jsonl")
    ap.add_argument("--out", type=str, required=True, help="Output directory for leaderboard files")
    args = ap.parse_args()

    results_dir = Path(args.results_dir)
    out_dir = Path(args.out)

    files = find_result_files(results_dir)
    if not files:
        print(f"ERROR: No result.json or results.jsonl found under {results_dir}", file=sys.stderr)
        sys.exit(1)

    records = []
    for f in files:
        records.extend(load_records(f))

    df = to_rows(records)
    lb = make_leaderboard(df)
    write_outputs(df, lb, out_dir)
    print(f"[OK] Wrote leaderboard to: {out_dir}")

if __name__ == "__main__":
    main()
