# CODEx Memory

This file stores durable, medium-term memory for `MT-phase-2`.

## Stable Decisions

- The repo uses a supervisor-plus-experts architecture: Supervisor -> Router -> ME/DE/DS.
- Shared repo operating rules should live in `AGENTS.md`; `CLAUDE.md` should stay wrapper-style.
- The current evaluation direction emphasizes context engineering, harness engineering, and regression gating over larger prompts.
- `tep_combined.db` is the main SQLite target for DE workflows.

## Domain Concepts

- `ME`: Machine Expert, responsible for document retrieval, knowledge lookup, and grounded synthesis.
- `DE`: Data Engineer, responsible for schema-aware SQL access and dataset export.
- `DS`: Data Scientist, responsible for Python analysis, statistics, and plotting.
- `TEP`: Tennessee Eastman Process benchmark used for fault diagnosis and process analysis.
- `IDV`: TEP disturbance or fault identifier used throughout evals and knowledge lookups.

## Important Paths

- `prompt/`: condition-specific prompt cards.
- `eval/`: golden QA and regression tooling.
- `tests/`: regression suite.
- `TEP_docs/`: domain references.
- `datasets/` and `artifacts/`: generated analysis outputs.

## Constraints

- Keep bootstrap startup truth in `SESSION_START.md` and current-session truth in `SESSION_PROGRESS.md`.
- Do not overload handoff files with generated artifact inventories or transient task logs.
- Avoid moving transient planning detail into `AGENTS.md` or `CLAUDE.md`.

## Open Questions

- Whether `PLAN.md` and `PROGRESS.md` should remain as compact archive documents or be retired completely later.
- Whether future session bootstrap should also reference any neighboring KG repo workflows explicitly.
