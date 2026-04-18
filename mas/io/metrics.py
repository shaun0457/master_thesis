#!/usr/bin/env python3
"""
O-MAS Metrics Computation Module.

This module computes all behavioral signals and process metrics from event logs.
These metrics form the foundation of the O-MAS framework for evaluating
multi-agent system collaboration quality.

Metrics Computed:
    Topology Metrics (Communication Structure):
        - C (Centralization): How much communication is dominated by one agent
        - H (Handoff Entropy): Diversity of communication partners
        - G (Ownership Gini): Inequality in turn authorship

    Knowledge-Flow Metrics (Blackboard Patterns):
        - reuse_rate: Fraction of writes that were read by others
        - orphan_rate: Fraction of writes never read (1 - reuse)
        - t_first_read_ms: Mean delay to first read
        - readers_mean: Average number of readers per artifact

    Stability Metrics:
        - L (Loop Density): Cycles / total paths in delegation graph
        - TDI (Topic Drift Index): Semantic drift from original goal

    Governance Metrics:
        - A (Adherence): 1 - violation_rate
        - V (Violation Rate): Protocol violations / total events

Data Sources:
    - run.turn.v2.jsonl: Agent turn events
    - router.event.v2.jsonl: Router validation decisions
    - bb.write.v1.jsonl: Blackboard write events
    - run.read.v1.jsonl: Blackboard read events

References:
    - Chapter 3: Methodology (metric definitions)
    - Appendix A: Process Metric Dictionary
    - glossary.md: Symbol definitions

Author: Cheng-Ting Chen
Thesis: Observable Multi-Agent Systems (O-MAS)
"""

from typing import List, Dict, Any
import networkx as nx
import numpy as np
from collections import defaultdict, Counter

from mas.io.utils import parse_timestamp


# =============================================================================
# TOPOLOGY METRICS
# =============================================================================

def compute_centralization(router_events: List[dict]) -> float:
    """
    Compute Freeman's degree centralization from router events.

    Freeman's centralization measures how much the interaction network
    is dominated by a single central node. In hierarchical protocols
    (Planner-to-Worker), the Supervisor typically has high centrality.
    In peer protocols (Debate, Delphi), centralization is lower.

    Mathematical Definition:
        C = Σ(d_max - d_i) / ((n-1)(n-2))

        where:
        - d_i = out-degree of node i (number of delegations sent)
        - d_max = maximum out-degree in the graph
        - n = number of nodes (agents)

    Interpretation:
        - C = 0.0: Perfectly decentralized (all nodes have equal degree)
        - C = 1.0: Star topology (one node sends all delegations)

    Args:
        router_events: List of router.event.v2 dictionaries.
            Required fields:
            - sender (str): Role that sent the message
            - recipient (str): Role that received the message

    Returns:
        float: Centralization score in [0, 1].

    References:
        Freeman, L. C. (1978). Centrality in social networks:
        Conceptual clarification. Social Networks, 1(3), 215-239.

    Example:
        >>> events = [
        ...     {"sender": "supervisor", "recipient": "de"},
        ...     {"sender": "supervisor", "recipient": "ds"},
        ...     {"sender": "de", "recipient": "supervisor"}
        ... ]
        >>> C = compute_centralization(events)
        >>> print(f"Centralization = {C:.3f}")
        Centralization = 0.667
    """
    if not router_events:
        return 0.0

    # Build directed graph from delegation events
    # Exclude self-loops: they don't represent delegation to others
    G = nx.DiGraph()
    for ev in router_events:
        sender = ev.get("sender")
        recipient = ev.get("recipient")
        if sender and recipient and sender != recipient:
            G.add_edge(sender, recipient)

    if len(G) < 2:
        return 0.0

    # Compute out-degrees (number of delegations sent by each node)
    degrees = [G.out_degree(n) for n in G.nodes()]
    d_max = max(degrees) if degrees else 0
    n = len(G)

    # Freeman's centralization formula
    numerator = sum(d_max - d for d in degrees)
    denominator = (n - 1) * (n - 2) if n > 2 else 1

    return numerator / denominator if denominator > 0 else 0.0


