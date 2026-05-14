# `supervisor_tools`

## 檔案目的

`supervisor_tools` 為最高層級的協調者——**Supervisor 代理**——定義了一套專用的工具。這些工具本質上不是執行具體任務的工具，而是 Supervisor 用來**發號施令**的**委派指令（Delegation Commands）**。

此模組的核心作用是將「委派給某個專家」這一抽象的決策，轉化為一個具體的、可被 LangChain 框架理解和調用的 `@tool`。

## 主要功能與工具

此模組使用 Pydantic 模型來嚴格定義每個工具的參數，然後將其封裝為 LangChain 工具。

1.  **Pydantic 參數模型**:
    *   `DelegateMEArgs`: 定義了委派給 ME（機器專家）時必須提供的參數，即 `question`（要問的問題）。
    *   `DelegateDEArgs`: 定義了委派給 DE（數據工程師）時必須提供的參數，即 `task`（要執行的數據任務）。
    *   `DelegateDSArgs`: 定義了委派給 DS（數據科學家）時必須提供的參數，即 `task`（要執行的分析任務）。
    *   `FinalAnswerArgs`: 定義了提供最終答案時必須提供的參數，即 `answer`（綜合專家意見後給出的最終回覆）。

2.  **工具定義**:
    *   `@tool("delegate_to_me", ...)`: 將任務委派給 ME 的指令。當 Supervisor 決定需要從文檔中尋找答案時，它會調用此工具。
    *   `@tool("delegate_to_de", ...)`: 將任務委派給 DE 的指令。當需要從資料庫中提取或處理數據時，Supervisor 會調用此工具。
    *   `@tool("delegate_to_ds", ...)`: 將任務委派給 DS 的指令。當需要進行數據分析、建模或視覺化時，Supervisor 會調用此工具。
    *   `@tool("final_answer", ...)`: 標誌著整個任務流程的結束。當 Supervisor 認為已經收集了足夠的證據並準備好回答使用者最初的問題時，它會調用此工具來提交最終答案。

3.  **工具集提供者 (`get_supervisor_tools`)**:
    *   這是一個工廠函式，它將上述所有工具打包成一個列表，方便 `supervisor_workflow` 在構建 Supervisor 的 LLM 執行器時直接使用。

## 設計理念

*   **意圖即工具（Intent as a Tool）**: 這個模組的設計巧妙地將 Supervisor 的「意圖」（例如，「我需要讓 ME 去查資料」）轉化為一個形式化的「工具調用」。這使得 Supervisor 的決策過程可以完全在 LangChain 的 ReAct 框架內進行，而無需為其設計一套獨立的指令系統。
*   **無執行邏輯**: 這些工具本身**不包含任何執行邏輯**。當 Supervisor 調用 `delegate_to_de_tool` 時，它僅僅是返回一個表示「意圖」的字典。真正的執行邏輯位於 `router` 中。`router` 會攔截到這個工具調用，並根據工具的名稱（`delegate_to_de`）來啟動對應的 DE 子工作流。
*   **強型別參數**: 使用 Pydantic 模型來定義工具的參數，確保了 Supervisor 在生成委派指令時，必須提供格式正確、內容完整的參數（例如，委派給 ME 時必須提供 `question`），這增加了系統的穩定性。

## 依賴關係

*   **LangChain**: `langchain_core.tools.tool`。
*   **Pydantic**: 用於定義參數的 `BaseModel` 和 `Field`。

## 在專案中的角色

`supervisor_tools` 是 Supervisor 代理的「**權杖**」或「**指揮棒**」。它為 Supervisor 提供了一套清晰、有限且強型別的行動選項。通過限制 Supervisor 只能從這幾個委派工具中進行選擇，系統的設計者確保了 Supervisor 始終扮演著一個高層次的協調者角色，而不會陷入到具體的任務執行細節中。這是在一個分層式多代理系統中實現職責分離（Separation of Concerns）的關鍵設計。

# `me_tools`

## 檔案目的

`me_tools` 為機器專家（Machine Expert, ME）代理提供了一套專用的 LangChain 工具。這些工具是 ME 代理執行其 RAG（檢索增強生成）工作流的直接介面。它們將 `me_docs` 提供的底層索引和檢索能力，封裝成 LLM（大型語言模型）在 ReAct 循環中可以理解和調用的具體「行動」。

## 主要功能與工具

1.  **索引初始化**:
    *   `init_me_index_from_dir(doc_dir: str)`: 這是一個初始化函式，它調用 `me_docs.load_or_build_index` 來載入或建立 RAG 索引。這個函式必須在 ME 代理開始工作前被調用一次，以確保全域變數 `DOC_INDEX` 已被正確設定。

