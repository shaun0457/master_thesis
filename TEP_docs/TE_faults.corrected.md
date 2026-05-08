# Tennessee Eastman Process — 20 Fault Modes

以下為 TE 經典 20 種故障模式（含類型）彙整，便於設計 ME 的來源對齊與 DS 的標註/評估。

> 註：不同資料版本會將 16、17 設為「未知/雜訊」故障；學界常以 0 表示「正常」類別。

| Fault No. | Type / Pattern | Description |
|---:|:---|:---|
| 1 | Step | Step change in A/C feed ratio (Stream 4) |
| 2 | Step | Step change in B composition (Stream 4) |
| 3 | Step | Step change in D feed temperature (Stream 2) |
| 4 | Step | Step change in reactor cooling water inlet temperature |
| 5 | Step | Step change in condenser cooling water inlet temperature |
| 6 | Step | Loss of A feed (Stream 1) |
| 7 | Step | C header pressure loss |
| 8 | Step | Step change in A, B, C feed composition (Stream 4) |
| 9 | Random | Random variation in D feed temperature |
| 10 | Random | Random variation in C header pressure |
| 11 | Random | Random variation in reactor CW inlet temperature |
| 12 | Random | Random variation in condenser CW inlet temperature |
| 13 | Drift | Slow drift in reaction kinetics |
| 14 | Stiction | Sticking reactor cooling water valve |
| 15 | Stiction | Sticking condenser cooling water valve |
| 16 | Random | Random variation of steam supply to stripper (steam system) |
| 17 | Random | Random variation of heat transfer in reactor |
| 18 | Random | Random variation of heat transfer in condenser |
| 19 | Unknown | Unknown fault |
| 20 | Random | Unknown (random variation) |

---

## 使用建議
- **ME（RAG）**：將每個 Fault 與「受影響的變數群」建立對應（例如 F4 → 反應器冷卻水相關變數：XMEAS21 / XMV10）。
- **DS（建模）**：可將 `faultNumber` 作為分類標籤；或針對單一 fault 進行 one-vs-rest 異常偵測。
- **DE（資料交付）**：建議在資料中保留 `faultNumber`（若有）與時間戳，便於跨代理/跨文件對齊。