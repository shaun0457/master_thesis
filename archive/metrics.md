# `metrics.py`

## 檔案目的

`metrics.py` 是一個核心的指標計算與管理模組，它為整個 MAS（多代理系統）實驗框架提供了**可觀測性（Observability）**的基礎。此模組的職責橫跨兩個層面：

1.  **即時指標記錄**: 在 MAS 運行的過程中，提供函式來即時記錄關鍵事件（如工具調用）和更新狀態中的指標。
2.  **實驗後分析**: 提供一系列複雜的函式，用於在實驗結束後，從收集到的完整事件日誌中計算高階的團隊協作指標（Proxies for 7 Constructs）。

## 主要功能

### 即時記錄功能

*   **`init_metrics(state: dict, ...)`**: 在一次實驗運行開始時被調用，用於在 `state` 字典中創建並初始化 `metrics` 容器，並設定所有指標的預設值。
*   **`note_tool_event(state: dict, ...)`**: 在每次工具被調用時執行，它會將工具的名稱、參數、延時等資訊記錄到 `state['tool_events']` 列表中，並更新工具調用的總次數。
*   **`update_me_citation_metrics(state: dict, answer_text: str)`**: 專門為 ME（機器專家）代理設計，用於計算其最終答案的**引用覆蓋率**。它會分析答案文本，統計其中包含了有效引用的句子所佔的比例。
*   **`finalize_metrics(state: dict, ...)`**: 在實驗運行結束時被調用，負責計算最終的持續時間，並根據實驗類型（ME 或 DS）和結果，判定一個最終的成功或失敗結論（`ds_verdict`）。

### 實驗後分析功能

這部分功能通常在 `agent_log_parser_template.py` 中被調用，處理的是已經匯總的 `events_df`（一個 Pandas DataFrame）。

*   **`attach_topic_columns(events_df)`**: 這是進行主題級別分析的關鍵第一步。它會分析每個事件的內容（如 SQL 查詢、問題文本），並為其生成一個 `topic_key` 和一個 `topic_id`。這使得分析師能夠將分散在整個運行過程中的、但與同一個子任務相關的事件鏈串聯起來。
*   **`compute_all_proxies(events_df, behaviors_df)`**: 這是計算七個核心協作構念指標的總入口，它會調用以下各個計算函式：
    *   **`compute_leadership`**: 根據委派事件（`delegate`）建立一個有向圖，並計算 **Freeman 中心化指數**，以衡量領導力的集中程度。
    *   **`compute_knowledge_sharing`**: 計算**知識寫入-讀取延遲**和**知識重用率**，以衡量團隊內部知識流動的效率。
    *   **`compute_coord_eff`**: 計算**決策延遲**（從委派到第一個成功工具調用的時間），以衡量協調效率。
    *   **`compute_team_learning`**: 分析從錯誤到成功的轉換率和反饋循環次數，以衡量團隊的學習能力。
    *   **`compute_goal_alignment`**: 通過計算初始任務與最終產出之間的**語意相似度**，來衡量目標的一致性。
    *   **`compute_conflict_handling`**: 分析黑板上連續寫入內容的差異性，以衡量從分歧到收斂的時間。
    *   **`compute_workload_balance`**: 使用**吉尼係數（Gini）**和**熵（Entropy）**來衡量工作負載在不同代理間的分配均衡性。

## 設計理念

*   **雙模態設計**: `metrics.py` 同時服務於**即時監控**和**離線分析**兩種場景。即時記錄的 `tool_events` 為離線時計算更複雜的 `proxies` 提供了原始數據。
*   **數據驅動的評估**: 此模組體現了用數據來客觀評估 MAS 性能和協作模式的設計思想。它不僅僅是記錄成功或失敗，而是試圖從多個維度去量化「為什麼」成功或失敗。
*   **可擴展性**: 結構化的設計使得未來可以方便地加入新的指標計算函式，以滿足新的分析需求。

## 依賴關係

*   **Python 函式庫**: `time`, `json`, `re`, `hashlib`, `pandas`, `numpy`, `networkx`。
*   **`scikit-learn`** (可選): 如果安裝了 `scikit-learn`，`_cosine_sim` 會使用 TF-IDF 來計算語意相似度，否則會回退到較簡單的 Jaccard 相似度。

## 在專案中的角色

`metrics.py` 是整個實驗框架的**評估核心**。它像一個精密的儀表板，不僅記錄了 MAS 運行過程中的基本遙測數據，還提供了一套高階的分析工具，能夠將原始的、混亂的事件流轉化為對團隊協作行為的深刻洞見。它是理解代理行為、診斷系統瓶頸、以及比較不同策略（如不同 `policy` 設定）優劣的關鍵所在。
