# TEP 工業製程故障診斷 — 多智能體系統

> 一個以協作推理為核心的生產級多智能體 AI 系統，由多位專業 AI 智能體共同診斷工業製程故障。

[English](./README.md) | **繁體中文**

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow)

---

## 這個系統在做什麼？

你丟一個問題進去，例如「反應器進料溫度異常飆升，這是什麼故障？」，系統內部的 AI 智能體團隊會協作回答：

- **機器專家（ME）** 翻遍技術文件 PDF 與知識圖譜，找出領域依據
- **資料工程師（DE）** 對歷史感測器資料庫執行 SQL，取出異常時段數據
- **資料科學家（DS）** 執行統計分析、跨相關計算、繪製診斷圖
- **督導者（Supervisor）** 統籌三者、決定呼叫誰、合成最終診斷結論

研究領域是 **Tennessee Eastman Process（TEP）**——一個工業製程控制與故障偵測的標準基準，包含 21 種標記故障，涉及反應器溫度、流量、壓縮機喘振等情境。

---

## 系統架構

```
使用者輸入（CLI 或 REST API）
        │
        ▼
┌─────────────────────────────────────────────────┐
│             督導者 Supervisor（LangGraph）        │
│  • 決定呼叫哪位專家                              │
│  • 維護共用黑板（事實 / 資料集 / 引用文獻）       │
│  • 合成最終答案                                  │
└──────────────┬──────────────────────────────────┘
               │  透過 Router 委派
       ┌───────┼────────────────┐
       ▼       ▼                ▼
  ┌─────────┐ ┌──────────────┐ ┌──────────────────┐
  │   ME    │ │     DE       │ │       DS         │
  │機器專家  │ │  資料工程師  │ │   資料科學家     │
  │         │ │              │ │                  │
  │ • PDF   │ │ • SQL 查詢   │ │ • Python 分析    │
  │   RAG   │ │   TEP 感測器 │ │ • 統計 / 繪圖    │
  │ • Neo4j │ │   資料庫     │ │ • 跨相關 / 因果  │
  │   知識圖 │ │ • 資料集匯出 │ │ • 異常偵測       │
  └─────────┘ └──────────────┘ └──────────────────┘
       │
  ┌────┴──────────┐
  │  TEP PDF KG   │
  │（Neo4j 圖譜） │
  │  • 由學術論文 │
  │    PDF 解析   │
  │    建構而來   │
  └───────────────┘
```

### 模組對照表

| 檔案 / 資料夾 | 功能 |
|---|---|
| `chat_cli.py` | 互動式 CLI 入口 |
| `api_server.py` | FastAPI REST 伺服器 |
| `agents/supervisor_workflow.py` | LangGraph 督導者圖 |
| `agents/router.py` | 委派邏輯與專家分派 |
| `agents/me_workflow.py` / `me_tools.py` | 機器專家智能體 |
| `agents/de_workflow.py` / `de_tools.py` | 資料工程師智能體 |
| `agents/ds_workflow_s2.py` / `ds_tools.py` | 資料科學家智能體 |
| `agents/bb_tools.py` | 共用黑板（智能體間記憶） |
| `simulation/diagnose_flow.py` | 批次 / 自動化診斷流程 |
| `core/context_assembler.py` | Prompt 上下文組裝 |
| `core/llm_harness.py` / `llm_cache.py` | LLM 呼叫管理與快取 |
| `core/judge.py` / `metrics.py` | 答案品質評分 |
| `knowledge/neo4j_kg.py` | Neo4j 知識圖譜存取 |
| `tep_pdf_kg/` | PDF → Neo4j 知識圖譜 pipeline |
| `eval/` | Golden QA 評估 + 回歸閘門 |
| `tests/` | 單元與整合測試套件 |

---

## Tennessee Eastman Process（TEP）

TEP 是工業製程控制與故障偵測研究的標準基準測試平台，模擬一座化工廠，包含：

- **52 個感測器變數**（溫度、壓力、流量、液位）
- **21 種標記故障類型**（IDV 1–21），涵蓋步階擾動到閥門卡死
- **連續時間序列資料**，代表正常與異常的製程運作

本系統將 TEP 診斷視為**多跳推理問題**：正確答案需要同時關聯即時感測器異常、歷史基準、技術文獻領域知識與統計分析——這些任務分散給三位專家智能體協作處理。

---

