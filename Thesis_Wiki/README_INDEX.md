---
title: "Thesis Wiki Index"
author: "Cheng-Ting Chen"
last_updated: 2025-10-17
version: 1.0
purpose: "Central entry for LLM/Agentic parsing of thesis Wiki structure"
---

# 🎓 Thesis Wiki Overview

This repository documents the structure, logic, and semantic links of Cheng-Ting Chen’s master thesis on **Multi-Agent Systems (MAS)** and **prompt-driven collaboration stability and quality**.

All files in `/docs/wiki/` are self-contained and written bilingually (English + Traditional Chinese) for multi-LLM interoperability.

---

## 📘 Chapter Overview

| File | Version | Focus | Status |
|------|----------|--------|--------|
| **01_Motivation.md** | v1.0 (Final) | Research background, industrial relevance, and conceptual framing of MAS collaboration as cross-department AI governance | ✅ Finalized |
| **02_Research_Questions.md** | v0.3 (Pre-Experiment) | Defines RQ1–RQ3, hypotheses, metric mapping to “Stabilität” and “Kooperationsqualität” | ⚙️ Stable pre-experiment version |
| **03_Methods.md** | v0.3 (Pre-Analysis) | Framework overview, provenance of metrics, communication architecture (Blackboard), and knowledge-flow constructs | 🚧 Requires formula & analysis plan integration |
| **04_Discussion.md** | v0.2 (Transferability Draft) | Transferability of results from Tennessee Eastman Process (TEP) to manufacturing governance and industrial implications | 🧩 Draft complete, ready for validation round |

---

## 🧩 Semantic Links

| Concept | Appears In | Operational Level |
|----------|-------------|-------------------|
| **Prompt Strategies (Planner→Worker / Debate / Delphi)** | 01, 02, 03 | Independent variable |
| **Stability (Stabilität)** | 02, 03, 04 | Dependent variable – convergence, loop density, success variance |
| **Cooperation Quality (Kooperationsqualität)** | 02, 03, 04 | Dependent variable – reuse, orphan, Gini, flow efficiency |
| **Knowledge Flow Metrics** | 03 | Mechanistic layer (mediators) |
| **Blackboard Architecture** | 03 | Communication mechanism & traceability layer |
| **Transferability to Industry** | 04 | External validity & governance implications |

---

## 🧮 Suggested Parsing Order (for LLMs)
1️⃣ 01_Motivation.md → establish rationale and industrial context
2️⃣ 02_Research_Questions.md → extract RQ–Hypothesis–Indicator mapping
3️⃣ 03_Methods.md → parse experimental framework, metric definitions, and architecture
4️⃣ 04_Discussion.md → interpret generalization and governance transferability


---

## 🧠 Notes for Agentic Assistants

- Every Markdown file includes **bilingual content (EN + ZH)** and **YAML metadata**.  
- Metrics mentioned follow the “Seven-plus constructs” schema: C, H, G, reuse, orphan, t_first_read, t_owner_read, flow_efficiency, loop_density.  
- Files are designed for **hierarchical loading** — use context windows per chapter to minimize token load.  
- Referencing: each metric or construct can be cross-linked using the key pattern `@metric:C` or `@section:3.6` for programmatic retrieval.

---

## 🧩 Example LLM Query Mapping

| Query Intent | Relevant File(s) | Example Key |
|---------------|------------------|--------------|
| "What motivates studying MAS stability?" | 01_Motivation.md | @section:1.2 |
| "List all metrics for cooperation quality" | 03_Methods.md | @metric:reuse, @metric:Gini |
| "How is TEP mapped to production?" | 04_Discussion.md | @section:4.5 |
| "Show mediation hypotheses" | 02_Research_Questions.md | @section:2.2–2.3 |

---

## 🏁 Next Update Targets

| Target | Description | Responsible |
|--------|--------------|--------------|
| **v0.4 Methods Update** | Add formal equations for all metrics, define ANOVA + mediation model | Shaun |
| **v0.3 Discussion Update** | Add Limitations + Future Work | Shaun |
| **v1.0 Wiki Export** | Freeze finalized bilingual thesis wiki for submission | All supervisors confirmed |

---

> **Purpose:** This index enables structured parsing and autonomous reasoning by LLM systems (Claude, GPT, Gemini) when analyzing the thesis.  
> It ensures semantic consistency, modularity, and reproducibility across runs.


