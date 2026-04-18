# mas/logging/event_writer.py
"""
Event Writers for O-MAS Observability Pipeline.

This module provides functions for writing structured events to JSONL log files.
These events form the basis for post-hoc metric extraction and analysis.
All events are validated against JSON Schemas before writing.

Event Types:
    - run.turn.v2: Agent turn events (message, intent, action, metrics)
    - router.event.v2: Router validation events (violations, next_owner)
    - bb.write.v1: Blackboard write events (artifact creation)
    - run.read.v1: Blackboard read events (artifact access)

Key Features:
    1. Schema Validation: All events validated before writing
    2. Role Normalization: Converts role names to lowercase canonical form
    3. Anti-Contamination: Blocks external URLs in event data
    4. Auto-Fill: Automatically populates run_id from store context
    5. Append-Only: Events written to JSONL for crash-safe logging

Output Files (under data/runs/<run_id>/):
    - run.turn.v2.jsonl: All agent turn events
    - router.event.v2.jsonl: Router validation decisions
    - bb.write.v1.jsonl: Blackboard write operations
    - run.read.v1.jsonl: Blackboard read operations

These logs enable extraction of O-MAS behavioral signals:
    - Communication patterns (C, H, G)
    - Knowledge flow (reuse, orphan, t_first_read)
    - Stability indicators (loop_density, TDI)
    - Governance metrics (adherence, violations)

Author: Cheng-Ting Chen
Thesis: Observable Multi-Agent Systems (O-MAS)
"""

import json
import re
from pathlib import Path
from typing import Any, Dict
import jsonschema


# =============================================================================
# ANTI-CONTAMINATION PATTERNS
# =============================================================================
# These patterns detect external URLs that should not appear in experimental data.
# This prevents agents from accessing or referencing external knowledge sources,
# ensuring controlled experimental conditions.

FORBIDDEN_URL_PATTERNS = [
    r'https?://',   # HTTP/HTTPS URLs only — domain suffixes are legitimate in filenames
]

# Module-level schema cache: avoids re-reading schema files on every event write
_SCHEMA_CACHE: Dict[str, Any] = {}


# =============================================================================
# HELPERS
# =============================================================================

def _runs_dir(store) -> Path:
    """Return the run output directory path for the given store."""
    return Path(__file__).parents[2] / "data" / "runs" / store.run_id


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_against_schema(obj: dict, schema_id: str) -> None:
    """
    Validate a dictionary against a JSON Schema.

    JSON Schemas define the required structure and types for event data.
    Validation catches structural errors early, preventing corrupt logs
    that would break downstream analysis.

    Args:
        obj: Dictionary to validate.
        schema_id: Schema identifier matching filename in /schema/ directory.
                   Examples: "run.turn.v2", "bb.write.v1", "run.read.v1"

    Raises:
        jsonschema.ValidationError: If obj doesn't match schema.
            Error message includes path to invalid field.
        FileNotFoundError: If schema file doesn't exist.

    Example:
        >>> validate_against_schema(
        ...     {"turn_index": 5, "role": "supervisor", "message": "..."},
        ...     "run.turn.v2"
        ... )
    """
    if schema_id not in _SCHEMA_CACHE:
        schema_path = Path(__file__).parents[2] / "schema" / f"{schema_id}.json"
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema not found: {schema_path}")
        with open(schema_path, 'r', encoding='utf-8') as f:
            _SCHEMA_CACHE[schema_id] = json.load(f)

    jsonschema.validate(instance=obj, schema=_SCHEMA_CACHE[schema_id])


def _normalize_role(role: str) -> str:
    """
    Normalize agent role name to lowercase canonical form.

    This ensures consistent role identifiers across all events,
    regardless of how agents report their role names.

    Canonical Forms:
        - "Supervisor" / "SUPERVISOR" / "supervisor" → "supervisor"
        - "DE" / "DataEngineer" / "de" → "de"
        - "DS" / "DataScientist" / "ds" → "ds"
        - "ME" / "MachineExpert" / "me" → "me"

    Args:
        role: Raw role string from agent.

    Returns:
        str: Lowercase canonical role name.
    """
    role_map = {
        "Supervisor": "supervisor",
        "DE": "de",
        "DS": "ds",
        "ME": "me"
    }
    return role_map.get(role, role.lower())


