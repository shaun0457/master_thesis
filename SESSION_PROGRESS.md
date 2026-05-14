# Session Progress

Read this after `AGENTS.md` and `WORKSPACE_INDEX.md` when starting a new session.

## Purpose

This file is the short-horizon working memory for active development in `MT-phase-2`.

Use it for:

- what was just finished
- what is currently true
- what should happen next
- blockers, assumptions, and temporary decisions

Do not use it for long-term architecture explanation. That belongs in:

- [CODEx_MEMORY.md](./CODEx_MEMORY.md)
- [WORKSPACE_INDEX.md](./WORKSPACE_INDEX.md)
- [AGENTS.md](./AGENTS.md)

## Current Status

- Regression baseline: `pytest tests/ -q → 136 passed` (2026-05-14, after Phase 6)
- Live evaluation baseline: `9/9 PASS` (2026-05-13) — diagnosis items (gq10-12) not yet run live
- 工作軌：**Production-Ready Fault Diagnosis Pipeline** — **全部 phase 完成** ✓
  - Plan: `C:\Users\chengting\.claude\plans\jolly-plotting-spring.md`

## Current Phase

Phase: **all diagnosis pipeline phases shipped** — ready for live demo / eval

## Completed Recently (2026-05-14)

### Diagnosis Pipeline — Phase 1（commit b159359）
- `scripts/build_baseline_stats.py`：52 sensors × {mean, std, p01, p50, p99} 從 250K 筆 faultnumber=0 → `datasets/baseline_stats.parquet`（7KB, committed）
- `scripts/simulate_observation.py`：從 tep_combined.db 抽 N 筆，剝掉 faultnumber + simulationrun 後輸出 parquet
- `scripts/init_live_buffer.py`：建立 `live_observations.db`（observations + diagnoses tables）
- `scripts/build_kg_sensor_relationships.py`：Neo4j enrichment（72 個 HAS_SENSOR 關係，已 dry-run，待連線跑 live）

### Diagnosis Pipeline — Phase 2（commit f2e8384）
- `tep_knowledge.match_fault_by_sensors_local()`：Jaccard 評分，tie-break 低 fault_id
- `neo4j_kg.match_fault_by_sensors()`：Neo4j primary + local fallback（同 query_fault_kg 模式）
- `me_tools.kg_match_fault_by_sensors`：新 @tool 註冊到 ME tool set
- 8 個單元測試（local + Neo4j success + Neo4j failure fallback + empty records + ME wrapper）

### Diagnosis Pipeline — Phase 3（commit 46e6fd3）
- `diagnose_flow.py`：orchestrator wrap graph.invoke；register obs + baseline 到 blackboard；regex 解析 fault_id；持久化到 live_observations.db
- `api_server.py`：FastAPI（`/diagnose`, `/observations`, `/diagnoses`, `/admin/baseline`, `/health`）
- `requirements.txt`：加 fastapi, uvicorn[standard], httpx
- 12 個新測試（fault_id parsing, graph success/error path, all endpoints）

### Diagnosis Pipeline — Phase 3.5
- `stream_simulator.py`：synthetic SCADA feed，支援 `--pattern "normal:60,fault4:30"` 排程注入
- `file_watcher.py`：監看 inbox/ 自動 POST /diagnose
- 6 個新測試（pattern parsing, row stripping, posting, run_once flow）

### Diagnosis Pipeline — Phase TS (time-series semantics)
- `scripts/init_live_buffer.py`：observations 加 `sample_idx`, `simulationrun` 欄位 + 冪等 ALTER migration
- `stream_simulator.py`：refactor 為 stateful `RunCursor` (sample-by-sample walk)；rollover 到下個 run；phase 切換重建 cursor；新增 `--start-sample`、`--run-idx`；POST 附 `sample_indices` / `simulationruns` 陣列
- `api_server.py`：新端點 `POST /diagnose/window`（取 buffer 最近 N 筆做診斷）；IngestRequest 接受新欄位；`_persist_observations` 寫入 sample axis
- 14 個新/改寫測試：cursor 推進、run rollover、新 payload shape、window 端點 4 條路徑（empty/last_n/source filter/explicit truth）
- 既存 buffer migration 已驗證（2 個 ALTER 成功，欄位齊全）

### Diagnosis Pipeline — Phase 4（commit f08a513）
- `context_assembler.py`：新 `PHASE_SNIPPETS["Supervisor:diagnose"]`，state["phase"]=="diagnose" 時注入；硬規則禁止 faultnumber 過濾，要求呼叫 kg_match_fault_by_sensors
- `diagnose_flow.py`：state["phase"]="diagnose"
- `monitoring/dashboard.py`：純 HTML 視圖，最近 50 筆診斷、accuracy badge、10 秒自動 refresh
- `api_server.py`：GET /dashboard 端點
- 5 個新測試

### Diagnosis Pipeline — Phase 5（commit e8fa0cb）
- `eval/golden_qa.json`：加 gq10/11/12（三個 sensor family 的反向查詢測試）
- `tests/test_diagnose_e2e.py`：3 個 end-to-end 整合測試（simulator → /observations → window → /diagnoses → /dashboard 完整鏈）

