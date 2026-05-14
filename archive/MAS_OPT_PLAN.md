# MAS 架構優化計劃 — 2026-05-13

## 背景：今晚 Live Eval 診斷結論

### 已修復的 Bug（本 session）
| Bug | 根本原因 | 修法 |
|-----|---------|------|
| ME subgraph 不執行 | `me_docs.py` 的 `import camelot` 在 module-level，camelot 未安裝 → import chain 斷裂 | 改為 lazy import |
| ME subgraph 不執行（其次） | RAG init 失敗 → `delegate_to_me` 直接 return error，ME subgraph 從未進入 | 改為注入 `[System]` note，讓 LLM 自適應 |
| run_eval.py 找不到 API key | 未呼叫 `load_dotenv()` | 加入 dotenv 載入 |

### Live Eval 修後行為（已驗證）
- ME 正確執行：`kg_query_fault(4)` → `synthesize_and_cite` → 答案含 step / cooling water / reactor / temperature
- DE 問題：只跑 `COUNT(*)` 就停，沒有 `deliver_dataframe` 真實資料，DS 拿到空殼 parquet
- DS 問題：parquet 欄位是 `COUNT(*)` 而非感測器資料，`df.sort_values('sample')` → KeyError

---

## 現有架構的三大問題

### 問題 A：嚴格序列執行
```
Supervisor → delegate_to_me  → [等 ~30s]
           → delegate_to_de  → [等 ~5s]
           → delegate_to_ds  → [等 ~30s]
           → final_answer
總耗時：~65s（ME + DE + DS 完全沒有重疊）
```
ME（KG lookup）與 DE（SQL query）完全獨立，理論上可以並行，節省 ~30s。

### 問題 B：跨 Agent 知識斷層（無 BB-mediated context）
ME 查完 KG 知道「IDV_4 → 看 XMEAS_9, XMEAS_7」，但這個知識**沒有自動傳遞給 DE**。
DE 收到的只是 Supervisor 的自然語言任務說明，DE LLM 自己猜要查什麼、要不要 deliver。

根本原因：Blackboard 有讀寫功能，但沒有強制的跨 agent **結構化寫入協定**。

### 問題 C：P2P 是同步阻塞嵌套，不是真正協作
DS 呼叫 `request_delegate("DE")` → Router 在 DS 的那一輪裡同步執行 DE subgraph → DE 完成才回到 DS。
等同於 blocking function call，不是 peer-to-peer。DE 不知道 DS 需要什麼格式，DS 不知道 DE 有什麼。

---

## 優化方案

### 方案 B：BB-mediated Context Injection（最高優先）
**目標**：ME 查完後，DE 自動知道要查哪些感測器、要不要 deliver。

**實作**：
1. ME 的 `kg_query_fault` tool 回傳後，在 `delegate_to_me` 函數裡自動解析結果，將結構化 fault facts 寫入 BB：
```python
# delegate_tools.py — after ME subgraph completes
fault_facts = _extract_me_fault_facts(out_state)
if fault_facts:
    bb_add_facts([fault_facts], agent="ME", source_tool="kg_query_fault")
```

2. `delegate_to_de` 開頭自動讀 BB 的 ME fault facts，注入到 DE 的 task context：
```python
# delegate_tools.py — delegate_to_de
me_facts = _read_bb_me_facts(state)
if me_facts:
    task = f"[Context from ME]\n{me_facts}\n\nPlease deliver_dataframe with actual sensor data (not just COUNT).\n\n{task}"
```

**效果**：DE 不再靠猜，直接收到「查 xmeas_9, xmeas_7，faultnumber=4，要 deliver_dataframe」。

---

### 方案 D：結構化 ME BB Write 協定
**目標**：ME 結束後 BB 有一個標準格式的 fault fact，讓 DE 和 DS 都能讀取。

**結構**：
```json
{
  "agent": "ME",
  "source_tool": "kg_query_fault",
  "fault_id": 4,
  "root_cause": "reactor cooling water inlet temperature step change",
  "diagnostic_sensors": [
    {"sensor": "xmeas_9", "direction": "increases", "magnitude": "strong"},
    {"sensor": "xmeas_7", "direction": "increases", "magnitude": "mild"}
  ],
  "process_unit": "Reactor"
}
```

