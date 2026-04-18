# mas/runtime/__init__.py
"""
Runtime Module for O-MAS Experiment Execution.

This module provides the main execution loop for running multi-agent
collaboration experiments.

Key Functions:
    - run_experiment: Execute a single experimental run

The runtime orchestrates:
    - Agent initialization with protocol-specific prompts
    - Turn-based execution with router validation
    - Blackboard I/O for shared memory communication
    - Event logging for metric extraction
    - Termination detection and finalization

Author: Cheng-Ting Chen
"""

from .loop import run_experiment

__all__ = ["run_experiment"]
