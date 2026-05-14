# `chat_cli.py`

## 檔案目的

`chat_cli.py` 是整個多代理系統（MAS）的**互動式命令列介面（CLI）**。它是使用者與 MAS 團隊進行互動的主入口點。此腳本負責初始化系統、管理整個對話生命週期、處理使用者輸入、調用核心的 `supervisor_workflow`，並確保所有過程都被詳盡地記錄下來。

## 主要功能

1.  **會話與環境初始化**：
    *   解析命令列參數，例如 `--policy`，用於設定 Supervisor 的介入策略（strict, gentle, free）。
    *   生成一個唯一的 `session_id`（也作為 `run_id`），並將其設定為環境變數，確保整個運行過程中的所有模組（如 `bb_tools`, `run_logger`）都使用同一個 ID。
    *   從環境變數讀取實驗的元數據，如 `SEED`, `TASK_ID`, `PROMPT_CONDITION`，並將它們注入到 `state` 中。

2.  **日誌系統啟動**：
    *   使用 `tee_console_logs` 將所有 `stdout` 和 `stderr` 的輸出同時重定向到主控台和日誌檔案（位於 `run_logs/` 目錄下）。這確保了即使程式崩潰，所有過程記錄也會被保存下來。
    *   初始化 `run_logger`，記錄下本次運行的元數據（如模型參數、資料庫路徑等）。

3.  **主互動循環**：
    *   建立一個主 `while` 循環來接收使用者輸入。
    *   支援多行輸入模式（使用 `<<<` 和 `>>>`）。
    *   提供特殊指令：
        *   `:quit`: 退出程式。
        *   `:reset`: 重置當前會話狀態（清空訊息和黑板），但保留 `run_id`。
        *   `:save`: 手動將當前會話狀態保存為 JSON 檔案。

4.  **圖（Graph）的調用與狀態管理**：
    *   導入並調用 `supervisor_workflow.build_team_graph()` 來建構 LangGraph 工作流圖。
    *   維護一個核心的 `state` 字典，其中包含 `messages`, `blackboard`, `tool_events`, `turn_counter` 等關鍵資訊，並在每次循環中傳遞給圖。
    *   在一個內層 `while` 循環中反覆調用 `graph.invoke(state)`，直到 Supervisor 產出最終答案或達到最大回合數（15輪）限制。

5.  **結果呈現與儲存**：
    *   在每個回合結束時，調用 `_print_last` 來打印 Supervisor 的最終回覆或追問。
    *   調用 `_print_recent_tool_events` 和 `_print_blackboard_summary` 來顯示最近的活動摘要，增加透明度。
    *   自動將每個回合結束時的 `state` 儲存到 `interactive_logs/` 目錄下的 JSON 檔案中，方便除錯和追蹤。

6.  **優雅關閉與最終指標計算**：
    *   使用 `try...finally` 和 `try...except KeyboardInterrupt` 結構確保在程式退出（正常結束、崩潰或手動中斷）時，能夠執行清理工作。
    *   在 `finally` 區塊中，調用 `finalize_metrics` 來計算並記錄最終的成功分數。
    *   調用 `emit_outcome` 和 `end_run` 來記錄本次運行的最終結果和結束時間。
    *   將最後的 `state` 完整地保存下來。

## 程式碼結構

*   **輔助函式**: 包含一系列 `_` 前綴的內部函式，用於序列化訊息（`_serialize_msg`）、保存會話（`_save_session`）、打印輸出（`_print_last`）等。
*   **`main()` 函式**: 包含了程式的完整邏輯：
    1.  **初始化**: 解析參數，設定 `run_id` 和環境變數。
    2.  **日誌上下文**: 使用 `with tee_console_logs(...)` 包裹整個會話。
    3.  **建構圖與狀態**: 調用 `build_team_graph()` 並建立初始 `state`。
    4.  **日誌記錄**: 調用 `begin_run` 和 `emit_run_meta` 記錄實驗元數據。
    5.  **主循環**: 處理使用者輸入和特殊指令。
    6.  **內循環**: 反覆調用 `graph.invoke()`，處理多代理之間的協作，直到任務完成。
    7.  **清理**: 在 `finally` 中保存所有最終狀態和指標。
*   **入口 (`if __name__ == "__main__":`)**: 呼叫 `main` 函式。

## 依賴關係

*   **Python 函式庫**: `os`, `json`, `uuid`, `datetime`, `traceback`, `argparse`。
*   **LangChain**: `langchain_core.messages` 中的各種訊息類別。
*   **內部模組**:
    *   `tee_logs.py`: 用於重定向和保存主控台輸出。
    *   `common.py`: 提供 `ensure_run_id`, `get_seed` 等通用函式。
    *   `metrics.py`: 用於初始化和最終化實驗指標。
    *   `run_logger.py`: 提供 `get_run_logger`, `begin_run`, `emit_outcome` 等日誌記錄功能。
    *   `supervisor_workflow.py`: **核心依賴**，用於建構和執行整個 MAS 的工作流圖。