def compute_self_loops(router_events: List[dict]) -> Dict[str, Any]:
    """
    Compute self-loop metrics from router events.

    Self-loops occur when an agent's action targets itself (action.target == self).
    This indicates continued processing rather than delegation, and can signal:
    - Appropriate: Deep analysis requiring multiple passes
    - Problematic: Agent stuck in processing loop

    Args:
        router_events: List of router.event.v2 dictionaries.

    Returns:
        dict containing:
            - self_loop_rate (float): Fraction of edges that are self-loops
            - self_loops_by_role (dict): Count of self-loops per role
            - total_self_loops (int): Total count of self-loop events

    Example:
        >>> events = [
        ...     {"sender": "supervisor", "recipient": "supervisor"},  # Self-loop
        ...     {"sender": "supervisor", "recipient": "de"},          # Delegation
        ... ]
        >>> metrics = compute_self_loops(events)
        >>> print(f"Self-loop rate: {metrics['self_loop_rate']:.2f}")
        Self-loop rate: 0.50
    """
    if not router_events:
        return {
            "self_loop_rate": 0.0,
            "self_loops_by_role": {},
            "total_self_loops": 0
        }

    self_loops_by_role = defaultdict(int)
    total_edges = 0
    total_self_loops = 0

    for ev in router_events:
        sender = ev.get("sender")
        recipient = ev.get("recipient")

        if sender and recipient:
            total_edges += 1
            if sender == recipient:
                self_loops_by_role[sender] += 1
                total_self_loops += 1

    self_loop_rate = total_self_loops / total_edges if total_edges > 0 else 0.0

    return {
        "self_loop_rate": self_loop_rate,
        "self_loops_by_role": dict(self_loops_by_role),
        "total_self_loops": total_self_loops
    }


def compute_ownership_gini(turn_events: List[dict]) -> float:
    """
    Compute Gini coefficient of turn authorship inequality.

    The Gini coefficient measures how unevenly turns are distributed
    among agents. High Gini indicates one agent dominates the conversation;
    low Gini indicates balanced participation.

    Mathematical Definition:
        G = Σ|x_i - x_j| / (2n²μ)

        where:
        - x_i = turn count for role i
        - n = number of roles
        - μ = mean turn count

    Interpretation:
        - G = 0.0: Perfect equality (all roles have equal turns)
        - G = 1.0: Maximum inequality (one role has all turns)

    Args:
        turn_events: List of run.turn.v2 dictionaries.
            Required field: role (str)

    Returns:
        float: Gini coefficient in [0, 1].

    Example:
        >>> turns = [
        ...     {"role": "supervisor"},
        ...     {"role": "supervisor"},
        ...     {"role": "de"}
        ... ]
        >>> G = compute_ownership_gini(turns)
        >>> print(f"Gini = {G:.3f}")
    """
    if not turn_events:
        return 0.0

    # Count turns per role
    role_counts = Counter(t.get("role", "unknown") for t in turn_events)
    counts = np.array(list(role_counts.values()), dtype=float)

    if len(counts) == 0 or counts.sum() == 0:
        return 0.0

    n = len(counts)
    mu = counts.mean()

    if mu == 0:
        return 0.0

    # Gini formula: sum of absolute differences
    numerator = sum(abs(x_i - x_j) for x_i in counts for x_j in counts)
    denominator = 2 * n**2 * mu

    return numerator / denominator


def compute_handoff_entropy(router_events: List[dict]) -> float:
    """
    Compute handoff entropy (H) from router delegation events.

    Handoff entropy measures the diversity of delegation destinations.
    High entropy indicates agents delegate to many different partners;
    low entropy indicates delegations concentrate on few targets.

    Mathematical Definition:
        H = -Σ p_j log₂(p_j)

        where p_j = probability of handoff to role j
                  = count(delegations to j) / total delegations

    Interpretation:
        - H = 0.0: All delegations go to same recipient
        - H = log₂(n): Uniform distribution across n recipients
        - Higher H: More diverse communication patterns

    Args:
        router_events: List of router.event.v2 dictionaries.
            Required field: recipient (str)

    Returns:
        float: Shannon entropy (bits), ≥ 0.

    Example:
        >>> events = [
        ...     {"sender": "supervisor", "recipient": "de"},
        ...     {"sender": "supervisor", "recipient": "ds"},
        ...     {"sender": "de", "recipient": "supervisor"}
        ... ]
        >>> H = compute_handoff_entropy(events)
        >>> print(f"Entropy = {H:.3f} bits")
    """
    if not router_events:
        return 0.0

    # Count recipient occurrences
    recipients = [ev.get("recipient") for ev in router_events if ev.get("recipient")]
    if not recipients:
        return 0.0

    counts = Counter(recipients)
    total = sum(counts.values())

    # Shannon entropy
    H = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            H -= p * np.log2(p)

    return H


