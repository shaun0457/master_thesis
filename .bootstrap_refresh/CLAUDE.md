@AGENTS.md

# Claude Notes

Use [AGENTS.md](./AGENTS.md) as the canonical repo operating contract for this repository.

## Claude-Specific Notes

- Keep this file thin.
- Put shared rules, startup flow, and session-end obligations in [AGENTS.md](./AGENTS.md).
- When migrating from the current repo root, preserve useful repo-specific detail from the existing `CLAUDE.md` by moving durable shared rules into `AGENTS.md` and moving transient status into `SESSION_PROGRESS.md`.
