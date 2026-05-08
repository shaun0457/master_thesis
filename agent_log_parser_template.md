# `agent_log_parser_template.py`

## 檔案目的

此腳本是一個獨立的日誌解析器，專門用於處理由 MAS（多代理系統）在運行過程中產生的日誌檔案（JSON 和 TXT 格式）。它的主要功能是將原始日誌轉換為結構化的數據（CSV 格式），計算關於團隊協作的各種指標（Proxies），並生成視覺化圖表以供分析。

這是一個用於**實驗後分析**的工具，而不是 MAS 運行時的一部分。

## 主要功能

1.  **日誌解析**：
    *   解析 `chat_*.json` 檔案，提取結構化的事件，如代理間的委派（delegation）、工具調用（tool calls）和訊息交換。
    *   解析 `*_stdout.txt` 檔案，通過正則表達式匹配，提取非結構化的行為日誌，如錯誤、節點進入事件、路由事件等。

2.  **數據正規化**：
    *   定義了一個 `_ensure_events_schema` 函式，確保從不同來源解析的事件數據框（DataFrame）具有統一的欄位結構，方便後續處理。
    *   對時間相關的欄位進行正規化，以 `event_time_ms` 為主，並提供一個近似時間 `approx_time` 以便排序。

3.  **指標計算**：
    *   導入並使用 `metrics.py` 中的 `attach_topic_columns` 和 `compute_all_proxies` 函式。
    *   `attach_topic_columns`：根據事件內容（如 SQL 查詢、問題文本）為每個事件分配一個 `topic_id`，用於追蹤與同一個子問題相關的活動鏈。
    *   `compute_all_proxies`：計算代表七個團隊協作構念（如領導力、知識共享、目標一致性等）的量化指標。

4.  **產出檔案**：
    *   `agent_events.csv`: 包含所有從 JSON 日誌中提取的結構化事件。
    *   `agent_behaviors.csv`: 包含所有從 TXT 日誌中提取的行為標籤。
    *   `agent_timeline_joined.csv`: 將事件和行為合併並按時間排序的時間線。
    *   `agent_events_with_topics.csv`: 帶有 `topic_id` 的事件表。
    *   `proxies.json`: 計算出的七個協作構念指標。
    *   `chart_*.png`: 三張視覺化圖表，分別展示：
        *   各代理的事件數量。
        *   委派或工具調用的頻率。
        *   行為標籤的頻率。

## 執行方式

此腳本可通過命令列直接運行：

```bash
python agent_log_parser_template.py --data_dir /path/to/your/logs
```

*   `--data_dir`: 包含 `chat_*.json` 和 `*_stdout.txt` 日誌檔案的目錄。預設為當前目錄。

## 依賴關係

*   **Python 函式庫**: `os`, `re`, `json`, `glob`, `datetime`, `pandas`, `numpy`, `matplotlib`。
*   **內部模組**:
    *   `metrics.py`: 為了計算協作指標，從此模組導入 `attach_topic_columns` 和 `compute_all_proxies`。

## 程式碼結構

*   **基本工具 (`derive_run_id`, `safe_json_load`)**: 提供路徑解析和安全的 JSON 讀取功能。
*   **欄位正規化 (`_ensure_events_schema`, `normalize_timecols`)**: 核心數據清洗步驟，確保數據一致性。
*   **解析器 (`parse_json_events`, `parse_txt_behaviors`)**: 分別處理兩種不同格式的日誌來源。
*   **主流程 (`main`)**:
    1.  使用 `glob` 找到所有目標日誌檔案。
    2.  調用解析器讀取並轉換數據。
    3.  將數據載入 Pandas DataFrame。
    4.  調用 `metrics.py` 中的函式計算 `topic_id` 和協作指標。
    5.  合併事件和行為，創建統一的時間線。
    6.  將處理後的數據和指標寫入 CSV 和 JSON 檔案。
    7.  使用 Matplotlib 生成並儲存分析圖表。
*   **入口 (`if __name__ == "__main__":`)**: 解析命令列參數並啟動 `main` 函式。
