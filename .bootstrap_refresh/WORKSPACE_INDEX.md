# Workspace Index

Read this first when resuming work in this repo after the startup file.

## Current Focus

`MT-phase-2` is a LangGraph-based multi-agent system for industrial process analysis on the Tennessee Eastman Process benchmark, with an emphasis on delegation quality, evaluation, and production-style observability.

## Core Entry Files

- [SESSION_START.md](./SESSION_START.md): session bootstrap entry.
- [AGENTS.md](./AGENTS.md): canonical operating contract.
- [CODEx_MEMORY.md](./CODEx_MEMORY.md): durable decisions and domain memory.
- [SESSION_PROGRESS.md](./SESSION_PROGRESS.md): active state and next action.
- `README.md`: project overview and usage.
- `README_zh-TW.md`: Chinese overview.

## Main Locations

- `chat_cli.py`: CLI entrypoint for interactive runs.
- `supervisor_workflow.py`, `router.py`, `delegate_tools.py`, `supervisor_tools.py`: orchestration and delegation.
- `me_workflow.py`, `de_workflow.py`, `ds_workflow_s2.py`: agent workflows.
- `me_tools.py`, `de_tools.py`, `ds_tools.py`, `bb_tools.py`: tool layer.
- `context_assembler.py`, `prompt_builder.py`, `prompt/`: prompt and context assembly.
- `llm_harness.py`, `llm_cache.py`, `judge.py`, `metrics.py`, `run_logger.py`, `harness_callback.py`: runtime control and observability.
- `eval/`: `run_eval.py`, `regression_gate.py`, and eval helpers.
- `tests/`: unit and integration tests.
- `scripts/build_tep_combined_db.py`: combined SQLite build script.
- `TEP_docs/`: PDFs and Markdown domain references.
- `datasets/`, `artifacts/`, `run_logs/`, `interactive_logs/`: generated outputs and logs.
- `tep_combined.db`: primary combined TEP SQLite database used by the DE path.

## Stable Conventions

- Prompt-condition assets live under `prompt/` and support `debate`, `delphi`, and `ptow`.
- Evaluation assets live under `eval/` and should be kept aligned with regression expectations.
- Runtime-generated datasets and plots should stay out of handoff documents except when directly relevant to the current session.

## Session Resume Rule

In a new session, start with [SESSION_START.md](./SESSION_START.md) and use [SESSION_PROGRESS.md](./SESSION_PROGRESS.md) for the immediate next step.