2.  **檢索工具**:
    *   `@tool initial_search(topic: str)`: 這是 ME 代理的研究起點。它接收一個主題（`topic`），並調用 `DOC_INDEX.search` 來執行廣泛的混合搜尋（Hybrid Search）。
        *   **同義詞擴展**: 在搜尋前，它會對查詢主題進行同義詞擴展（`_syn_expand`），以提高召回率。
        *   **文件類型加權**: 它會對 Markdown (`.md`) 文件的分數給予輕微加權，並根據策略（`md_first`, `pdf_first`）調整從不同類型文件中選取候選頁面的數量。
        *   **穩定排序**: 使用固定的亂數種子（`get_seed`）來打亂同分項的順序，確保了即使分數相同，每次運行的排序結果也是一致和可重複的。
    *   `@tool read_document_chunk(doc_id: str, page: int)`: 根據 `initial_search` 返回的候選頁面，ME 代理可以調用此工具來讀取指定文件（`doc_id`）的特定頁面（`page`）的完整文本內容。

3.  **合成與引用工具**:
    *   `@tool synthesize_and_cite(question: str, hits: List[Dict])`: 這是 ME 代理工作流中**最關鍵**的工具，負責生成最終答案。
        *   **Rerank**: 在合成答案之前，它會先讓 LLM 對提供的 `hits`（已讀取的文本片段）進行一次重排序（Rerank），以選出與問題最相關的證據。
        *   **合成**: 將經過重排序的、最相關的文本片段（`context`）與原始問題一起提交給 LLM，並要求其生成一個綜合性的答案。
        *   **自動引用 (`_auto_cite`, `_ensure_full_citations`)**: 這是此工具的核心亮點。在 LLM 生成答案後，它會執行一個複雜的後處理步驟，以確保答案的每一句話都附帶了正確的來源引用 `[檔名 p.頁碼]`。它能夠處理各種邊界情況，如列表、標題，並能智慧地在沒有引用的句子後面補上最相關的引用。

4.  **黑板互動工具**:
    *   `@tool me_write_fact(...)`: 允許 ME 將其發現的關鍵事實或總結寫入中心黑板。它通過調用 `bb_tools.bb_write` 來實現，確保了寫入的內容有關聯的 `topic_id` 和 `artifact_id`，使其可被其他代理發現和追蹤。
    *   `@tool me_warmup_read()`: 一個引導性的工具，建議代理在開始時先讀取一次黑板。這有助於觸發 `bb_read` 事件，以便在後續分析中計算知識共享的相關指標（如讀取延遲）。

5.  **工具集提供者 (`get_me_tools`)**:
    *   `get_me_tools(mode: str)`: 將上述所有工具打包成 LangChain 相容的列表和 `tool_map`，供 `me_workflow` 使用。

## 設計與互動模式

*   **研究工作流的體現**: `initial_search` -> `read_document_chunk` -> `synthesize_and_cite` 這一系列工具共同構成了一個經典的「檢索-閱讀-綜合」的研究工作流。
*   **引用作為一等公民**: `synthesize_and_cite` 中複雜的引用後處理邏輯表明，系統的設計非常強調答案的**可追溯性**和**證據支持**。它不是簡單地讓 LLM 自己生成引用，而是通過程式碼邏輯來強制和規範引用的格式與位置，大大提高了可靠性。
*   **與底層 RAG 解耦**: `me_tools` 作為一個中間層，將高階的「研究」行動（如 `initial_search`）與底層的「索引」實現（`me_docs`）解耦。這使得未來可以輕易地替換底層的索引技術，而無需改變 ME 代理的行為邏輯。

## 依賴關係

*   **Python 函式庫**: `json`, `re`, `os`, `random`。
*   **LangChain**: `langchain_core.tools.tool`, `langchain_core.messages`。
*   **內部模組**:
    *   `me_docs`: **核心依賴**，提供了 `DocIndex` 物件和 `load_or_build_index` 等底層 RAG 功能。
    *   `bb_tools`: 用於與中心黑板進行寫操作。
    *   `run_logger`: 用於記錄工具執行事件。
    *   `common`: 獲取全域 `llm` 實例和 `get_seed` 函式。

## 在專案中的角色

如果說 `me_docs` 是 ME 代理的「長期記憶」（知識庫），那麼 `me_tools` 就是它的「工作記憶」和「推理能力」。它定義了 ME 如何與其知識庫互動，並如何將檢索到的零散資訊轉化為一個有結構、有證據支持的、可交付的答案。它是 ME 代理能夠作為一個「專家」參與團隊協作的關鍵所在。

