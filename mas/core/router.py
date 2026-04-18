# mas/core/router.py
"""
Protocol Router for O-MAS Multi-Agent System.

Validates agent turn messages against protocol rules, determines next agent,
and logs routing events. Non-cognitive: does not modify message content.

Supported protocols:
    - neutral: Free handoff with minimal rules
    - planner_to_worker: Hierarchical; blocks Worker→Worker P2P
    - debate: Adversarial exchange with violation warnings
    - delphi: Iterative anonymous consensus
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from mas.logging.event_writer import write_router

# Worker roles that cannot communicate directly under planner_to_worker
_WORKER_ROLES = {"de", "ds", "me"}

# Protocol-specific P2P enforcement
_P2P_BLOCKED_PROTOCOLS = {"planner_to_worker"}


class Router:
    """
    Protocol-enforcing message router for O-MAS experiments.

    Validates each turn message against the active protocol rules and
    determines which agent should act next. Writes router.event.v2 events
    to the run log for downstream metric extraction.

    Attributes:
        protocol (str): Active collaboration protocol.
        run_id (str): Current experiment run identifier.
        violation_count (int): Total violations detected this run.
    """

    def __init__(self, bb_store, protocol: str, run_id: str) -> None:
        self.bb_store = bb_store
        self.protocol = protocol
        self.run_id = run_id
        self._violations = 0
        self._turn_counter = 0

    @property
    def violation_count(self) -> int:
        return self._violations

    def route(self, turn_message: dict) -> Dict[str, Any]:
        """
        Validate a turn message and determine the next agent.

        Args:
            turn_message: Structured turn dict (run.turn.v2 schema).

        Returns:
            dict with keys:
                - status (str): "ok" or violation code
                - violations (list[str]): List of violation codes detected
                - next_owner (str): Role of agent to act next
        """
        violations = []
        sender = turn_message.get("role", "unknown").lower()
        action = turn_message.get("action", {}) or {}
        target = action.get("target")
        next_owner = target.lower() if isinstance(target, str) else "supervisor"

        # Protocol enforcement
        if self.protocol in _P2P_BLOCKED_PROTOCOLS:
            if sender in _WORKER_ROLES and next_owner in _WORKER_ROLES and sender != next_owner:
                violations.append("ROUTING_P2P_FORBIDDEN")
                next_owner = "supervisor"

        # Debate: record P2P as warning (not hard block)
        elif self.protocol == "debate":
            if sender in _WORKER_ROLES and next_owner in _WORKER_ROLES and sender != next_owner:
                violations.append("ROUTING_P2P_WARNING")

        # Ensure next_owner is a known role
        known_roles = {"supervisor", "de", "ds", "me"}
        if next_owner not in known_roles:
            next_owner = "supervisor"

        status = "ok" if not violations else violations[0]
        self._violations += len([v for v in violations if not v.endswith("_WARNING")])
        self._turn_counter += 1

        # Write router event to log
        router_event = {
            "schema": "router.event.v2",
            "run_id": self.run_id,
            "turn_index": turn_message.get("turn_index", self._turn_counter),
            "sender": sender,
            "status": status,
            "violations": violations,
            "next_owner": next_owner,
            "protocol": self.protocol,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        try:
            write_router(self.bb_store, router_event)
        except Exception:
            pass  # Logging failure must not block execution

        return {
            "status": status,
            "violations": violations,
            "next_owner": next_owner,
        }
