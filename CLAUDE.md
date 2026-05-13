# CLAUDE.md — MAS Refactor 2026

## ⚡ 新 Session 啟動協定（每次都要做，不能跳過）

**Step 1：讀進度**
```
讀 PROGRESS.md，確認「目前狀態」和「🔴 下一個動作」
```

**Step 2：驗證測試基線**
```bash
pytest tests/ -v --tb=no -q
```
若有失敗，**先修復**再繼續工作。

**Step 3：核對 CLAUDE.md 檔案索引**
確認「關鍵檔案索引」欄位的狀態與磁碟實際一致。如有出入，先更新 CLAUDE.md。

**Step 4：繼續 PROGRESS.md 裡標記的下一步**

---

## 🤖 自動化規則（強制執行，不等使用者提醒）

### 規則 A：每個 checkbox 完成後立刻更新 PROGRESS.md
每當一個子任務（PROGRESS.md 裡的 `- [ ]`）完成：
1. 執行 `pytest tests/ -q` 確認無 regression
2. 把對應的 `- [ ]` 改為 `- [x]`
3. 若該 Step 的所有 checkbox 都變成 `[x]`，把 Step 標題加上 `✅ YYYY-MM-DD`
4. 更新 PROGRESS.md 的「Test Status」區塊為最新數字
5. 更新 PROGRESS.md 最頂部的「🔴 下一個動作」為下一個未完成的任務

### 規則 B：每個完整 Step 完成後立刻 git commit
當一個 Step 的所有 checkbox 全部打勾：
```bash
git add -p   # 只 stage 相關檔案，不要用 git add .
git commit -m "feat: <step description>"
# commit message 格式：conventional commits（feat/fix/refactor/docs/chore）
# Co-Authored-By 行照常加
```
**commit 的時機**：Step 全部完成 + pytest 全過 + PROGRESS.md 已更新，三個條件都滿足才 commit。

### 規則 C：不可跳過的安全檢查
- commit 前必須先跑 `pytest tests/ -q`，有失敗不 commit
- 不使用 `git add .` 或 `git add -A`（避免意外 stage .env 或大型檔案）
- 不 force push

---

## 這個 Repo 是什麼
針對田納西-伊士曼製程（TEP）的多代理系統（MAS），使用 LangGraph 建構。
目前正在進行 **2026 production-grade 重構**：從 prompt engineering 架構升級到 context engineering + harness engineering。

## 重構方向（絕對不走回頭路）
- **不保留**任何舊版 prompt cards（`prompt/*.md` 已刪除）
- **不保留**任何 backward compatibility shim
- System prompt 目標 ≤300 tokens（原本每個 agent ~1,700 tokens）
- 每個新模組 **TDD 先行**：先寫 `tests/`，再寫實作

## 目前重構狀態
**查看 `PROGRESS.md` 取得最新進度（含「下一個動作」）**

---

## 關鍵檔案索引

### ✅ 新建完成（重構核心）
| 檔案 | 狀態 | 說明 |
|------|------|------|
| `structured_outputs.py` | ✅ | Pydantic schemas：MEReport / DSReport / DEReport / JudgeScore / SelfEvalResult |
| `context_assembler.py` | ✅ | 取代 prompt/ 資料夾；動態組裝 ≤300 token system prompt |
| `llm_harness.py` | ✅ | LLMCallHarness + SelfEvaluator；記錄 latency/token |
| `judge.py` | ✅ | JudgeLLM.judge_sync()；final_answer 品質評估 |
| `llm_cache.py` | ✅ | ExactMatchCache (LRU+TTL) + PrefixStabilizer + GeminiContextCacheManager |
| `tests/conftest.py` | ✅ | mock fixtures（不呼叫真實 API） |
| `tests/test_structured_outputs.py` | ✅ | 14/14 |
| `tests/test_context_assembler.py` | ✅ | 14/14 |
| `tests/test_llm_harness.py` | ✅ | 12/12 |
| `tests/test_judge.py` | ✅ | 9/9 |
| `tests/test_llm_cache.py` | ✅ | 14/14 |

### ✅ 已完成（Step 6 接線）
| 檔案 | 狀態 | 說明 |
|------|------|------|
| `metrics.py` | ✅ | 加 ~20 個新欄位 + note_judge_result() |
| `run_logger.py` | ✅ | llm_call() context mgr；summary.json；assert → warning |
| `prompt_builder.py` | ✅ | 完整重寫為 thin wrapper → context_assembler |
| `delegate_tools.py` | ✅ | _summarize_out 改 Pydantic primary path |
| `supervisor_workflow.py` | ✅ | phase-aware prompt + judge trigger |
| `me_workflow.py` | ✅ | LLM invoke → LLMCallHarness；SelfEvaluator |
| `de_workflow.py` | ✅ | LLM invoke → LLMCallHarness |
| `ds_workflow_s2.py` | ✅ | LLM invoke → LLMCallHarness；SelfEvaluator |
| `chat_cli.py` | ✅ | judge score + usage summary 顯示 |
| `common.py` | ✅ | AgentState 加 token_usage / harness_metrics 欄位 |

### ✅ KG 接線（KG-5 完成）
| 檔案 | 狀態 | 說明 |
|------|------|------|
| `neo4j_kg.py` | ✅ | Neo4j 連線 + kg_query_fault_local()（fallback） |
| `tep_knowledge.py` | ✅ | TEP lookup tables（FAULT_DESCRIPTIONS/FAULT_SENSORS/PROCESS_UNITS） |
| `me_tools.py` | ✅ | kg_query_fault @tool → Neo4j + fallback；已加入 get_me_tools() |

### ✅ 已切換（非重構核心）
| 檔案 | 狀態 | 說明 |
|------|------|------|
| `common.py` | ✅ | Vertex AI → Google AI Studio (langchain-google-genai) |
| `me_docs.py` | ✅ | VertexAIEmbeddings → GoogleGenerativeAIEmbeddings |
| `chat_cli.py` | ✅ | 加 load_dotenv() |

### 已刪除（不要再建）
- `prompt/` 資料夾（12 個 .md card）
- `prompts.py`（靜態 prompt 字串）

### 未修改（現有功能正常）
| 檔案 | 說明 |
|------|------|
| `router.py` | P2P 委派調度器（最多 8 跳） |
| `delegate_tools.py` | 子圖工廠與 _run_subgraph（Step 6 前保持原樣） |
| `bb_tools.py` | 黑板讀寫工具 |
| `me_tools.py` / `me_docs.py` | ME RAG 工具 |
| `de_tools.py` | DE SQL 工具 |
| `ds_tools.py` | DS Python 執行工具 |
| `te_tag_map.csv` | TEP 感測器標籤對照 |
| `TEP_docs/` | 領域知識 PDF + Markdown |

---

## 如何執行測試
```bash
cd MT-phase-2
pytest tests/ -v --tb=short -q
```
**預期：81 passed**（MAS Opt Plan A+B+D 完成後）

## 如何執行系統
```bash
cp .env.example .env  # 填入 GOOGLE_API_KEY
python chat_cli.py
```

## 架構圖（完成後）
```
context_assembler.py  ≤300 token system prompts
    → llm_harness.py LLMCallHarness + SelfEvaluator
    → llm_cache.py   ExactMatchCache + PrefixStabilizer
        → supervisor_workflow.py
            → router.py → delegate_tools.py
                → me_workflow / de_workflow / ds_workflow
        → judge.py  final_answer 後觸發
structured_outputs.py  被 delegate_tools._summarize_out 使用
metrics.py + run_logger.py  observability 層
```
