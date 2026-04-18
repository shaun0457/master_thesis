# mas/enrich/policy.py
"""
Policy adherence evaluation for X-MAS experiments.

Computes:
- adherence_A: Adherence rate to protocol rules [0, 1]
- violation_rate_V: Violation rate [0, 1]
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional


def load_protocol_rules(protocol: str, router_root: Path = None) -> Dict[str, Any]:
    """
    Load protocol rules from router config files.

    Args:
        protocol: Protocol name (neutral, planner_to_worker, debate, delphi)
        router_root: Root directory for router configs (default: ./router/)

    Returns:
        dict: Protocol rules configuration
    """
    if router_root is None:
        router_root = Path(__file__).parent.parent.parent / "router"

    # Map protocol names to config files
    protocol_map = {
        "neutral": "neutral_rules.config.json",
        "planner_to_worker": "ptow_rules.config.json",
        "ptow": "ptow_rules.config.json",
        "debate": "debate_rules.config.json",
        "delphi": "delphi_rules.config.json"
    }

    config_file = protocol_map.get(protocol.lower())
    if not config_file:
        raise ValueError(f"Unknown protocol: {protocol}")

    config_path = router_root / config_file
    if not config_path.exists():
        # Return minimal rules if file doesn't exist
        return {
            "protocol": protocol,
            "rules": {},
            "p2p_forbidden": []
        }

    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Handle markdown-wrapped JSON (files that start with ## and contain ```json)
    if content.strip().startswith('#'):
        import re
        # Extract JSON from markdown code block
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        else:
            # Return minimal rules if no JSON found
            return {
                "protocol": protocol,
                "rules": {},
                "p2p_forbidden": []
            }

    # Parse JSON
    rules = json.loads(content)

    # Extract p2p_forbidden pairs if routing_rules exists
    p2p_forbidden = []
    if rules.get("routing_rules", {}).get("p2p_delegation_allowed") is False:
        # Build p2p forbidden list for worker roles
        workers = ["de", "ds", "me"]
        for w1 in workers:
            for w2 in workers:
                if w1 != w2:
                    p2p_forbidden.append([w1, w2])

    rules["p2p_forbidden"] = p2p_forbidden
    return rules


def check_p2p_violation(
    owner: str,
    target: str,
    protocol: str,
    rules: Dict[str, Any]
) -> bool:
    """
    Check if owner→target transition violates P2P rules.

    Args:
        owner: Current owner role
        target: Target role for next turn
        protocol: Protocol name
        rules: Protocol rules dict

    Returns:
        bool: True if violation detected, False otherwise
    """
    if protocol.lower() not in ["planner_to_worker", "ptow"]:
        return False

    # Get forbidden pairs from rules
    forbidden = rules.get("p2p_forbidden", [])

    # Check if (owner, target) is forbidden
    pair = (owner.lower(), target.lower())
    return pair in [tuple(p) for p in forbidden]


def check_contamination_violation(
    content: str,
    refs: List[str]
) -> bool:
    """
    Check if content or refs contain forbidden external URLs.

    Args:
        content: Message content
        refs: List of reference URIs

    Returns:
        bool: True if violation detected, False otherwise
    """
    import re

    # Forbidden URL patterns (external web)
    url_pattern = re.compile(r'https?://(?!bb://|facts/|TEP_docs/)')

    # Check content
    if url_pattern.search(content):
        return True

    # Check refs
    for ref in refs:
        if url_pattern.search(ref):
            return True

    return False


def check_evidence_completeness(
    content: str,
    refs: List[str]
) -> bool:
    """
    Check if evidence claims have proper references.

    Args:
        content: Message content
        refs: List of reference URIs

    Returns:
        bool: True if missing evidence detected, False otherwise
    """
    # Evidence keywords that should have refs
    evidence_keywords = [
        "according to",
        "based on",
        "shows that",
        "indicates",
        "from the data",
        "analysis shows"
    ]

    # Check if content mentions evidence
    has_evidence_claim = any(kw in content.lower() for kw in evidence_keywords)

    # If evidence claim but no refs, it's a violation
    if has_evidence_claim and len(refs) == 0:
        return True

    return False


def evaluate_turn_against_policy(
    turn_event: Dict[str, Any],
    protocol_rules: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Evaluate a single turn event against protocol policy.

    Args:
        turn_event: run.turn.v2 event dict
        protocol_rules: Protocol rules configuration

    Returns:
        dict: Evaluation result with violations list and metrics
    """
    violations = []

    # Extract fields
    protocol = turn_event.get("protocol", "neutral")
    owner = turn_event.get("owner", "")
    target = turn_event.get("target")
    content = turn_event.get("message", "")
    refs = turn_event.get("refs", [])

    # Check P2P routing violation
    if target and check_p2p_violation(owner, target, protocol, protocol_rules):
        violations.append({
            "type": "ROUTING_P2P_FORBIDDEN",
            "severity": "error",
            "detail": f"Direct handoff {owner}→{target} forbidden in {protocol}"
        })

    # Check contamination
    if check_contamination_violation(content, refs):
        violations.append({
            "type": "FORBIDDEN_SOURCE",
            "severity": "error",
            "detail": "External URL detected in content or refs"
        })

    # Check evidence completeness
    if check_evidence_completeness(content, refs):
        violations.append({
            "type": "MISSING_EVIDENCE",
            "severity": "warning",
            "detail": "Evidence claim without references"
        })

    # Compute metrics
    total_checks = 3  # P2P, contamination, evidence
    violation_count = len(violations)

    adherence_A = 1.0 - (violation_count / total_checks)
    violation_rate_V = violation_count / total_checks

    return {
        "adherence_A": adherence_A,
        "violation_rate_V": violation_rate_V,
        "violations": violations,
        "checks_performed": total_checks,
        "protocol": protocol
    }


