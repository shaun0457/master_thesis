# `supervisor_workflow`

## 檔案目的

`supervisor_workflow` 是整個多代理系統（MAS）的**最高層級工作流**定義檔案。它使用 `langgraph` 構建了 Supervisor 代理所在的圖（Graph），並定義了整個團隊的宏觀協調邏輯。它不僅僅是 Supervisor 的個人工作流，更是連接 Supervisor、Router 和糾錯機制的**團隊總工作流**。

## 主要功能與圖（Graph）結構

此模組的核心是 `build_team_graph` 函式，它創建了一個包含以下關鍵節點和邊的圖：

1.  **節點（Nodes）**:
    *   `Supervisor` (`supervisor_node`): 這是整個工作流的入口點和決策核心。它負責：
        *   從 `prompt_builder` 獲取 Supervisor 的角色卡（System Prompt）。
        *   將當前的對話歷史（`messages`）傳遞給一個綁定了 Supervisor 工具（來自 `supervisor_tools`）的 LLM。
        *   讓 LLM 根據全局上下文，做出最高層級的決策：是委派任務給某個專家（`delegate_to_*`），還是直接回答使用者（`final_answer`），或是向使用者提出澄清問題。
    *   `Router` (`router_node`): 這是決策的**執行節點**。它本身不包含邏輯，而是直接調用 `router` 中的 `route_and_execute` 函式。當 Supervisor 決定委派任務時，`Router` 節點會確保這個委派被正確地執行，並將專家代理的回覆作為 `ToolMessage` 返回。
    *   `Correction` (`correction_node`): 這是一個**糾錯或「護欄」節點**。當 Supervisor 做出不符合規則的行為時（例如，在沒有足夠證據的情況下就嘗試回答問題），流程會被導向此節點。此節點會向對話歷史中添加一條系統糾錯訊息，強制 Supervisor 在下一輪重新思考其決策。

2.  **邊（Edges）與路由（Routing）**:
    *   **`Supervisor` -> `Router` / `Correction` / `END`**: 這是整個系統的**大腦中樞**。在 `Supervisor` 節點執行後，`_cond` 路由函式會被調用，它會根據 Supervisor 的輸出和當前的**策略（policy）**來決定下一步的走向：
        *   **策略 (`policy`)**: `chat_cli` 在啟動時可以設定 `strict`, `gentle`, `free` 三種策略之一。
        *   **違規檢查**: `_cond` 會檢查 Supervisor 的行為是否違規，例如：
            *   在沒有任何黑板證據（`_has_min_evidence`）的情況下就調用 `final_answer`。
            *   一次性調用多個工具（預期只委派一項任務）。
        *   **路由決策**:
            *   在 `strict` 模式下，任何違規都會導致流程被路由到 `Correction` 節點。
            *   在 `gentle` 模式下，違規會被記錄，系統會向 LLM 注入一條提示訊息，但仍然會允許其執行（用於觀察）。
            *   在 `free` 模式下，違規會被記錄，但流程會繼續正常執行。
            *   如果行為有效（例如，一個合法的委派），則路由到 `Router` 節點。
            *   如果 Supervisor 決定結束對話（調用 `final_answer` 或不調用任何工具），則路由到 `END`。
    *   **`Router` -> `Supervisor`**: 在 `Router` 執行完專家代理的子圖後，流程**總是**返回到 `Supervisor` 節點，讓 Supervisor 能夠觀察到專家的回覆，並進行下一步的全局規劃。
    *   **`Correction` -> `Supervisor`**: 在向 Supervisor 發送糾錯訊息後，流程也返回到 `Supervisor` 節點，迫使其重新決策。

## 核心設計

*   **分層式控制（Hierarchical Control）**: 這個工作流清晰地體現了分層式控制結構。Supervisor 位於頂層，負責宏觀規劃和決策；Router 和專家代理位於執行層，負責具體任務的實現。
*   **策略驅動的行為（Policy-Driven Behavior）**: 通過引入 `policy` 參數，系統的行為（特別是對錯誤的容忍度）可以被靈活地調整，這對於進行對比實驗和研究不同協作模式的影響至關重要。
*   **帶有護欄的自主性（Guarded Autonomy）**: 系統給予 Supervisor 很大的自主決策權，但同時通過 `Correction` 節點和 `_cond` 路由中的違規檢查為其設定了「護欄」，防止其做出明顯錯誤或低效的行為，確保了整個系統的穩定性和任務的收斂性。