## 核心功能

- **多智能體協作**：透過 LangGraph `StateGraph` 實現帶型別狀態與中斷安全路由的協作流程
- **共用黑板機制**：智能體將事實、資料集、引用文獻發布到黑板，其他智能體可接力使用
- **雙模式互動**：支援對話式 CLI（`chat_cli.py`）與 REST API（`api_server.py`）
- **自動化診斷 Pipeline**：`diagnose_flow.py` 支援批次 / 串流觀測資料的無人監督診斷
- **從 PDF 建構知識圖譜**：TEP 學術論文由 Docling 解析、分塊，再透過 Gemini 提取三元組寫入 Neo4j
- **評估框架**：Golden QA 資料集（`eval/golden_qa.json`）+ 自動化回歸閘門（`eval/regression_gate.py`）
- **LLM 回應快取**：降低開發期間的 API 費用
- **結構化輸出**：Pydantic v2 保障智能體間資料契約的可靠性
- **API 速率限制與健康檢查**：符合生產環境需求

---

## 技術棧

| 層次 | 技術 |
|---|---|
| 智能體框架 | LangGraph、LangChain |
| 大型語言模型 | Google Gemini（`langchain-google-genai`） |
| API 伺服器 | FastAPI + uvicorn |
| 知識圖譜 | Neo4j |
| 感測器資料庫 | SQLite（`tep_combined.db`） |
| 資料分析 | Pandas、NumPy、scikit-learn |
| 結構化輸出 | Pydantic v2 |
| PDF 解析 | Docling / PyMuPDF |
| 測試 | pytest |

---

## 快速開始

### 1. 安裝依賴

```bash
conda create -n tep-mas python=3.11
conda activate tep-mas
pip install -r requirements.txt
```

### 2. 設定環境變數

```bash
cp .env.example .env
# 填入：GOOGLE_API_KEY、NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD
```

### 3. 啟動互動式 CLI

```bash
python chat_cli.py
```

### 4. 啟動 REST API

```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
```

送出一筆診斷請求：

```bash
curl -X POST http://localhost:8000/diagnose \
  -H "Content-Type: application/json" \
  -d '{"observation_path": "datasets/sample_obs.parquet"}'
```

### 5. 執行評估套件

```bash
# 單元 + 整合測試
pytest tests/ -q

# Golden QA 回歸閘門
python eval/regression_gate.py
```

---

## 範例問句

以下是這個系統設計用來回答的問題類型。每個問題都需要督導者協調多位專家，才能給出完整答案。

**感測器異常診斷**
> 分離器液位（XMEAS_12）出現無明顯外因的間歇性異常飆升，沒有提供故障 ID。請提出至少 3 個機制假說、設計可驗偽的測試、執行領先滯後 / 因果分析，並發布含信心度的候選因果圖（DAG）。

**製程根因調查**
> 我們懷疑冷卻迴路機制正在影響反應器穩定性，但「冷卻水進口溫度」的標籤語義不確定（例如 XMEAS_46 或其他）。請建立 / 更新標籤對照表並附上證據，執行多時間窗的領先滯後掃描，提供機制解釋與可行介入方案。

**受限條件下的優化**
> 管理層要求在不明顯增加風險的前提下提升 5–10% 產能，同時面臨可能的迴路飽和或上游組成變異。請說明機制限制、透過歷史反事實建構響應面，並提出保守與積極兩個設定點，附監控 KPI 與回滾標準。

---

## 論文研究背景

本系統是一篇探討**多智能體系統設計應用於工業故障診斷**碩士論文的實作成果。研究聚焦於不同提示策略（標準、辯論、德爾菲、PTOW）如何影響 TEP 故障情境下的診斷準確率。

程式碼設計定位為「研究等級但具備生產形態」：
- 模組化設計，可替換 LLM 或智能體策略
- 透過結構化運行日誌與指標提供可觀測性
- 以 Golden Eval 集進行回歸閘門驗證

研究理論背景請參閱 [`docs/research_context/`](./docs/research_context/)：

- **01_Motivation** — 工業應用相關性與多智能體故障診斷的立論依據
- **02_Definitions** — 核心構念：穩定性、協作品質、知識流指標
- **03_Methods** — 實驗框架、指標定義、黑板架構
- **04_Discussion** — 研究結果在製造業治理的可移植性、限制與未來方向

---

## 授權

MIT
