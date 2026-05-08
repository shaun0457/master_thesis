# PLAN.md — 2026 Agentic AI 重構計劃

## 目標
將 2025/6 論文 MAS（prompt engineering，~6,800 tokens/turn system prompt）重構為：
- **Context Engineering**：system prompt ≤300 tokens，動態組裝
- **Harness Engineering**：LLM call 前後有 validation、self-eval、judge LLM
- **Production Observability**：分層 latency、token budget、structured metrics
- **TDD**：每個新模組先寫測試

## Step 0：持久化文件 ✅
建立 CLAUDE.md / PLAN.md / PROGRESS.md

## Step 1：`structured_outputs.py`（TDD）
**測試**：`tests/test_structured_outputs.py`
- MEReport 接受合法 citation_coverage（0.0-1.0）
- MEReport 拒絕 coverage > 1.0（ValidationError）
- JudgeScore 拒絕分數 > 3
- SelfEvalResult 可從 JSON 字串 parse

**實作**：Pydantic models — MEReport / DSReport / DEReport / JudgeScore / SelfEvalResult

**驗收**：`pytest tests/test_structured_outputs.py` 全過

## Step 2：`context_assembler.py`（TDD）
**測試**：`tests/test_context_assembler.py`
- 每個 agent system prompt 估算 ≤300 tokens
- phase snippet 正確注入
- compress_messages 確實縮短 token 數

**實作**：DynamicContextAssembler（STATIC_CORES + PHASE_SNIPPETS + PROTOCOL_SNIPPETS）

**驗收**：`pytest tests/test_context_assembler.py` 全過

## Step 3：`llm_harness.py`（TDD）
**測試**：`tests/test_llm_harness.py`
- harness invoke 後 llm_calls_total += 1
- llm_latency_ms_sum > 0
- token count 正確提取
- SelfEvaluator 解析合法 JSON → SelfEvalResult
- SelfEvaluator 遇到惡意 JSON → None（不 crash）

**實作**：LLMCallHarness + SelfEvaluator

**驗收**：`pytest tests/test_llm_harness.py` 全過

## Step 4：`judge.py`（TDD）
**測試**：`tests/test_judge.py`
- judge_sync 回傳 JudgeScore（0-3）
- judge_triggered 寫入 metrics
- 解析失敗 → None（不 crash）

**實作**：JudgeLLM.judge_sync()

**驗收**：`pytest tests/test_judge.py` 全過

## Step 5：`llm_cache.py`（TDD）
**測試**：`tests/test_llm_cache.py`
- ExactMatchCache：相同 messages hash → 回傳 cached response，不呼叫 LLM
- ExactMatchCache：不同 messages → cache miss，正常呼叫 LLM
- TTL 過期後 cache miss
- PrefixStabilizer：system prompt 永遠在最前面
- GeminiContextCacheManager：ME 文件語料庫可建立 cache（需 ≥32K tokens）

**實作**：
- `ExactMatchCache`：LRU + TTL，key = sha256(messages)
- `PrefixStabilizer`：確保 message 順序一致，最大化 implicit KV cache hit
- `GeminiContextCacheManager`：包裝 Gemini Context Caching API（只給 ME）

**驗收**：`pytest tests/test_llm_cache.py` 全過；harness 的 `llm_calls_total` 在 cache hit 時不遞增

## Step 6：接線到現有系統
**刪除**：prompt/*.md（12 個）、prompts.py

**修改**：
- metrics.py：加 ~20 個新欄位 + note_judge_result()
- run_logger.py：llm_call() context mgr + summary.json + 修復 assert
- prompt_builder.py：完整重寫為 thin wrapper
- delegate_tools.py：_summarize_out Pydantic primary path
- supervisor_workflow.py：phase-aware prompt + judge trigger
- me/de/ds_workflow*.py：LLM invoke → harness wrapper
- chat_cli.py：judge score + usage summary 顯示

**驗收**：`python chat_cli.py` 顯示 [Judge] 和 [Usage] 兩行

## Regression Gate（Step 5 後）
跑 queries/Q1-Q3.txt，記錄到 PROGRESS.md：
- ds_verdict 成功率 ≥ 70%
- me_citation_coverage 平均 ≥ 0.3
- judge_factual_grounding 平均 ≥ 1