## 依賴關係

*   **LangChain/LangGraph**: `langgraph.graph.StateGraph`, `langchain_core.prompts`, `langchain_core.messages`。
*   **內部模組**:
    *   `common`: 獲取 `llm` 實例和 `AgentState` 定義。
    *   `prompt_builder`: **核心依賴**，用於動態載入 Supervisor 的角色卡。
    *   `supervisor_tools`: 獲取 Supervisor 可用的委派工具。
    *   `router`: **核心依賴**，`router_node` 的所有功能都委託給了此模組的 `route_and_execute` 函式。
    *   `bb_tools`: `_has_min_evidence` 函式依賴此模組來檢查黑板狀態。

## 在專案中的角色

`supervisor_workflow` 是整個 MAS 團隊的**總指揮部和操作系統**。它定義了團隊如何接收任務、如何進行高層決策、如何執行決策、如何從錯誤中恢復，以及如何最終完成任務的宏觀流程。它是將所有獨立的專家代理（ME, DE, DS）和基礎設施（黑板、日誌）整合為一個能夠協同工作的、有目標的有機整體的關鍵所在。

# `me_workflow`

## 檔案目的

`me_workflow` 使用 `langgraph` 函式庫為機器專家（Machine Expert, ME）代理定義了其**自主工作流**。它構建了一個狀態機（StateGraph），詳細地描述了 ME 代理如何通過一個 ReAct（Reason-Act）循環來執行其 RAG（檢索增強生成）任務：從接收問題，到搜尋、閱讀、綜合資訊，再到最終產出一個帶有引用的答案。

## 主要功能與圖（Graph）結構

此模組的核心是 `build_me_graph` 函式，它創建了一個包含以下節點和邊的圖：

1.  **節點（Nodes）**:
    *   `ME` (`ME_node`): 圖的入口點和決策中心。它負責：
        *   接收當前狀態 `AgentState`。
        *   調用一個綁定了 ME 工具（來自 `me_tools`）的 LLM 執行器。
        *   讓 LLM 根據當前狀態和歷史訊息，生成思考（thought）並決定下一步要調用哪個 RAG 工具（如 `initial_search` 或 `read_document_chunk`）。
    *   `Tool` (`Tool_node`): 執行 `ME` 節點所規劃的工具。它會：
        *   解析 `AIMessage` 中的 `tool_calls` 並執行相應的工具。
        *   將從工具（如 `initial_search`, `read_document_chunk`）返回的結果（`hits`）聚合到 `state['hits']` 中。
        *   **強制綜合邏輯**: 這是此節點的一個關鍵特性。它會檢查是否滿足了觸發「綜合」的條件（例如，已經收集了足夠的文本片段 `filled`，或者工具調用次數過多）。如果滿足條件，它會**強制調用** `synthesize_and_cite` 工具，即使 LLM 本身沒有計畫這一步。這確保了代理最終總會嘗試生成一個綜合性的答案，而不是無休止地檢索。
        *   將工具的輸出（`ToolMessage`）添加到狀態中，供 `ME` 節點在下一輪進行觀察。
    *   `End` (`Validator_end`): 終端節點，在工作流結束時被調用。它負責：
        *   從最終狀態中提取 ME 產出的答案。
        *   調用 `update_me_citation_metrics` 來計算答案的引用覆蓋率等指標。
        *   根據指標（如覆蓋率）為本次任務判定一個最終的 `ds_verdict`（SUCCESS, FAILURE 等）。
        *   將所有計算出的指標和結果封裝到 `state['metrics']` 中。

