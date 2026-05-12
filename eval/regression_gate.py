"""Regression gate for golden eval results — T3-P10.

Reads eval/results.json and enforces:
  - keyword_hit_rate >= min_keyword_hits / len(keywords) for each question
  - DS questions: ds_verdict in ("ok", None) — None means DS wasn't exercised
  - ME questions: me_citation_coverage >= 0.3 OR None (not exercised)
  - Overall pass rate >= 60% of questions

Exit code 0 = all gates passed.
Exit code 1 = one or more gates failed (prints which).

Usage:
    python eval/regression_gate.py [--results eval/results.json]
"""
import sys
import json
import argparse
from pathlib import Path

RESULTS_DEFAULT = Path(__file__).parent / "results.json"
GOLDEN_DEFAULT  = Path(__file__).parent / "golden_qa.json"

PASS_RATE_THRESHOLD        = 0.60  # 60% of questions must hit keywords
ME_CITATION_MIN            = 0.30  # me_citation_coverage must be >= this (if reported)
DS_VERDICT_FAIL_VALUES     = {"error", "fail", "failed"}  # these count as DS failure


def load(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8"))


def gate(results: list, golden: list) -> tuple[bool, list[str]]:
    golden_map = {item["id"]: item for item in golden}
    failures = []
    keyword_passes = 0

    for r in results:
        qid = r["id"]
        item = golden_map.get(qid, {})
        expected_kws = item.get("expected_keywords", [])
        min_hits = item.get("min_keyword_hits", 1)
        n_kw = max(len(expected_kws), 1)

        # Gate 1: keyword threshold
        hit_rate = r.get("keyword_hit_rate", 0.0)
        required_rate = min_hits / n_kw
        if hit_rate >= required_rate:
            keyword_passes += 1
        else:
            failures.append(
                f"[{qid}] keyword_hit_rate {hit_rate:.2f} < required {required_rate:.2f}"
            )

        # Gate 2: DS verdict (only if ds_verdict is reported and question is DS-path)
        if "DS" in item.get("agent_path", []):
            verdict = r.get("ds_verdict")
            if isinstance(verdict, str) and verdict.lower() in DS_VERDICT_FAIL_VALUES:
                failures.append(f"[{qid}] ds_verdict='{verdict}' is a failure value")

        # Gate 3: ME citation coverage (only if reported)
        if "ME" in item.get("agent_path", []):
            cov = r.get("me_citation_coverage")
            if cov is not None and cov < ME_CITATION_MIN:
                failures.append(
                    f"[{qid}] me_citation_coverage {cov:.2f} < {ME_CITATION_MIN}"
                )

    # Gate 4: overall pass rate
    pass_rate = keyword_passes / max(len(results), 1)
    if pass_rate < PASS_RATE_THRESHOLD:
        failures.append(
            f"Overall keyword pass rate {pass_rate:.0%} < {PASS_RATE_THRESHOLD:.0%} threshold"
        )

    return len(failures) == 0, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default=str(RESULTS_DEFAULT))
    parser.add_argument("--golden",  default=str(GOLDEN_DEFAULT))
    args = parser.parse_args()

    results_path = Path(args.results)
    golden_path  = Path(args.golden)

    if not results_path.exists():
        print(f"ERROR: results file not found: {results_path}")
        print("Run `python eval/run_eval.py --dry-run` first.")
        sys.exit(2)

    results = load(results_path)
    golden  = load(golden_path)

    ok, failures = gate(results, golden)

    if ok:
        print(f"[PASS] Regression gate: all checks passed ({len(results)} questions)")
        sys.exit(0)
    else:
        print(f"[FAIL] Regression gate: {len(failures)} issue(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
