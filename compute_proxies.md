# `compute_proxies.py`

## 檔案目的

`compute_proxies.py` 是一個用於**實驗後分析**的腳本，其核心目的是從結構化的事件日誌（`events.parquet`）中計算一系列高階的**協作指標（proxies）**。這些指標旨在量化多代理系統（MAS）在運行過程中的拓撲結構、知識共享效率和工作負載分配等方面的特性。

此腳本不是 MAS 運行時的一部分，而是作為一個獨立的分析工具，將底層的事件數據轉換為有意義的、可用於評估團隊協作模式的量化指標。

## 主要功能

1.  **讀取事件數據**：
    *   腳本的主要輸入是一個 Parquet 檔案 (`events.parquet`)，該檔案應包含 MAS 運行期間記錄的所有詳細事件。

2.  **計算拓撲與工作負載指標 (`compute_topology_metrics`)**：
    *   **Freeman Out-degree Centralization (C_out)**: 衡量委派網絡的中心化程度。一個高的 C_out 值意味著委派集中在少數幾個代理身上（例如，星狀網絡）。
    *   **Handoff Entropy (H)**: 衡量委派行為的多樣性或可預測性。熵越高，表示代理的委派目標越分散和不可預測。
    *   **Workload Gini (gini_workload)**: 使用吉尼係數（Gini coefficient）來衡量工作負載（以事件數量計）在不同代理之間的分配公平性。值越高，表示工作負載分配越不均衡。

3.  **計算黑板（Blackboard）相關指標 (`compute_bb_metrics`)**：
    *   **First-Read Latency (t_first_read_ms_median)**: 衡量一個 artifact 從被寫入黑板到**首次被其他代理讀取**之間的時間延遲（取中位數）。這個指標反映了知識流動的速度。
    *   **Reuse Rate (reuse_rate)**: 衡量被寫入黑板的 artifacts 中，至少被**其他代理**讀取過一次的比例。這個指標反映了知識的有效利用程度。
    *   **Orphan Rate (orphan_rate)**: 衡量被寫入黑板的 artifacts 中，**從未**被任何其他代理讀取過的比例。高的孤兒率可能意味著代理產生了無用的資訊。

4.  **數據產出**：
    *   **`run_metrics.parquet`**: 將為每個 `run_id` 計算出的所有指標匯總後，儲存為 Parquet 檔案。
    *   **`run_metrics.csv`**: 可選地，同時儲存為 CSV 檔案。

5.  **視覺化作圖**：
    *   `fig_topology_metrics.png`: 將 `C_out`, `Gini`, `H` 三個拓撲指標繪製在同一張條形圖中，方便比較不同運行（run）之間的差異。
    *   `fig_read_latency.png`: 繪製每個 run 的首次讀取延遲，直觀地展示知識傳播速度。
    *   `fig_reuse_orphan.png`: 繪製 `reuse_rate` vs `orphan_rate` 的散點圖，用於分析知識共享的有效性。

## 執行方式

此腳本通過命令列運行：

```bash
python compute_proxies.py --in events.parquet --out_dir ./analysis_results
```

*   `--in`:必需，指向輸入的 `events.parquet` 檔案路徑。
*   `--out_dir`: 必需，指定輸出指標檔案和圖表的目錄。
*   `--save_csv`: 可選，如果提供此標誌，將額外生成 `run_metrics.csv`。
*   `--fig_*`: 可選，用於自訂輸出的圖檔名稱。

## 依賴關係

*   **Python 函式庫**: `argparse`, `os`, `json`, `ast`, `numpy`, `pandas`, `matplotlib`。

## 核心演算法

*   **Gini Coefficient**: 實現了計算基尼不均衡係數的標準演算法。
*   **Freeman Centralization**: 實現了簡化版的 Freeman out-degree centralization 計算，用於有向圖。
*   **Handoff Entropy**: 通過計算每個代理節點出邊（handoffs）的機率分佈的熵，並進行加權平均和規模化，來衡量委派的混亂程度。
*   **Event Filtering and Joining**: 大量使用 Pandas 來對事件進行篩選（例如，區分 `bb_write` 和 `bb_read`）、分組和連接（join），以計算跨事件的指標（如讀取延遲）。