2.  **邊（Edges）與路由（Routing）**:
    *   **`ME` -> `Tool` 或 `End`**: 在 `ME` 節點執行後，`route` 函式會進行決策。
        *   如果 ME 的回覆中包含 `tool_calls`，則路由到 `Tool` 節點去執行工具。
        *   如果沒有 `tool_calls`，或者工具調用次數達到了上限（10次），則路由到 `End` 節點結束流程。
    *   **`Tool` -> `ME`**: 在工具執行後，流程總是返回到 `ME` 節點，讓代理觀察工具結果並進行下一步規劃。這構成了核心的 ReAct 循環。
    *   **`End` -> `END`**: 在驗證節點執行完畢後，整個圖的流程結束。

## 核心設計

*   **帶有強制措施的 ReAct 循環**: 與其他工作流不同，ME 的工作流在 ReAct 循環中加入了一個「護欄」機制。`Tool_node` 中的強制綜合邏輯確保了代理不會陷入無效的檢索循環，而是在適當的時機被引導至最終的答案生成步驟，這大大增強了工作流的魯棒性。
*   **以指標為導向的終結**: `Validator_end` 節點的存在，使得 ME 工作流的結束不僅僅是流程上的終止，更是一個**量化評估**的過程。它產出的指標（特別是引用覆蓋率）為衡量 ME 代理的表現提供了客觀的依據。
*   **可組合的子系統**: `build_me_graph` 返回的已編譯圖，可以被上層協調器（如 `router`）作為一個獨立的「ME 子系統」來調用，實現了複雜任務的分解。

## 依賴關係

*   **Python 函式庫**: `os`, `json`, `time`, `traceback`, `re`。
*   **LangChain/LangGraph**: `langgraph.graph.StateGraph`, `langchain_core.messages`, `langchain_core.prompts`。
*   **內部模組**:
    *   `common`: 獲取 `llm` 實例、`AgentState` 定義和 `run_and_log_experiment` 執行器。
    *   `me_tools`: **核心依賴**，提供了 ME 代理所需的所有工具（`initial_search`, `synthesize_and_cite` 等）。
    *   `metrics`: 用於在 `Validator_end` 節點中記錄和計算最終指標。
    *   `bb_tools`: `Tool_node` 在強制綜合後，可能會調用 `bb_add_citations` 等函式將結果寫入黑板。

## 在專案中的角色

`me_workflow` 是 ME 代理的「大腦」和「神經系統」。它不僅僅是讓代理能夠思考和行動，更重要的是，它為代理的 RAG 任務定義了一個**有結構、有目標、有護欄、有評估**的完整流程。它確保了 ME 代理能夠以一種可靠和可衡量的方式，將非結構化的文檔知識轉化為對使用者有價值的、有證據支持的答案。

# `ds_workflow_s2`

## 檔案目的

`ds_workflow_s2` 使用 `langgraph` 函式庫為數據科學家（Data Scientist, DS）代理定義了一個優化的、適用於第二階段（Stage-2）實驗的**自主工作流**。與 `de_workflow` 類似，它構建了一個狀態機（StateGraph）來實現 DS 代理的 ReAct（Reason-Act）循環，使其能夠自主地進行數據分析、建模和視覺化。

這個版本被標記為 `s2`（Stage-2），意味著它可能比早期的版本更簡潔或針對更複雜的任務進行了優化。

## 主要功能與圖（Graph）結構

此模組的核心是 `build_graph` 函式，它創建了一個包含以下節點和邊的圖：

1.  **節點（Nodes）**:
    *   `DataScientist` (`ds_node`): 這是圖的入口點和核心決策節點。它負責：
        *   接收當前的 `AgentState`。
        *   調用一個綁定了 DS 工具（來自 `ds_tools`）的 LLM 執行器 (`ds_executor`)。
        *   讓 LLM 根據當前狀態和歷史訊息，生成思考（thought）並決定下一步要調用哪個工具（`tool_calls`）。
        *   將 LLM 的回覆（`AIMessage`）加入到狀態中。
    *   `ToolExecutor` (`tool_node_ds`): 執行 `DataScientist` 節點計畫的工具。它會：
        *   解析 `AIMessage` 中的 `tool_calls`。
        *   根據工具名稱在 `tool_map` 中找到對應的函式並執行。
        *   記錄工具執行的指標（使用 `note_tool_event`）。
        *   將工具的輸出結果封裝成 `ToolMessage` 並加入到狀態中，供 `DataScientist` 節點在下一輪循環中進行觀察和思考。

