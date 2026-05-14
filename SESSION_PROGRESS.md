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

- Regression baseline: `pytest tests/ -q → 111 passed` (2026-05-14, after Phase 3.5)
- Live evaluation baseline: `9/9 PASS` (2026-05-13)
- 執行中工作軌：**Production-Ready Fault Diagnosis Pipeline**（Plan: `C:\Users\chengting\.claude\plans\jolly-plotting-spring.md`）
- 已完成 Phase 1, 2, 3, 3.5（共 6 個 phase）；**準備進入 Phase 4 前等待 user 確認**

## Current Phase

Phase: production diagnosis pipeline — **Phase 4 待啟動** (Supervisor prompt + monitoring dashboard)

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
