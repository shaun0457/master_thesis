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
- MAS2 internal delegation/runtime refactor landed on 2026-05-14:
  - canonical subagent contract models now live in `subagent_contracts.py`
  - delegate routing normalizes into structured tickets and delegate requests with lineage/depth fields
  - subgraph invocation now builds `ContextPack`-style contract/evidence/history-tail inputs with runtime limits
  - handoff validation is explicit for `ME -> DE`, `DE -> DS`, and `DS -> Supervisor`
  - `deliver_dataframe` now returns `artifact_id` and `columns` so DS-ready dataset gating is schema-backed
- Local diagnosis test automation landed on 2026-05-14:
  - `scripts/run_diagnose_checks.py` can run inline/window API smoke checks without manually starting uvicorn
  - the script also exposes pytest slices for diagnosis API coverage

## Verification

- Targeted regressions passed on 2026-05-14:
  - `pytest tests/test_workflow_hardening.py -q --basetemp .\_pytest_tmp_workflow`
  - `pytest tests/test_blackboard_unified.py -q --basetemp .\_pytest_tmp_unified`
  - `pytest tests/test_bb_me_injection.py -q --basetemp .\_pytest_tmp_meinj`
  - `pytest tests/test_diagnose_flow.py -q --basetemp .\_pytest_tmp_diag`
- Contract/runtime verification passed on 2026-05-14:
  - `python -m py_compile subagent_contracts.py context_assembler.py delegate_tools.py router.py common.py de_tools.py`
  - `pytest tests/test_subagent_contracts.py tests/test_context_assembler.py tests/test_workflow_hardening.py -q --basetemp .\_pytest_tmp_contracts`
  - `pytest tests/test_bb_me_injection.py tests/test_blackboard_unified.py -q --basetemp .\_pytest_tmp_contracts2`
- Local test script verification passed on 2026-05-14:
  - `python .\scripts\run_diagnose_checks.py --mode window-mock`
  - `python .\scripts\run_diagnose_checks.py --mode pytest-api`
  - `python -m py_compile .\scripts\run_diagnose_checks.py`
- Broad regression run on 2026-05-14:
  - `pytest tests/ -q --basetemp .\_pytest_tmp_all`: 149 passed, 1 failed.
  - Failure reproduced alone: `tests/test_hardening.py::test_rate_limit_blocks_after_threshold` expected 429 on the 4th `/diagnose` request but got 200.

## Open Items

- Fix or triage the pre-existing `/diagnose` rate-limit regression in `tests/test_hardening.py::test_rate_limit_blocks_after_threshold`.
- Re-run live diagnosis evaluation items `gq10-12`; they were not yet revalidated live after the workflow hardening.
- Decide whether to further clean old commented legacy code blocks in `delegate_tools.py` and `router.py` now that the contract path is in place.

## Next Recommended Step

1. Re-run the broad regression suite against the new contract runtime, then fix or triage the remaining `/diagnose` rate-limit regression if it still reproduces.
