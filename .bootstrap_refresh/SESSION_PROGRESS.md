# Session Progress

Read this after `AGENTS.md` and `WORKSPACE_INDEX.md` when starting a new session.

## Purpose

This file is the short-horizon working memory for active development in `MT-phase-2`.

Use it for:

- what was just finished
- what is currently true
- what should happen next
- blockers, assumptions, and temporary decisions

Do not use it for long-term architecture explanation. That belongs in:

- [CODEx_MEMORY.md](./CODEx_MEMORY.md)
- [WORKSPACE_INDEX.md](./WORKSPACE_INDEX.md)

## Current Status

- Bootstrap audit was run on 2026-05-14.
- Existing repo-root handoff files are mixed-format: `CLAUDE.md` exists, but `AGENTS.md`, `SESSION_START.md`, `WORKSPACE_INDEX.md`, `CODEx_MEMORY.md`, and `SESSION_PROGRESS.md` are missing.
- Legacy planning/history files already exist in the repo root: `PLAN.md` and `PROGRESS.md`.
- The latest recorded regression baseline in `PROGRESS.md` is `pytest tests/ -q -> 85 passed` on 2026-05-13.
- The latest recorded live evaluation baseline in `PROGRESS.md` is `9/9 PASS` on 2026-05-13.

## Current Phase

Phase: bootstrap migration review

## Completed Recently

- Ran the session-bootstrap audit and confirmed contract drift in the existing repo-root `CLAUDE.md`.
- Generated non-destructive refresh proposals under `.bootstrap_refresh/`.
- Customized the candidate bootstrap files with this repo's actual architecture, entrypoints, and current status.

## Current Working Assumptions

- The user wants bootstrap standardization without overwriting current repo-root files automatically.
- `PROGRESS.md` remains the richest source for recent implementation history until the new bootstrap set is promoted.
- The repo is still actively evolving around eval reliability, regression gating, and TEP fault-analysis workflows.

## Next Recommended Step

Current next action:

1. Review `.bootstrap_refresh/` and decide whether to promote the proposed bootstrap files into the repo root.

## Open Tasks

- If the bootstrap set is accepted, merge or retire overlapping legacy guidance from `CLAUDE.md`, `PLAN.md`, and `PROGRESS.md`.
- After migration, keep only one authoritative current-state file: `SESSION_PROGRESS.md`.
- Preserve the current project workstream around regression-gate automation and any remaining DS live-eval issues when rewriting the handoff.

## Update Rules

Update this file when:

- the next practical step changes
- the phase changes
- a blocker changes what the next session should do
- a major assumption is added or removed

Keep updates short and operational.

## Session Discipline

- `SESSION_START.md` is the only startup entry.
- `SESSION_PROGRESS.md` is the single source of truth for current status and next action.
- At the end of every substantial work block, update this file before ending the turn when the working state changed.
