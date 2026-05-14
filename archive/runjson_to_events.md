# `runjson_to_events.py`

## 檔案目的

`runjson_to_events.py` 是一個批次處理的**實驗後 ETL（Extract, Transform, Load）工具**。它的主要功能是掃描指定的日誌目錄，找到由 `chat_cli.py` 生成的會話日誌檔案（`chat_*.json`），並將這些半結構化的 JSON 檔案轉換為一個**完全扁平化、以事件為導向**的單一表格數據（`events.parquet` 和 `events.csv`）。

與 `agent_log_parser_template.py` 相比，此腳本更側重於將**所有類型**的活動（包括使用者發言、AI 思考、工具調用意圖、工具執行結果）統一到一個共享的、正規化的事件綱要（schema）下，為後續的序列分析和指標計算提供一個乾淨、統一的數據源。

## 主要功能

1.  **輸入檔案發現 (`discover_inputs`)**:
    *   提供了強大的檔案發現機制，可以通過多種方式指定輸入：
        *   掃描指定的 `in_chat_dir` 和 `in_stdout_dir` 目錄。
        *   使用更靈活的 `glob_chat` 和 `glob_stdout` 模式進行匹配。
        *   通過一個 `manifest` CSV 檔案來精確指定每一對 `run_json` 和 `stdout` 檔案的路徑。
    *   它能夠根據檔案名稱中的時間戳和 `run_id` 特徵，自動將 `chat_*.json` 和對應的 `*_stdout.txt` 檔案進行配對。

2.  **事件映射 (`map_tool_events`, `map_messages`)**:
    *   `map_tool_events`: 遍歷 `run_json['tool_events']` 列表，將每一次工具的實際執行記錄轉換為一個標準的事件格式。它會特別處理與黑板相關的事件，提取 `artifact_id` 和 `fact_ids_served` 等關鍵資訊。
    *   `map_messages`: 遍歷 `run_json['messages']` 列表，這是一個更複雜的過程：
        *   對於 `AIMessage`，如果包含 `tool_calls`，則將其轉換為 `intent`（意圖）事件，代表代理「計畫」要執行某個工具。
        *   如果 `AIMessage` 不含 `tool_calls`，則將其視為一次 `say`（發言）事件。
        *   對於 `ToolMessage`，將其轉換為 `tool_result` 事件，代表工具執行的結果被返回給了代理。
        *   對於 `HumanMessage`，也將其轉換為 `say` 事件。

3.  **數據正規化與輸出 (`normalize_df`, `write_outputs`)**:
    *   所有從單個 `run_json` 中提取的事件行（rows）會被合併成一個 Pandas DataFrame。
    *   `normalize_df` 函式會確保 DataFrame 包含所有必要的欄位（`REQ_COLS`），並根據 `run_id` 和時間戳進行排序，確保事件的時序性。
    *   `write_outputs` 函式會將所有 runs 的 DataFrame 合併成一個大的 DataFrame，並將其儲存為 `events.parquet` 和 `events.csv`。
    *   支援 `--per_run` 選項，可以為每個 `run_id` 單獨生成一個 Parquet/CSV 檔案。

4.  **元數據聚合**:
    *   在處理過程中，腳本還會從 `stdout.txt` 中嘗試提取運行的開始和結束時間，並將這些元數據與每個 run 的事件計數等摘要資訊一起，儲存到一個總的 `meta.json` 檔案中。

## 執行方式

此腳本完全通過命令列驅動，提供了靈活的配置選項：

```bash
# 示例：掃描兩個目錄並將結果輸出到 out/
python runjson_to_events.py \
    --in_chat_dir ./interactive_logs \
    --in_stdout_dir ./run_logs \
    --out_dir ./events_output \
    --per_run
```

## 設計理念

*   **批次處理**: 專為一次性處理大量實驗日誌而設計，實現了從原始日誌到分析就緒數據（Analysis-Ready Data）的自動化轉換。
*   **事件的原子性**: 將原始日誌中複雜的、巢狀的結構（如 `messages` 列表）打散，轉換為一系列扁平的、具有明確 `event_type` 的原子事件。這種格式極大地簡化了後續使用 SQL、Pandas 或其他工具進行查詢和分析的複雜度。
*   **意圖與執行的分離**: 通過創建 `intent` 事件來代表代理的「計畫」，並用 `tool_call` 事件來代表工具的「實際執行」，此腳本在數據層面上清晰地區分了代理的決策與其行動的結果，這對於分析代理的推理鏈路和錯誤非常有價值。

## 依賴關係

*   **Python 函式庫**: `argparse`, `json`, `re`, `os`, `sys`, `hashlib`, `time`, `glob`, `pandas`。

## 在專案中的角色

`runjson_to_events.py` 是連接**原始實驗產出**和**最終數據分析**的關鍵橋樑。它扮演著數據倉庫中 ETL 的角色，負責將混亂、多樣的原始日誌清洗、轉換並載入到一個統一的、結構化的「事件事實表」中。所有後續的量化分析、指標計算（如 `compute_proxies.py`）和視覺化，都建立在這個由它產出的乾淨數據之上。它是保證整個實驗框架數據流一致性和分析效率的重要工具。