def _check_contamination(obj: dict) -> None:
    """
    Check for external URL contamination in event data.

    Anti-contamination is critical for controlled experiments. If agents
    reference external URLs, it indicates they may be accessing knowledge
    outside the experimental context, invalidating results.

    Args:
        obj: Dictionary to check.

    Raises:
        ValueError: If any forbidden URL pattern is detected.
            Includes the specific pattern found.

    Example:
        >>> _check_contamination({"message": "See https://example.com"})
        ValueError: Anti-contamination violation: detected 'https?://'
    """
    obj_str = json.dumps(obj)
    for pattern in FORBIDDEN_URL_PATTERNS:
        if re.search(pattern, obj_str, re.IGNORECASE):
            raise ValueError(
                f"Anti-contamination violation: detected forbidden pattern '{pattern}' "
                f"in event. External URLs are prohibited."
            )


def _auto_fill_run_id(ev: dict, run_id: str) -> dict:
    """
    Auto-fill run_id field if missing; validate if present.

    Ensures all events are tagged with the correct run identifier
    for proper association during analysis.

    Args:
        ev: Event dictionary (may or may not have run_id).
        run_id: Expected run identifier from BlackboardStore.

    Returns:
        dict: Event with run_id field populated.

    Raises:
        ValueError: If event has different run_id than expected.
            This indicates a bug where events from different runs
            are being mixed.
    """
    if "run_id" in ev:
        if ev["run_id"] != run_id:
            raise ValueError(
                f"run_id mismatch: event has '{ev['run_id']}', "
                f"but store expects '{run_id}'"
            )
    else:
        ev["run_id"] = run_id
    return ev


def _normalize_roles_in_event(ev: dict) -> dict:
    """
    Normalize all role-related fields in an event to lowercase.

    Multiple fields may contain role names:
        - role: Primary role of the event originator
        - sender: Message sender (for routing events)
        - recipient: Message recipient (for delegation)
        - writer_role: Author of blackboard write
        - reader_role: Reader of blackboard artifact

    Args:
        ev: Event dictionary with potential role fields.

    Returns:
        dict: Event with all role fields normalized.
    """
    if "role" in ev:
        ev["role"] = _normalize_role(ev["role"])
    if "sender" in ev:
        ev["sender"] = _normalize_role(ev["sender"])
    if "recipient" in ev and ev["recipient"] is not None:
        ev["recipient"] = _normalize_role(ev["recipient"])
    if "writer_role" in ev:
        ev["writer_role"] = _normalize_role(ev["writer_role"])
    if "reader_role" in ev:
        ev["reader_role"] = _normalize_role(ev["reader_role"])
    return ev


# =============================================================================
# EVENT WRITERS
# =============================================================================

def write_turn(store, ev: dict) -> None:
    """
    Write a turn event (run.turn.v2) to the turn log.

    Turn events capture each agent action during experiment execution.
    They are the primary source for extracting behavioral signals.

    Event Contents (run.turn.v2 schema):
        - run_id: Experiment run identifier
        - turn_index: Sequential turn number (0-based)
        - role: Agent role (supervisor, de, ds, me)
        - message: Full text of agent's response
        - intent: Classified intent (delegate, analyze, report, etc.)
        - action: Structured action details (target, task_id, etc.)
        - metrics_trace: Runtime metrics (latency, token counts)
        - blackboard_refs: List of bb:// URIs referenced
        - ts: ISO 8601 timestamp

    Output File:
        data/runs/<run_id>/run.turn.v2.jsonl

    Args:
        store: BlackboardStore instance providing run context.
        ev: Turn event dictionary conforming to run.turn.v2 schema.

    Raises:
        ValueError: On contamination detection or run_id mismatch.
        jsonschema.ValidationError: If event doesn't match schema.

    Example:
        >>> write_turn(store, {
        ...     "turn_index": 5,
        ...     "role": "supervisor",
        ...     "message": "I'm delegating data analysis to DS...",
        ...     "intent": "delegate",
        ...     "action": {"target": "ds", "task_id": "analyze-001"},
        ...     "ts": "2024-11-15T14:30:22Z"
        ... })
    """
    # Pre-processing: auto-fill and normalize
    ev = _auto_fill_run_id(ev, store.run_id)
    ev = _normalize_roles_in_event(ev)

    # Safety check: no external URLs
    _check_contamination(ev)

    # Schema validation
    validate_against_schema(ev, "run.turn.v2")

    # Write to JSONL file (append mode)
    runs_dir = _runs_dir(store)
    event_file = runs_dir / "run.turn.v2.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)

    with open(event_file, 'a', encoding='utf-8') as f:
        json.dump(ev, f, ensure_ascii=False, sort_keys=True)
        f.write('\n')


