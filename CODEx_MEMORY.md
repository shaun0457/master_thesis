# CODEx Memory

This file stores durable, medium-term memory for `MT-phase-2`.

## Stable Decisions

- The repo uses a supervisor-plus-experts architecture: Supervisor -> Router -> ME/DE/DS.
- Shared repo operating rules should live in `AGENTS.md`; `CLAUDE.md` should stay wrapper-style.
- The current evaluation direction emphasizes context engineering, harness engineering, and regression gating over larger prompts.
- `tep_combined.db` is the main SQLite target for DE workflows.
- The TEP PDF KG ingestion path is now parser-native and Markdown-first:
  - `opendataloader-pdf` is the default canonical parser target
  - `Docling` is retained as comparison / repair source, not the default canonical winner
  - parser-native `document.md` is the semantic handoff surface for chunking; parser JSON is retained for provenance
- TEP PDF KG extraction is Gemini-first:
  - chunking reads canonical Markdown, not parser section adapters
  - Gemini reads chunk Markdown plus slim metadata, not raw PDF and not full `parser_json`
  - heuristic extraction remains fallback / test mode
- TEP PDF KG execution is chunk-checkpointed:
  - per-document extraction writes `extract_status.jsonl` and `chunk_claims/`
  - `--resume` is status-driven and skips only `succeeded` chunks
  - final `claims.raw.jsonl` / `claims.validated.jsonl` are derived artifacts rebuilt from succeeded chunk artifacts
- Markdown fusion is the planned normalization layer between parser output and chunking:
  - `tep_pdf_kg/markdown_fusion.py` owns deterministic ODL/Docling pre-clean, alignment, and canonical cleaned Markdown generation
  - `fusion/canonical.cleaned.md` is intended to become the preferred future chunk input once alignment quality is good enough

## Domain Concepts

- `ME`: Machine Expert, responsible for document retrieval, knowledge lookup, and grounded synthesis.
- `DE`: Data Engineer, responsible for schema-aware SQL access and dataset export.
- `DS`: Data Scientist, responsible for Python analysis, statistics, and plotting.
- `TEP`: Tennessee Eastman Process benchmark used for fault diagnosis and process analysis.
- `IDV`: TEP disturbance or fault identifier used throughout evals and knowledge lookups.

## Important Paths

- `prompt/`: condition-specific prompt cards.
- `eval/`: golden QA and regression tooling.
- `tests/`: regression suite.
- `TEP_docs/`: domain references.
- `datasets/` and `artifacts/`: generated analysis outputs.
- `tep_pdf_kg/`: Neo4j-first PDF KG ingestion package.
- `scripts/run_tep_pdf_kg_pipeline.py`: end-to-end PDF KG runner.
- `scripts/run_tep_pdf_md_fusion.py`: standalone ODL/Docling markdown fusion runner.

## Constraints

- Keep bootstrap startup truth in `SESSION_START.md` and current-session truth in `SESSION_PROGRESS.md`.
- Do not overload handoff files with generated artifact inventories or transient task logs.
- Avoid moving transient planning detail into `AGENTS.md` or `CLAUDE.md`.
- Treat `archive/` as historical storage, not as an active operating-doc source.

## Open Questions

- Whether `PROGRESS.md` should remain as a compact archive stub in the repo root or be moved into `archive/` later.
- Whether future session bootstrap should also reference any neighboring KG repo workflows explicitly.
