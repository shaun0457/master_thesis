---
title: "03 — Methods and Metrics Framework"
author: "Cheng-Ting Chen"
version: 0.1
last_updated: 2025-10-15
---

## English

### 3.1 Framework Overview
Seven constructs quantify the MAS behavior:
1. **Centralization (C)** – concentration of communication.
2. **Entropy (H)** – interaction diversity.
3. **Gini (G)** – contribution inequality.
4. **Reuse rate** – effective knowledge reuse.
5. **Orphan rate** – information loss.
6. **t_first_read** – responsiveness.
7. **t_owner_read** – self-monitoring loop.

---

### 3.1.1 Provenance of Metrics
The metrics used in this work originate from two complementary sources:

| Metric | Origin | Key Reference | Nature |
|---------|---------|----------------|---------|
| Centralization (C) | Network topology measure | Freeman (1978, 1979) | Established structural metric |
| Entropy (H) | Information diversity | Shannon (1948) | Established structural metric |
| Gini (G) | Contribution inequality | Gini (1912) | Established structural metric |
| reuse / orphan | Blackboard knowledge flow | Nii (1986); Corkill (2003) | Novel process metric, event-based |
| t_first_read / t_owner_read | Temporal event analysis | This study (blackboard event logs) | Novel governance metric |
| handoff success | Process hand-off correctness | This study | Novel governance metric |

**Structural metrics (C, H, G)**  
Adopted from social network and information theory literature to describe team topology—how communication is distributed among agents.  

**Process metrics (reuse, orphan, t_first_read, t_owner_read, handoff success)**  
Inspired by classical blackboard architectures, these quantify *how information flows and is reused* among agents.  
Existing LLM-MAS works (e.g., CAMEL, Multi-Agent Debate) report only task success or reasoning quality; this study introduces governance-oriented, auditable process metrics to enable reproducibility and behavioral analysis.

> *We adopt network centralization (Freeman, 1978/1979), entropy (Shannon, 1948), and Gini inequality (Gini, 1912) to quantify team topology and contribution balance.  
> Building on the blackboard problem-solving paradigm (Nii, 1986), we introduce process-level, event-log-based metrics—reuse/orphan, t_first_read, t_owner_read, and handoff success—to audit knowledge flow and hand-offs in LLM-MAS.*

---

