# `tee_logs.py`

## 檔案目的

`tee_logs.py` 是一個簡單而強大的日誌記錄輔助模組，其靈感來源於 Unix/Linux 中的 `tee` 指令。它提供了一個上下文管理器（context manager），能夠將程式在運行過程中的所有標準輸出（`stdout`）和標準錯誤（`stderr`）**同時**輸出到兩個地方：

1.  原始的目的地（通常是主控台）。
2.  指定的日誌檔案。

這確保了在運行 `chat_cli.py` 等互動式應用時，既能即時看到輸出，又能將完整的、一字不差的過程記錄保存到檔案中，以供後續的除錯和分析。

## 主要功能與組件

1.  **`_TeeStream` 類 (Class)**:
    *   這是一個自訂的檔案流（file-like object）類別。
    *   它的 `write` 方法在被調用時，會遍歷其內部儲存的所有流（streams），並將接收到的數據寫入到每一個流中。
    *   這就是實現「複製」功能的關鍵。

2.  **`tee_console_logs` 上下文管理器**:
    *   這是此模組對外提供的核心功能。
    *   當進入 `with` 區塊時，它會：
        *   創建日誌目錄（如果不存在）。
        *   打開指定的 `stdout` 和 `stderr` 日誌檔案。
        *   保存原始的 `sys.stdout` 和 `sys.stderr`。
        *   使用 `_TeeStream` 的實例來替換 `sys.stdout` 和 `sys.stderr`。此時，`_TeeStream` 實例會同時包含原始的流和檔案流。
    *   在 `with` 區塊內部，任何對 `print()` 的調用或任何未被捕獲的錯誤引發的堆疊追蹤，都會被 `_TeeStream` 攔截，並同時寫入到主控台和檔案。
    *   當離開 `with` 區塊時（無論是正常結束還是發生異常），`finally` 區塊會確保：
        *   將 `sys.stdout` 和 `sys.stderr` 還原為原始的流。
        *   關閉檔案流，確保所有緩衝區的內容都被寫入到磁碟。

3.  **`read_tail` 函式**:
    *   一個輔助工具，用於讀取一個大檔案的末尾部分（預設為最後 4096 位元組）。
    *   這在需要將日誌檔案的摘要內容嵌入到另一個 JSON 檔案中，但又不希望因為日誌過大而導致主檔案體積膨脹的場景下非常有用。

## 使用範例

在 `chat_cli.py` 中，整個 `main` 函式的主體都被包裹在 `tee_console_logs` 中：

```python
from tee_logs import tee_console_logs

# ...

with tee_console_logs(run_id=session_id, log_dir=RUN_LOG_DIR) as log_paths:
    # 在此區塊內的所有 print 和錯誤都會被記錄
    print(f"日誌將被寫入到: {log_paths['stdout_path']}")
    # ... 執行 MAS 的主循環 ...
```

## 設計理念

*   **非侵入性（Non-invasive）**: 使用上下文管理器和 `sys` 模組的猴子補丁（monkey-patching），`tee_logs` 能夠在不修改專案中大量 `print()` 語句的情況下，實現全局的日誌記錄。開發人員可以像往常一樣使用 `print` 進行除錯，而無需關心日誌寫入的細節。
*   **魯棒性（Robustness）**: 通過 `try...finally` 結構，它確保了即使在程式崩潰時，日誌檔案也能被正確關閉，並且 `sys.stdout`/`stderr` 能被還原，避免了對外部環境的永久性污染。使用行緩衝（`buffering=1`）也最大程度地保證了在崩潰前一刻的日誌也能被即時寫入檔案。
*   **簡單性**: 它用非常少的程式碼實現了一個非常實用的功能，遵循了 Unix 的「做一件事並把它做好」的哲學。

## 依賴關係

*   **Python 函式庫**: `os`, `sys`, `io`, `contextlib`。

## 在專案中的角色

`tee_logs.py` 是整個實驗框架**最基礎的日誌記錄保障**。它確保了每一次實驗運行的**最原始、最完整的過程記錄**都被保存了下來。這些 `stdout.txt` 和 `stderr.txt` 檔案是除錯的終極依據，也是 `agent_log_parser_template.py` 等分析工具的原始數據來源之一。它為整個系統的可追溯性和事後分析提供了最低層但最可靠的保障。
