#!/usr/bin/env python3
# analysis/run_models.py
"""
Pre-registered analysis:
1) Logistic GLM for success ~ protocol + C + C^2 + reuse + orphan + t_owner_read + task_type FE
2) Simple mediation (bootstrap) for protocol -> mediator -> success

Notes:
- This starter version uses statsmodels if available; otherwise falls back to pandas ops and flags gaps.
- Cluster-robust SE by task_type to approximate mixed-effects robustness without full GLMM.
"""

import argparse, sys, math, random
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import pandas as pd

# Optional statsmodels
_HAS_SM = True
try:
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
except Exception:
    _HAS_SM = False

def load_results(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        try:
            return pd.read_parquet(path)
        except Exception:
            # fallback if parquet engine missing
            return pd.read_csv(path.with_suffix(".csv"))
    elif path.suffix == ".csv":
        return pd.read_csv(path)
    else:
        raise ValueError("Unsupported results format. Use .parquet or .csv")

def add_success_flag(df: pd.DataFrame, thr: float) -> pd.DataFrame:
    df = df.copy()
    if "final_quality_score" not in df.columns:
        raise ValueError("final_quality_score missing.")
    df["success"] = (df["final_quality_score"] >= thr).astype(int)
    return df

def ensure_columns(df: pd.DataFrame, cols: List[str]) -> List[str]:
    missing = [c for c in cols if c not in df.columns]
    return missing

def logistic_glm(df: pd.DataFrame, out_dir: Path) -> None:
    if not _HAS_SM:
        (out_dir / "model_glm_success.csv").write_text("statsmodels not installed; cannot fit GLM.\n", encoding="utf-8")
        print("WARNING: statsmodels not available; wrote a placeholder file.", file=sys.stderr)
        return

    # Build design with dummies for protocol and task_type
    # We expect mechanism columns if present; otherwise they get dropped gracefully.
    candidates = ["C", "H", "reuse", "orphan", "t_owner_read"]
    available = [c for c in candidates if c in df.columns]
    squared = []
    if "C" in available:
        df["C2"] = df["C"]**2
        squared = ["C2"]

    # categorical encodings
    for cat in ["strategy", "task_type"]:
        if cat in df.columns:
            df[cat] = df[cat].astype("category")

    # formula
    rhs_parts = []
    if "strategy" in df.columns:
        rhs_parts.append("C(strategy)")
    if available:
        rhs_parts += available
    if squared:
        rhs_parts += squared
    if "task_type" in df.columns:
        rhs_parts.append("C(task_type)")
    rhs = " + ".join(rhs_parts) if rhs_parts else "1"

    formula = f"success ~ {rhs}"
    # Cluster-robust SE by task_type if present
    cov_kw = {}
    if "task_type" in df.columns:
        cov_kw = {"cov_type": "cluster", "cov_kwds": {"groups": df["task_type"]}}

    model = smf.glm(formula=formula, data=df, family=sm.families.Binomial())
    res = model.fit(**cov_kw) if cov_kw else model.fit()

    # Export coefficient table
    coefs = res.summary2().tables[1]
    coefs.to_csv(out_dir / "model_glm_success.csv")
    # Save a quick text summary too
    (out_dir / "model_glm_success.txt").write_text(str(res.summary()), encoding="utf-8")

def bootstrap_mediation(df: pd.DataFrame, mediator: str, out_dir: Path, n_boot: int = 2000, seed: int = 123) -> None:
    """
    Baron-Kenny style (modernized) simple mediation with binary outcome (logit) and continuous mediator.
    protocol is proxied by strategy (1 vs baseline) for illustration.
    """
    if mediator not in df.columns:
        (out_dir / f"mediation_{mediator}.csv").write_text(f"mediator {mediator} missing.\n", encoding="utf-8")
        return
    if "strategy" not in df.columns:
        (out_dir / f"mediation_{mediator}.csv").write_text("strategy column missing.\n", encoding="utf-8")
        return

    # Make a binary contrast: pick baseline (alphabetical first) vs focal (second)
    # You can pass an explicit contrast later if you want.
    levels = sorted(df["strategy"].astype(str).unique())
    if len(levels) < 2:
        (out_dir / f"mediation_{mediator}.csv").write_text("Need at least two strategies for mediation.\n", encoding="utf-8")
        return
    base, focal = levels[0], levels[1]
    d = df.copy()
    d["protocol_bin"] = (d["strategy"].astype(str) == focal).astype(int)

    rng = np.random.default_rng(seed)

    # Helper regressions using statsmodels if available; otherwise numpy fallbacks
    def fit_logit(y, X):
        if _HAS_SM:
            Xc = sm.add_constant(X, has_constant="add")
            m = sm.Logit(y, Xc).fit(disp=False)
            return m.params, m
        # fallback: approximate with OLS on logit-transformed y clipped (very rough)
        y2 = np.clip(y, 1e-6, 1 - 1e-6)
        z = np.log(y2 / (1 - y2))
        Xc = np.column_stack([np.ones(len(X)), X])
        beta = np.linalg.pinv(Xc).dot(z)
        return pd.Series(beta, index=["const"] + (X.columns.tolist() if hasattr(X, "columns") else [f"x{i}" for i in range(X.shape[1])])), None

    def fit_ols(y, X):
        if _HAS_SM:
            Xc = sm.add_constant(X, has_constant="add")
            m = sm.OLS(y, Xc).fit()
            return m.params, m
        Xc = np.column_stack([np.ones(len(X)), X])
        beta = np.linalg.pinv(Xc).dot(y)
        return pd.Series(beta, index=["const"] + (X.columns.tolist() if hasattr(X, "columns") else [f"x{i}" for i in range(X.shape[1])])), None

    # a path: protocol -> mediator
    X_a = pd.DataFrame({"protocol": d["protocol_bin"]})
    a_params, _ = fit_ols(d[mediator].astype(float), X_a)

    # b & c' paths: mediator + protocol -> success (logit)
    X_b = pd.DataFrame({"protocol": d["protocol_bin"], mediator: d[mediator].astype(float)})
    b_params, _ = fit_logit(d["success"].astype(int), X_b)

    a = float(a_params.get("protocol", np.nan))
    b = float(b_params.get(mediator, np.nan))
    cprime = float(b_params.get("protocol", np.nan))
    indirect = a * b

    # bootstrap CI for indirect effect
    inds = []
    n = len(d)
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        s = d.iloc[idx]
        Xa = pd.DataFrame({"protocol": s["protocol_bin"]})
        ap, _ = fit_ols(s[mediator].astype(float), Xa)
        Xb = pd.DataFrame({"protocol": s["protocol_bin"], mediator: s[mediator].astype(float)})
        bp, _ = fit_logit(s["success"].astype(int), Xb)
        a_b = float(ap.get("protocol", np.nan)) * float(bp.get(mediator, np.nan))
        inds.append(a_b)
    inds = np.array(inds)
    lo, hi = np.percentile(inds[~np.isnan(inds)], [2.5, 97.5])

    out = pd.DataFrame([{
        "baseline_strategy": base,
        "focal_strategy": focal,
        "mediator": mediator,
        "a": a,
        "b": b,
        "c_prime": cprime,
        "indirect": indirect,
        "indirect_ci_lo": lo,
        "indirect_ci_hi": hi,
        "n_boot": n_boot
    }])
    out.to_csv(out_dir / f"mediation_{mediator}.csv", index=False)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=str, required=True, help="Path to leaderboard/results.parquet (or .csv)")
    ap.add_argument("--out", type=str, required=True, help="Output directory for model tables/figures")
    ap.add_argument("--success_threshold", type=float, default=0.75, help="Threshold to binarize final_quality_score into success")
    ap.add_argument("--mediator", type=str, default="reuse", help="Mediator column name (e.g., reuse, H, orphan, t_owner_read)")
    ap.add_argument("--bootstrap", type=int, default=2000, help="Number of bootstrap resamples for mediation CI")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_results(Path(args.results))
    df = add_success_flag(df, thr=args.success_threshold)

    # Inform about missing columns (we don't fail hard; we record gaps)
    needed = ["strategy", "task_type"]
    mech = ["C","H","reuse","orphan","t_owner_read"]
    missing_basic = [c for c in needed if c not in df.columns]
    missing_mech  = [c for c in mech if c not in df.columns]

    with open(out_dir / "model_inputs_report.txt", "w", encoding="utf-8") as f:
        f.write("Model Inputs Report\n")
        f.write("===================\n\n")
        f.write(f"Loaded rows: {len(df)}\n")
        f.write(f"Columns present: {list(df.columns)}\n\n")
        if missing_basic:
            f.write(f"[MISSING BASIC COLS] {missing_basic}\n")
        if missing_mech:
            f.write(f"[MISSING MECHANISM COLS] {missing_mech}\n")
        f.write("\nNotes: Missing mechanism columns reduce model scope; results remain reproducible.\n")

    logistic_glm(df, out_dir)
    # mediation on requested mediator if available
    bootstrap_mediation(df, mediator=args.mediator, out_dir=out_dir, n_boot=args.bootstrap)

    print(f"[OK] Analysis outputs written to: {out_dir}")

if __name__ == "__main__":
    main()

