# Bootstrap Refresh Plan

repo: `C:\Users\chengting\OneDrive\桌面\thesis_new\MAS_code\MT-phase-2`
output dir: `C:\Users\chengting\OneDrive\桌面\thesis_new\MAS_code\MT-phase-2\.bootstrap_refresh`

## Audit Summary

- `AGENTS.md`: `missing` - missing
- `CLAUDE.md`: `drift` - exists but does not satisfy the full-form contract
  - missing required section: Project Type
  - missing required section: Working Rules
  - missing required section: Fast Path
  - missing required section: Session Memory Rules
  - missing required section: Session End Rules
  - missing authority reference: SESSION_START.md
  - missing authority reference: WORKSPACE_INDEX.md
  - missing authority reference: CODEx_MEMORY.md
  - missing authority reference: SESSION_PROGRESS.md
- `SESSION_START.md`: `missing` - missing
- `WORKSPACE_INDEX.md`: `missing` - missing
- `CODEx_MEMORY.md`: `missing` - missing
- `SESSION_PROGRESS.md`: `missing` - missing

## Proposed Outputs

- write proposed `AGENTS.md` to `C:\Users\chengting\OneDrive\桌面\thesis_new\MAS_code\MT-phase-2\.bootstrap_refresh\AGENTS.md`
- write proposed `CLAUDE.md` to `C:\Users\chengting\OneDrive\桌面\thesis_new\MAS_code\MT-phase-2\.bootstrap_refresh\CLAUDE.md`
- write proposed `SESSION_START.md` to `C:\Users\chengting\OneDrive\桌面\thesis_new\MAS_code\MT-phase-2\.bootstrap_refresh\SESSION_START.md`
- write proposed `WORKSPACE_INDEX.md` to `C:\Users\chengting\OneDrive\桌面\thesis_new\MAS_code\MT-phase-2\.bootstrap_refresh\WORKSPACE_INDEX.md`
- write proposed `CODEx_MEMORY.md` to `C:\Users\chengting\OneDrive\桌面\thesis_new\MAS_code\MT-phase-2\.bootstrap_refresh\CODEx_MEMORY.md`
- write proposed `SESSION_PROGRESS.md` to `C:\Users\chengting\OneDrive\桌面\thesis_new\MAS_code\MT-phase-2\.bootstrap_refresh\SESSION_PROGRESS.md`

## Review Rules

- Review the proposed files before copying anything into the repo root.
- Merge any useful legacy content manually, especially from project-specific handoff or memory files.
- Treat these proposals as candidate replacements or starting points, not as automatic truth.
- Prefer `AGENTS.md` as the canonical operating contract and keep `CLAUDE.md` thin unless the repo truly needs a full-form Claude file.

## Content Routing Notes

- `What Exists`, `Important Files`, and `Data Locations` from an old `CODEx_MEMORY.md` are routed toward `WORKSPACE_INDEX.md`.
- Durable design and caution sections from an old `CODEx_MEMORY.md` are routed back into the proposed `CODEx_MEMORY.md`.
- `Current Goal` style sections from an old `CODEx_MEMORY.md` are routed toward `SESSION_PROGRESS.md`.

## Legacy Mapping Notes

- No built-in legacy mapping notes were detected.

## Candidate Content Sizes

- `AGENTS.md`: 45 lines
- `CLAUDE.md`: 13 lines
- `SESSION_START.md`: 18 lines
- `WORKSPACE_INDEX.md`: 32 lines
- `CODEx_MEMORY.md`: 23 lines
- `SESSION_PROGRESS.md`: 72 lines
