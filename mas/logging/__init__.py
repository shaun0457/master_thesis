# mas/logging/__init__.py
"""
Event Logging Module for O-MAS Observability Pipeline.

This module provides structured event logging for multi-agent experiments.
All agent interactions are captured as typed events in JSONL format,
enabling post-hoc extraction of behavioral signals and process metrics.

Event Types:
    - Turn Events (run.turn.v2): Agent actions and messages
    - Router Events (router.event.v2): Protocol validation decisions
    - Write Events (bb.write.v1): Blackboard artifact creation
    - Read Events (run.read.v1): Blackboard artifact access

Usage:
    from mas.logging.event_writer import write_turn, write_bb_write, write_read

    # Log an agent turn
    write_turn(store, turn_event)

    # Log a blackboard write
    write_bb_write(store, write_event)

Author: Cheng-Ting Chen
Thesis: Observable Multi-Agent Systems (O-MAS)
"""

from .event_writer import write_turn, write_router, write_bb_write, write_read

__all__ = ["write_turn", "write_router", "write_bb_write", "write_read"]
