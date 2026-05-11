# PROGRESS.md — 重構進度追蹤

## 目前狀態：Production Upgrade Tier 1 進行中 — T1-P1 完成 ✅

## 🔴 下一個動作（新 session 直接從這裡開始）

```
Production Upgrade Tier 2 + 3（T2-P5/P6/P7/P9 全部完成 ✅）。
完整計劃：C:\Users\chengting\.claude\plans\code-2025-6-2026agentic-code-prompt-eng-expressive-island.md

下一個 item：T2-P8 — DS 程式碼沙箱（ds_tools.py subprocess 隔離）
  先建：tests/integration/eval_t2p8.py
  實作：ds_tools.py execute_python_code 改 subprocess 隔離 + timeout
  驗收：timeout 後回傳 {"error": "Timeout after 30s"}

之後：T3-P9（retry）→ T3-P10（eval pipeline）→ T3-P11（run report）→ T3-P12（delegation contract）
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
pytest tests/ → 63 passed (2026-05-08)
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

---

## Regression Gate（Step 6 完成後填入）
| 指標 | 目標 | 實測值 |
|------|------|--------|
| ds_verdict 成功率 | ≥ 70% | — |
| me_citation_coverage 平均 | ≥ 0.3 | — |
| judge_factual_grounding 平均 | ≥ 1 | — |
