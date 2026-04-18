# mas/enrich/__init__.py
"""
Post-hoc Metric Enrichment Module for O-MAS.

This module provides functions for enriching event logs with additional
metrics computed after the experiment run completes.

Enrichment Types:
    - TDI (Topic Drift Index): Semantic drift from original goal
    - Policy: Protocol adherence and violation metrics

These enrichments require embedding computation (TDI) or policy rule
evaluation that cannot be done during real-time execution.

Author: Cheng-Ting Chen
"""

from .tdi import compute_tdi_for_run
from .policy import compute_policy_for_run

__all__ = ["compute_tdi_for_run", "compute_policy_for_run"]
