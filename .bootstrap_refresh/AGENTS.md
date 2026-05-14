# Agent Entry

New session bootstrap: read [SESSION_START.md](./SESSION_START.md) first.

## Purpose

This repository contains a research-grade multi-agent system for Tennessee Eastman Process analysis.

The codebase centers on a LangGraph supervisor that delegates industrial-domain questions to:

- a Machine Expert (`ME`) for document and knowledge retrieval
- a Data Engineer (`DE`) for SQLite access and dataset export
- a Data Scientist (`DS`) for Python-based analysis and plotting

## Operating Rules

- Treat [SESSION_START.md](./SESSION_START.md) as the single session bootstrap entry.
- Treat [WORKSPACE_INDEX.md](./WORKSPACE_INDEX.md) as the stable repo map.
- Treat [CODEx_MEMORY.md](./CODEx_MEMORY.md) as medium-term durable memory.
- Treat [SESSION_PROGRESS.md](./SESSION_PROGRESS.md) as the single source of truth for current state and next step.
- Do not use `PLAN.md` or `PROGRESS.md` as the startup source once the bootstrap set is adopted; they are legacy planning/history files.
- Keep shared operating rules in this file and keep [CLAUDE.md](./CLAUDE.md) thin.
- Before ending a meaningful work block, update [SESSION_PROGRESS.md](./SESSION_PROGRESS.md) if the phase, blockers, assumptions, or next step changed.

## Session Memory Rules

- Use [WORKSPACE_INDEX.md](./WORKSPACE_INDEX.md) for durable navigation, architecture entrypoints, and key folders.
- Use [CODEx_MEMORY.md](./CODEx_MEMORY.md) for stable project conventions, domain vocabulary, and non-transient constraints.
- Use [SESSION_PROGRESS.md](./SESSION_PROGRESS.md) for the active handoff, current phase, recent completions, and exactly one next action.
- If a decision only matters for the current work block, keep it in [SESSION_PROGRESS.md](./SESSION_PROGRESS.md), not here.

## Main Locations

- `chat_cli.py`: interactive entrypoint for running the MAS.
- `supervisor_workflow.py`, `router.py`, `delegate_tools.py`: top-level orchestration and delegation path.
- `me_workflow.py`, `de_workflow.py`, `ds_workflow_s2.py`: expert-agent workflows.
- `me_tools.py`, `de_tools.py`, `ds_tools.py`, `bb_tools.py`: agent tool surfaces.
- `context_assembler.py`, `llm_harness.py`, `llm_cache.py`, `judge.py`, `metrics.py`, `run_logger.py`: prompt assembly, harness, caching, judging, and observability.
- `tests/`: unit and integration regression suite.
- `eval/`: golden QA evaluation and regression gate scripts.
- `prompt/`: prompt cards for `debate`, `delphi`, and `ptow` conditions.
- `TEP_docs/`, `tep_knowledge.py`, `neo4j_kg.py`: domain documents and knowledge access.
- `datasets/`, `artifacts/`, `run_logs/`, `interactive_logs/`: generated runtime outputs.

## Session End Rules

Before ending a session:

- Update [SESSION_PROGRESS.md](./SESSION_PROGRESS.md) if current status, active artifacts, blockers, assumptions, or the next action changed.
- Update [WORKSPACE_INDEX.md](./WORKSPACE_INDEX.md) only if repo structure or canonical entrypoints changed.
- Update [CODEx_MEMORY.md](./CODEx_MEMORY.md) only when a convention, durable constraint, or domain decision should persist across many sessions.
