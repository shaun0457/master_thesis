"""
Minimal extractor skeleton for X‑MAS metrics.

Reads events.jsonl and emits result.json fields aligned to schema/schema_result.json.
This is a starting point with simple, easily auditable transformations.

Usage:
  python analysis/scripts/extract_metrics.py \
    --events data/runs/<run_id>/events.jsonl \
    --out reports/runs/<run_id>/result.json \
    --schema schema/schema_result.json

Validation uses jsonschema if available; otherwise it will skip validation and print a warning.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections import defaultdict, Counter
from statistics import mean


def load_events(path: Path):
    import json
    events = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events


def freeman_out_centralization(edges: list[tuple[str, str]]):
    if not edges:
        return None
    out_deg = Counter([u for (u, v) in edges])
    nodes = set([u for (u, v) in edges] + [v for (u, v) in edges])
    n = len(nodes)
    if n < 3:
        return None
    kmax = max(out_deg.values()) if out_deg else 0
    num = sum((kmax - out_deg.get(node, 0)) for node in nodes)
    den = (n - 1) * (n - 2)
    return num / den if den > 0 else None


def normalized_entropy_partner(edges: list[tuple[str, str]]):
    if not edges:
        return None
    by_sender = defaultdict(list)
    for u, v in edges:
        by_sender[u].append(v)
    import math
    entropies = []
    for u, vs in by_sender.items():
        total = len(vs)
        if total == 0:
            continue
        counts = Counter(vs)
        ps = [c / total for c in counts.values()]
        h = -sum(p * math.log(p + 1e-12) for p in ps)
        m = math.log(len(counts)) if counts else 1.0
        entropies.append(h / m if m > 0 else 0.0)
    return mean(entropies) if entropies else None


def gini(xs: list[float]):
    n = len(xs)
    if n == 0:
        return None
    xs = sorted(xs)
    cum = 0
    for i, x in enumerate(xs, start=1):
        cum += i * x
    s = sum(xs)
    if s == 0:
        return 0.0
    return (2 * cum) / (n * s) - (n + 1) / n


def compute_signals(events: list[dict]):
    # Simple joins for bb_write/bb_read
    writes = [e for e in events if e.get("type") == "bb_write"]
    reads = [e for e in events if e.get("type") == "bb_read"]
    handoffs = [(e.get("actor"), e.get("to")) for e in events if e.get("type") in {"handoff", "address"} and e.get("to")]

    # Topology
    C = freeman_out_centralization(handoffs)
    H = normalized_entropy_partner(handoffs)

    # Contribution base for G: number of writes per agent
    contrib = Counter([w.get("actor") for w in writes])
    G = gini(list(contrib.values())) if contrib else None

    # Knowledge flow
    write_by_id = {w.get("id"): w for w in writes if w.get("id")}
    readers_by_write = defaultdict(set)
    first_read_ms = []
    owner_read_ms = []
    for r in reads:
        wid = r.get("ref") or r.get("write_id")
        if not wid or wid not in write_by_id:
            continue
        readers_by_write[wid].add(r.get("actor"))
        # delays
        tw = write_by_id[wid].get("time_ms")
        tr = r.get("time_ms")
        if isinstance(tw, (int, float)) and isinstance(tr, (int, float)):
            if r.get("actor") != write_by_id[wid].get("actor"):
                first_read_ms.append(max(0, tr - tw))
            else:
                owner_read_ms.append(max(0, tr - tw))

    total_writes = len(write_by_id)
    read_by_others = sum(1 for wid, readers in readers_by_write.items() if any(a != write_by_id[wid].get("actor") for a in readers))
    reuse_rate = (read_by_others / total_writes) if total_writes > 0 else 0.0
    orphan_write = ((total_writes - len(readers_by_write)) / total_writes) if total_writes > 0 else 0.0

    t_first_read_ms = mean(first_read_ms) if first_read_ms else None
    t_owner_read_ms = mean(owner_read_ms) if owner_read_ms else None

    return {
        "centralization_C": C,
        "handoff_entropy_H": H,
        "ownership_gini": G,
        "reuse_rate": reuse_rate,
        "orphan_write": orphan_write,
        "t_first_read_ms": t_first_read_ms,
        "t_owner_read_ms": t_owner_read_ms,
    }


def try_validate(obj: dict, schema_path: Path):
    try:
        import jsonschema
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(obj, schema)
        return True, None
    except Exception as e:
        return False, str(e)


def main():
    ap = argparse.ArgumentParser(description="Extract X‑MAS process/outcome signals to result.json")
    ap.add_argument("--events", type=Path, required=True, help="Path to events.jsonl")
    ap.add_argument("--out", type=Path, required=True, help="Output result.json path")
    ap.add_argument("--schema", type=Path, default=Path("schema/schema_result.json"), help="JSON Schema path")
    args = ap.parse_args()

    events = load_events(args.events)
    signals = compute_signals(events)

    result = {
        "schema_version": "1.0",
        "run_id": args.events.parent.name,
        "dataset_id": "[NEED_EVIDENCE]",
        "task_id": "[NEED_EVIDENCE]",
        "task_type": "[NEED_EVIDENCE]",
        "strategy": "[NEED_EVIDENCE]",
        "model": {"name": "[NEED_EVIDENCE]", "provider": "[NEED_EVIDENCE]", "version": "[NEED_EVIDENCE]"},
        "policy": {"temperature": 0.2, "max_tokens": 2048},
        "tools": [],
        "seed": 0,
        "process": signals,
        "outcome": {"success": 0, "final_quality_score": 0.0, "turn_count": 0, "tool_call_count": 0},
        "cost": {"tokens_total": 0},
        "timing": {"start_time": "[NEED_EVIDENCE]", "end_time": "[NEED_EVIDENCE]"},
        "provenance": {"git_commit": "[NEED_EVIDENCE]", "code_version": "[NEED_EVIDENCE]", "data_hash": "[NEED_EVIDENCE]"},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    ok, err = try_validate(result, args.schema)
    if ok:
        print(f"Wrote and validated: {args.out}")
    else:
        print(f"Wrote: {args.out}; validation skipped/failed: {err}")


if __name__ == "__main__":
    main()

