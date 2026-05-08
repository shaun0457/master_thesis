# `bb_tools.py`

## 檔案目的

`bb_tools.py` 實現了一個基於檔案系統的**黑板（Blackboard）**，作為多代理系統（MAS）中所有代理共享資訊的**單一事實來源（Single Source of Truth）**。它提供了一套穩定的 API，用於寫入、讀取和管理不同類型的資訊，如事實（facts）、數據集（datasets）、引用（citations）和待解決議題（open_issues）。

此模組的設計核心是**持久化**和**可追溯性**，確保所有寫入黑板的內容都有唯一的 `artifact_id`，並且所有操作都會觸發事件日誌，供後續的指標分析（ETL）使用。

## 主要功能

1.  **核心 API (`bb_write`, `bb_read`)**:
    *   `bb_write`: 將一條資訊（如一個發現、一個結論）寫入黑板的指定 `section`。此函式會：
        *   產生一個基於內容和時間的、穩定的 `artifact_id`。
        *   將紀錄（包含 `topic_id`, `created_by`, `preview` 等元數據）儲存到 `registry.json` 中。
        *   自動觸發 `emit_bb_write` 和 `note_tool_call` 事件，記錄寫入操作。
    *   `bb_read`: 從黑板的指定 `section` 讀取最新的資訊。此函式會：
        *   可選擇性地根據 `topic_id` 進行過濾。
        *   為每一次讀取操作觸發 `emit_bb_read` 事件，用於計算如「首次讀取延遲」、「知識重用率」等指標。

2.  **高階寫入介面 (`write_to_blackboard`)**:
    *   這是一個更方便的封裝函式，它接收一個 Python 物件（`content`），將其儲存為一個獨立的 JSON blob 檔案，然後再調用 `bb_write` 將該檔案的引用（URI）和摘要寫入黑板。
    *   它還會將寫入的內容**鏡射（mirror）**到當前的 `state` 物件中，讓同一回合（turn）內的下游代理可以立即看到此資訊，無需等待下一輪的 `bb_read`。

3.  **數據集管理 (`bb_register_dataset_path`, `bb_list_datasets_py`)**:
    *   `bb_register_dataset_path`: 專門用於將一個已存在的檔案（如 Parquet 或 CSV）註冊到黑板的 `datasets` section。它會記錄檔案路徑、格式、行數等元數據，並同樣產生一個 `artifact_id`。
    *   `bb_list_datasets_py`: 以 Python 列表的形式返回當前所有已註冊的數據集資訊。

4.  **LangChain 工具 (`@tool` decorators)**:
    *   模組內將部分核心功能（如 `bb_list_datasets`, `bb_preview_dataset`, `write_to_blackboard`）封裝成了 LangChain 工具。
    *   這使得 LLM（大型語言模型）可以直接在其 ReAct 流程中以工具調用的方式與黑板互動，回傳值為 JSON 字串。

5.  **穩定性與追蹤**:
    *   **穩定 ID**: 使用 `_mk_artifact_id` 函式，通過對內容進行雜湊（hash）來產生確定性的 ID，確保即使在多次運行中，相同的內容也能被識別。
    *   **事件打點**: 幾乎所有公開的函式都內建了對 `run_logger` 的調用，確保每一次黑板的讀寫操作都被記錄下來，這對於後續的協作行為分析至關重要。

## 檔案結構與路徑

*   所有黑板數據都儲存在 `RUNS_DIR` 環境變數指定的目錄下（預設為 `/mnt/data/runs`）。
*   每個 `run_id` 對應一個子目錄，其結構如下：
    ```
    <RUNS_DIR>/
    └── <run_id>/
        └── blackboard/
            ├── registry.json       # 所有 artifact 的索引
            └── <artifact_id>.json  # 由 write_to_blackboard 產生的內容實體
    ```

## 依賴關係

*   **Python 函式庫**: `os`, `json`, `time`, `uuid`, `hashlib`, `pandas`。
*   **LangChain**: `langchain.tools.tool` 用於定義 LLM 可調用的工具。
*   **內部模組**:
    *   `run_logger.py`: 用於發送 `emit_bb_write`, `emit_bb_read`, `note_tool_call` 等事件日誌。

## 設計理念

*   **中心化與去耦合**: 黑板作為中心化的資訊交換中心，讓代理之間無需直接通訊，降低了系統的耦合度。
*   **非同步協作**: 代理可以隨時將中間結果寫入黑板，而其他代理可以在需要時讀取，支持了非同步的工作流程。
*   **可觀測性**: 通過為每個操作打點，使得整個團隊的知識流動過程變得完全可觀測和可分析，是衡量團隊協作效率的基礎。
