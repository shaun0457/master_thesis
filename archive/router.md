# `router.py`

## 檔案目的

`router.py` 是多代理系統（MAS）的**核心執行引擎和協調中樞**。它位於 Supervisor 和各個專家代理之間，扮演著「總承包商」的角色。當 Supervisor 決定要將任務委派給某個專家時，`router.py` 負責接收這個指令，調用對應的專家子圖，並管理其執行過程，最後將結果返回給 Supervisor。

它最複雜也最關鍵的功能是處理**對等（Peer-to-Peer, P2P）委派**，即一個專家代理在執行任務的過程中，請求另一個專家代理的協助。

## 主要功能

1.  **主委派執行 (`route_and_execute`)**: 這是此模組的核心函式，由 `supervisor_workflow.py` 中的 `router_node` 調用。其主要職責是：
    *   解析 Supervisor 的 `AIMessage` 中包含的 `tool_calls`（例如，`delegate_to_me`）。
    *   對於每一個委派請求，調用 `_exec_one_tool` 函式來啟動對應專家代理的子工作流。
    *   收集子工作流的回傳結果，將其格式化為 `ToolMessage`，並添加回 `state['messages']` 中，供 Supervisor 在下一輪決策時查看。

2.  **子圖調用 (`_exec_one_tool`)**: 這是一個內部輔助函式，它實際執行對 `delegate_tools.py` 中 `delegate_to_*` 函式的調用。它還負責：
    *   **上下文管理**: 調用 `ensure_topic_in_args` 來確保每個子任務都有一個明確的 `topic_id` 和 `owner`，這對於後續的日誌追蹤和指標分析至關重要。
    *   **事件記錄**: 圍繞著工具的執行進行詳細的事件打點，包括使用 `run_logger` 記錄工具的開始、結束、延時和成功狀態，以及使用 `emit_delegate_event` 記錄一次清晰的「交接邊」（handoff edge）。

3.  **P2P 委派循環 (`_consume_p2p_requests` 和 `route_and_execute` 內的循環)**:
    *   當一個專家代理（例如 ME）的子圖執行結束後，`router` 會檢查其回傳結果中是否包含 `delegate_requests` 列表（這是由注入到子圖中的 `request_delegate` 工具產生的）。
    *   如果存在 P2P 請求，`router` 會啟動一個**內部委派循環**。
    *   在這個循環中，`router` 會逐一執行這些 P2P 請求，再次調用 `_exec_one_tool` 來啟動被請求的專家（例如 DE）的子圖。
    *   它甚至可以處理**鏈式 P2P 委派**（例如，ME -> DE -> DS）。
    *   在 P2P 委派的子圖執行完畢後，`router` 會將其結果匯總成一條「反饋筆記」（`_feedback_note`），並調用 `continue_agent` 讓最初發起請求的代理（ME）繼續其工作。

4.  **安全護欄（Safety Guardrails）**:
    *   **`MAX_GLOBAL_TOOL_CALLS`**: 限制在單個使用者問題的處理過程中，整個系統（包括所有主委派和 P2P 委派）的工具調用總次數上限，防止無休止的循環。
    *   **`_MAX_P2P_HOPS`**: 限制在一次 P2P 委派鏈中可以發生的最大「跳轉」次數。
    *   **`_MAX_OPEN_REQS`**: 限制在一輪 P2P 委派中可以同時處理的請求數量。
    *   **請求去重 (`_dedup_key`)**: 為每個 P2P 請求生成一個唯一的簽名，以防止在循環中重複執行完全相同的請求。

## 設計模式

*   **中央協調器（Central Coordinator）**: `router` 作為一個中央協調器，負責解釋高層指令（來自 Supervisor）並管理底層執行單元（專家代理子圖）的生命週期。這是一種常見的複雜系統設計模式。
*   **遞歸與堆疊（Recursion/Stack）**: P2P 委派的實現方式本質上是一種遞歸調用。`router` 調用 `delegate_to_me`，在 ME 的執行過程中，可能會觸發 `router` 再次調用 `delegate_to_de`，形成一個調用堆疊。安全護欄（如 `_MAX_P2P_HOPS`）是防止這種遞歸無限進行的關鍵。
*   **事件驅動**: 整個流程是事件驅動的。Supervisor 的 `tool_calls` 是一個事件，`router` 響應這個事件；專家代理的 `delegate_requests` 也是一個事件，`router` 再次響應它。

## 依賴關係

*   **Python 函式庫**: `json`, `os`, `uuid`, `hashlib`, `time`。
*   **LangChain**: `langchain_core.messages`。
*   **內部模組**:
    *   `delegate_tools.py`: **核心依賴**，`router` 通過調用此模組中的 `delegate_to_*` 函式來執行子圖。
    *   `run_logger.py` 和 `metrics.py`: 用於在執行過程中進行密集的事件和指標記錄。
    *   `common.py`: 用於確保 `run_id` 的一致性等。

## 在專案中的角色

`router.py` 是 MAS 團隊能夠進行**複雜協作**的**實現核心**。如果說 Supervisor 是「大腦」，專家代理是「手腳」，那麼 `router.py` 就是連接大腦和手腳的「**神經系統**」。它不僅僅是簡單地傳遞指令，更重要的是，它管理著複雜的執行流程、處理代理間的互動，並通過一系列安全護欄確保整個系統的穩定和收斂。它是整個系統從「單個代理的集合」躍升為「一個協同工作的團隊」的關鍵所在。
