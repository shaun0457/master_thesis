# Session Progress

Read this after `AGENTS.md` and `WORKSPACE_INDEX.md` when starting a new session.

## Current Status

- **Repo restructured (2026-05-16):** 28 flat-root Python modules moved into four new packages (`core/`, `agents/`, `knowledge/`, `simulation/`) using `git mv`; 291 import rewrites across 57 files; all 98 .py files compile cleanly (`python -m py_compile`). `fix_imports.py` left at root for reference. Committed as `refactor: restructure flat root into core/agents/knowledge/simulation packages`.
- Diagnosis pipeline and MAS2 delegation hardening are landed and previously regression-tested.
- TEP PDF KG v1 is operational under `tep_pdf_kg/`:
  - parser-native markdown/json ingestion exists
  - chunk checkpointing and `--resume` are in place
  - markdown fusion and Gemini repair stages exist
  - pipeline prefers repaired markdown when available
- Claim extraction / validation alignment landed on 2026-05-15:
  - Gemini claim prompt now includes relation-role rules, capability/inventory negative guidance, and confidence calibration
  - LLM fallback confidence now defaults to `0.7`; validator threshold remains `0.55`
  - schema/import/validation now support `Capability`, `HAS_CAPABILITY`, and claim type `capability`
  - relation-role mismatches are now rejected during validation
- `Decentralized_control_of_the_Tennessee_E.pdf` is now the active easier pilot:
  - real parser-native markdown conversion completed under `artifacts\tep_pdf_kg_decentralized_probe\Decentralized_control_of_the_Tennessee_E\`
  - fusion completed with `65` review candidates
  - a bounded Gemini repair probe (`10` candidates on `gemini-2.5-flash-lite`) succeeded with `8 replace`, `2 keep_deferred`
  - a bounded live Gemini claim-extraction probe over the first `3` chunks succeeded on the repaired-markdown path with `2` raw claims, `2` validated claims, and `0` rejected claims
- `DOWNS.pdf` still remains the harder pilot because of noisy front-matter, inventory language, quota pressure, and repaired-markdown complexity.

## Verification

- Prior diagnosis and MAS2 hardening regressions passed on 2026-05-14, except the known `/diagnose` rate-limit failure in `tests/test_hardening.py::test_rate_limit_blocks_after_threshold`.
- KG pipeline verification passed on 2026-05-15:
  - `pytest tests\test_tep_pdf_kg_pipeline.py tests\test_neo4j_kg.py tests\test_kg_match_fault.py -q`
  - parser-native markdown path, checkpointed extraction, and repaired-markdown preference were unit/integration verified
- Claim-alignment verification passed on 2026-05-15:
  - `python -m py_compile tep_pdf_kg\schema.py tep_pdf_kg\extraction.py tep_pdf_kg\gemini_extractor.py tep_pdf_kg\validation.py tep_pdf_kg\neo4j_import.py tests\test_tep_pdf_kg_pipeline.py`
  - `pytest tests\test_tep_pdf_kg_pipeline.py -q --basetemp .\_pytest_tmp_claimcap`
  - `pytest tests\test_neo4j_kg.py tests\test_kg_match_fault.py -q --basetemp .\_pytest_tmp_claimcap_neo`
- Live environment facts already confirmed on 2026-05-15:
  - `opendataloader-pdf` and Java work locally for real markdown conversion
  - Gemini live runs are functional but constrained by quota / sandbox network restrictions depending on execution mode
- Decentralized staged probe passed on 2026-05-16:
  - parser-native conversion required running outside the sandbox for the ODL Java/JDK access path
  - `docling` completed after setting `KMP_DUPLICATE_LIB_OK=TRUE`
  - live pipeline probe used `canonical_source = fusion_repaired_markdown` and produced `144` chunks total, with the first `3` chunks processed successfully
  - semantic quality note: the first validated claims were schema-valid but still abstract (`ControlAction SUBJECT_TO Constraint`, `ControlAction HAS_RISK Risk`) rather than the more concrete fault/sensor/unit claims desired for downstream KG utility

## Open Items

- Fix or triage the pre-existing `/diagnose` rate-limit regression.
- Decide whether to continue `Decentralized_control_of_the_Tennessee_E.pdf` by probing later chunks first, or to tighten prompt/validation further so abstract control-strategy prose in the introduction does not dominate validated output.
- Decide whether broader `DOWNS` repair/extraction should wait for quota reset or continue in small bounded `gemini-2.5-flash-lite` batches.
- Continue broader repair on the remaining `55` pending fusion candidates if cleaner chunking becomes necessary.
- Further tighten `prose_conflict` handling if repaired markdown from the easier pilot still contains hybrid fragments.

## Next Recommended Step

1. Continue the `Decentralized_control_of_the_Tennessee_E.pdf` live claim-extraction probe on later chunks beyond the introduction, because the first `3` chunks ran successfully but mostly yielded abstract control-strategy claims.
2. If later chunks still skew abstract, tighten Gemini prompt guidance and/or validation semantics for generic `ControlAction -> Constraint/Risk` claims before scaling the probe wider.
3. Return to `DOWNS.pdf` only after the easier pilot shows a more useful validated-claim profile.