# `ds_tools`

## 檔案目的

`ds_tools` 為數據科學家（Data Scientist, DS）代理提供了一套專用的 LangChain 工具。這些工具賦予了 DS 代理執行 Python 程式碼進行數據分析、與黑板上的數據集進行互動的能力。此模組是 DS 代理完成其分析和建模任務的基礎。

## 主要功能與工具

1.  **Python 程式碼執行**:
    *   `@tool execute_python_code(code: str)`: 這是 DS 代理最核心、最強大的工具。它本質上是對 LangChain 的 `PythonREPLTool` 的一個封裝。
        *   **沙箱環境**: 允許 DS 代理在一個受控的 Python 直譯器環境（REPL）中執行任意 Python 程式碼片段。
        *   **能力**: DS 可以利用這個工具來讀取檔案（例如，使用 `pandas.read_parquet`）、進行數據處理、統計分析、機器學習建模（使用 `scikit-learn`）以及數據視覺化（使用 `matplotlib`）。
        *   **事件記錄**: 每次程式碼執行都被 `run_logger` 的 `tool_exec` 上下文管理器包裹，用於記錄執行的成功與否、耗時等指標。如果程式碼執行出錯，錯誤事件也會被記錄下來。

2.  **黑板數據集互動**:
    *   `@tool bb_list_datasets()`: 列出當前黑板上所有已註冊的數據集。這通常是 DS 開始工作時的第一步，用來了解有哪些可用的數據。
    *   `@tool bb_get_latest_dataset()`: 獲取黑板上最新註冊的一個數據集。這是一個方便的快捷工具。
    *   `@tool bb_preview_dataset(ref: str, n: int = 5)`: 預覽一個指定的 Parquet 或 CSV 檔案的內容，包括其欄位名、總行數和前 `n` 行的數據。這使得 DS 無需完整讀取整個檔案就能快速了解其結構。
    *   `@tool ds_pick_dataset_path(prefer_topic: str = "")`: 這是一個更智慧的數據集選擇工具。它會：
        *   從黑板上列出所有數據集。
        *   如果提供了 `prefer_topic`，它會優先尋找與該主題 ID (`topic_id`) 匹配的數據集。
        *   如果沒有找到或沒有提供 `topic_id`，它會回退到選擇最新的一個可讀數據集。
        *   最終回傳一個包含 `{"status":"ok","path":"..."}` 的 JSON 字串，直接為 `execute_python_code` 中的 `pd.read_parquet` 提供檔案路徑。

3.  **工具集提供者 (`get_ds_tools`)**:
    *   `get_ds_tools(mode: str)`: 這是一個工廠函式，它將上述所有工具打包成一個列表和一個字典（`tool_map`），方便 `ds_workflow_s2` 來建構代理的執行器。

## 設計與互動模式

*   **程式碼即行動**: DS 代理的核心工作模式是通過生成和執行 Python 程式碼來完成任務。`execute_python_code` 是實現這一模式的唯一途徑。
*   **數據發現**: `bb_list_datasets` 和 `ds_pick_dataset_path` 等工具的組合，為 DS 提供了一個從「數據在哪裡？」到「我應該使用哪個檔案？」的清晰發現路徑。
*   **安全性與隔離**: 雖然 `execute_python_code` 很強大，但它在一個 REPL 環境中運行，與主應用程式的進程有一定的隔離。工具的輸出（`stdout`）會被捕獲並回傳給 LLM，而不是直接打印到主控台。
*   **可觀測性**: 所有工具的調用，特別是 `execute_python_code`，都被 `run_logger` 嚴密監控，使得 DS 的每一步分析操作都是可追溯和可評估的。

## 依賴關係

*   **Python 函式庫**: `os`, `json`。
*   **LangChain**: `langchain_core.tools.tool`, `langchain_experimental.toolsthonREPLTool`。
*   **內部模組**:
    *   `bb_tools`: 依賴其 `bb_list_datasets_py` 等底層函式來與黑板數據進行互動。
    *   `run_logger`: 用於記錄工具執行事件。

## 在專案中的角色

`ds_tools` 是 DS 代理的「武器庫」。它提供的工具讓 DS 能夠從一個抽象的分析任務（例如，「找出導致故障的根本原因」）轉化為具體的、可執行的程式碼。這個模組的設計直接決定了 DS 代理能夠執行任務的廣度和深度，是整個 MAS 團隊實現最終數據洞見和價值產出的關鍵執行層。

