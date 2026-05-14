# `common.py`

## 檔案目的

`common.py` 是一個共享的工具模組，提供了整個專案中多個代理和工作流都會用到的通用函式、設定和數據結構。它的主要目的是**減少程式碼重複**，並為整個系統提供一個一致的基礎，特別是在 LLM 配置、狀態管理和實驗日誌記錄方面。

## 主要功能

1.  **LLM 全域配置**：
    *   從環境變數中讀取 Google Vertex AI 的設定，如專案 ID (`VERTEX_PROJECT`)、地區 (`VERTEX_LOCATION`)、模型名稱 (`GEMINI_MODEL`) 和溫度 (`GEMINI_TEMP`)。
    *   初始化並導出一個全域的 `ChatVertexAI` 實例（名為 `llm`），供所有需要與語言模型互動的模組使用。

2.  **亂數種子管理 (`get_seed`, `set_global_seeds`)**:
    *   提供 `get_seed` 函式，以一個固定的優先序（`state['seed']` -> 環境變數 `SEED` -> 從 `run_id` 和 `task_id` 衍生）來獲取亂數種子，確保實驗的可重複性。
    *   提供 `set_global_seeds` 函式，用於設定 Python 內建的 `random` 和 `numpy` 的亂數種子。

3.  **共享狀態定義 (`AgentState`)**：
    *   定義了一個 `TypedDict` 名為 `AgentState`，它是一個通用的狀態結構，包含了 `messages`, `hits`, `tool_events`, `metrics` 等多個代理都可能用到的欄位。
    *   使用 `total=False` 使得所有鍵都是可選的，這為不同代理（ME, DE, DS）使用狀態的不同子集提供了靈活性。

4.  **實驗執行與日誌記錄 (`run_and_log_experiment`)**：
    *   提供了一個高階的實驗運行器，它接收一個已編譯的 LangGraph 圖（`graph`）和初始狀態（`initial_state`）。
    *   **自動化日誌記錄**：它會自動處理實驗的開始、過程中的節點追蹤和結束，並在實驗完成或崩潰時，將完整的狀態（包括訊息、工具事件、指標等）保存到一個 JSON 檔案中。
    *   **崩潰防護**：即使圖的執行過程中發生錯誤，`finally` 區塊也能確保當前的狀態被記錄下來，避免數據丟失。

5.  **黑板工具函式 (`bb_merge`, `bb_snapshot_text`)**：
    *   `bb_merge`: 提供了一個非破壞性的方式來合併新的資訊到 `state` 中的黑板裡，並能進行簡單的去重。
    *   `bb_snapshot_text`: 生成一個給 LLM 看的、可讀的黑板快照。它會智慧地合併記憶體中（`state['blackboard']`）和檔案中（由 `bb_tools.py` 管理）的黑板內容，確保 LLM 能看到最新的、去重後的資訊摘要。

6.  **運行 ID 管理 (`ensure_run_id`)**：
    *   提供 `ensure_run_id` 函式，確保在整個應用程式的生命週期中，`state['run_id']` 和環境變數 `os.environ['RUN_ID']` 始終保持一致。這是確保所有日誌和產出物都關聯到同一次運行的關鍵。

## 依賴關係

*   **Python 函式庫**: `os`, `time`, `json`, `traceback`, `uuid`, `random`, `hashlib`。
*   **LangChain**: `langchain_core.messages` 和 `langchain_google_vertexai`。
*   **內部模組**:
    *   `bb_tools.py`: `bb_snapshot_text` 函式會選擇性地從 `bb_tools` 導入 `get_bb_snapshot` 來讀取檔案黑板的內容。

## 在專案中的角色

`common.py` 如同一個基礎設施層，為上層的各個代理工作流（`me_workflow`, `de_workflow`, `supervisor_workflow` 等）提供必要的共享服務。通過將 LLM 初始化、狀態結構和核心工具函式集中在此，它簡化了其他模組的實現，並確保了整個系統行為的一致性和可維護性。
