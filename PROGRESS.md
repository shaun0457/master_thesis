# PROGRESS.md — 重構進度追蹤

## 目前狀態：System Prompt 重設計完成，TEP DB 合併進行中

## 🔴 下一個動作（新 session 直接從這裡開始）

```
DB + KG schema 完成。下一步：ME agent 加 KG query tool。

待實作：
- [ ] ME agent 加 kg_query_fault tool（呼叫 manufacturing-kg-agent 的 query_tep_fault_tool）
  - me_tools.py 新建 kg_query_fault @tool（包裝 query_fault_knowledge 或 HTTP call）
  - me_workflow.py 加入 kg_query_fault 到 ME tools list
  - 驗收：ME 可直接查詢 IDV=4 的診斷 sensor 列表（不需讀 PDF）
- [ ] 確認 PyTorch crash 不影響 63 unit tests（已驗證：unit tests 全過）
```

**接線順序（依賴關係）：**
1. `metrics.py` — 獨立，先改
2. `run_logger.py` — 獨立，先改
3. `prompt_builder.py` — 依賴 context_assembler（已完成），可改
4. `common.py` — 加 AgentState 欄位
5. `delegate_tools.py` — 依賴 structured_outputs（已完成）
6. `me_workflow.py` / `de_workflow.py` / `ds_workflow_s2.py` — 依賴 llm_harness（已完成）
7. `supervisor_workflow.py` — 依賴 judge（已完成）
8. `chat_cli.py` — 最後，整合顯示

---

## ✅ 完成

### Step 0：Session 持久化文件（2026-05-08）
- [x] `CLAUDE.md` — 建立
- [x] `PLAN.md` — 建立
- [x] `PROGRESS.md` — 建立

### Step 1：`structured_outputs.py`（TDD）✅ 2026-05-08
- [x] `tests/conftest.py` — mock fixtures
- [x] `tests/test_structured_outputs.py` — 14 tests
- [x] `structured_outputs.py` — 實作
- [x] pytest 全過：**14/14 passed**

### Step 2：`context_assembler.py`（TDD）✅ 2026-05-08
- [x] `tests/test_context_assembler.py` — 14 tests
- [x] `context_assembler.py` — 實作
- [x] pytest 全過：**14/14 passed**

### Step 3：`llm_harness.py`（TDD）✅ 2026-05-08
- [x] `tests/test_llm_harness.py` — 12 tests
- [x] `llm_harness.py` — 實作
- [x] pytest 全過：**12/12 passed**

### Step 4：`judge.py`（TDD）✅ 2026-05-08
- [x] `tests/test_judge.py` — 9 tests
- [x] `judge.py` — 實作
- [x] pytest 全過：**9/9 passed**

### Step 5：`llm_cache.py`（TDD）✅ 2026-05-08
- [x] `tests/test_llm_cache.py` — 14 tests
- [x] `llm_cache.py` — ExactMatchCache + PrefixStabilizer + GeminiContextCacheManager
- [x] pytest 全過：**14/14 passed**

---

## 🔄 Step 6：接線到現有系統（進行中）

### 6-a：`metrics.py` ✅ 2026-05-08
- [x] 加 20 個新欄位到 _ensure_metrics（llm_calls_total / tokens / latency / cache / judge / self-eval / prompt_tokens_est）
- [x] 加 note_judge_result() 函數

### 6-b：`run_logger.py` ✅ 2026-05-08
- [x] llm_call() context manager
- [x] flush() 輸出 summary.json（含 harness 關鍵指標）
- [x] assert → logger.warning（emit_event）

### 6-c：`prompt_builder.py` ✅ 2026-05-08
- [x] 完整重寫為 thin wrapper → context_assembler

### 6-d：`common.py` ✅ 2026-05-08
- [x] AgentState 加 token_usage / harness_metrics 欄位

### 6-e：`delegate_tools.py` ✅ 2026-05-08
- [x] _summarize_out Pydantic primary path（MEReport/DSReport/DEReport，失敗才 fallback）

### 6-f：`me_workflow.py` / `de_workflow.py` / `ds_workflow_s2.py` ✅ 2026-05-08
- [x] executor.invoke 加計時 → llm_calls_total / llm_latency_ms_sum
- [x] SelfEvaluator（ME + DS，非阻塞）

### 6-g：`supervisor_workflow.py` ✅ 2026-05-08
- [x] phase-aware system prompt（get_system_prompt("Supervisor", phase=state["phase"])）
- [x] _cond 觸發 JudgeLLM（final_answer + evidence 路徑）
- [x] supervisor_node 加計時 → llm_calls_total / llm_latency_ms_sum

### 6-h：`chat_cli.py` ✅ 2026-05-08
- [x] 啟動時顯示 4 個 agent system prompt token 估算
- [x] 每回合結尾顯示 [Usage] tokens_in / tokens_out / llm_latency / cache_hits
- [x] judge_triggered 時顯示 [Judge] Factual/Complete/Coherent

