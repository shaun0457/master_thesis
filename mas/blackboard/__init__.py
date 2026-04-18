# mas/blackboard/__init__.py
"""
Blackboard Storage Layer for O-MAS Multi-Agent System.

The blackboard pattern provides a shared memory space where agents can
read and write artifacts (data, analysis results, plans, reports).
This enables asynchronous, loosely-coupled communication between agents.

Key Features:
    - Run isolation: Each experiment run has its own namespace
    - Schema validation: All writes validated against JSON schemas
    - Atomic writes: Uses temp file + rename for crash safety
    - Content hashing: SHA-256 for integrity verification

URI Format:
    bb://<namespace>/<artifact_name>

    Examples:
        bb://context/task.json      - Task context
        bb://data/xmeas_v1.csv      - Input dataset
        bb://analysis/correlation.json  - Analysis results
        bb://reports/final.md       - Final report

Author: Cheng-Ting Chen
Thesis: Observable Multi-Agent Systems (O-MAS)
"""

from .store import BlackboardStore

__all__ = ["BlackboardStore"]
