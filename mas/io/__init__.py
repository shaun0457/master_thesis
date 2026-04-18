# mas/io/__init__.py
"""
I/O and Metrics Module for O-MAS.

This module provides:
    - Event log reading and parsing
    - Process metric computation
    - Utility functions for timestamp handling

Key Functions:
    - compute_centralization: Freeman's degree centralization
    - compute_handoff_entropy: Shannon entropy of delegations
    - compute_ownership_gini: Gini coefficient of turn distribution
    - compute_loop_density: Cycle ratio in delegation graph
    - compute_reuse_and_orphan: Knowledge flow metrics

Author: Cheng-Ting Chen
"""

from .metrics import (
    compute_centralization,
    compute_handoff_entropy,
    compute_ownership_gini,
    compute_loop_density,
    compute_reuse_and_orphan,
    compute_read_delays,
    compute_readers_mean,
    aggregate_tdi_metrics,
    aggregate_policy_metrics
)

__all__ = [
    "compute_centralization",
    "compute_handoff_entropy",
    "compute_ownership_gini",
    "compute_loop_density",
    "compute_reuse_and_orphan",
    "compute_read_delays",
    "compute_readers_mean",
    "aggregate_tdi_metrics",
    "aggregate_policy_metrics"
]