# =============================================================================
# KNOWLEDGE-FLOW METRICS
# =============================================================================

def compute_reuse_and_orphan(writes: List[dict], reads: List[dict]) -> Dict[str, float]:
    """
    Compute reuse rate and orphan rate from blackboard events.

    Reuse measures how much agents build on each other's work.
    Orphan measures wasted effort (artifacts created but never used).

    Definitions:
        - reuse_rate = |writes ∩ reads| / |writes|
          Fraction of written artifacts that were subsequently read
        - orphan_rate = 1 - reuse_rate
          Fraction of written artifacts never read by others

    Args:
        writes: List of bb.write.v1 dictionaries.
            Required field: artifact (str) - bb:// URI
        reads: List of run.read.v1 dictionaries.
            Required field: artifact (str) - bb:// URI

    Returns:
        dict containing:
            - reuse_rate (float): In [0, 1]
            - orphan_write (float): In [0, 1], equals 1 - reuse_rate

    Example:
        >>> writes = [{"artifact": "bb://a"}, {"artifact": "bb://b"}]
        >>> reads = [{"artifact": "bb://a"}]  # Only 'a' was read
        >>> metrics = compute_reuse_and_orphan(writes, reads)
        >>> print(f"Reuse: {metrics['reuse_rate']:.2f}")
        Reuse: 0.50
    """
    if not writes:
        return {"reuse_rate": 0.0, "orphan_write": 0.0}

    # Extract artifact URIs
    written_artifacts = {w.get("artifact") for w in writes if w.get("artifact")}
    read_artifacts = {r.get("artifact") for r in reads if r.get("artifact")}

    # Compute intersection (artifacts both written and read)
    reused = written_artifacts & read_artifacts
    reuse_rate = len(reused) / len(written_artifacts) if written_artifacts else 0.0
    orphan_write = 1.0 - reuse_rate

    return {
        "reuse_rate": reuse_rate,
        "orphan_write": orphan_write
    }


def compute_read_delays(writes: List[dict], reads: List[dict]) -> Dict[str, float]:
    """
    Compute time delays between writes and reads.

    Measures responsiveness: how quickly are artifacts consumed after creation?

    Metrics:
        - t_first_read_ms: Mean time from write to first read by any agent
        - t_owner_read_ms: Mean time from write to read by the artifact owner

    Args:
        writes: List of bb.write.v1 dictionaries.
            Required: artifact, ts, owner_role
        reads: List of run.read.v1 dictionaries.
            Required: artifact, ts, reader_role

    Returns:
        dict containing:
            - t_first_read_ms (float): Mean delay in milliseconds
            - t_owner_read_ms (float): Mean owner read delay in milliseconds

    Example:
        >>> writes = [{
        ...     "artifact": "bb://analysis",
        ...     "ts": "2024-11-15T12:00:00Z",
        ...     "owner_role": "de"
        ... }]
        >>> reads = [{
        ...     "artifact": "bb://analysis",
        ...     "ts": "2024-11-15T12:00:15Z",
        ...     "reader_role": "ds"
        ... }]
        >>> delays = compute_read_delays(writes, reads)
        >>> print(f"First read delay: {delays['t_first_read_ms']}ms")
        First read delay: 15000.0ms
    """
    # Build artifact → (write_time, owner) mapping
    write_times = {}
    write_owners = {}
    for w in writes:
        artifact = w.get("artifact")
        ts = w.get("ts")
        owner = w.get("owner_role")
        if artifact and ts:
            try:
                write_times[artifact] = parse_timestamp(ts)
                write_owners[artifact] = owner
            except ValueError:
                continue

    # Compute delays for each read
    first_read_delays = []
    owner_read_delays = []

    for r in reads:
        artifact = r.get("artifact")
        reader = r.get("reader_role")
        ts = r.get("ts")

        if not (artifact and ts and artifact in write_times):
            continue

        try:
            read_time = parse_timestamp(ts)
        except ValueError:
            continue

        write_time = write_times[artifact]
        delay_ms = (read_time - write_time).total_seconds() * 1000

        if delay_ms >= 0:  # Ignore negative delays (clock skew)
            first_read_delays.append(delay_ms)

            if reader == write_owners.get(artifact):
                owner_read_delays.append(delay_ms)

    return {
        "t_first_read_ms": float(np.mean(first_read_delays)) if first_read_delays else 0.0,
        "t_owner_read_ms": float(np.mean(owner_read_delays)) if owner_read_delays else 0.0
    }


