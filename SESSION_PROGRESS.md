# Session Progress

Read this after `AGENTS.md` and `WORKSPACE_INDEX.md` when starting a new session.

## Current Status

- Diagnosis pipeline is shipped and recently hardened.
- Blackboard is unified on `bb_tools.py`; delegate blackboard tools and diagnosis flow now use the canonical registry.
- MAS2 workflow control flow was hardened on 2026-05-14:
  - evidence checks now use the current `run_id`
  - router artifacts now default to workspace `runs/`
  - diagnosis-mode DE context no longer leaks `faultnumber=<predicted id>`
  - DE only hands off to DS after a real `deliver_dataframe` success
  - delegate subgraphs are rebuilt per call so state-bound blackboard/P2P tools do not leak across runs
  - router returns new `ToolMessage`s for LangGraph reducer merging instead of mutating `state["messages"]`
  - ME fault fact injection now prefers the current state `run_id` over the global environment

## Verification

- Targeted regressions passed on 2026-05-14:
  - `pytest tests/test_workflow_hardening.py -q --basetemp .\_pytest_tmp_workflow`
  - `pytest tests/test_blackboard_unified.py -q --basetemp .\_pytest_tmp_unified`
  - `pytest tests/test_bb_me_injection.py -q --basetemp .\_pytest_tmp_meinj`
  - `pytest tests/test_diagnose_flow.py -q --basetemp .\_pytest_tmp_diag`
- Broad regression run on 2026-05-14:
  - `pytest tests/ -q --basetemp .\_pytest_tmp_all`: 149 passed, 1 failed.
  - Failure reproduced alone: `tests/test_hardening.py::test_rate_limit_blocks_after_threshold` expected 429 on the 4th `/diagnose` request but got 200.

## Open Items

- Fix or triage the pre-existing `/diagnose` rate-limit regression in `tests/test_hardening.py::test_rate_limit_blocks_after_threshold`.
- Re-run live diagnosis evaluation items `gq10-12`; they were not yet revalidated live after the workflow hardening.
- Decide whether to further clean old commented legacy code blocks in workflow files after the runtime bugs are fixed.

## Next Recommended Step

1. Fix or triage the `/diagnose` rate-limit regression, then re-run the broad regression suite.