### 驗收
- [x] 程式碼結構完成（需真實 GOOGLE_API_KEY 才能端到端驗證）

---

## Test Status
```
pytest tests/ → 63 passed (2026-05-12)
  test_structured_outputs.py  14/14
  test_context_assembler.py   14/14
  test_llm_harness.py         12/12
  test_judge.py                9/9
  test_llm_cache.py           14/14
```

---

---

## Production Upgrade Tier 1

### T1-P1：`harness_callback.py` ✅ 2026-05-09
- [x] `harness_callback.py` — 新建 HarnessCallback（on_llm_start + on_llm_end）
- [x] `tests/integration/eval_t1p1.py` — integration evaluator（需真實 API key）
- [x] `me_workflow.py` — 移除手工計時，加 config={"callbacks": [HarnessCallback(state, "ME")]}
- [x] `de_workflow.py` — 移除手工計時，_run 接受 config，加 HarnessCallback
- [x] `ds_workflow_s2.py` — 移除手工計時，加 config={"callbacks": [HarnessCallback(state, "DS")]}
- [x] pytest regression：63 passed（無退步）

### T1-P2：`delegate_tools.py` — 加法式 metrics merge ✅ 2026-05-09
- [x] `tests/integration/eval_t1p2.py` — evaluator（純邏輯，不需 API key）
- [x] `_merge_metrics()` helper — 數值加法合併，字串覆蓋
- [x] 替換 `_invoke_stage1()` 的 `state["metrics"].update(...)` → `_merge_metrics(...)`
- [x] pytest regression：63 passed（無退步）

### T1-P3：`supervisor_workflow.py` — PostAnswer node ✅ 2026-05-09
- [x] `post_answer_node` 函數（從 messages 找最後一個 final_answer tool_call）
- [x] `_cond()` 改純路由：final_answer + evidence → "PostAnswer"（不再執行 Judge I/O）
- [x] `supervisor_node` 手工計時移除，改用 HarnessCallback
- [x] `build_team_graph()` 加 PostAnswer node + edge(PostAnswer→END)
- [x] pytest regression：63 passed（無退步）

### T1-P4：`delegate_tools.py` — Wire `compress_messages` ✅ 2026-05-09
- [x] `tests/integration/eval_t1p4.py` — evaluator
- [x] `_invoke_stage1()` 加 compress_messages 暫行版（target_tokens=8000）
- [x] T2-P9 會在同一位置換成 anchor 方案（bb_index + 歷史壓縮）
- [x] pytest regression：63 passed（無退步）

### T2-P5：Phase 驅動 ✅ 2026-05-09
- [x] `tests/integration/eval_t2p5.py` — evaluator（source code 靜態驗證）
- [x] `me_workflow.py` Tool_node：synthesize_and_cite 後設 state["phase"] = "ME:synthesize"（regular + forced 兩路徑）
- [x] `de_workflow.py` tool_node：deliver_dataframe 後設 state["phase"] = "DE:deliver"
- [x] `supervisor_workflow.py` supervisor_node：state.setdefault("phase", "initial")
- [x] pytest regression：63 passed（無退步）

### T2-P6：Blackboard Provenance ✅ 2026-05-09
- [x] `tests/integration/eval_t2p6.py` — 4 tests
- [x] `bb_tools.py` 加 `_fact_entry()` helper
- [x] `bb_tools.py` `bb_add_facts` 自動正規化（str/dict → provenance dict）
- [x] `me_workflow.py` bb_add_facts 呼叫加上 agent="ME", source_tool="synthesize_and_cite"
- [x] pytest regression：63 passed（無退步）

### T2-P7：evidence_utilization 指標 ✅ 2026-05-09
- [x] `tests/integration/eval_t2p7.py` — 5 tests（含 stop words 防虛高）
- [x] `metrics.py` `compute_evidence_utilization()` + `_STOP_WORDS`
- [x] `supervisor_workflow.py` post_answer_node 呼叫並印 [Evidence] utilization
- [x] pytest regression：63 passed（無退步）

### T2-P9：Blackboard Index Injection ✅ 2026-05-09
- [x] `tests/integration/eval_t2p9.py` — 4 tests
- [x] `delegate_tools.py` `_format_bb_index()` — 支援 provenance dict + legacy string facts
- [x] `delegate_tools.py` `_invoke_stage1` 替換 T1-P4 暫行版為 anchor_msg 方案（bb_index + task 永不被截斷）
- [x] pytest regression：63 passed（無退步）

### T2-P8：DS 程式碼沙箱 ✅ 2026-05-09
- [x] `tests/integration/eval_t2p8.py` — 4 tests（basic/timeout/syntax error/tool interface）
- [x] `ds_tools.py` `_execute_python_subprocess()` — subprocess 隔離 + timeout
- [x] `execute_python_code` @tool 改用 subprocess，移除 langchain_experimental 依賴
- [x] pytest regression：63 passed（無退步）

