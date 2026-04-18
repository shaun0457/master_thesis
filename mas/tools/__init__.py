# mas/tools/__init__.py
"""
Tool stubs for O-MAS public release.

The actual dataset-dependent tools (SQLSandbox, RAGEngine) require proprietary
datasets that are not included in this public release. Agents degrade gracefully
when these tools are unavailable.
"""


class SQLSandbox:
    """Stub: SQL sandbox for TEP dataset queries (dataset not included)."""

    def __init__(self):
        raise ImportError(
            "SQLSandbox requires TEP dataset (not included in public release)"
        )


class RAGEngine:
    """Stub: RAG engine for TEP documentation queries (docs not included)."""

    def __init__(self):
        raise ImportError(
            "RAGEngine requires TEP docs (not included in public release)"
        )


class MLToolbox:
    """Stub: ML toolbox for model training (sklearn dataset not included)."""

    def __init__(self):
        raise ImportError(
            "MLToolbox requires scikit-learn and TEP dataset (not included in public release)"
        )


__all__ = ["SQLSandbox", "RAGEngine", "MLToolbox"]
