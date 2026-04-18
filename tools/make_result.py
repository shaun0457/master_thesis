#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
make_result.py
Aggregate per-run logs -> result.json that conforms to schema_result.json.

Usage:
  python tools/make_result.py --runs_dir ./data/runs --out_dir ./data/reports --schema ./schema/schema_result.json

What it computes (per run):
- outcome: final_quality_score? (if present), counts (turns, tool_call_count, loop_count, blackboard_writes, recovery_events, success?)
- process: centralization_C, ownership_gini, handoff_entropy_H, t_first_read_ms, t_owner_read_ms,
           reuse_rate, orphan_write, read_after_k{k1,k2,k3}, readers_mean,
           topic_drift{mean_D, slope_beta, embed_model, goal_embed_ref, turns_sampled},
           policy_adherence{A, V, violation_counts}, event_counts{write_events_n, read_events_n, compliance_events_n}
- cost: tokens_total (from run.turn.v2 tokens_total if present; else sum placeholders)
- timing: start/end/time_to_first_action_ms (from earliest/latest ts)
- provenance: optionally from meta.json or inferred

Notes:
- We assume ISO8601 timestamps in events.
- We avoid heavyweight deps; jsonschema is optional.
"""

import argparse
import json
import os
import glob
from collections import defaultdict, Counter
from datetime import datetime, timezone
from math import log
from statistics import mean

# ---------- Helpers ----------

ISO_FORMATS = ("%Y-%m-%dT%H:%M:%S.%fZ",
               "%Y-%m-%dT%H:%M:%SZ",
               "%Y-%m-%dT%H:%M:%S.%f%z",
               "%Y-%m-%dT%H:%M:%S%z")

def parse_iso(ts):
    if not ts:
        return None
    for fmt in ISO_FORMATS:
        try:
            dt = datetime.strptime(ts, fmt)
            # normalize to UTC
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    # last resort: try fromisoformat (py3.11+)
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def safe_mean(seq):
    seq = [x for x in seq if x is not None]
    return sum(seq)/len(seq) if seq else 0.0

def gini(values):
    xs = [v for v in values if v is not None]
    n = len(xs)
    if n == 0:
        return 0.0
    mu = sum(xs)/n
    if mu == 0:
        return 0.0
    diff_sum = 0.0
    for i in range(n):
        for j in range(n):
            diff_sum += abs(xs[i]-xs[j])
    return diff_sum / (2 * n * n * mu)

def freeman_centralization(degrees):
    """
    Freeman centralization C = sum_i (k* - k_i) / max sum_i (k* - k_i)
    For directed graphs we can use out-degree or in-degree; we default to out-degree.
    degrees: dict[node] -> degree
    """
    if not degrees:
        return 0.0
    k_star = max(degrees.values())
    num = sum((k_star - k_i) for k_i in degrees.values())
    # Maximum possible sum for a graph with N nodes is (N-1)*(N-2) for out-degree centralization on a star
    N = len(degrees)
    if N <= 2:
        # define trivial cases
        return 0.0
    denom = (N - 1) * (N - 2)
    if denom <= 0:
        return 0.0
    return min(max(num / denom, 0.0), 1.0)

def detect_cycles(edges):
    """
    Detect cycles in a directed graph using DFS.
    Returns the count of back edges (cyclic paths).

    Definition per glossary.md §4.1:
    L = (# cyclic paths) / (# total paths)

    This implementation counts back edges during DFS traversal,
    where a back edge indicates a cycle in the graph.

    Args:
        edges: list of (src, dst) tuples representing directed edges

    Returns:
        int: number of back edges (cyclic paths) detected
    """
    if not edges:
        return 0

    # Build adjacency list
    graph = defaultdict(list)
    for src, dst in edges:
        graph[src].append(dst)

    # DFS state tracking
    visited = set()      # Fully processed nodes
    rec_stack = set()    # Nodes in current recursion stack
    cycle_count = 0      # Count of back edges (cycles)

    def dfs(node):
        nonlocal cycle_count
        visited.add(node)
        rec_stack.add(node)

        for neighbor in graph[node]:
            if neighbor in rec_stack:
                # Back edge found - this creates a cycle
                cycle_count += 1
            elif neighbor not in visited:
                dfs(neighbor)

        rec_stack.remove(node)

    # Visit all nodes (handle disconnected components)
    all_nodes = set(graph.keys()) | set(dst for _, dst in edges)
    for node in all_nodes:
        if node not in visited:
            dfs(node)

    return cycle_count

def entropy(p_list):
    eps = 1e-12
    ps = [p for p in p_list if p > 0]
    if not ps:
        return 0.0
    return -sum(p * log(p + eps) for p in ps)

def ols_slope(x, y):
    # simple OLS slope beta for y = a + beta x
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    x_bar = sum(x) / len(x)
    y_bar = sum(y) / len(y)
    num = sum((xi - x_bar) * (yi - y_bar) for xi, yi in zip(x, y))
    den = sum((xi - x_bar) ** 2 for xi in x)
    if den == 0:
        return 0.0
    return num / den

def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def try_load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_jsonl(path):
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    # skip malformed
                    continue
    except FileNotFoundError:
        pass
    return events

# ---------- Aggregation per run ----------

def aggregate_run(run_dir):
    # Local paths (convention translating bb://logs/turns to local)
    turns_dir = os.path.join(run_dir, "logs", "turns")
    turn_files = sorted(glob.glob(os.path.join(turns_dir, "*.jsonl")),
                        key=lambda p: int(os.path.splitext(os.path.basename(p))[0]) if os.path.splitext(os.path.basename(p))[0].isdigit() else 10**9)

    all_events = []
    for tf in turn_files:
        all_events.extend(load_jsonl(tf))

    # Also load standalone event files from run root (BB events, reads, router events)
    # These files are written by event_writer.py to the run root directory
    for schema_file in ["run.turn.v2.jsonl", "bb.write.v1.jsonl", "run.read.v1.jsonl", "router.event.v2.jsonl", "run.compliance.v1.jsonl"]:
        path = os.path.join(run_dir, schema_file)
        if os.path.exists(path):
            all_events.extend(load_jsonl(path))

    # If no events, return None
    if not all_events:
        return None, {"warn": "no_events"}

    # Buckets
    write_events = []      # run.turn.v1 or run.turn.v2 (we treat both as "write" if event authored content)
    read_events = []       # run.read.v1
    compliance_events = [] # run.compliance.v1
    ack_events = []        # bb.ack.v1 owner_read_ack
    failures = []          # run.failure.v1
    recoveries = []        # run.recovery.v1

    # For edges
    # We'll construct handoff edges from (agent -> target) using run.turn.v2 action where sensible.
    # For PTOW centralization, supervisor -> (DE|DS|ME) dominate.
    edges = []            # list of (src, dst) excluding self-loops
    out_degree = Counter()
    self_loops = Counter()  # Track self-loops per role (agent -> agent)
    # For ownership series
    owners_by_turn = {}

    # For reuse/orphan: artifact writes & reads
    # We expect write events to include refs_out (artifacts). read events include artifact
    wrote_artifacts = {}    # artifact -> timestamp (first write)
    writers = {}            # artifact -> agent
    artifact_reads = defaultdict(list)  # artifact -> list of (reader, ts)

    # TDI per turn
    tdi_by_turn = {}   # turn_index -> drift_D
    tdi_model = None
    goal_embed_ref = None

    # tokens, timing
    tokens_total = 0
    tokens_prompt = 0
    tokens_completion = 0
    start_ts = None
    end_ts = None
    first_action_ts = None

    # policy adherence
    violation_counts = Counter()
    eligible_n = 0
    violation_n = 0

    # Various counters
    tool_call_count = 0
    blackboard_writes = 0
    loop_count = 0
    recovery_events_n = 0
    turn_count = 0

    # Metadata inference
    run_id = os.path.basename(run_dir.rstrip("/\\"))
    dataset_id = None
    task_type = None
    strategy = None
    model_name = None
    model_provider = None
    model_version = None
    seed = None
    prompt_version = None
    policy_temperature = None
    policy_max_tokens = None

    # Try load run context for fixed metadata
    ctx = try_load_json(os.path.join(run_dir, "context.json")) or {}
    if ctx:
        dataset_id = ctx.get("dataset_id") or dataset_id
        task_type = ctx.get("task_type") or task_type
        seed = ctx.get("seed") or seed
        # map protocol id to schema enum where possible
        proto = (ctx.get("protocol_id") or "").lower()
        if proto.startswith("ptow") or "planner" in proto:
            strategy = "PlannerWorker"
        elif proto.startswith("debate"):
            strategy = "Debate"
        elif proto.startswith("delphi"):
            strategy = "Delphi"
        # providers -> model/policy
        prov = (ctx.get("providers") or {}).get("llm") or {}
        model_provider = prov.get("provider") or model_provider
        model_name = prov.get("name") or model_name
        model_version = prov.get("version") or model_version
        policy_temperature = prov.get("temperature", policy_temperature)
        policy_max_tokens = prov.get("max_output_tokens", policy_max_tokens)

    def update_timing(ts_str):
        nonlocal start_ts, end_ts, first_action_ts
        dt = parse_iso(ts_str)
        if not dt:
            return
        if start_ts is None or dt < start_ts:
            start_ts = dt
        if end_ts is None or dt > end_ts:
            end_ts = dt
        if first_action_ts is None:
            first_action_ts = dt

    for ev in all_events:
        schema = ev.get("schema", "")
        ts = ev.get("ts") or ev.get("timestamp")
        update_timing(ts)

        # Metadata gleaning
        if model_name is None:
            model_name = (ev.get("model") or ev.get("model_name") or
                          (ev.get("provenance", {}) or {}).get("model"))
        if model_provider is None:
            mp = ev.get("model_provider") or ((ev.get("model") or {}).get("provider") if isinstance(ev.get("model"), dict) else None)
            if mp:
                model_provider = mp
        if model_version is None:
            mv = ((ev.get("model") or {}).get("version") if isinstance(ev.get("model"), dict) else None)
            if mv:
                model_version = mv
        if strategy is None:
            strategy = ev.get("strategy") or ((ev.get("protocol_state") or {}).get("active"))
        if task_type is None:
            task_type = ev.get("task_type")
        if dataset_id is None:
            dataset_id = ev.get("dataset_id")
        if seed is None:
            seed = ev.get("seed")
        if prompt_version is None:
            prompt_version = ev.get("prompt_version") or ((ev.get("provenance") or {}).get("prompt_version"))

        # TDI gather
        if schema.startswith("run.turn."):
            turn_index = ev.get("turn_index") or ev.get("turn_id")
            mtrace = ev.get("metrics_trace") or {}
            tdi = mtrace.get("tdi") or {}
            if "drift_D" in tdi:
                try:
                    tdi_by_turn[int(turn_index)] = float(tdi["drift_D"])
                except Exception:
                    pass
            if tdi and tdi_model is None:
                tdi_model = tdi.get("embed_model")
            if tdi and goal_embed_ref is None:
                goal_embed_ref = tdi.get("user_goal_ref")

        # Tokens (optional fields)
        if "tokens_total" in ev:
            try:
                tokens_total += int(ev["tokens_total"])
            except Exception:
                pass

        # Classify & collect
        if schema.startswith("run.turn."):
            turn_count += 1
            write_events.append(ev)
            # tool calls?
            if ev.get("event_type") == "tool_call" or (ev.get("action", {}).get("type") == "tool_call"):
                tool_call_count += 1
            # blackboard writes signaled by blackboard_refs (per run.turn.v2 schema)
            refs_out = ev.get("blackboard_refs") or []
            if refs_out:
                blackboard_writes += 1
                for art in refs_out:
                    wrote_artifacts.setdefault(art, ts)
                    writers.setdefault(art, ev.get("agent") or ev.get("role"))
            # owners for latency and centralization
            agent = ev.get("agent") or ev.get("role")
            action_obj = ev.get("action") or {}
            target = action_obj.get("target")
            # Build edges heuristically:
            # - If supervisor delegates or plans to worker, add edge agent->target
            # - Else if 'addressed_to' exists, edge agent->addressed_to
            # - Self-loops (agent->agent) tracked separately
            dst = target or ev.get("addressed_to")
            if agent and dst and isinstance(dst, str) and dst.lower() != "null":
                agent_str = str(agent).lower()
                dst_str = str(dst).lower()

                if agent_str == dst_str:
                    # Self-loop: agent continues processing
                    self_loops[agent_str] += 1
                else:
                    # Delegation edge: agent hands off to another
                    edges.append((agent_str, dst_str))
                    out_degree[agent_str] += 1
            # ownership trace (for single-active-owner model)
            ownership = (ev.get("metrics_trace") or {}).get("ownership") or {}
            curr_owner = ownership.get("owner")
            if turn_index is not None and curr_owner:
                owners_by_turn[int(turn_index)] = curr_owner

        elif schema == "run.read.v1":
            read_events.append(ev)
            art = ev.get("artifact")
            if art:
                artifact_reads[art].append((ev.get("reader_role"), ts))

        elif schema == "run.compliance.v1":
            compliance_events.append(ev)
            eligible = ev.get("eligible")
            violation = ev.get("violation")
            if eligible is True:
                eligible_n += 1
                if violation is True:
                    violation_n += 1
                    rule_id = ev.get("rule_id") or "unspecified"
                    violation_counts[rule_id] += 1

        elif schema == "bb.ack.v1":
            ack_events.append(ev)

        elif schema == "run.failure.v1":
            failures.append(ev)
            if ev.get("failure_type") == "F-LOOP":
                loop_count += 1

        elif schema == "run.recovery.v1":
            recoveries.append(ev)

    # Calculate TDI
    if tdi_by_turn:
        xs = sorted(tdi_by_turn.keys())
        ys = [tdi_by_turn[i] for i in xs]
        mean_D = safe_mean(ys)
        slope_beta = ols_slope(xs, ys)
        turns_sampled = len(xs)
    else:
        mean_D, slope_beta, turns_sampled = 0.0, 0.0, 0

    # Policy adherence
    if eligible_n > 0:
        V = violation_n / float(eligible_n)
    else:
        V = 0.0
    A = max(0.0, min(1.0, 1.0 - V))

    # Event counters
    event_counts = {
        "write_events_n": len(write_events),
        "read_events_n": len(read_events),
        "compliance_events_n": len(compliance_events)
    }

    # Reuse / Orphan / readers_mean / read_after_k
    # Define "write" units by artifacts in refs_out; consider read if any run.read.v1 refers to it
    artifacts = list(wrote_artifacts.keys())
    if artifacts:
        read_flags = []
        readers_counts = []
        first_read_delays = []  # ms
        for art in artifacts:
            w_ts = parse_iso(wrote_artifacts[art])
            reads = artifact_reads.get(art, [])
            read_flags.append(1 if reads else 0)
            # distinct readers
            readers = set(r for r, _ in reads if r)
            readers_counts.append(len(readers))
            # first read latency
            if w_ts and reads:
                fr_ts = min((parse_iso(t2) for _, t2 in reads if parse_iso(t2)), default=None)
                if fr_ts:
                    first_read_delays.append((fr_ts - w_ts).total_seconds() * 1000.0)
        reuse_rate = sum(read_flags) / len(artifacts) if artifacts else 0.0
        orphan_write = 1.0 - reuse_rate
        readers_mean = safe_mean(readers_counts)
        t_first_read_ms = safe_mean(first_read_delays)
    else:
        reuse_rate = orphan_write = readers_mean = 0.0
        t_first_read_ms = 0.0

    # t_owner_read_ms via ack_events (owner_read_ack)
    owner_read_delays = []
    # We approximate by matching plan_step_id write time with first ack for same step
    # If bb.plan.v1 is stored in refs_out we would need to map plan_step_id -> write ts.
    # Heuristic: use run.turn events that include "plan_step_id" in refs_out path name p_<n>
    # Fallback: use first_action_ts as write baseline if unknown.
    plan_write_ts_by_id = {}
    for ev in write_events:
        # Try to infer plan_step_id from refs_out like bb://plans/<run>/p_<n>.json
        for r in ev.get("refs_out") or []:
            # crude parse
            if "/p_" in r:
                pid = r.split("/p_")[-1].split(".")[0]
                if pid and ev.get("ts"):
                    plan_write_ts_by_id.setdefault(f"p_{pid}", parse_iso(ev["ts"]))
    for ack in ack_events:
        if ack.get("ack_type") == "owner_read_ack":
            pid = ack.get("plan_step_id")
            ack_ts = parse_iso(ack.get("ts"))
            w_ts = plan_write_ts_by_id.get(pid) or first_action_ts
            if ack_ts and w_ts:
                owner_read_delays.append((ack_ts - w_ts).total_seconds() * 1000.0)
    t_owner_read_ms = safe_mean(owner_read_delays)

    # Handoff entropy H: based on edges distribution of destination nodes
    if edges:
        dst_counts = Counter(dst for _, dst in edges)
        total_edges = sum(dst_counts.values())
        ps = [c / total_edges for c in dst_counts.values()] if total_edges > 0 else []
        H = entropy(ps)
    else:
        H = 0.0

    # Centralization C: use out-degree centralization from edges
    C = freeman_centralization(out_degree)

    # Ownership inequality Gini: distribute "message/tool workload" by agent ~ approximate via out_degree or authored writes
    workload = Counter()
    for ev in write_events:
        agent = ev.get("agent") or ev.get("role")
        if agent:
            workload[agent] += 1
    G = gini(list(workload.values()))

    # Loop density L: cyclic paths / total paths (per glossary.md §4.1)
    # This is a primary indicator of instability (RQ2) and core mediator in RQ3
    cyclic_paths = detect_cycles(edges)
    total_paths = len(edges) if edges else 0
    loop_density = cyclic_paths / total_paths if total_paths > 0 else 0.0

    # INTERACTION GRAPH (P1-1): Build edges from BB read-write pairs
    # This captures peer-to-peer interactions missed by delegation graph
    # Essential for debate (DS↔DE) and delphi (critique cycles) protocols
    interaction_edges = []
    interaction_out_degree = Counter()

    for read_ev in read_events:
        writer_role = (read_ev.get('write_ref') or {}).get('writer_role')
        reader_role = read_ev.get('reader_role')
        if writer_role and reader_role:
            # Edge from writer to reader (information flow)
            interaction_edges.append((writer_role, reader_role))
            interaction_out_degree[writer_role] += 1

    # Interaction-based H: entropy over destination distribution
    if interaction_edges:
        i_dst_counts = Counter(dst for _, dst in interaction_edges)
        i_total_edges = sum(i_dst_counts.values())
        i_ps = [c / i_total_edges for c in i_dst_counts.values()] if i_total_edges > 0 else []
        H_interaction = entropy(i_ps)
    else:
        H_interaction = 0.0

    # Interaction-based C: Freeman centralization from out-degree
    C_interaction = freeman_centralization(interaction_out_degree)

    # Interaction-based G: Gini from workload (use write_events as before)
    # Note: G is based on write workload, not interaction topology, so same as delegation G
    G_interaction = G  # Same computation as delegation G

    # read_after_k proxy from per-artifact first-read turn distance (approx): compute if we can map write turn -> first read turn
    # We approximate by using event order index; if missing, leave zeros.
    read_after_k = {"k1": 0.0, "k2": 0.0, "k3": 0.0}
    try:
        # Build artifact->write turn; read events -> first read turn
        art_write_turn = {}
        art_first_read_turn = {}
        for ev in write_events:
            t = ev.get("turn_index") or ev.get("turn_id")
            for r in ev.get("refs_out") or []:
                if r not in art_write_turn and t is not None:
                    art_write_turn[r] = int(t)
        for ev in read_events:
            t = ev.get("turn_index")
            art = ev.get("artifact")
            if art and t is not None:
                if art not in art_first_read_turn:
                    art_first_read_turn[art] = int(t)
        diffs = []
        for art, wt in art_write_turn.items():
            rt = art_first_read_turn.get(art)
            if rt is not None:
                diffs.append(max(0, rt - wt))
        if art_write_turn:
            def ratio_within(k):
                within = sum(1 for art, wt in art_write_turn.items()
                             if (art_first_read_turn.get(art) is not None and (art_first_read_turn[art] - wt) <= k))
                return within / max(len(art_write_turn), 1)
            read_after_k["k1"] = ratio_within(1)
            read_after_k["k2"] = ratio_within(2)
            read_after_k["k3"] = ratio_within(3)
    except Exception:
        pass

    # Outcome aggregates (best-effort from events; your pipeline may override via grader)
    # We count loops from failure events (F-LOOP), recovery events count, blackboard writes already counted
    recovery_events_n = len(recoveries)

    # success heuristic: if there is a final acceptance or explicit success flag in last write; else 0/1 placeholder
    success = 1 if len(write_events) > 0 and len(failures) == 0 else 0

    # time to first action
    if start_ts and first_action_ts:
        t_first_action_ms = max(0, int((first_action_ts - start_ts).total_seconds() * 1000.0))
    else:
        t_first_action_ms = 0

    # Build result object
    # provenance defaults (lightweight, avoid hard failure)
    git_commit = None
    try:
        import subprocess
        git_commit = subprocess.check_output(["git","rev-parse","--short","HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        git_commit = "0000000"

    # Compute self-loop metrics
    total_self_loops = sum(self_loops.values())
    total_actions = len(edges) + total_self_loops  # edges + self-loops
    self_loop_rate = total_self_loops / total_actions if total_actions > 0 else 0.0

    result = {
        "schema_version": "1.0",
        "run_id": run_id,
        "dataset_id": dataset_id or "",
        "task_id": "",  # optional if you have it
        "task_type": task_type or "",
        "strategy": (strategy or "").replace("planner_to_worker", "PlannerWorker"),
        "model": {
            "name": model_name or "",
            "provider": model_provider or "",
            "version": model_version or ""
        },
        "policy": {
            "temperature": float(policy_temperature) if policy_temperature is not None else 0.0,
            "max_tokens": int(policy_max_tokens) if policy_max_tokens is not None else 1
        },
        "tools": [],
        "seed": int(seed) if isinstance(seed, int) or (isinstance(seed, str) and seed.isdigit()) else 0,
        "outcome": {
            "final_quality_score": None,   # fill from grader if available
            "turn_count": turn_count,
            "tool_call_count": tool_call_count,
            "loop_count": loop_count,
            "blackboard_writes": blackboard_writes,
            "recovery_events": recovery_events_n,
            "success": success
        },
        "process": {
            "centralization_C": round(C, 6),
            "ownership_gini": round(G, 6),
            "handoff_entropy_H": round(H, 6),
            "loop_density": round(loop_density, 6),
            "centralization_C_interaction": round(C_interaction, 6),
            "ownership_gini_interaction": round(G_interaction, 6),
            "handoff_entropy_H_interaction": round(H_interaction, 6),
            "t_first_read_ms": round(t_first_read_ms, 3),
            "t_owner_read_ms": round(t_owner_read_ms, 3),
            "reuse_rate": round(reuse_rate, 6),
            "orphan_write": round(orphan_write, 6),
            "read_after_k": {
                "k1": round(read_after_k["k1"], 6),
                "k2": round(read_after_k["k2"], 6),
                "k3": round(read_after_k["k3"], 6)
            },
            "readers_mean": round(readers_mean, 6),
            "self_loop_rate": round(self_loop_rate, 6),
            "self_loops_by_role": dict(self_loops),
            "topic_drift": {
                "mean_D": round(mean_D, 6),
                "slope_beta": round(slope_beta, 6),
                "embed_model": tdi_model or "",
                "goal_embed_ref": goal_embed_ref or "",
                "turns_sampled": turns_sampled
            },
            "policy_adherence": {
                "A": round(A, 6),
                "V": round(V, 6),
                "violation_counts": dict(violation_counts)
            },
            "event_counts": {
                "write_events_n": event_counts["write_events_n"],
                "read_events_n": event_counts["read_events_n"],
                "compliance_events_n": event_counts["compliance_events_n"]
            }
        },
        "cost": {
            "tokens_total": int(tokens_total) if tokens_total else 0,
            "tokens_prompt": int(tokens_prompt) if tokens_prompt else 0,
            "tokens_completion": int(tokens_completion) if tokens_completion else 0
        },
        "grading": {
            "quality_grader": None,
            "quality_rubric_id": None,
            "score": None,
            "confidence": None
        },
        "timing": {
            "start_time": start_ts.isoformat().replace("+00:00", "Z") if start_ts else None,
            "end_time": end_ts.isoformat().replace("+00:00", "Z") if end_ts else None,
            "time_to_first_action_ms": t_first_action_ms
        },
        "provenance": {
            "git_commit": git_commit,
            "code_version": "",
            "data_hash": "",
            "prompt_version": prompt_version or None
        },
        "notes": None
    }

    return result, None

# ---------- Validation & Saving ----------

def validate_against_schema(obj, schema_path):
    try:
        import jsonschema
    except ImportError:
        return {"warn": "jsonschema not installed; skipping validation"}
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    try:
        jsonschema.validate(instance=obj, schema=schema)
        return None
    except jsonschema.ValidationError as e:
        return {"error": f"Schema validation failed: {e.message}", "path": list(e.path), "validator": e.validator}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs_dir", required=True, help="Directory containing per-run folders")
    ap.add_argument("--out_dir", required=True, help="Where to write per-run result.json and rollups")
    ap.add_argument("--schema", required=False, help="Path to schema_result.json (optional but recommended)")
    args = ap.parse_args()

    runs_dir = args.runs_dir
    out_dir = args.out_dir
    ensure_dir(out_dir)

    run_dirs = [d for d in glob.glob(os.path.join(runs_dir, "*")) if os.path.isdir(d)]
    results = []
    errors = []

    for rd in sorted(run_dirs):
        run_id = os.path.basename(rd.rstrip("/\\"))
        result, warn = aggregate_run(rd)
        if result is None:
            errors.append({"run": run_id, "error": warn or "aggregate_failed"})
            continue
        # validate
        val = None
        if args.schema:
            val = validate_against_schema(result, args.schema)
        # save per-run
        run_out_dir = os.path.join(out_dir, run_id)
        ensure_dir(run_out_dir)
        out_path = os.path.join(run_out_dir, "result.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        # record summary
        results.append(result)
        if val and "error" in val:
            errors.append({"run": run_id, **val})

    # rollups
    # 1) results.jsonl
    jsonl_path = os.path.join(out_dir, "results.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 2) results.csv (minimal)
    csv_path = os.path.join(out_dir, "results.csv")
    import csv
    with open(csv_path, "w", newline="", encoding="utf-8") as cf:
        w = csv.writer(cf)
        w.writerow([
            "run_id","dataset_id","task_type","strategy",
            "final_quality_score","turn_count","tool_call_count","loop_count","blackboard_writes","recovery_events","success",
            "C","G","H","loop_density","t_first_read_ms","t_owner_read_ms","reuse_rate","orphan_write",
            "tdi_mean_D","tdi_slope_beta","A","V","write_events_n","read_events_n","compliance_events_n",
            "tokens_total","start_time","end_time"
        ])
        for r in results:
            p = r["process"]
            o = r["outcome"]
            c = r["cost"]
            t = r["timing"]
            w.writerow([
                r["run_id"], r.get("dataset_id"), r.get("task_type"), r.get("strategy"),
                o.get("final_quality_score"), o.get("turn_count"), o.get("tool_call_count"), o.get("loop_count"), o.get("blackboard_writes"), o.get("recovery_events"), o.get("success"),
                p.get("centralization_C"), p.get("ownership_gini"), p.get("handoff_entropy_H"), p.get("loop_density"), p.get("t_first_read_ms"), p.get("t_owner_read_ms"),
                p.get("reuse_rate"), p.get("orphan_write"),
                p["topic_drift"].get("mean_D"), p["topic_drift"].get("slope_beta"),
                p["policy_adherence"].get("A"), p["policy_adherence"].get("V"),
                p["event_counts"].get("write_events_n"), p["event_counts"].get("read_events_n"), p["event_counts"].get("compliance_events_n"),
                c.get("tokens_total"), t.get("start_time"), t.get("end_time")
            ])

    # 3) report any errors
    if errors:
        err_path = os.path.join(out_dir, "results_errors.json")
        with open(err_path, "w", encoding="utf-8") as f:
            json.dump(errors, f, indent=2, ensure_ascii=False)

    print(f"[make_result] processed {len(results)} runs; results at:")
    print(f"  - {jsonl_path}")
    print(f"  - {csv_path}")
    if errors:
        print(f"  - errors: {len(errors)} (see {os.path.join(out_dir, 'results_errors.json')})")

if __name__ == "__main__":
    main()