### System Prompt 重設計 ✅ 2026-05-12
- [x] `context_assembler.py` STATIC_CORES 全面重寫：
  - Supervisor：加診斷 SOP（ME→DE→DS→final_answer 順序）+ success_criteria 提醒
  - ME：加 sensor-fault 映射表（IDV 4/11/14 → XMEAS 7/9; IDV 1-3/6/7 → XMEAS 1-4/6 等）
  - DE：加完整 DB schema（tep_combined.db 欄位名、常用 SQL pattern、fault onset ~sample 160）
  - DS：加分析 SOP（trend plot → statistical test → PCA/T²）
- [x] PHASE_SNIPPETS / PROTOCOL_SNIPPETS 同步更新
- [x] `scripts/build_tep_combined_db.py` 新建（合併 FaultFree + Faulty，各 50 runs/fault）
- [x] pytest regression：63 passed

### T3-P12：Delegation Contract ✅ 2026-05-12
- [x] `supervisor_tools.py` — 3 個 delegate tool Args 加 `success_criteria: Optional[str]` 欄位
- [x] `delegate_tools.py` — `_format_task_contract()` helper；`_run_subgraph` + `_invoke_stage1` 加 `success_criteria` 參數；anchor 改為 `bb_index + [TASK CONTRACT]`
- [x] `router.py` — `_exec_one_tool` 把 `args.get("success_criteria")` 傳進三個 delegate 函數
- [x] `tests/integration/eval_t3p12.py` — 5 tests（全通過）
- [x] pytest regression：63 passed（無退步）

### T3-P11：Cost Tracking + Run Report ✅ 2026-05-12
- [x] `harness_callback.py` `_extract_tokens()` — 3 條路徑 fallback（llm_output / generation_info / AIMessage.usage_metadata），0 token 只有在三條都沒資料才回傳
- [x] `run_logger.py` `_compute_cost_usd()` — token=0 回傳 None（不虛報 $0.0000）；pricing 可用 env var 覆寫
- [x] `run_logger.py` `_write_run_report()` — 輸出 run_report.md（Cost/Tokens/Quality 三節）
- [x] `run_logger.py` `flush()` — 加 cost_usd + run_report.md
- [x] `chat_cli.py` — `[Cost]` 行：有 token 顯示真實金額，無 token 顯示明確警告
- [x] `tests/integration/eval_t3p11.py` — 6 tests（全通過）
- [x] pytest regression：63 passed（無退步）

### T3-P10：Golden Dataset Eval Pipeline ✅ 2026-05-12
- [x] `eval/golden_qa.json` — 5 條 TEP 問答（ME×3 + DS×2）
- [x] `eval/run_eval.py` — dry-run + live 兩模式，輸出 results.json
- [x] `eval/regression_gate.py` — keyword hit rate / DS verdict / ME citation gate，exit code 0/1
- [x] `tests/integration/eval_t3p10.py` — 5 tests（全通過）
- [x] pytest regression：63 passed（無退步）

### tep_combined.db ✅ 2026-05-12
- [x] `scripts/build_tep_combined_db.py` — 合併 FaultFree (IDV=0, 250K) + Faulty (IDV 1-20, 25K each)
- [x] `de_tools.py` — DB_URL 改指向 `tep_combined.db`
- [x] 驗收：DE 可查 IDV=4 的 xmeas_9 平均值（25,000 rows, AVG=120.4°C）

### KG TEP Schema ✅ 2026-05-12
- [x] `manufacturing-kg-agent/config/tep_schema.py` — TEP_FAULT_DESCRIPTIONS(IDV 0-20) + TEP_FAULT_SENSORS + TEP_PROCESS_UNITS + TEP_RELATION_ENDPOINTS
- [x] `config/graph_schema.py` — merge TEP node labels (Fault/Measurement/ManipulatedVar/ProcessUnit) + relations
- [x] `tools/neo4j_client.py` — TEP constraints/indexes + populate_tep_knowledge() + query_fault_knowledge() + populate_tep_tool + query_tep_fault_tool
- [x] manufacturing-kg-agent tests: 83 passed（無退步）

### T3-P9：Retry + Circuit Breaker ✅ 2026-05-12
- [x] `tests/integration/eval_t3p9.py` — 5 tests（retry/reraise/429/no-retry/source check）
- [x] `common.py` 加 `invoke_with_retry()` — tenacity @retry on ServiceUnavailable + ResourceExhausted，wait_exponential(min=1,max=60)，stop_after_attempt(3)
- [x] pytest regression：63 passed（無退步）

---

## Regression Gate（Step 6 完成後填入）
| 指標 | 目標 | 實測值 |
|------|------|--------|
| ds_verdict 成功率 | ≥ 70% | — |
| me_citation_coverage 平均 | ≥ 0.3 | — |
| judge_factual_grounding 平均 | ≥ 1 | — |
