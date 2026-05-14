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

- The bootstrap set has been promoted into the repo root on 2026-05-14.
- `AGENTS.md`, `SESSION_START.md`, `WORKSPACE_INDEX.md`, `CODEx_MEMORY.md`, and `SESSION_PROGRESS.md` are now the authoritative session files.
- `CLAUDE.md` has been reduced to a wrapper around `AGENTS.md`.
- `PLAN.md` and `PROGRESS.md` have been reduced to legacy archive documents to avoid conflicting with the bootstrap flow.
- The latest recorded regression baseline from the legacy progress log is `pytest tests/ -q -> 85 passed` on 2026-05-13.
- The latest recorded live evaluation baseline from the legacy progress log is `9/9 PASS` on 2026-05-13.

## Current Phase

Phase: post-bootstrap normalization

## Completed Recently

- Ran a bootstrap audit and generated non-destructive refresh proposals.
- Promoted the bootstrap file set from `.bootstrap_refresh/` into the repo root.
- Consolidated overlapping session guidance across `CLAUDE.md`, `PLAN.md`, and `PROGRESS.md`.
- Created a pre-migration rollback snapshot commit before promoting the new root files.

## Current Working Assumptions

- New sessions should start from `SESSION_START.md`, not from the legacy handoff files.
- The repo is still actively evolving around eval reliability, regression gating, and TEP fault-analysis workflows.
- The old detailed milestone history remains available in git history if the compact archive files are not sufficient.

## Next Recommended Step

Current next action:

1. Resume normal repo work using `SESSION_START.md` and keep future live status updates only in `SESSION_PROGRESS.md`.

## Open Tasks

- Decide later whether `PLAN.md` and `PROGRESS.md` should remain as lightweight archive stubs or be removed entirely.
- If another active engineering track becomes the main focus, rewrite this file to reflect that work instead of adding status elsewhere.

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