def compute_read_after_k(writes: List[dict], reads: List[dict], turns: List[dict]) -> Dict[str, float]:
    """
    Compute fraction of writes read within k turns.

    Measures collaboration tightness: how quickly do agents respond
    to each other's outputs?

    Metrics:
        - k1: Fraction of writes read within 1 turn
        - k2: Fraction of writes read within 2 turns
        - k3: Fraction of writes read within 3 turns

    Args:
        writes: List of bb.write.v1 dicts with artifact, turn_index
        reads: List of run.read.v1 dicts with artifact, turn_index
        turns: List of run.turn.v2 dicts (for validation)

    Returns:
        dict: {"k1": float, "k2": float, "k3": float}

    Example:
        >>> writes = [{"artifact": "bb://a", "turn_index": 0}]
        >>> reads = [{"artifact": "bb://a", "turn_index": 1}]
        >>> turns = [{"turn_index": i} for i in range(10)]
        >>> rak = compute_read_after_k(writes, reads, turns)
        >>> print(f"Read within 1 turn: {rak['k1']:.0%}")
        Read within 1 turn: 100%
    """
    if not writes:
        return {"k1": 0.0, "k2": 0.0, "k3": 0.0}

    # Build artifact → write_turn mapping
    write_turn = {}
    for w in writes:
        artifact = w.get("artifact")
        turn_idx = w.get("turn_index")
        if artifact and turn_idx is not None:
            write_turn[artifact] = turn_idx

    # Build artifact → first_read_turn mapping (earliest read)
    read_turn = {}
    for r in sorted(reads, key=lambda x: x.get("turn_index", 999)):
        artifact = r.get("artifact")
        turn_idx = r.get("turn_index")
        if artifact and turn_idx is not None and artifact not in read_turn:
            read_turn[artifact] = turn_idx

    # Compute turn deltas
    deltas = []
    for artifact, w_turn in write_turn.items():
        if artifact in read_turn:
            delta = read_turn[artifact] - w_turn
            deltas.append(delta)
        else:
            deltas.append(999)  # Never read

    if not deltas:
        return {"k1": 0.0, "k2": 0.0, "k3": 0.0}

    k1 = sum(1 for d in deltas if d <= 1) / len(deltas)
    k2 = sum(1 for d in deltas if d <= 2) / len(deltas)
    k3 = sum(1 for d in deltas if d <= 3) / len(deltas)

    return {"k1": k1, "k2": k2, "k3": k3}


def compute_readers_mean(writes: List[dict], reads: List[dict]) -> float:
    """
    Compute average number of unique readers per artifact.

    Measures knowledge dissemination: are artifacts shared broadly
    or consumed by just one agent?

    Args:
        writes: List of bb.write.v1 dicts with artifact field
        reads: List of run.read.v1 dicts with artifact, reader_role

    Returns:
        float: Average number of unique readers per written artifact.

    Example:
        >>> writes = [{"artifact": "bb://report"}]
        >>> reads = [
        ...     {"artifact": "bb://report", "reader_role": "ds"},
        ...     {"artifact": "bb://report", "reader_role": "me"}
        ... ]
        >>> avg = compute_readers_mean(writes, reads)
        >>> print(f"Avg readers: {avg:.1f}")
        Avg readers: 2.0
    """
    if not writes:
        return 0.0

    # Count unique readers per artifact
    artifact_readers = defaultdict(set)
    for r in reads:
        artifact = r.get("artifact")
        reader = r.get("reader_role")
        if artifact and reader:
            artifact_readers[artifact].add(reader)

    # Compute average
    written_artifacts = [w.get("artifact") for w in writes if w.get("artifact")]
    reader_counts = [len(artifact_readers[a]) for a in written_artifacts]

    return float(np.mean(reader_counts)) if reader_counts else 0.0


# =============================================================================
# STABILITY METRICS
# =============================================================================