# `de_tools`

## 檔案目的

`de_tools` 為數據工程師（Data Engineer, DE）代理提供了一套專用的 LangChain 工具。這些工具賦予了 DE 代理與 SQL 資料庫互動、進行數據轉換以及向黑板交付數據集的能力。此模組是 DE 代理執行其核心職責的基礎。

## 主要功能與工具

1.  **SQL 資料庫互動**:
    *   `@tool sql_db_query(query: str)`: 這是 DE 最核心的工具。它負責執行一個唯讀的 `SELECT` SQL 查詢。
        *   **安全性**: 內建正則表達式 `FORBIDDEN` 來防止 `INSERT`, `UPDATE`, `DELETE` 等寫入操作。
        *   **自動註冊 (Auto-Register)**: 這是一個關鍵的保險絲機制。當查詢成功後，如果環境變數 `DE_AUTOREGISTER` 為 `1`（預設值），它會自動將查詢結果的**輕量樣本**儲存為一個 Parquet 檔案，並調用 `bb_register_dataset_path` 將其註冊到黑板。這確保了即使 DE 沒有明確執行交付步驟，下游的 DS 代理也能立即獲得一份可用的數據樣本。
        *   **事件記錄**: 每次調用都會通過 `run_logger` 記錄詳細的工具執行事件。
    *   `@tool sql_db_list_tables()`: 列出資料庫中所有可用的資料表。
    *   `@tool sql_db_schema(table_name: str)`: 獲取指定資料表的結構，包括欄位名和數據類型。

2.  **數據轉換**:
    *   `@tool pandas_transform(df_json: str, operations: List[str])`: 允許 DE 對一個以 JSON 格式表示的 DataFrame 執行一系列的轉換操作。支援的操作包括：
        *   `rename`: 重命名欄位。
        *   `cast`: 轉換數據類型。
        *   `select`: 選擇部分欄位。
        *   `dropna`: 刪除含有缺失值的行。
        *   `to_numeric`: 將欄位轉換為數值類型。
        *   `parse_mmss_to_hhmmss`: 自訂的時間格式轉換。
        這提供了一個在 SQL 無法輕易完成數據清洗或格式化時的強大補充能力。

3.  **數據交付**:
    *   `@tool deliver_dataframe(df_json: str)`: 將一個以 JSON 格式表示的 DataFrame 儲存為 Parquet 檔案，並將其正式註冊到黑板。這通常是 DE 在完成所有數據提取和轉換後的最後一步，標誌著一個完整的、可供 DS 使用的數據集已準備就緒。

4.  **工具集提供者 (`get_de_tools`)**:
    *   `get_de_tools(mode: str)`: 這是一個工廠函式，它將上述所有工具打包成一個列表和一個字典（`tool_map`），方便 `de_workflow` 根據需要來建構代理的執行器。

## 核心設計與互動模式

*   **ReAct 模式**: 所有工具都被設計為在一個 ReAct（Reasoning and Acting）循環中被 LLM 調用。工具的回傳值通常是 JSON 字串，包含了 `status`（ok/error）和結果，供 LLM 在下一步的思考中參考。
*   **與黑板的整合**: DE 的工具與 `bb_tools` 緊密整合。
    *   `sql_db_query` 的自動註冊功能通過調用 `bb_register_dataset_path` 來實現。
    *   `deliver_dataframe` 也依賴黑板來發布最終產出物。
*   **可觀測性**: 每個工具的執行都通過 `run_logger` 進行了插樁（instrumented），記錄了工具的調用者、參數、延時和成功狀態，這對於後續的性能分析和行為追蹤至關重要。
*   **資料庫連線管理**: 模組在頂層通過 `create_engine` 維護一個資料庫連線引擎 `ENGINE`，並提供 `_get_db_engine` 函式來獲取它，確保了連線的統一管理。

## 依賴關係

*   **Python 函式庫**: `sqlalchemy`, `pandas`, `json`, `os`。
*   **LangChain**: `langchain.tools.tool`。
*   **內部模組**:
    *   `bb_tools`: 用於將數據集註冊到黑板。
    *   `run_logger`: 用於記錄工具執行事件。

## 在專案中的角色

`de_tools` 是 DE 代理的「手和腳」，使其能夠與外部數據源（SQL 資料庫）進行互動，並對數據進行處理。它是連接原始數據和下游分析（DS 代理）的關鍵橋樑，其設計直接影響了數據的可用性和 MAS 團隊的整體效率。
