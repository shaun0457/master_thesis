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

## Verification

- Targeted regressions passed on 2026-05-14:
  - `pytest tests/test_workflow_hardening.py -q --basetemp .\_pytest_tmp_workflow`
  - `pytest tests/test_blackboard_unified.py -q --basetemp .\_pytest_tmp_unified2`
  - `pytest tests/test_bb_me_injection.py -q --basetemp .\_pytest_tmp_meinj`
  - `pytest tests/test_diagnose_flow.py -q --basetemp .\_pytest_tmp_diag2`

## Open Items

- Run the full regression suite again before the next live demo / eval.
- Re-run live diagnosis evaluation items `gq10-12`; they were not yet revalidated live after the workflow hardening.
- Fix remaining MAS2 workflow bugs found in review:
  - `delegate_tools._invoke_stage1()` caches graphs that close over per-call blackboard/P2P tool state.
  - `de_workflow.router_after_tool()` can hand off to DS after bare `sql_db_query` rowcount, bypassing `deliver_dataframe`.
  - `router.route_and_execute()` mutates `state["messages"]` and also returns the same messages, risking duplicate ToolMessages.
  - `delegate_tools._read_me_fault_facts()` still resolves run id from global `RUN_ID` instead of current state.
- Decide whether to further clean old commented legacy code blocks in workflow files after the runtime bugs are fixed.

## Next Recommended Step

1. Fix the remaining MAS2 workflow bugs above, then run the broader regression/eval pass.
