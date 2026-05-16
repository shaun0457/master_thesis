---
title: "02 — Research Questions and Hypotheses"
author: "Cheng-Ting Chen"
version: 0.2
last_updated: 2025-10-16
---

## English

### 2.1 Overview
This thesis analyzes how **prompt-based collaboration strategies** affect the **stability** and **cooperation quality** of a multi-agent system (MAS).  
Three research questions structure the investigation, linking **strategies → mechanisms → outcomes**.

---

### 2.2 Research Questions

#### **RQ1 — Strategy → Structure and Flow**
**RQ1:** How do different prompt-based collaboration strategies affect the *structure of team interaction* and the *flow of knowledge*?

| Hypothesis | Expected Pattern | Indicators |
|-------------|------------------|-------------|
| **H1-1:** Planner→Worker increases **centralization (C)** and **inequality (Gini)**, while Debate and Delphi produce more distributed and diverse communication (**H↑**). | Hierarchical vs peer-level cooperation | C, H, G |
| **H1-2:** Debate and Delphi enhance **knowledge reuse** and reduce **orphan rate**, but may increase **t_first_read** due to deliberation. | More dialogue → richer reuse, slower first response | reuse, orphan, t_first_read |

---

#### **RQ2 — Structure / Flow → Stability & Cooperation Quality**
**RQ2:** How do structural and knowledge-flow properties determine the **stability** and **cooperation quality** of multi-agent collaboration?

| Hypothesis | Relationship | Indicators (predictors → outcomes) |
|-------------|--------------|------------------------------------|
| **H2-1 (Stability):** Moderate **centralization** and lower **loop density** predict higher **stability** (fewer off-topic or cyclic runs). | “Inverted-U” between centralization and stability | C, loop_density → success rate, variance |
| **H2-2 (Cooperation Quality):** Higher **reuse**, lower **orphan**, more balanced contributions (**Gini↓**), and faster response (**t_first_read↓**) predict better cooperation quality. | Efficient knowledge transfer | reuse, orphan, Gini, t_first_read → cooperation quality |
| **H2-3 (Efficiency):** Greater **flow efficiency** (reuse × 1/t_first_read) improves both stability and cooperation quality. | Composite indicator | flow_efficiency |

---

#### **RQ3 — Mechanisms (Mediation)**
**RQ3:** *Through which mechanisms do prompt strategies influence stability and cooperation quality?*  
(i.e., Are the effects of prompt protocols mediated by changes in team topology and knowledge flow?)

| Hypothesis | Mechanism | Expected Mediation |
|-------------|------------|--------------------|
| **H3-1:** The advantages of Debate and Delphi on **cooperation quality** are mediated by **H↑ / reuse↑ / orphan↓ / Gini↓**. | Distributed exchange → balanced participation → improved cooperation | Indirect effects significant |
| **H3-2:** The effects of prompt strategies on **stability** are mediated by **loop_density↓** and **flow_efficiency↑**. | Fewer oscillations and faster flow → more stable convergence | Indirect effects significant |

---

### 2.3 Theoretical Alignment

| Thesis Keyword | RQ Connection | Empirical Operationalization |
|----------------|----------------|-------------------------------|
| **Prompt-Strategien** | RQ1 (manipulated variable) | Planner→Worker / Debate / Delphi |
| **Stabilität** | RQ2 & RQ3 (dependent variable) | success rate, loop_density, convergence variance |
| **Kooperationsqualität** | RQ2 & RQ3 (dependent variable) | reuse, orphan, Gini, flow_efficiency |

---

### 2.4 Conceptual Diagram (text-based)
+------------------------+
| Prompt Strategy (IV) |
| - Planner→Worker |
| - Debate / Delphi |
+------------------------+
│
▼
+-----------------------------------+
| Mechanisms (Mediators) |
| - Structure: C, H, G |
| - Knowledge Flow: reuse, orphan |
| t_first_read, flow_efficiency |
| - Stability Factors: loop_density |
+-----------------------------------+
│
▼
+------------------------------------+
| Outcomes |
| - Stability (success, variance) |
| - Cooperation Quality (reuse, Gini, efficiency) |
+------------------------------------+


---

## 中文（繁體）

