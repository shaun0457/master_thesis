# Session Progress

Read this after `AGENTS.md` and `WORKSPACE_INDEX.md` when starting a new session.

## Current Status

- Diagnosis pipeline is shipped and recently hardened.
- Neo4j-first TEP PDF KG v1 is landed and operational:
  - parser-native Markdown-first ingestion exists under `tep_pdf_kg/`
  - chunk checkpointing and `--resume` are in place
  - Gemini prompt slimming and structured-output fallback are in place
  - standalone markdown fusion exists under `tep_pdf_kg/markdown_fusion.py`
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
- Gemini extractor tolerance hardening passed on 2026-05-15:
  - `tep_pdf_kg\gemini_extractor.py` now falls back from strict structured parsing to tolerant JSON extraction, keeps valid claims, and drops malformed partial items instead of aborting the whole document run
  - `python -m py_compile tep_pdf_kg\gemini_extractor.py tests\test_tep_pdf_kg_pipeline.py`
  - `pytest tests\test_tep_pdf_kg_pipeline.py -q --basetemp .\_pytest_tmp_gemini_tolerant2`
- Live Gemini KG run status on 2026-05-15:
  - full pipeline run with `.env`-loaded API key confirmed real `opendataloader-pdf` parser execution and real Gemini extraction calls
  - pre-hardening failure mode: Gemini sometimes returned partially malformed structured claims, which previously crashed the run
  - post-hardening failure mode: the full all-doc run no longer failed fast on malformed claim items, but the end-to-end Gemini pass still exceeded the command timeout when run monolithically
  - partial live artifact note: `artifacts\tep_pdf_kg_gemini_live_full_retry2\DOWNS\claims.raw.jsonl` was populated during the live run, confirming chunk-level extraction progress before timeout
- Chunk-checkpoint KG execution landed on 2026-05-15:
  - extraction stage now writes per-chunk artifacts under `chunk_claims/` and an append-only `extract_status.jsonl` ledger
  - `--resume` now skips `succeeded` chunks and retries `failed` / stale `running` chunks based on chunk-level state rather than raw file append position
  - final `claims.raw.jsonl`, `claims.validated.jsonl`, and `claims.rejected.json` are now derived from succeeded chunk artifacts in chunk order during a separate merge/validate phase
  - `scripts\run_tep_pdf_kg_pipeline.py` now supports bounded parallel extraction via `--max-workers`; `--append-claims` remains only as deprecated compatibility for resume semantics
  - parser/chunking reuse on resume is now file-backed: if canonical markdown/json and `chunks.jsonl` already exist, the extraction retry path reuses them instead of re-running native parsers
- Live DOWNS checkpointed Gemini run on 2026-05-15:
  - fresh checkpointed run at `artifacts\tep_pdf_kg_gemini_downs_checkpointed\DOWNS` completed parser/chunking successfully and persisted `canonical_document.md`, `chunks.jsonl`, `extract_status.jsonl`, and `chunk_claims\`
  - `DOWNS.pdf` produced `75` chunks; all `75` chunk extraction attempts failed with `429 RESOURCE_EXHAUSTED`
  - failure root cause was quota on `generativelanguage.googleapis.com/generate_content_paid_tier_input_token_count` for `gemini-2.5-flash`, not parser or checkpoint logic
- Post-slimming live DOWNS retry on 2026-05-15:
  - Gemini no longer receives full `parser_json`; it now reads slim metadata plus the chunk payload
  - resume run with `--max-workers 1` partially succeeded: `4` chunks succeeded, `71` still failed on `429 RESOURCE_EXHAUSTED`
  - current bottleneck is still Gemini per-minute input-token quota, not parser execution or checkpointing
- Markdown fusion stage landed on 2026-05-15:
  - new deterministic `tep_pdf_kg\markdown_fusion.py` can preclean ODL/Docling markdown, align sections, and emit `fusion\canonical.cleaned.md`, `fusion_report.json`, and `alignment.jsonl`
  - new `scripts\run_tep_pdf_md_fusion.py` runs the fusion stage independently from the KG extraction pipeline
  - live `DOWNS` fusion run completed at `artifacts\tep_pdf_kg_gemini_downs_checkpointed\DOWNS\fusion`
  - current limitation: v1 fusion is conservative and still heavily favors ODL on `DOWNS`; section alignment quality is not yet strong enough to repair many noisy table/OCR regions from Docling
- Markdown fusion v2 hardening landed on 2026-05-15:
  - `tep_pdf_kg\markdown_fusion.py` is now block-aware instead of section-only and emits richer `alignment.jsonl` rows plus `review_candidates.jsonl`
  - low-quality table-heavy regions are now deferred with `defer_table_review` rather than forced into canonical prose
  - live rerun on `DOWNS` now reports `19` sections, `277` block alignments, `27` deferred table regions, and `70` review candidates
  - current limitation: `canonical.cleaned.md` is cleaner around deferred tables, but front-matter and some low-confidence prose conflicts still need another cleanup pass before it is clearly chunk-ready for full live Gemini extraction
- Two-stage Gemini repair pipeline landed on 2026-05-15:
  - new `tep_pdf_kg\gemini_repair.py` adds selective per-candidate Gemini repair over `fusion\review_candidates.jsonl`
  - repair checkpointing now writes `fusion_repair\candidate_*.json` plus append-only `fusion_repair_status.jsonl`
  - merge step now rebuilds `fusion\canonical.repaired.md` and `fusion\canonical.repaired.report.json` from deterministic fusion plus succeeded repair artifacts
  - new `scripts\run_tep_pdf_md_repair.py` provides standalone repair execution with `--resume`, candidate bounds, worker bounds, and model override
  - KG pipeline now automatically prefers `fusion\canonical.repaired.md` for chunking when present and invalidates old chunk-extraction checkpoints if the canonical markdown source changes
- Live `DOWNS` Gemini repair attempt on 2026-05-15:
  - in-sandbox run reached candidate checkpointing but Gemini calls failed with `WinError 10013`, confirming sandbox network restriction rather than repair-code failure
  - non-sandbox resumed run reached real Gemini API calls successfully, then failed on `429 RESOURCE_EXHAUSTED` against `gemini-2.5-flash`
  - current partial artifacts under `artifacts\tep_pdf_kg_gemini_downs_checkpointed\DOWNS\fusion_repair\` show `candidate_0000` through `candidate_0004` persisted as failed attempts; no `canonical.repaired.md` has been produced yet because no candidate repair succeeded
  - practical blocker remains Gemini quota, now reproduced on both chunk claim extraction and the new repair stage

## Open Items

- Fix or triage the pre-existing `/diagnose` rate-limit regression in `tests/test_hardening.py::test_rate_limit_blocks_after_threshold`.
- Re-run live diagnosis evaluation items `gq10-12`; they were not yet revalidated live after the workflow hardening.
- Decide whether to further clean old commented legacy code blocks in `delegate_tools.py` and `router.py` now that the contract path is in place.
- Tune batch sizing / worker defaults for real Gemini runs now that checkpointed resume and parallel chunk execution exist operationally.
- Run a live `DOWNS` selective repair pass to confirm `canonical.repaired.md` materially improves chunk-ready text and downstream Gemini extraction yield.
- Decide whether to switch live repair/extraction retries to a lower-quota-cost Gemini model or wait for quota reset before continuing the `DOWNS` markdown repair run.

## Next Recommended Step

1. After Gemini quota resets or a cheaper model is selected, resume `scripts\run_tep_pdf_md_repair.py --resume` on `DOWNS.pdf` and only then compare repaired-markdown chunking against the prior raw canonical baseline.
