# Session Progress

Read this after `AGENTS.md` and `WORKSPACE_INDEX.md` when starting a new session.

## Current Status

- Diagnosis pipeline is shipped and recently hardened.
- Neo4j-first TEP PDF KG v1 scaffolding landed on 2026-05-15:
  - new `tep_pdf_kg/` ingestion package now persists parser reports, normalized documents, chunks, raw claims, validated claims, and rejected claims per document
  - pilot runner `scripts/run_tep_pdf_kg_pipeline.py` supports the 2 target PDFs and optional Neo4j import
  - default parser execution is deterministic and fast via PyMuPDF normalization; native `opendataloader-pdf` / `Docling` activation is gated behind `TEP_KG_ENABLE_NATIVE_PARSERS=1`
  - `neo4j_kg.py` now exposes richer fault graph context (`symptoms`, `affected_units`, `suggested_actions`, `constraints`, `risks`) while preserving local fallback behavior
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
- KG ingestion verification passed on 2026-05-15:
  - `python -m py_compile neo4j_kg.py tep_pdf_kg\__init__.py tep_pdf_kg\schema.py tep_pdf_kg\parsers.py tep_pdf_kg\chunking.py tep_pdf_kg\extraction.py tep_pdf_kg\validation.py tep_pdf_kg\neo4j_import.py tep_pdf_kg\pipeline.py scripts\run_tep_pdf_kg_pipeline.py tests\test_neo4j_kg.py tests\test_tep_pdf_kg_pipeline.py`
  - `pytest tests\test_neo4j_kg.py tests\test_kg_match_fault.py tests\test_tep_pdf_kg_pipeline.py -q --basetemp .\_pytest_tmp_tepkg`
  - `python .\scripts\run_tep_pdf_kg_pipeline.py --output-root .\artifacts\tep_pdf_kg_smoke --doc DOWNS.pdf`
  - smoke-run result: full staged artifacts emitted for `DOWNS.pdf`; validated claim count remained `0` on raw parser output, so manual normalization review remains necessary before useful semantic extraction/import on the pilot PDFs

## Open Items

- Improve normalized parser quality for the pilot PDFs before relying on semantic extraction; current raw `DOWNS.pdf` smoke output is traceable but too OCR-noisy to yield useful claims without manual review or stronger parser mapping.
- Decide whether to add a real LLM-backed extractor path for `tep_pdf_kg/extraction.py` or keep v1 on heuristic/manual-reviewed artifacts until parser quality improves.
- Fix or triage the pre-existing `/diagnose` rate-limit regression in `tests/test_hardening.py::test_rate_limit_blocks_after_threshold`.
- Re-run live diagnosis evaluation items `gq10-12`; they were not yet revalidated live after the workflow hardening.
- Decide whether to further clean old commented legacy code blocks in `delegate_tools.py` and `router.py` now that the contract path is in place.

## Next Recommended Step

1. Review and correct the normalized pilot document artifacts for `DOWNS.pdf` and `Decentralized_control_of_the_Tennessee_E.pdf`, then rerun `scripts/run_tep_pdf_kg_pipeline.py` to validate non-zero claim extraction before attempting Neo4j import.