### 3.2 Quantitative Formulas
- \( C=\frac{\sum_i(\max_j d_j^- - d_i^-)}{(n-1)(n-2)} \)  
- \( H=-\sum_e p(e)\log p(e) \)  
- \( G=\frac{\sum_i\sum_j|x_i-x_j|}{2n\sum_i x_i} \)  
- \( reuse=\frac{\#read\_by\_others}{\#written} \)  
- \( orphan=\frac{\#unread}{\#written} \)

### 3.3 Experimental Design
- **Independent variable:** prompt strategy (Planner→Worker / Debate / Delphi)  
- **Task types:** diagnosis, data preparation, goal optimization.  
- **Replications:** 15 random seeds per strategy × task (105 runs).  
- **Controlled factors:** model, temperature, toolset, dataset.  
- **Outputs:** `stdout.txt`, `events.jsonl`, `metrics.json`, `timeline.csv`.

### 3.4 Analysis Plan
- Compare strategies using ANOVA or Kruskal-Wallis.  
- Test mediation: topology / flow → stability / cooperation.  
- Report effect sizes and confidence intervals.

---

### 3.5 Communication Architecture and the Role of the Blackboard

#### 3.5.1 Motivation
Most existing LLM-Agent frameworks (e.g., AutoGPT, CrewAI, LangChain Multi-Agent) are **controller-centric**.  
Sub-agents do not directly share state; they communicate through prompt concatenation managed by a central planner.  
This creates an *illusion of communication*—no persistent memory, no explicit events, and no traceable decision path.

#### 3.5.2 Why the Blackboard
The **blackboard system** serves as a persistent, structured event layer shared by all agents.  
Each read/write operation is stored with:
- author (agent name)  
- timestamp  
- referenced objects  
- status (active, read, reused, orphan)

This allows:
- event-based reasoning instead of text concatenation;  
- traceable, auditable collaboration;  
- quantitative computation of governance metrics (reuse, orphan, t_first_read, t_owner_read, handoff success).

Without a blackboard, MAS collaboration cannot be measured or reproduced:  
no event logs → no stability metrics → no governance audit.

#### 3.5.3 Comparative View
| Aspect | Without Blackboard | With Blackboard |
|--------|--------------------|-----------------|
| Communication | Prompt concatenation | Structured event exchange |
| Observability | Hidden inside LLM context | Transparent, timestamped |
| Reproducibility | Low (context drift) | High (event replay) |
| Governance | No decision trace | Full audit trail |
| Metric computability | Impossible | Enabled (C/H/G + process metrics) |

#### 3.5.4 Conceptual Diagram (textual)
[Planner/Controller] ---> (Prompt Routing) ---> [Sub-Agents]
| |
v v
[Context Buffer] (hidden memory)

versus

[All Agents]
↕
[Shared Blackboard] --(timestamped events: write/read/reuse/hand-off)-->


#### 3.5.5 Theoretical Background
The blackboard model of problem-solving (Nii, 1986; Corkill, 2003) established an architecture where multiple knowledge sources collaborate through a shared memory.  
This work reinterprets that paradigm for LLM-based MAS, turning implicit textual interactions into explicit, machine-auditable events.

> *The blackboard is not an extra feature—it transforms a collection of LLMs into a measurable system. Without it, concepts such as stability or cooperation quality cannot be operationalized.*

---

### 3.6 Knowledge-Flow Metrics (Core and Extended)

#### 3.6.1 Core Indicators
The *knowledge-flow construct* is based on four observable metrics derived from blackboard event logs:

| Metric | Meaning | Governance Dimension | Formula basis |
|---------|----------|----------------------|---------------|
| **reuse rate** | proportion of messages read/referenced by others | utilization | count(referenced) / total messages |
| **orphan rate** | messages never read or referenced | information waste | count(unread) / total messages |
| **t_first_read** | delay until first external read | responsiveness | avg(Δt between write and first read) |
| **t_owner_read** | delay until creator rereads own message | self-monitoring | avg(Δt between write and self read) |

These four indicators form a **minimal observable knowledge-flow framework** enabling fine-grained analysis of information propagation, loss, and latency within the team.

#### 3.6.2 Extended Indicators
To capture higher-level properties of information flow and cooperation, three composite or derived indicators are introduced.

| Metric | Definition | Interpretation | Use case |
|---------|-------------|----------------|-----------|
| **Flow Efficiency (E_f)** | \( E_f = \frac{reuse}{avg(t\_{first\_read})} \) | Combines utilization and speed | Overall fluency of team communication |
| **Flow Centrality** | in/out-degree of each agent in the reference graph | Identifies brokers or bottlenecks | Locates dominant or passive agents |
| **Loop Density (L)** | cyclic paths / total paths | Measures redundant or oscillatory discussion | Detects instability and conversational loops |

#### 3.6.3 Hierarchical Organization
| Level | Purpose | Metrics |
|--------|----------|----------|
| **Structural** | describe topology | Centralization, Entropy, Gini |
| **Knowledge-Flow Core** | measure propagation and reaction | reuse, orphan, t_first_read, t_owner_read |
| **Extended Flow** | explain macro behaviors | flow_efficiency, flow_centrality, loop_density |

#### 3.6.4 Novelty Attribution
- Structural metrics (C/H/G) → **adapted from established literature**.  
- Knowledge-flow metrics (reuse/orphan/t_first_read/t_owner_read/handoff success) → **introduced by this study**, operationalized via blackboard event logs.  
- Extended metrics (flow efficiency/centrality/loop density) → **composite or contextualized adaptations** of existing graph concepts.  

> *To our knowledge, within LLM-based multi-agent systems, no prior work has reported governance-oriented event metrics such as reuse, orphan, or read delays. These indicators provide a traceable, quantitative layer for analyzing cooperation quality and stability.*

#### 3.6.5 Validation Plan
1. **Computability** — every metric derived directly from event logs (reproducible).  
2. **Sensitivity** — verify expected shifts across strategies (Planner→Worker, Debate, Delphi).  
3. **Manipulation checks** — artificially delay reads or drop references to confirm metric responsiveness.  
4. **Outcome linkage** — correlate metrics with success, convergence, and failure patterns.  
5. **Robustness** — test consistency across temperature/model/task length variations.

---

## References (selected)

```bibtex
@article{Freeman1978,
  author = {Linton C. Freeman},
  title = {Centrality in Social Networks: Conceptual Clarification},
  journal = {Social Networks},
  year = {1978},
  pages = {215–239}
}

@article{Shannon1948,
  author = {Claude E. Shannon},
  title = {A Mathematical Theory of Communication},
  journal = {Bell System Technical Journal},
  year = {1948},
  volume = {27},
  pages = {379–423}
}

@article{Gini1912,
  author = {Corrado Gini},
  title = {Variability and Mutability},
  journal = {C. Cuppini, Bologna},
  year = {1912}
}

@article{Nii1986,
  author = {H. Penny Nii},
  title = {The Blackboard Model of Problem Solving and the Evolution of Blackboard Architectures},
  journal = {AI Magazine},
  year = {1986},
  volume = {7},
  number = {2},
  pages = {38–53}
}

@article{Corkill2003,
  author = {Daniel Corkill},
  title = {Collaborating AI Systems Using the Blackboard Architecture},
  journal = {Proceedings of the International Lisp Conference},
  year = {2003}
}

@article{Rahwan2019,
  author = {Iyad Rahwan et al.},
  title = {Machine behavior},
  journal = {Science},
  year = {2019},
  volume = {366},
  pages = {477–486}
}