def eval_adherence_for_turn(
    turn_event: Dict[str, Any],
    protocol: str,
    router_root: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Evaluate policy adherence for a single turn.

    Args:
        turn_event: run.turn.v2 event dict
        protocol: Protocol name
        router_root: Root directory for router configs

    Returns:
        dict: Policy metrics with structure:
        {
            "adherence_A": float,       # [0, 1]
            "violation_rate_V": float,  # [0, 1]
            "policy_events": [
                {
                    "type": "ROUTING_P2P_FORBIDDEN",
                    "severity": "error",
                    "detail": "..."
                }
            ]
        }
    """
    # Load protocol rules
    rules = load_protocol_rules(protocol, router_root)

    # Evaluate turn
    result = evaluate_turn_against_policy(turn_event, rules)

    return {
        "adherence_A": result["adherence_A"],
        "violation_rate_V": result["violation_rate_V"],
        "policy_events": result["violations"]
    }


def enrich_turn_with_policy(
    turn_event: Dict[str, Any],
    protocol: str,
    router_root: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Enrich a run.turn.v2 event with computed policy adherence metrics.

    Args:
        turn_event: run.turn.v2 event dict
        protocol: Protocol name
        router_root: Root directory for router configs

    Returns:
        dict: Updated turn event with real policy values
    """
    # Compute policy adherence
    policy = eval_adherence_for_turn(turn_event, protocol, router_root)

    # Update metrics_trace.policy
    if "metrics_trace" not in turn_event:
        turn_event["metrics_trace"] = {}

    turn_event["metrics_trace"]["policy"] = policy

    return turn_event


def compute_aggregate_adherence(
    turn_events: List[Dict[str, Any]],
    protocol: str,
    router_root: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Compute aggregate policy adherence across multiple turns.

    Args:
        turn_events: List of run.turn.v2 events
        protocol: Protocol name
        router_root: Root directory for router configs

    Returns:
        dict: Aggregate metrics
        {
            "mean_adherence_A": float,
            "mean_violation_rate_V": float,
            "total_violations": int,
            "violation_breakdown": {
                "ROUTING_P2P_FORBIDDEN": int,
                "FORBIDDEN_SOURCE": int,
                "MISSING_EVIDENCE": int
            }
        }
    """
    if not turn_events:
        return {
            "mean_adherence_A": 1.0,
            "mean_violation_rate_V": 0.0,
            "total_violations": 0,
            "violation_breakdown": {}
        }

    # Load rules once
    rules = load_protocol_rules(protocol, router_root)

    # Evaluate all turns
    adherence_values = []
    violation_values = []
    all_violations = []

    for turn in turn_events:
        result = evaluate_turn_against_policy(turn, rules)
        adherence_values.append(result["adherence_A"])
        violation_values.append(result["violation_rate_V"])
        all_violations.extend(result["violations"])

    # Count violations by type
    violation_breakdown = {}
    for v in all_violations:
        v_type = v.get("type", "UNKNOWN")
        violation_breakdown[v_type] = violation_breakdown.get(v_type, 0) + 1

    return {
        "mean_adherence_A": sum(adherence_values) / len(adherence_values),
        "mean_violation_rate_V": sum(violation_values) / len(violation_values),
        "total_violations": len(all_violations),
        "violation_breakdown": violation_breakdown
    }