**實作**：在 `me_tools.py` 的 `kg_query_fault` 工具裡，把 KG 查詢結果寫入 BB（或在 `delegate_to_me` post-process 時做）。

---

### 方案 A：Router 並行執行
**目標**：ME + DE 在同一 Supervisor turn 並行跑，節省 ~30s latency。

**前置條件**：
1. Supervisor system prompt 說明「可在同一 turn 同時 call delegate_to_me 和 delegate_to_de」
2. Router 的 `for call in last.tool_calls` 改用 `ThreadPoolExecutor`
3. BB 作為並行結果的共享儲存（各自 write 自己的 section）

**實作草圖（router.py）**：
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

PARALLELIZABLE = {"delegate_to_me", "delegate_to_de"}
parallel = [c for c in last.tool_calls if c["name"] in PARALLELIZABLE]
serial   = [c for c in last.tool_calls if c["name"] not in PARALLELIZABLE]

if len(parallel) > 1:
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(_exec_one_tool, c["name"], c["args"], state): c
                   for c in parallel}
        for f in as_completed(futures):
            res = f.result()
            outputs.append(...)
```

**注意**：`state` dict 是共享的，並行寫入需要小心 race condition。BB（file-backed）天然是序列化的（JSON write），但 `state["metrics"]` 等 in-memory dict 需要加鎖或改用 `defaultdict` + atomic operations。

---

### 方案 C：P2P → BB Pull 模式（架構升級，後期）
**目標**：取消同步阻塞的 P2P，改用 BB 作為非同步需求佇列。

**現狀**（同步）：
```
DS turn: request_delegate(DE) → Router blocking → DE → DS continues
```

**新設計**（非同步）：
```
DS turn:  bb_add_open_issue("need: xmeas_9 fault=4 raw data")  → DS 結束本輪
Supervisor: 讀 BB open_issues → 看到 DS 需求 → delegate_to_de
DE turn:  deliver_dataframe → bb write
Supervisor: → delegate_to_ds  ← DS 從 BB 讀已備好的資料
```

**好處**：Supervisor 全局可見、可中斷、可優先排序；不再有嵌套 blocking。
**實作成本**：高（需改 supervisor_workflow、bb_tools 加 open_issues API、DS 工具改寫）。

---

## 優先順序與預估工作量

| 優化 | 依賴 | 工作量 | 效益 | 建議時機 |
|------|------|--------|------|---------|
| **B. BB-mediated ME→DE context** | 無 | ~30 行 | 高（DE 不再猜） | 下個 session 第一個 |
| **D. 結構化 ME BB write** | 無，但與 B 搭配 | ~20 行 | 高（跨 agent 知識傳遞） | 與 B 同步實作 |
| **A. Router 並行執行** | B/D 完成後 | ~50 行 + 測試 | 中（省 30s/query） | B/D 之後 |
| **C. P2P → BB Pull** | A 完成 | ~200 行 | 高（架構正確性） | 論文最終版 |

---

## 論文貢獻點對應

| 優化 | 對應論文主張 |
|------|------------|
| B + D | "BB-mediated structured knowledge transfer between heterogeneous agents" |
| A | "Parallel agent execution with blackboard synchronization" |
| C | "Asynchronous P2P coordination via shared working memory" |

這三點合起來可以支撐「Context Engineering + Harness Engineering」的論文框架：
- Context Engineering：B + D（確定性邏輯準備 context，LLM 只做理解和生成）
- Harness Engineering：A（執行層優化，不改 agent 邏輯）

---

## 待確認的技術細節（討論用）

1. **方案 A 的 state race condition**：`state["metrics"]["global_tool_calls"]` 在兩個 thread 同時 += 1 會有問題。方案：改成 `threading.Lock` 保護，或把 metrics 改成 thread-local + 最後 merge。

2. **方案 B 的 trigger 時機**：是在 `delegate_to_me` 的 post-process 裡自動做（程式碼驅動），還是讓 ME LLM 自己決定要不要 `me_write_fact`（LLM 驅動）？前者更可靠，後者更彈性。

3. **方案 C 的 open_issues 生命週期**：issue 被 DE 解決後，誰來 close？Supervisor 讀到 DE 的 deliver 後自動 close，還是 DS 確認資料夠了之後 close？

---

*產生時間：2026-05-13，基於今晚 live eval trace 分析*
