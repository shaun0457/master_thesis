# Tennessee Eastman (TE) — 名詞／縮寫表（ME 友善版）

> 目的：讓 ME 能把資料標籤（tag）翻成可理解語意，並在回答中使用一致術語。

## 一、單元與設備
- **Reactor（反應器）**：連續多組分反應容器，受控於 T/P/Level。  
- **Condenser（冷凝器）**：將蒸汽冷凝成液體以便分離或回收。  
- **Vapor–Liquid Separator（氣液分離槽）**：達到相平衡、分出頂氣與底液。  
- **Recycle Compressor（回收壓縮機）**：壓縮未反應/不凝氣返送反應器。  
- **Stripper / Column（汽提/精餾塔）**：移除輕端/惰性、獲得符合規格之產品。  
- **Purge（排放）**：排走部份循環氣避免惰性累積。

## 二、量測與控制常用縮寫
- **T/P/F/L**：溫度（Temperature）/壓力（Pressure）/流量（Flow）/液位（Level）  
- **TT/ PT/ FT/ LT**：量測點（Transmitter）  
- **TIC/ PIC/ FIC/ LIC**：閉環控制器（Indicator Controller）  
- **TC/ PC/ FC/ LC**：控制閥或控制訊號  
- **PID**：比例–積分–微分控制  
- **VSD**：變頻驅動（Variable Speed Drive）  
- **P&ID**：管線與儀表圖  
- **DCS**：分散式控制系統

## 三、資料與標籤
- **Tag Dictionary（標籤字典）**：將像 `FICL1_203_PV` 這類儀控代碼翻成「**哪個設備／哪個測點／單位**」。  
- **xMEAS / xMV**（TE 慣例）  
  - xMEAS：量測變數索引（例：流量、壓力、溫度、液位…）  
  - xMV：操縱變數索引（例：閥位、回流、再沸器、壓縮機負荷…）  
- **Units（單位）**：壓力（bar）、溫度（°C/K）、流量（kmol/h 或 kg/h）、液位（%）、組成（mol%）。

## 四、品質與安全
- **Spec / Off-spec（規格/超規）**：產品是否符合規格界線。  
- **Alarm / Trip（警報/聯鎖停機）**：超限或設備保護動作。  
- **LOPA / SIL**：層級式保護分析 / 安全完整性等級（若文件有提及）。

## 五、常見分析用語（Phase-2 會用到）
- **Source Alignment（來源對齊）**：每個陳述對應 `(doc_id, page, span)`。  
- **Hallucination Rate（幻覺率）**：未對齊來源之句子比例。  
- **Coverage（覆蓋率）**：答案涉及的文件數 / 應參考文件數。  

## 六、占位詞（請以實際資料補齊）
- **設備代碼**：`R-###`（反應器）、`V-###`（分離槽）、`E-###`（換熱器）、`C-###`（壓縮機）、`T-###`（塔）  
- **範例 tag**：`TIC-Rxxx`（反應器溫控）、`PIC-Vxxx`（分離槽壓控）、`LIC-Txxx`（塔底液位控）、`FIC-PURGE`（排放流量控）

> 建議：將 Schaeffler 的實際 tag 對照（名稱、單位、設備/位置、正常範圍）貼回本檔底部，讓 ME 在 RAG 回答中可直接引用。