### 2.1 概述
本研究旨在分析**不同提示策略（prompt-based collaboration strategies）**如何影響多代理系統（MAS）的**穩定性（Stabilität）**與**協作品質（Kooperationsqualität）**。  
研究以「**策略 → 機制 → 結果**」為主軸，對應三個核心研究問題。

---

### 2.2 研究問題

#### **RQ1 — 策略對結構與知識流的影響**
**RQ1：** 不同提示策略如何改變團隊互動結構與知識流動模式？

| 假說 | 預期趨勢 | 對應指標 |
|------|------------|-----------|
| **H1-1：** Planner→Worker 提高互動集中度（C）與不均衡度（Gini）；Debate 與 Delphi 則提升多樣性（H↑）。 | 層級式 vs 平級協作 | C, H, G |
| **H1-2：** Debate 與 Delphi 提升資訊重用（reuse↑）並降低浪費（orphan↓），但可能因討論延遲而增加 **t_first_read**。 | 深度對話導致重用↑、反應慢↓ | reuse, orphan, t_first_read |

---

#### **RQ2 — 結構與知識流對穩定性與協作品質的影響**
**RQ2：** 互動結構與知識流動特徵如何決定系統的穩定性與協作品質？

| 假說 | 關係 | 指標（預測變數 → 結果變數） |
|------|------|----------------------------|
| **H2-1（穩定性）：** 中度集中化（C 適中）與較低迴圈密度（loop_density↓）可提升穩定性。 | 「倒 U 型」關係 | C, loop_density → success rate |
| **H2-2（協作品質）：** 高重用（reuse↑）、低浪費（orphan↓）、貢獻均衡（Gini↓）與快速回應（t_first_read↓）代表更好的協作品質。 | 資訊交換效率 | reuse, orphan, Gini, t_first_read |
| **H2-3（效率）：** 高流效率（flow_efficiency↑）同時改善穩定性與協作。 | 綜合指標 | flow_efficiency |

---

#### **RQ3 — 機制與中介效應**
**RQ3：** 不同提示策略透過哪些機制影響穩定性與協作品質？  
（即：策略對結果的影響是否由結構與知識流中介？）

| 假說 | 機制 | 預期中介效果 |
|------|------|---------------|
| **H3-1：** Debate / Delphi 對協作品質的提升主要透過 **H↑ / reuse↑ / orphan↓ / Gini↓**。 | 分散式溝通 → 均衡參與 → 協作提升 | 間接效果顯著 |
| **H3-2：** 策略對穩定性的影響主要透過 **loop_density↓** 與 **flow_efficiency↑**。 | 減少震盪 → 收斂更穩 | 間接效果顯著 |

---

### 2.3 與論文題目對齊
| 題目關鍵詞 | 對應研究問題 | 操作化變數 |
|-------------|----------------|--------------|
| **Prompt-Strategien** | RQ1（操弄變項） | Planner→Worker / Debate / Delphi |
| **Stabilität（穩定性）** | RQ2 / RQ3 | success rate、loop_density、variance |
| **Kooperationsqualität（協作品質）** | RQ2 / RQ3 | reuse、orphan、Gini、flow_efficiency |

---

### 2.4 概念結構圖（文字版）
┌───────────────────────┐
│ 提示策略 (Prompt Strategies) │
│ - Planner→Worker │
│ - Debate / Delphi │
└──────────────┬──────────────┘
│
▼
┌────────────────────────────────────────┐
│ 機制層 (Mechanisms) │
│ 結構指標：C, H, G │
│ 知識流指標：reuse, orphan, t_first_read, flow_efficiency │
│ 穩定性因素：loop_density │
└────────────────────────────────────────┘
│
▼
┌────────────────────────────────────────┐
│ 結果層 (Outcomes) │
│ - 穩定性 (Stability): success, variance, loop_density │
│ - 協作品質 (Cooperation Quality): reuse, Gini, efficiency │
└────────────────────────────────────────┘

---

### 2.5 Summary
- **RQ1** defines how prompt strategies manipulate the system’s structure and knowledge flow.  
- **RQ2** links those mechanisms to measurable outcomes of stability and cooperation.  
- **RQ3** explains *why* these effects occur—through mediated pathways in communication and information flow.