### Diagnosis Pipeline — Phase 6 (hardening)
- `diagnose_flow._weighted_confidence`：confidence 改用 base × (0.5 + 0.5 × margin)，明確反映 tie（同 family 兄弟 fault）的模糊性
- `api_server.py`：rate limit middleware（環境變數 `API_RATE_LIMIT_ENABLED=1` 啟用，預設關閉；路徑可設定）
- `_ensure_buffer`：thread-safe 加鎖 + cache，支援並發寫
- 9 個新測試（5 個 confidence、3 個 rate limit、1 個 50-concurrent stress）

### 早先（commit b2af005）— CODEX_REVIEW 4 個修補
- `bb_tools.py` 同名覆蓋、`de_tools.py` SQL LIMIT、`router.py` P2P 節流、`tests/conftest.py` 硬編碼路徑

## Current Working Assumptions

- Neo4j AuraDB 仍可連（KG enrichment 跑 live 時需驗證）
- 不更動 `chat_cli.py`，FastAPI 是 production entry，CLI 是互動 REPL
- 三個 share-sensor 的 fault 家族（{1,2,3,6,7}, {4,11,13,14}, {5,12,15}, {8,9,10}）造成的診斷模糊性是正確行為，不是 bug

## Next Recommended Step

1. **Phase 3**：`api_server.py` + `diagnose_flow.py` + `diagnoses.db` schema（FastAPI `/diagnose`、`/observations`、`/diagnoses`、`/health`）
2. 接著 Phase 3.5（stream simulator + watcher）、Phase 4（prompt + dashboard）、Phase 5（tests + eval）、Phase 6（hardening）

## Open Items

- KG enrichment 待真實 Neo4j 連線後跑：`python scripts/build_kg_sensor_relationships.py`（已 dry-run 確認）
- 根目錄孤兒 PNG（separator_temp_flow.png 等）尚未清理；屬於先前 DS 隨意 savefig 問題

- 2026-05-14 architecture check: diagnosis still spans two unsynchronized blackboard paths. `delegate_tools.read_blackboard()` reads only `state["blackboard"]`, while `bb_register_dataset_path()` / `bb_list_datasets_py()` / `ds_pick_dataset_path()` read the file-backed registry. In `diagnose_flow.py`, seeded in-memory datasets use dataset-like `topic_id` values (`obs_<run_id>`, `baseline_stats`) but disk registrations use `topic_id="diagnose"`, so DS lookup by `prefer_topic` can miss and then fall back to the wrong latest dataset. DS prompts also do not explicitly forbid treating `write_to_blackboard` as in-subprocess Python or remind the model to use raw strings for Windows paths.

- 2026-05-14 blackboard unification shipped: `bb_tools.py` is now the canonical source of truth for blackboard state. Dataset records are normalized with `name` + workflow `topic_id` + `kind`/`role`/`aliases`; `delegate_tools.make_blackboard_tools()` now reads/writes through `bb_tools` instead of maintaining an independent in-memory board; `diagnose_flow.py` registers obs/baseline datasets into the canonical registry and then syncs state from it; `ds_pick_dataset_path()` now resolves by dataset identity instead of `topic_id` equality. Added `tests/test_blackboard_unified.py` and verified `pytest tests/test_blackboard_unified.py -q --basetemp .\\_pytest_tmp_unified` plus `pytest tests/test_diagnose_flow.py -q --basetemp .\\_pytest_tmp_diag`.

- 2026-05-14 MAS2 workflow review found new flow-control bugs to fix next: `supervisor_workflow._has_min_evidence()` reads `get_bb_snapshot()` without the current `run_id`, `router.py` still defaults run artifacts to `/mnt/data/runs`, diagnosis-mode DE context injection in `delegate_tools._read_me_fault_facts()` tells DE to query `faultnumber=<predicted id>` even though diagnosis mode hides the label, and `de_workflow.router_after_de()` treats any DE turn with no tool call as successful handoff to DS even when no dataset was delivered.

- 2026-05-14 workflow hardening shipped: `supervisor_workflow._has_min_evidence()` now checks the current run's registry, `router.py` now defaults artifacts to the workspace `runs/` root like `bb_tools.py`, diagnosis-mode `_read_me_fault_facts()` no longer leaks `faultnumber=<predicted id>` into DE prompts, and `de_workflow.router_after_de()` now keeps DE in-loop until a real `deliver_dataframe` success is observed. Also renamed shadowed legacy helpers in `delegate_tools.py` / `de_tools.py` and added `tests/test_workflow_hardening.py`. Verified with `pytest tests/test_workflow_hardening.py -q --basetemp .\\_pytest_tmp_workflow`, `pytest tests/test_blackboard_unified.py -q --basetemp .\\_pytest_tmp_unified2`, `pytest tests/test_bb_me_injection.py -q --basetemp .\\_pytest_tmp_meinj`, and `pytest tests/test_diagnose_flow.py -q --basetemp .\\_pytest_tmp_diag2`.
