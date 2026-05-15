# Session Progress

Read this after `AGENTS.md` and `WORKSPACE_INDEX.md` when starting a new session.

## Current Status

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
- `DOWNS.pdf` remains the hardest pilot document because of noisy front-matter, inventory language, and repaired-markdown complexity, so the next KG probe should use `Decentralized_control_of_the_Tennessee_E.pdf` first.

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

## Open Items

- Fix or triage the pre-existing `/diagnose` rate-limit regression.
- Run a staged KG attempt on `Decentralized_control_of_the_Tennessee_E.pdf` before returning to `DOWNS.pdf`.
- Decide whether broader `DOWNS` repair/extraction should wait for quota reset or continue in small bounded `gemini-2.5-flash-lite` batches.
- Further tighten `prose_conflict` handling if repaired markdown from the easier pilot still contains hybrid fragments.

## Next Recommended Step

1. Run markdown conversion for `Decentralized_control_of_the_Tennessee_E.pdf` to produce parser-native markdown/json artifacts.
2. Run markdown fusion plus Gemini repair on that document and inspect whether the repaired canonical markdown is chunk-ready.
3. Only then run a small live Gemini claim-extraction probe on `Decentralized_control_of_the_Tennessee_E.pdf` with `gemini-2.5-flash-lite`.