2.  **邊（Edges）與路由（Routing）**:
    *   **`DataScientist` -> `ToolExecutor` 或 `END`**: 在 `DataScientist` 節點執行後，`router_ds` 函式會進行路由決策。
        *   如果 LLM 的回覆中**包含** `tool_calls`，則流程會被路由到 `ToolExecutor` 節點去執行工具。
        *   如果 LLM 的回覆中**不包含** `tool_calls`，則代表 DS 代理認為它的任務已經完成，準備好產出最終答案了。在這種情況下，流程會被路由到 `END`，結束本次工作流。
    *   **`ToolExecutor` -> `DataScientist`**: 在工具執行完成後，流程總是會返回到 `DataScientist` 節點。這形成了一個閉環，讓代理能夠觀察到工具執行的結果，並根據這個新的資訊來規劃下一步的行動。

## 核心設計

*   **簡潔的 ReAct 循環**: `DataScientist` -> `ToolExecutor` -> `DataScientist` ... 這個結構是一個非常清晰的 ReAct 實現。代理持續在「思考/規劃」和「行動/執行」之間切換，直到它自己決定任務完成為止。
*   **自主終止**: 與 `de_workflow` 不同，DS 工作流的終止條件完全由 LLM 內在地決定。當 LLM 認為分析已經足夠，不再需要調用任何工具，而是要直接給出結論時，它就會停止生成 `tool_calls`，從而自然地結束循環。這賦予了代理更高的自主性。
*   **狀態驅動**: 整個工作流同樣由 `AgentState` 物件驅動，所有節點共享並更新同一個狀態，確保了資訊在循環中的連續性。
*   **可組合性與靈活性**: `build_graph` 返回一個已編譯的圖，可以被上層協調器（如 `router`）作為一個獨立的「DS 子系統」來調用。同時，`create_ds_executor` 函式接受外部傳入的 `system_prompt`，使得可以輕鬆地為 DS 代理更換「角色卡」或指令，以適應不同的實驗需求。

## 依賴關係

*   **Python 函式庫**: `os`, `json`。
*   **LangChain/LangGraph**: `langgraph.graph.StateGraph`, `langchain_core.messages`, `langchain_core.prompts`。
*   **內部模組**:
    *   `common`: 獲取全域的 `llm` 實例和 `AgentState` 定義。
    *   `prompts`: 獲取 DS 代理的預設系統提示。
    *   `metrics`: 用於記錄工具事件。
    *   `ds_tools`: 雖然沒有直接導入，但 `tool_map` 和 `tools` 參數預期是從 `ds_tools.get_ds_tools()` 獲取的。

## 在專案中的角色

`ds_workflow_s2` 為 DS 代理提供了**進行複雜數據分析和建模的自主能力**。它將 DS 的「大腦」（LLM）和其強大的「武器庫」（`ds_tools`，特別是 `execute_python_code`）有效地結合在一起。在整個 MAS 團隊中，DS 代理是負責將數據轉化為最終洞見和結論的關鍵角色，而這個工作流檔案就是實現這一目標的核心引擎。

# `de_workflow`

## 檔案目的

`de_workflow` 使用 `langgraph` 函式庫定義了數據工程師（Data Engineer, DE）代理的**自主工作流**。它構建了一個狀態機（StateGraph），模擬了 DE 代理在接收到任務後，如何進行思考、調用工具、觀察結果、並再次思考的 ReAct（Reason-Act）循環，直到最終產出一個可交付的數據集為止。

## 主要功能與圖（Graph）結構

此模組的核心是 `build_graph` 函式，它創建了一個包含以下節點和邊的圖：