def write_router(store, ev: dict) -> None:
    """
    Write a router validation event (router.event.v2) to the router log.

    Router events capture the protocol enforcement decisions made by
    the Router component. They record violations, warnings, and
    next-agent determinations.

    Event Contents (router.event.v2 schema):
        - run_id: Experiment run identifier
        - turn_index: Turn this routing applies to
        - sender: Agent that sent the message
        - recipient: Intended recipient (if delegation)
        - status: Routing decision (ok, violation, warning)
        - violations: List of protocol rule violations
        - next_owner: Agent to act next
        - ts: ISO 8601 timestamp

    Output File:
        data/runs/<run_id>/router.event.v2.jsonl

    Used to calculate:
        - Adherence (A): 1 - (violations / total_events)
        - Violation rate (V): violations / total_events

    Args:
        store: BlackboardStore instance.
        ev: Router event dictionary.

    Raises:
        ValueError: On contamination or run_id mismatch.
        jsonschema.ValidationError: If event doesn't match schema.
    """
    ev = _auto_fill_run_id(ev, store.run_id)
    ev = _normalize_roles_in_event(ev)
    _check_contamination(ev)
    validate_against_schema(ev, "router.event.v2")

    runs_dir = _runs_dir(store)
    event_file = runs_dir / "router.event.v2.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)

    with open(event_file, 'a', encoding='utf-8') as f:
        json.dump(ev, f, ensure_ascii=False, sort_keys=True)
        f.write('\n')


def write_bb_write(store, ev: dict) -> None:
    """
    Write a blackboard write event (bb.write.v1) to the writes log.

    Write events capture when agents create artifacts on the blackboard.
    They enable tracking knowledge creation and flow patterns.

    Event Contents (bb.write.v1 schema):
        - run_id: Experiment run identifier
        - write_id: Unique write identifier
        - turn_index: Turn when write occurred
        - writer_role: Agent that wrote the artifact
        - topic_id: Logical topic/namespace
        - artifact: bb:// URI of written artifact
        - artifact_kind: Type (text, json, csv, plan, etc.)
        - refs_out: URIs referenced by this artifact
        - ts: ISO 8601 timestamp

    Output File:
        data/runs/<run_id>/bb.write.v1.jsonl

    Used to calculate:
        - Orphan rate: writes never read by others
        - Knowledge creation patterns per role

    Args:
        store: BlackboardStore instance.
        ev: Write event dictionary.

    Raises:
        ValueError: On contamination or run_id mismatch.
        jsonschema.ValidationError: If event doesn't match schema.
    """
    ev = _auto_fill_run_id(ev, store.run_id)
    ev = _normalize_roles_in_event(ev)
    _check_contamination(ev)
    validate_against_schema(ev, "bb.write.v1")

    runs_dir = _runs_dir(store)
    event_file = runs_dir / "bb.write.v1.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)

    with open(event_file, 'a', encoding='utf-8') as f:
        json.dump(ev, f, ensure_ascii=False, sort_keys=True)
        f.write('\n')


def write_read(store, ev: dict) -> None:
    """
    Write a blackboard read event (run.read.v1) to the reads log.

    Read events capture when agents access artifacts from the blackboard.
    Combined with write events, they enable knowledge flow analysis.

    Event Contents (run.read.v1 schema):
        - run_id: Experiment run identifier
        - read_id: Unique read identifier
        - turn_index: Turn when read occurred
        - reader_role: Agent that read the artifact
        - artifact: bb:// URI of read artifact
        - artifact_kind: Type of artifact
        - read_purpose: Why the read was performed
        - write_ref: Reference to original write event
            - event_id: Original write_id
            - turn_index: Turn of original write
            - writer_role: Original author
        - ts: ISO 8601 timestamp

    Output File:
        data/runs/<run_id>/run.read.v1.jsonl

    Used to calculate:
        - Reuse rate: writes read by others / total writes
        - t_first_read: Time from write to first read
        - Knowledge flow patterns (who reads whose work)

    Args:
        store: BlackboardStore instance.
        ev: Read event dictionary.

    Raises:
        ValueError: On contamination or run_id mismatch.
        jsonschema.ValidationError: If event doesn't match schema.
    """
    ev = _auto_fill_run_id(ev, store.run_id)
    ev = _normalize_roles_in_event(ev)
    _check_contamination(ev)
    validate_against_schema(ev, "run.read.v1")

    runs_dir = _runs_dir(store)
    event_file = runs_dir / "run.read.v1.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)

    with open(event_file, 'a', encoding='utf-8') as f:
        json.dump(ev, f, ensure_ascii=False, sort_keys=True)
        f.write('\n')
