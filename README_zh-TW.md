# 工業製程分析多代理系統

這是一個以 [LangGraph](https://github.com/langchain-ai/langgraph) 為核心構建的研究型**多代理系統（Multi-Agent System, MAS）**，用於智能分析田納西-伊士曼製程（Tennessee Eastman Process, TEP）。TEP 是化工製程控制與故障檢測研究中廣泛採用的標準基準模擬器。

本系統協調一支由多個專業 AI 代理組成的團隊，透過整合 SQL 查詢、檢索增強生成（RAG）與 Python 數據科學工具，協作回答跨領域的複雜製程問題。

---

## 系統架構

```
使用者查詢
    │
    ▼
┌─────────────────────────────────────────┐
│           Supervisor Agent（監督者）     │  ← 高層規劃與任務委派
│  (政策模式: strict / gentle / free)     │
└──────────────────┬──────────────────────┘
                   │ 委派
                   ▼
┌─────────────────────────────────────────┐
│              Router（路由器）            │  ← 分派至各專家子圖
│   (管理代理間的 P2P 協作請求)            │
└────────┬──────────────┬─────────────────┘
         │              │              │
         ▼              ▼              ▼
   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │    ME    │   │    DE    │   │    DS    │
   │ 機器專家 │   │ 數據工程 │   │ 數據科學 │
   │  (RAG)   │   │  (SQL)   │   │(Python)  │
   └──────────┘   └──────────┘   └──────────┘
         │              │              │
         └──────────────┴──────────────┘
                        │
               ┌────────▼────────┐
               │  黑板（Blackboard）│  ← 代理間共享的非同步記憶體
               └─────────────────┘
```

### 核心架構模式

| 模式 | 實作方式 |
|---|---|
| **分層控制** | Supervisor → Router → 專家代理 |
| **ReAct 循環** | 每個專家代理運行自主的「推理-行動」循環 |
| **P2P 委派** | 代理可向同儕發起子委派（例如 DE 向 DS 請求數據分析） |
| **護欄機制** | Correction 節點對 Supervisor 行為執行規則約束 |
| **政策驅動行為** | `strict` / `gentle` / `free` 三種模式控制容錯程度 |
| **黑板模式** | 以檔案為基礎的共享記憶體，實現代理間非同步通訊 |

---

## 代理職責

### Supervisor Agent（監督者）
系統的最高決策者。接收使用者查詢後，將任務分解並委派給適合的專家代理。內建 **Correction 節點**作為行為護欄——例如，防止在取得足夠證據前過早給出最終答案。

### Router（路由器）
Supervisor 與專家子圖之間的執行橋樑，負責：
- 將 Supervisor 的委派指令分發至對應的專家子圖
- 管理專家代理間的 **P2P 委派**協作
- 透過可設定的跳躍上限進行循環偵測與防止

### Machine Expert（ME）—— RAG 文件檢索專家
從領域文件（PDF、技術手冊）中檢索資訊以回答問題：
- 使用 `pymupdf` 與 `camelot` 解析 PDF
- 基於 TF-IDF 與餘弦相似度的文件檢索
- 提供附引用來源的回答

### Data Engineer（DE）—— SQL 數據專家
查詢 TEP SQLite 資料庫以提取時序感測器數據：
- 具備 Schema 感知的 SQL 生成能力
- 動態查詢構建
- 將數據集輸出至黑板供後續分析使用

### Data Scientist（DS）—— Python 數據科學專家
對 DE 提供的數據執行量化分析：
- 透過 `PythonREPLTool` 執行沙盒化的 Python 程式碼
- 統計分析、視覺化與異常偵測
- 將圖表與分析結果寫回黑板

---

## 核心特色

- **多策略提示詞機制**：三種提示詞條件（`debate`辯論、`delphi`德菲、`ptow`規劃者-執行者）搭配 12 個代理提示卡，支援協作策略的受控實驗比較。
- **完整運行日誌**：結構化運行記錄捕捉每次代理行動、工具調用與訊息，支援離線分析與結果可重現。
- **指標收集**：追蹤每次運行的 Token 用量、工具調用次數、ME 引用率與運行時長。
- **黑板記憶體**：基於檔案的持久化共享儲存，解耦代理間的依賴並支援非同步數據傳遞。
- **故障注入就緒**：TEP 領域包含 21 種故障類型，可直接用於故障檢測與診斷工作流的實驗。

---

## 技術棧

| 類別 | 技術 |
|---|---|
| 代理框架 | [LangGraph](https://github.com/langchain-ai/langgraph) |
| LLM 後端 | 可配置（原為 Google Vertex AI，可替換為 OpenAI / Anthropic） |
| 資料庫 | SQLite + SQLAlchemy |
| PDF 解析 | PyMuPDF、Camelot |
| 數據分析 | NumPy、Pandas、Scikit-learn、Matplotlib |
| 執行環境 | Python 3.11+ |

---

## 專案結構

```
MT-phase-2/
├── chat_cli.py              # 入口點：MAS 的互動式 CLI
├── supervisor_workflow.py   # 頂層 LangGraph 圖（Supervisor + Router + Correction）
├── router.py                # 委派分發器與 P2P 協調邏輯
├── delegate_tools.py        # 子圖工廠與專家調用工具
├── supervisor_tools.py      # Supervisor 的委派工具（delegate_to_me/de/ds）
│
├── me_workflow.py           # Machine Expert（ME）ReAct 子圖
├── me_tools.py              # ME 工具：文件搜尋、檢索、摘要
├── me_docs.py               # PDF 索引與 TF-IDF 檢索引擎
│
├── de_workflow.py           # Data Engineer（DE）ReAct 子圖
├── de_tools.py              # DE 工具：SQL 查詢、Schema 檢查
│
├── ds_workflow_s2.py        # Data Scientist（DS）ReAct 子圖
├── ds_tools.py              # DS 工具：Python 程式碼執行
│
├── bb_tools.py              # 黑板讀寫工具
├── common.py                # 共享 LLM 配置、AgentState 定義、工具函式
├── prompt_builder.py        # 動態提示卡載入器
├── prompts.py               # 靜態提示詞字串
├── run_logger.py            # 結構化運行事件記錄器
├── metrics.py               # 每次運行的指標收集
├── tee_logs.py              # 控制台日誌同步寫入檔案
│
├── compute_proxies.py       # TEP 代理變數計算
├── cross_corr_tool.py       # 互相關分析工具
├── runjson_to_events.py     # 日誌解析與事件提取
├── agent_log_parser_template.py  # 離線日誌分析模板
│
├── prompt/                  # 代理提示卡（12 個：4 代理 × 3 條件）
│   ├── supervisor_card_debate.md
│   ├── supervisor_card_delphi.md
│   ├── supervisor_card_ptow.md
│   ├── de_card_*.md
│   ├── ds_card_*.md
│   └── me_card_*.md
│
├── TEP_docs/                # 領域知識文件（PDF + Markdown）
├── te_tag_map.csv           # TEP 感測器標籤名稱對照表
│
├── .env.example             # 環境變數範本
├── requirements.txt
└── README.md
```

---

## 快速開始

### 環境需求

- Python 3.11+
- LLM API 金鑰（支援 Vertex AI、OpenAI 或 Anthropic，請參見 `.env.example`）

### 安裝

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
cd YOUR_REPO_NAME

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 設定

```bash
cp .env.example .env
# 在 .env 中填入你的 API 金鑰與相關設定
```

### 執行

```bash
# 預設：strict 政策、debate 提示詞條件
python chat_cli.py

# 自定義配置
POLICY=gentle PROMPT_CONDITION=delphi python chat_cli.py
```

### 查詢範例

- *「反應器溫度與再循環壓縮機功率之間的關係為何？」*
- *「分析最近 500 個時間步的分離器液位感測器，是否有異常？」*
- *「TEP 規格定義了哪些故障條件？哪些變數最受故障 4 影響？」*

---

## 研究背景

本系統為碩士論文研究的一部分，旨在探討多代理協作策略在工業製程智能分析中的應用。以田納西-伊士曼製程作為實驗平台，原因在於其複雜度（41 個製程變數、12 個操縱變數、21 種故障類型）以及在製程控制與故障檢測文獻中的標準基準地位。

三種提示詞條件（`debate`、`delphi`、`ptow`）實現了不同的協作策略，使研究者能夠受控地比較不同互動模式對回答品質、收斂速度與代理行為的影響。

---

## 授權

本專案為學術研究用途。