1.  **節點（Nodes）**:
    *   `DataEngineer` (`de_node`): 這是圖的入口點和核心決策節點。它會：
        *   接收當前的狀態（`AgentState`），其中包含了歷史訊息。
        *   調用一個 `agent_executor`（一個綁定了 DE 工具的 LLM），讓模型根據當前狀態決定下一步的行動（是思考還是調用工具）。
        *   將 LLM 的回覆（一個 `AIMessage`，可能包含 `tool_calls`）新增到狀態中。
    *   `ToolExecutor` (`tool_node`): 執行工具的節點。它會：
        *   檢查 `DataEngineer` 節點產生的 `AIMessage` 中是否包含 `tool_calls`。
        *   如果存在，它會遍歷每一個工具調用請求，查找對應的工具函式（從 `tool_map` 中），並執行它。
        *   將工具執行的結果（一個 `ToolMessage`）新增到狀態中。
        *   同時，它會調用 `note_tool_event` 來記錄工具的執行指標（如延時、參數等）。
    *   `DataScientistValidator` (`ds_validator_node`): 這是一個終端節點，代表 DE 工作流的結束。在 DE 的獨立工作流中，它通常是一個簡單的佔位符，但在整合到更大的系統中時，它標誌著控制權將轉交給 DS 或 Supervisor。

2.  **邊（Edges）與路由（Routing）**:
    *   **`DataEngineer` -> `ToolExecutor` 或 `DataScientistValidator`**: 在 DE 節點執行後，`router_after_de` 函式會被調用來決定下一步去向。
        *   如果 DE 的回覆中包含 `tool_calls`，則路由到 `ToolExecutor` 節點去執行工具。
        *   如果沒有 `tool_calls`，則認為 DE 已經完成了它的工作（或無法繼續），路由到 `DataScientistValidator` 節點結束流程。
    *   **`ToolExecutor` -> `DataEngineer` 或 `DataScientistValidator`**: 在工具執行後，`router_after_tool` 函式會被調用。
        *   如果執行的工具是數據查詢或轉換類的工具，且產出的數據集**不滿足**下游的要求（例如，行數太少），則路由回 `DataEngineer` 節點，讓它根據工具的輸出結果（Observation）進行下一步思考。
        *   如果產出的數據集**滿足**要求，則路由到 `DataScientistValidator` 節點，準備將數據交付給 DS。

## 核心設計

*   **ReAct 循環**: `DataEngineer` -> `ToolExecutor` -> `DataEngineer` ... 這個循環是 ReAct 模式的經典實現，使得代理能夠像人一樣，通過「思考-行動-觀察」的循環來解決複雜問題。
*   **狀態驅動**: 整個工作流是圍繞 `AgentState` 這個狀態物件來驅動的。每個節點都接收 `state` 作為輸入，並將其更新後的版本作為輸出，傳遞給下一個節點。
*   **可組合性**: `build_graph` 函式返回一個已編譯的、可執行的 `graph` 物件。這個 `graph` 可以被看作是一個獨立的「DE 子系統」，可以被更高層級的協調器（如 `supervisor_workflow` 或 `router`）作為一個黑盒子來調用。
*   **靈活性**: `create_de_executor` 函式允許從外部傳入 `system_prompt`，這使得 DE 代理的行為可以被輕易地定製，而無需修改工作流的內部邏輯。這對於在不同實驗條件下（例如，不同的角色卡）測試代理行為至關重要。

## 依賴關係

*   **Python 函式庫**: `json`。
*   **LangChain/LangGraph**: `langgraph.graph.StateGraph`, `langchain_core.messages`, `langchain_core.runnables`。
*   **內部模組**:
    *   `common`: 獲取全域的 `llm` 實例和 `AgentState` 定義。
    *   `prompts`: 獲取 DE 代理的預設系統提示（System Prompt）。
    *   `metrics`: 用於記錄工具事件。
    *   `de_tools`: 雖然沒有直接導入，但 `tool_map` 和 `tools_for_agent` 參數預期是從 `de_tools.get_de_tools()` 獲取的。

## 在專案中的角色

`de_workflow` 為 DE 代理提供了**自主執行任務的能力**。它將 DE 的「大腦」（LLM）和「手腳」（`de_tools`）有效地組織在一起，形成一個能夠獨立完成從數據庫查詢到交付數據集這一完整流程的子系統。它是整個 MAS 中實現任務分解和專業化分工的關鍵一環。