def compute_loop_density(router_events: List[dict]) -> float:
    """
    Compute loop density (L) = cycles / total_paths.

    Loop density measures the proportion of cyclic patterns in the
    delegation graph. High loop density indicates potential instability:
    agents are delegating back and forth without making progress.

    Mathematical Definition:
        L = (# simple cycles in graph) / (# total delegation events)

    Interpretation:
        - L = 0.0: Acyclic delegation (no loops)
        - L > 0: Cyclic patterns present
        - High L: Many back-and-forth delegations (potential stuck loops)

    Role in O-MAS:
        Loop density is a primary mediator in RQ3, linking protocol
        design to process stability (PSI). Protocols that structure
        deliberation (Debate, Delphi) may have controlled loops.

    Args:
        router_events: List of router.event.v2 dictionaries.
            Required: sender, recipient

    Returns:
        float: Loop density in [0, 1].

    References:
        glossary.md §4.1, Chapter 3 §3.2

    Example:
        >>> events = [
        ...     {"sender": "de", "recipient": "ds"},
        ...     {"sender": "ds", "recipient": "de"},  # Creates cycle
        ...     {"sender": "ds", "recipient": "supervisor"}
        ... ]
        >>> L = compute_loop_density(events)
        >>> print(f"Loop density = {L:.3f}")
    """
    if not router_events:
        return 0.0

    # Build directed graph
    G = nx.DiGraph()
    for ev in router_events:
        sender = ev.get("sender")
        recipient = ev.get("recipient")
        if sender and recipient:
            G.add_edge(sender, recipient)

    if len(G) == 0:
        return 0.0

    # Count simple cycles in the graph
    try:
        cycles = list(nx.simple_cycles(G))
        cyclic_paths = len(cycles)
    except Exception:
        cyclic_paths = 0

    total_paths = len(router_events)

    return cyclic_paths / total_paths if total_paths > 0 else 0.0


def aggregate_tdi_metrics(turn_events: List[dict]) -> Dict[str, Any]:
    """
    Aggregate Topic Drift Index (TDI) metrics from turn events.

    TDI measures semantic drift from the original task goal using
    embedding similarity. High drift indicates the team is going
    off-topic; low drift indicates focused collaboration.

    Aggregated Metrics:
        - mean_D: Average drift across all turns
        - slope_beta: Linear trend (increasing = getting more off-topic)
        - embed_model: Embedding model used
        - goal_embed_ref: Reference to goal embedding
        - turns_sampled: Number of turns with TDI data

    Args:
        turn_events: List of run.turn.v2 dicts.
            TDI data in: metrics_trace.tdi.drift_D

    Returns:
        dict with aggregated TDI metrics.

    Example:
        >>> turns = [{
        ...     "turn_index": 0,
        ...     "metrics_trace": {
        ...         "tdi": {"drift_D": 0.1, "embed_model": "text-embedding-004"}
        ...     }
        ... }]
        >>> tdi = aggregate_tdi_metrics(turns)
        >>> print(f"Mean drift: {tdi['mean_D']:.3f}")
    """
    drifts = []
    goal_ref = None
    embed_model = None

    for t in turn_events:
        mt = t.get("metrics_trace", {})
        tdi = mt.get("tdi", {})

        drift_D = tdi.get("drift_D")
        if drift_D is not None:
            drifts.append(drift_D)

        if not goal_ref:
            goal_ref = tdi.get("user_goal_ref", "")
        if not embed_model:
            embed_model = tdi.get("embed_model", "unknown")

    # Compute linear trend (slope) via regression
    if len(drifts) > 1:
        x = np.arange(len(drifts))
        slope_beta, _ = np.polyfit(x, drifts, 1)
    else:
        slope_beta = 0.0

    return {
        "mean_D": float(np.mean(drifts)) if drifts else 0.0,
        "slope_beta": float(slope_beta),
        "embed_model": embed_model or "unknown",
        "goal_embed_ref": goal_ref or "",
        "turns_sampled": len(drifts)
    }


# =============================================================================
# GOVERNANCE METRICS
# =============================================================================

