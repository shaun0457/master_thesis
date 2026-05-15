# Session Progress

Read this after `AGENTS.md` and `WORKSPACE_INDEX.md` when starting a new session.

## Current Status

- Diagnosis pipeline is shipped and recently hardened.
- Neo4j-first TEP PDF KG v1 scaffolding landed on 2026-05-15:
  - new `tep_pdf_kg/` ingestion package now persists parser reports, normalized documents, chunks, raw claims, validated claims, and rejected claims per document
  - pilot runner `scripts/run_tep_pdf_kg_pipeline.py` supports the 2 target PDFs, optional Neo4j import, and selectable claim extraction mode
  - parser stage was refactored on 2026-05-15 to be parser-native and Markdown-first: `opendataloader-pdf` now serves as the default canonical parser target, `Docling` remains the comparison/fallback path, and per-parser `document.md` / `document.json` / `parser_report.json` artifacts are emitted as the real handoff surface
  - canonical ingestion now selects parser-native Markdown as the semantic source of truth, supports reviewed Markdown override, and carries parser JSON forward as provenance metadata
  - chunking now reads canonical Markdown directly, preserves heading-aware chunk order, and attaches best-effort parser provenance (`page_start/page_end`, heading path, element refs, bbox when available)
  - pipeline extraction defaults are now Gemini-first with resumable chunk windows via `--start-chunk`, `--max-chunks`, and append-friendly raw claim writing
  - `neo4j_kg.py` now exposes richer fault graph context (`symptoms`, `affected_units`, `suggested_actions`, `constraints`, `risks`) while preserving local fallback behavior
  - `tep_pdf_kg/gemini_extractor.py` continues to support structured `chunk -> claims` extraction, while heuristic extraction remains as fallback/test mode rather than the recommended primary path
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
- Gemini extractor plumbing verification passed on 2026-05-15:
  - `python -m py_compile tep_pdf_kg\gemini_extractor.py scripts\run_tep_pdf_kg_pipeline.py tests\test_tep_pdf_kg_pipeline.py`
  - `pytest tests\test_tep_pdf_kg_pipeline.py tests\test_neo4j_kg.py tests\test_kg_match_fault.py -q --basetemp .\_pytest_tmp_gemkg`
  - current limitation: no live Gemini extraction run was executed in-session, so the new `--extractor gemini` path is unit-verified but not yet validated against the real pilot PDFs and API responses
- Parser-native Markdown-first KG verification passed on 2026-05-15:
  - `python -m py_compile tep_pdf_kg\schema.py tep_pdf_kg\parsers.py tep_pdf_kg\chunking.py tep_pdf_kg\pipeline.py scripts\run_tep_pdf_kg_pipeline.py tests\test_tep_pdf_kg_pipeline.py`
  - `pytest tests\test_tep_pdf_kg_pipeline.py tests\test_neo4j_kg.py tests\test_kg_match_fault.py -q --basetemp .\_pytest_tmp_tepkg_md_native`
  - current limitation: the refactor is unit/integration verified with mocked native parser entrypoints, but no in-session live `opendataloader-pdf` / `Docling` run was executed yet against the pilot PDFs
- Live `opendataloader-pdf` environment check passed on 2026-05-15:
  - local environment already has `opendataloader-pdf 2.4.3` and `OpenJDK 24.0.1`
  - real `opendataloader_pdf.convert(..., format="markdown,json")` succeeded on `TEP_docs\DOWNS.pdf` and emitted `artifacts\tep_pdf_kg_odl_check\DOWNS.md` plus `DOWNS.json`
  - sandbox note: the first in-sandbox run failed with `AccessDeniedException` on the Java security file under the local JDK path, while the same conversion succeeded when re-run outside the sandbox

## Open Items

- Run the parser-native pipeline against the pilot PDFs with live `opendataloader-pdf` and `Docling` installs, then inspect canonical Markdown quality before further prompt tuning.
- Run `scripts/run_tep_pdf_kg_pipeline.py --extractor gemini` against the pilot PDFs with a real API key and compare claim yield/quality against the current heuristic baseline and reviewed-Markdown path.
- Fix or triage the pre-existing `/diagnose` rate-limit regression in `tests/test_hardening.py::test_rate_limit_blocks_after_threshold`.
- Re-run live diagnosis evaluation items `gq10-12`; they were not yet revalidated live after the workflow hardening.
- Decide whether to further clean old commented legacy code blocks in `delegate_tools.py` and `router.py` now that the contract path is in place.

## Next Recommended Step

1. Run `scripts/run_tep_pdf_kg_pipeline.py --doc Decentralized_control_of_the_Tennessee_E.pdf --extractor gemini --start-chunk 0 --max-chunks <small batch>` with live native parsers enabled, inspect `canonical_document.md`, `claims.raw.jsonl`, and `claims.validated.jsonl`, then decide whether parser cleanup or Gemini prompt/schema tuning is the higher-leverage next step before Neo4j import.
