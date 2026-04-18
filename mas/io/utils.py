#!/usr/bin/env python3
"""
Utility functions for timestamp parsing, hashing, and validation.
"""
from datetime import datetime
from pathlib import Path
import hashlib
import json
from typing import Any, Dict


def parse_timestamp(ts_str: str) -> datetime:
    """
    Parse ISO8601 timestamp to datetime (UTC).

    Handles formats:
        - "2025-10-27T12:00:00Z"
        - "2025-10-27T12:00:00.123Z"
        - "2025-10-27T12:00:00+00:00"

    Args:
        ts_str: ISO8601 timestamp string

    Returns:
        datetime object in UTC

    Raises:
        ValueError: If timestamp format is invalid

    Example:
        >>> ts = parse_timestamp("2025-10-27T12:00:00Z")
        >>> print(ts.isoformat())
        2025-10-27T12:00:00+00:00
    """
    if not ts_str:
        raise ValueError("Empty timestamp string")

    # Handle 'Z' suffix
    if ts_str.endswith('Z'):
        ts_str = ts_str[:-1] + '+00:00'

    try:
        return datetime.fromisoformat(ts_str)
    except ValueError as e:
        raise ValueError(f"Invalid timestamp format: {ts_str}") from e


def compute_data_hash(run_dir: str) -> str:
    """
    Compute SHA-256 hash of all event files in a run.

    Args:
        run_dir: Path to data/runs/<run_id>/

    Returns:
        SHA-256 hash with "sha256:" prefix

    Example:
        >>> hash_val = compute_data_hash("data/runs/R-2025-10-27-001")
        >>> print(hash_val)
        sha256:a3b4c5d6...
    """
    hasher = hashlib.sha256()

    event_files = [
        "run.turn.v2.jsonl",
        "router.event.v2.jsonl",
        "bb.write.v1.jsonl",
        "run.read.v1.jsonl"
    ]

    for fname in sorted(event_files):  # Sort for determinism
        fpath = Path(run_dir) / fname
        if fpath.exists():
            hasher.update(fpath.read_bytes())

    return "sha256:" + hasher.hexdigest()


def hash_content(obj: Dict[str, Any]) -> str:
    """
    Compute SHA-256 hash of a JSON object (canonical form).

    Args:
        obj: Dictionary to hash

    Returns:
        SHA-256 hash with "sha256:" prefix
    """
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def check_run_completeness(run_dir: str) -> Dict[str, Any]:
    """
    Check if run has all required event files.

    Args:
        run_dir: Path to data/runs/<run_id>/

    Returns:
        Dict with keys:
            - complete (bool): True if all required files exist
            - missing (List[str]): List of missing file names
            - status (str): "complete" or "partial"

    Example:
        >>> result = check_run_completeness("data/runs/R-2025-10-27-001")
        >>> if not result["complete"]:
        ...     print(f"Missing: {result['missing']}")
    """
    required_files = [
        "run.turn.v2.jsonl",
        "router.event.v2.jsonl",
        "context.json"
    ]

    missing = []
    for fname in required_files:
        if not (Path(run_dir) / fname).exists():
            missing.append(fname)

    complete = len(missing) == 0
    status = "complete" if complete else "partial"

    return {
        "complete": complete,
        "missing": missing,
        "status": status
    }
