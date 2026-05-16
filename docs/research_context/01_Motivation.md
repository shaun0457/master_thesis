---
title: "01 — Research Motivation and Goals"
author: "Cheng-Ting Chen"
version: 0.2
last_updated: 2025-10-16
---

## English

### 1.1 Background
In modern production environments, artificial intelligence is becoming an integral part of daily operations.  
Across departments—such as process engineering, quality assurance, energy management, logistics, and maintenance—teams are beginning to integrate **AI assistants or specialized agents** trained on domain-specific data and workflows.

These departmental AI agents already perform valuable functions:
- **Process optimization agents** adjust parameters based on sensor data.  
- **Quality agents** perform anomaly detection and report generation.  
- **Energy agents** monitor compressed-air consumption and suggest cost-saving strategies.  

However, these agents typically operate in **isolation**.  
Each serves a local goal, with limited understanding of other agents’ objectives or internal reasoning.

---

### 1.2 Emerging Challenge: Cross-Agent Collaboration
When two departments need to collaborate—for instance, energy management and quality assurance jointly analyzing an unexpected downtime—their respective AI agents must also exchange information, negotiate goals, and coordinate reasoning steps.  

This situation forms a **peer-to-peer Multi-Agent System (MAS)**:  
independent agents with comparable autonomy must cooperate without a central controller.

Such cross-agent collaboration raises new questions:
- How can communication remain **stable** when agents hold different task views?  
- How can the resulting knowledge exchange remain **transparent and auditable** for humans?  
- What strategies or prompt structures can improve **cooperation quality** across semi-autonomous agents?

Traditional single-agent or hierarchical planner–worker frameworks cannot fully capture these peer-level interactions.

---

### 1.3 Industrial Relevance
This shift is not speculative but **already emerging in industrial digitalization**.

| Department | Typical AI Agent | Potential Collaboration Partner | Resulting MAS Context |
|-------------|-----------------|--------------------------------|-----------------------|
| Manufacturing / Process | Process optimization agent | Quality or Maintenance | Cross-process fault diagnosis |
| Quality Assurance | Anomaly-detection agent | Process or Energy | Joint root-cause analysis |
| Energy Management | Energy monitoring agent | Quality / Production | Joint efficiency evaluation |
| Logistics | Scheduling agent | Production | Integrated planning and feedback |
| Maintenance | Predictive maintenance agent | Process / Quality | Coordinated response to early warnings |

> As each department deploys its own specialized agent, **cross-agent coordination** becomes inevitable—both within a company and across suppliers.  
> These agents must exchange hypotheses, data schemas, and reasoning results.  
> Understanding *how* such interactions unfold is a prerequisite for ensuring transparency, reproducibility, and stability in future industrial AI ecosystems.

---

### 1.4 Research Gap
Existing studies on Multi-Agent Systems focus either on:
- conceptual frameworks for distributed reasoning, or  
- performance gains in collaborative LLM systems (e.g., CAMEL, Debate, Delphi).  

What remains underexplored is the **governance dimension**—how to measure and compare cooperation stability, transparency, and information flow across different prompting strategies.

---

### 1.5 Research Objective
This thesis investigates **how different prompt-level interaction strategies shape the stability and cooperation quality of multi-agent collaboration**.  
By introducing a **blackboard-based event architecture**, all inter-agent communication becomes explicit and measurable.  
This enables the derivation of structural and knowledge-flow metrics, allowing systematic comparison of strategies such as *Planner→Worker*, *Debate*, and *Delphi*.

---

### 1.6 Conceptual Illustration (text-based diagram)
[ Team A: Quality Dept ] ---- uses ----> [ QA-Agent ]
[ Team B: Energy Dept ] ---- uses ----> [ Energy-Agent ]

↓
Both agents must collaborate on a shared diagnostic task:

exchange data and hypotheses

negotiate causes and priorities

align on a corrective plan

→ forms a peer-level Multi-Agent System (MAS)
→ requires prompt strategies to maintain stability & cooperation quality


---

### 1.7 Contribution Summary
1. **Industrial Motivation:** reframes MAS not as a futuristic AGI scenario, but as a natural outcome of cross-departmental AI agent collaboration in industry.  
2. **Governance Focus:** introduces auditable, event-based metrics to quantify knowledge flow and cooperation quality.  
3. **Empirical Framework:** provides reproducible experiments comparing prompting strategies across simulated industrial tasks.  
4. **Transferability:** bridges insights from the Tennessee Eastman Process to real manufacturing contexts.

---

## 中文（繁體）

### 1.1 研究背景
在現代生產環境中，人工智慧已逐漸成為日常運作的一部分。  
不同部門——例如製程工程、品質保證、能源管理、後勤與維護——開始導入**具專業領域知識的 AI Agent**，輔助資料分析與決策。

這些 AI Agent 已能分別執行：
- **製程優化 Agent**：依感測器資料自動調整參數；  
- **品質 Agent**：進行異常檢測與報告生成；  
- **能源 Agent**：監控壓縮空氣耗能並提出節能建議。  

然而，目前這些系統大多是**各自獨立運行**的。  
每個 Agent 只理解自己的目標與資料，缺乏與其他 Agent 的直接協作。

---

### 1.2 新興挑戰：跨 Agent 協作
當兩個部門必須協同作業時（例如品質與能源部門共同分析停機原因），  
他們各自的 AI Agent 也必須交換資訊、協調任務、同步推理。  
這樣的情境形成了**平級的多代理系統（Multi-Agent System, MAS）**：  
多個自治的 Agent 必須在無中央控制的情況下合作。

這帶來了新的問題：
- 在任務觀點不同的情況下，**如何保持協作穩定性**？  
- Agent 間的溝通能否被人類**追溯與解釋**？  
- 不同提示策略是否能**提升協作品質**？

---

### 1.3 工業應用關聯
這並非遙遠的願景，而是當前工業數位化的必然趨勢。

| 部門 | 常見 AI Agent 類型 | 合作對象 | 對應的 MAS 情境 |
|------|-------------------|-----------|----------------|
| 製造 / 製程 | 製程優化 Agent | 品質 / 維修部門 | 跨製程故障診斷 |
| 品質管理 | 異常檢測 Agent | 製程 / 能源 | 聯合根因分析 |
| 能源管理 | 能源監控 Agent | 品質 / 生產 | 效率協同分析 |
| 後勤調度 | 排程 Agent | 生產 | 生產-物流整合 |
| 維修保養 | 預測維修 Agent | 製程 / 品質 | 早期異常響應協作 |

> 隨著各部門分別部署自己的 AI Agent，跨 Agent 的協作將不可避免。  
> 為了確保未來這些系統的**透明度、可追溯性與穩定性**，我們需要理解不同提示策略下的協作行為。

---

### 1.4 研究缺口
現有研究多聚焦於：
- 分散式推理的概念架構，或  
- 透過多代理提升 LLM 任務表現的技術成果（如 CAMEL、Debate、Delphi）。  

但對於**治理層面（governance dimension）**——  
如何量測與比較多代理間的穩定性、透明度與知識流品質——仍缺乏系統性探討。

---

### 1.5 研究目標
本研究旨在探討**不同系統提示（System Prompt）策略如何影響多代理系統的穩定性與協作品質**。  
透過導入**黑板事件架構（Blackboard Architecture）**，  
將代理間的每一次讀寫行為具體化，使協作過程可被觀測、量測與重現，  
從而以可治理的方式比較 Planner→Worker、Debate 與 Delphi 等策略。

---

### 1.6 概念示意圖（文字版）
