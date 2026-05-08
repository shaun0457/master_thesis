# `create_tep_data.py`

## 檔案目的

`create_tep_data.py` 是一個一次性的數據準備腳本，其唯一目的是讀取田納西-伊斯曼過程（Tennessee Eastman Process, TEP）的訓練數據（從一個 CSV 檔案），並將其載入到一個 SQLite 資料庫中。這個腳本為後續的數據工程（DE）和數據科學（DS）任務準備了基礎數據環境。

## 主要功能

1.  **讀取 CSV 數據**：
    *   從 `TEP_data/` 目錄下讀取名為 `TEP_FaultFree_Training.csv` 的檔案。

2.  **數據清洗（欄位名）**：
    *   為了方便在 SQL 中進行查詢，腳本會對 DataFrame 的欄位名進行正規化處理，移除方括號 `[]` 並將空格替換為底線 `_`。

3.  **建立 SQLite 資料庫**：
    *   使用 `sqlalchemy` 函式庫創建一個名為 `tep_database_FaultFree.db` 的 SQLite 資料庫檔案。
    *   將清洗後的 DataFrame 寫入到資料庫中，資料表名為 `process_data`。如果該資料表已存在，則會替換它。

4.  **建立故障描述表**：
    *   在同一個資料庫中，額外創建一個名為 `fault_descriptions` 的資料表。
    *   此資料表包含 0 到 20 號共 21 種故障的文字描述，其中 0 號代表正常運行。

5.  **驗證與預覽**：
    *   在數據寫入完成後，腳本會連接到新創建的資料庫，執行一個 `SELECT` 查詢來讀取 `process_data` 表的前 5 行，並將其打印到主控台，以驗證數據是否已成功載入。

## 執行方式

直接通過 Python 解譯器運行此腳本即可：

```bash
python create_tep_data.py
```

腳本會自動在專案根目錄下生成 `tep_database_FaultFree.db` 檔案。

## 先決條件

*   必須存在 `TEP_data/TEP_FaultFree_Training.csv` 這個檔案。如果檔案不存在，腳本會打印錯誤訊息並退出。

## 依賴關係

*   **Python 函式庫**: `pandas`, `sqlalchemy`, `os`。

## 在專案中的角色

這個腳本是整個實驗環境的**第一步**。它將原始的、基於檔案的數據集轉換為一個結構化的、可查詢的資料庫，為後續所有需要存取 TEP 數據的代理（特別是 Data Engineer）提供了標準的數據來源。一旦資料庫建立完成，在 MAS 的正常運行中就不再需要執行此腳本。
