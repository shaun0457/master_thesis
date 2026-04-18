#!/usr/bin/env python3
"""
Event reader module for loading JSONL event logs from runs.
"""
from typing import List, Dict, Any, Iterator
from pathlib import Path
import json


def read_jsonl(file_path: Path) -> Iterator[dict]:
    """
    Generator that yields one event dict per line.

    Args:
        file_path: Path to JSONL file

    Yields:
        dict: Parsed JSON object per line

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If line is not valid JSON

    Example:
        >>> for event in read_jsonl(Path("run.turn.v2.jsonl")):
        ...     print(event["turn_index"])
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Event file not found: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[WARN] Invalid JSON at {file_path}:{line_num}: {e}")
                continue


def load_turn_events(run_dir: str) -> List[dict]:
    """
    Load all run.turn.v2 events for a run.

    Args:
        run_dir: Path to data/runs/<run_id>/

    Returns:
        List of turn events, sorted by turn_index

    Example:
        >>> turns = load_turn_events("data/runs/R-2025-10-27-001")
        >>> print(f"Loaded {len(turns)} turns")
    """
    file_path = Path(run_dir) / "run.turn.v2.jsonl"
    if not file_path.exists():
        print(f"[WARN] Missing run.turn.v2.jsonl in {run_dir}")
        return []

    events = list(read_jsonl(file_path))
    # Sort by turn_index
    events.sort(key=lambda e: e.get("turn_index", 0))
    return events


def load_router_events(run_dir: str) -> List[dict]:
    """Load all router.event.v2 events."""
    file_path = Path(run_dir) / "router.event.v2.jsonl"
    if not file_path.exists():
        print(f"[WARN] Missing router.event.v2.jsonl in {run_dir}")
        return []
    return list(read_jsonl(file_path))


def load_bb_writes(run_dir: str) -> List[dict]:
    """Load all bb.write.v1 events."""
    file_path = Path(run_dir) / "bb.write.v1.jsonl"
    if not file_path.exists():
        print(f"[WARN] Missing bb.write.v1.jsonl in {run_dir}")
        return []
    return list(read_jsonl(file_path))


def load_bb_reads(run_dir: str) -> List[dict]:
    """Load all run.read.v1 events."""
    file_path = Path(run_dir) / "run.read.v1.jsonl"
    if not file_path.exists():
        print(f"[WARN] Missing run.read.v1.jsonl in {run_dir}")
        return []
    return list(read_jsonl(file_path))


def load_context(run_dir: str) -> Dict[str, Any]:
    """
    Load context.json (run metadata: protocol, seed, model, etc.)

    Args:
        run_dir: Path to data/runs/<run_id>/

    Returns:
        dict with keys: run_id, protocol, seed, model, temperature, ...
        Empty dict if context.json doesn't exist.

    Example:
        >>> ctx = load_context("data/runs/R-2025-10-27-001")
        >>> print(f"Protocol: {ctx['protocol']}, Seed: {ctx['seed']}")
    """
    file_path = Path(run_dir) / "context.json"
    if not file_path.exists():
        print(f"[WARN] Missing context.json in {run_dir}")
        return {}

    try:
        return json.loads(file_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid context.json in {run_dir}: {e}")
        return {}
