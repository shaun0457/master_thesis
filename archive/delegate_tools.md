# `delegate_tools.py`

## 檔案目的

`delegate_tools.py` 是實現多代理系統（MAS）中**分層委派（Hierarchical Delegation）**和**對等委派（Peer-to-Peer Delegation）**的核心模組。它作為一個工具工廠和子圖執行器，主要負責以下兩件事：

1.  **動態生成工具**：為即將被調用的專家代理（ME, DE, DS）動態地創建一套上下文感知的工具，特別是與黑板（Blackboard）和對等委派（P2P）相關的工具。
2.  **執行子圖**：提供 `delegate_to_*` 函式，用於實際調用指定專家代理的 LangGraph 子工作流（subgraph），並管理其生命週期。

這個模組是連接 Supervisor（總指揮）和各個專家代理的橋樑，也是實現代理間靈活協作的關鍵。

## 主要功能

1.  **委派執行器 (`delegate_to_me`, `delegate_to_de`, `delegate_to_ds`)**：
    *   這些是 Supervisor 可以調用的高階工具，分別用於將任務委派給 ME、DE 和 DS。
    *   每個函式內部都會：
        *   準備一個介紹性的提示（`intro_note`）和具體的任務文本（`question` 或 `task`）。
        *   調用 `make_blackboard_tools` 來生成特定於該代理的黑板和 P2P 委派工具。
        *   調用核心的 `_run_subgraph` 函式來執行對應代理的子工作流。
        *   在子工作流結束後，處理其回傳結果，包括摘要、指標和任何新的 P2P 委派請求。

2.  **子圖執行器 (`_run_subgraph`)**：
    *   這是實際執行專家代理工作流的核心函式。
    *   它會從 `state` 中獲取全域上下文（如 `run_id`, `db_url`），並為子圖創建一個隔離的、乾淨的初始狀態 `sub_state`。
    *   **動態加載子圖**：它會動態地 `__import__` 對應代理的工作流模組（如 `me_workflow.py`）和工具模組（如 `me_tools.py`），並從中獲取 `build_graph` 和 `create_executor` 等函式。
    *   **上下文注入**：它將任務文本和即時的黑板快照（`bb_snapshot_text`）組合成一個 `HumanMessage`，作為子圖的啟動指令。
    *   **工具注入**：它將 `make_blackboard_tools` 生成的工具列表傳遞給子圖的執行器，使得子圖中的代理能夠使用這些上下文感知的工具。
    *   **日誌記錄**: 整個子圖的執行過程被包裹在 `run_logger` 的 `agent_node` 上下文中，確保了子任務的開始和結束都被記錄下來。

3.  **工具工廠 (`make_blackboard_tools`, `make_p2p_tools`)**：
    *   `make_blackboard_tools`: 這個工廠函式會創建與黑板互動的工具（`read_blackboard`, `write_to_blackboard`）。這些工具在被創建時就已經**綁定**了當前的 `state` 和 `agent_name`，因此在子圖內部調用時，它們能夠正確地讀寫黑板並記錄是哪個代理在操作。
    *   `make_p2p_tools`: 專門創建 `@tool("request_delegate")` 工具。當專家代理調用此工具時，它不會立即執行委派，而是將一個委派請求（包含目標代理 `to` 和任務 `task`）放入一個臨時的 `p2p_req_box` 列表中。這個列表會在子圖執行結束後被回傳給上層的 `router`，由 `router` 來決定如何以及何時執行這些 P2P 委派。

4.  **上下文管理 (`_TopicCtx`)**：
    *   提供一個上下文管理器，用於在執行子圖期間，將當前的 `topic_id` 和 `owner` 暫存到 `state['topic_ctx']` 中。這確保了在子圖中進行的所有黑板操作和事件記錄都能被正確地關聯到同一個主題上，離開子圖時會自動還原，避免污染主流程的狀態。

## 設計模式

*   **工廠模式（Factory Pattern）**: `make_*_tools` 函式是典型的工廠模式，根據傳入的上下文（`state`, `agent_name`）動態生成定製化的工具物件。
*   **策略模式（Strategy Pattern）**: `delegate_to_*` 函式可以看作是不同的委派策略，它們內部都依賴 `_run_subgraph` 這個統一的執行機制。
*   **依賴注入（Dependency Injection）**: `_run_subgraph` 在調用子圖時，將其所需的依賴（如上下文感知的工具）作為參數注入，而不是讓子圖自己去創建，這降低了子圖與外部環境的耦合。
*   **延遲執行（Deferred Execution）**: `request_delegate` 工具的設計是一種延遲執行。它只記錄意圖，真正的執行由上層的 `router` 決定，這給了中心協調器更大的控制權。

## 依賴關係

*   **Python 函式庫**: `json`, `os`, `uuid`, `hashlib`, `inspect`。
*   **LangChain**: `langchain_core.messages`。
*   **內部模組**:
    *   `prompt_builder.py`: 獲取各代理的角色卡。
    *   `common.py`: 獲取 `bb_snapshot_text`, `get_seed` 等通用函式。
    *   `run_logger.py` 和 `metrics.py`: 用於記錄事件和指標。
    *   `bb_tools.py`: `make_blackboard_tools` 依賴它來實現對中心化黑板的寫入。
    *   `me_workflow.py`, `de_workflow.py`, `ds_workflow_s2.py`: `_run_subgraph` 會動態導入這些模組來執行相應的子圖。

## 在專案中的角色

`delegate_tools.py` 是實現 MAS 團隊協作模式的**引擎**。它不僅僅是定義了一堆工具，更重要的是，它定義了**如何執行一個被委派的任務**，以及**代理之間如何發起新的委派**。它是連接宏觀層面（Supervisor 的意圖）和微觀層面（專家代理的自主 ReAct 循環）的關鍵樞紐。