def aggregate_policy_metrics(router_events: List[dict]) -> Dict[str, Any]:
    """
    Aggregate policy adherence and violation metrics from router events.

    Measures how well agents follow protocol rules. High adherence
    indicates disciplined collaboration; violations indicate protocol
    departures that may indicate problems or adaptation.

    Definitions:
        - A (Adherence) = 1 - (turns_with_violations / total_turns)
        - V (Violation Rate) = turns_with_violations / total_turns

    Args:
        router_events: List of router.event.v2 dicts.
            Violations in: policy.events (list of violation strings)

    Returns:
        dict containing:
            - A (float): Adherence rate in [0, 1]
            - V (float): Violation rate in [0, 1]
            - violation_counts (dict): Count per violation type

    Example:
        >>> events = [
        ...     {"policy": {"events": ["DEBATE:INVALID_INTENT: work"]}},
        ...     {"policy": {"events": []}},  # No violations
        ...     {"policy": {"events": ["DEBATE:INVALID_INTENT: work"]}}
        ... ]
        >>> metrics = aggregate_policy_metrics(events)
        >>> print(f"Adherence: {metrics['A']:.2f}")
        Adherence: 0.33
    """
    total_turns = len(router_events)
    total_violations = 0
    violation_counts = Counter()

    for event in router_events:
        policy = event.get("policy", {})
        events = policy.get("events", [])

        if events:
            total_violations += 1
            # Count each violation type
            for violation_str in events:
                violation_type = violation_str.split(':')[0] if ':' in violation_str else violation_str
                violation_counts[violation_type] += 1

    if total_turns == 0:
        return {
            "A": 1.0,
            "V": 0.0,
            "violation_counts": {}
        }

    V = total_violations / total_turns
    A = 1.0 - V

    return {
        "A": float(A),
        "V": float(V),
        "violation_counts": dict(violation_counts)
    }


# =============================================================================
# INTERACTION-BASED METRICS (Alternative to Delegation-Based)
# =============================================================================

def compute_interaction_centralization(writes: List[dict], reads: List[dict]) -> float:
    """
    Compute interaction-based centralization (C_int).

    Unlike delegation-based centralization (from router events), this
    measures centralization in the actual knowledge-sharing network
    (who reads whose artifacts).

    Useful for protocols where delegation events don't capture all
    meaningful interactions (e.g., Debate, Delphi).

    Args:
        writes: List of bb.write.v1 dicts with artifact, writer_role
        reads: List of run.read.v1 dicts with artifact, reader_role

    Returns:
        float: Interaction centralization in [0, 1].

    Example:
        >>> writes = [{"artifact": "bb://a", "writer_role": "de"}]
        >>> reads = [{"artifact": "bb://a", "reader_role": "ds"}]
        >>> C_int = compute_interaction_centralization(writes, reads)
    """
    if not writes or not reads:
        return 0.0

    # Build artifact → writer mapping
    artifact_writer = {}
    for w in writes:
        artifact = w.get("artifact")
        writer = w.get("writer_role")
        if artifact and writer:
            artifact_writer[artifact] = writer

    # Build interaction graph (writer → reader edges)
    G = nx.DiGraph()
    for r in reads:
        artifact = r.get("artifact")
        reader = r.get("reader_role")
        if artifact and reader and artifact in artifact_writer:
            writer = artifact_writer[artifact]
            G.add_edge(writer, reader)

    if len(G) < 2:
        return 0.0

    # Freeman's centralization formula
    degrees = [G.out_degree(n) for n in G.nodes()]
    d_max = max(degrees) if degrees else 0
    n = len(G)

    numerator = sum(d_max - d for d in degrees)
    denominator = (n - 1) * (n - 2) if n > 2 else 1

    return numerator / denominator if denominator > 0 else 0.0


def compute_interaction_entropy(writes: List[dict], reads: List[dict]) -> float:
    """
    Compute interaction-based handoff entropy (H_int).

    Measures diversity of knowledge sharing partners based on actual
    artifact reads rather than delegation events.

    Args:
        writes: List of bb.write.v1 dicts with artifact, writer_role
        reads: List of run.read.v1 dicts with artifact, reader_role

    Returns:
        float: Interaction entropy (bits), ≥ 0.

    Example:
        >>> writes = [{"artifact": "bb://a", "writer_role": "de"}]
        >>> reads = [
        ...     {"artifact": "bb://a", "reader_role": "ds"},
        ...     {"artifact": "bb://a", "reader_role": "me"}
        ... ]
        >>> H_int = compute_interaction_entropy(writes, reads)
    """
    if not writes or not reads:
        return 0.0

    # Build artifact → writer mapping
    artifact_writer = {}
    for w in writes:
        artifact = w.get("artifact")
        writer = w.get("writer_role")
        if artifact and writer:
            artifact_writer[artifact] = writer

    # Collect readers for artifacts with known writers
    readers = []
    for r in reads:
        artifact = r.get("artifact")
        reader = r.get("reader_role")
        if artifact and reader and artifact in artifact_writer:
            readers.append(reader)

    if not readers:
        return 0.0

    # Shannon entropy
    counts = Counter(readers)
    total = sum(counts.values())

    H = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            H -= p * np.log2(p)

    return H
