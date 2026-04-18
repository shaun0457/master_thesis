# Roles in the X-MAS Multi-Agent Architecture
**Status:** Stable (v1)  
**Scope:** Architectural Baseline — Fixed Component (Control Variable)  
**Related To:** Thesis Methodology – Multi-Agent Experimental Design  
**Author:** Cheng-Ting Chen  
**Framework:** MAS-A (thesis-defined architecture)

---

## Table of Contents
1. Purpose of Role Definition
2. Role Architecture in MAS-A
3. Variable Design in This Thesis  
   3.1 Independent, Dependent, Mediator, and Control Variables  
   3.2 Variable Structure Diagram
4. Role Architecture Overview  
   4.1 Architecture Diagram  
   4.2 Role Descriptions
5. Why These Roles?
6. Why Not More Roles?
7. Roles vs Collaboration Protocols (IMPORTANT)
8. Reproducibility and Experimental Validity
9. Alignment with RQ1–RQ3
10. Limitations

---

## 1. Purpose of Role Definition
This document defines the **fixed architectural role set** used throughout all experiments in this thesis.  
Roles enable controlled experimental evaluation and **white-box explainability** in multi-agent collaboration.

The purpose of explicitly defining roles is:
- **Experimental Control** – prevents confounding effects from uncontrolled agent behavior. 
- **Reproducibility** – guarantees consistent interactions across repeated runs.
- **Process Explainability** – enables tracing of interaction dynamics and failure causes.
- **Benchmarking** – ensures that comparisons across prompt strategies are methodologically valid.
- To isolate the **true effect of collaboration protocols**  
- To enable process-trace metrics such as **coordination centralization (C)** and **knowledge reuse**  


Role design is **not a creative preference**, but a **methodological necessity** to support valid benchmarking and process-level explainability.

---

## 2. Position within MAS-A Architecture
The thesis uses a structured agent architecture called **MAS-A (Multi-Agent System Architecture)**, a **thesis-defined conceptual framework** designed to evaluate collaboration mechanisms among LLM-based agents. MAS-A is not borrowed from existing literature but is formally introduced in this thesis to:

- Enforce **functional decomposition**
- Support **white-box diagnosis and traceability**
- Enable **causal reasoning at the process level**

It is layered as follows:

| Layer | Components | Purpose |
|-------|------------|----------|
| Governance Layer | Supervisor | Goal alignment, approval |
| Control Layer | Router | Enforces protocol rules |
| Reasoning Layer | DE, DS, ME | Collaborative problem solving |
| Shared Knowledge Layer | Blackboard | Memory + knowledge reuse |

Within MAS-A, **roles define the functional responsibilities of agents**. Roles are **fixed throughout all experiments** to maintain architectural consistency. Only **collaboration protocols** (prompt strategies) change between experiment conditions.

---

## 3. Design Principles for Role Selection
The role system follows four design principles:

| Principle | Description |
|-----------|-------------|
| Functional Decomposition | Each role must provide a necessary and non-overlapping capability |
| Cognitive Traceability | Every decision must be attributable to a role |
| Behavioral Observability | Interaction signals must be analyzable at the role level |
| Experimental Control | Role architecture must remain constant across conditions |

### 3.1 Variable Table
| Variable Type | In This Research |
|---------------|------------------|
| **Independent Variable (manipulated)** | Collaboration Protocol (Neutral / Planner→Worker / Debate / Delphi) |
| **Dependent Variables** | Performance, Efficiency, Stability |
| **Mediator Variables** | Behavioral Signals: C, H, reuse, orphan, t_owner_read |
| **Control Variables** | **Role Architecture**, **Router**, model config, tools, dataset, evaluation rubric |
| **Implementation Mechanism** | Protocol-specific system prompts |

### ✅ IMPORTANT Definition
> **In this thesis, the role architecture and system environment remain fixed as an *architectural control baseline*. The only manipulated variable is the *collaboration protocol*, implemented through protocol-specific system prompts. Role prompts define agent capabilities, while protocol prompts define interaction rules.**

### 3.2 Variable Structure Diagram

     ┌─────────────────────────────────────────────┐
     │        Experimental Variable Model          │
     └─────────────────────────────────────────────┘

    Independent Variable (Manipulated)
    ┌─────────────────────────────────────────────┐
    │ Collaboration Protocol                      │
    └─────────────────────────────────────────────┘
                           │
                           ▼
    Mediators (Process Mechanisms)
    ┌─────────────────────────────────────────────┐
    │ Behavioral Signals                          │
    │ C, H, reuse, orphan, t_owner_read           │
    └─────────────────────────────────────────────┘
                           │
                           ▼
    Dependent Variables (Outcomes)
    ┌─────────────────────────────────────────────┐
    │ Performance, Efficiency, Stability          │
    └─────────────────────────────────────────────┘
                           ▲
                           │
    Architectural Control Baseline (Fixed)
    ┌─────────────────────────────────────────────┐
    │ Roles (Supervisor, Router, DE, DS, ME)      │
    │ Model, Tools, Dataset, Blackboard Schema    │
    └─────────────────────────────────────────────┘


---

## 4. Overview of the Role Set

### 4.1 Role Architecture Diagram
                ┌───────────────────┐
                │    Supervisor     │
                │ (task governance) │
                └─────────▲─────────┘
                          │  read/write
                          │
                ┌─────────┴─────────┐
                │      Router       │   ← fixed communication control
                └───────▲───▲───────┘
                        │   │
                        │   │
    ┌───────────────────┘   └──────────────────┐
    │                                          │
┌──────────────┐ ↔ ┌────────────────┐ ↔ ┌─────────────────┐
│ Data Engineer│ ↔ │ Data Scientist │ ↔ │ Machine Expert  │
└──────────────┘   └────────────────┘   └─────────────────┘
    ↘──────────────── Shared Blackboard ────────────────↙
**Figure 1 – Role Architecture of X-MAS System**

### 🔧 Clarification
Although peer-to-peer communication among the Data Engineer (DE), Data Scientist (DS), and Machine Expert (ME) is permitted to emulate **human-like collaboration**, **all message routing is governed by the Router** to ensure:

- ✅ Reproducibility  
- ✅ Prevent message collision and chaos  
- ✅ Enforce protocol rules (Planner→Worker, Debate, Delphi)  
- ✅ Preserve experiment control  

The Router **does not alter message content** and has **no reasoning authority**.

### 4.2 Role Descriptions

| Role | Function |
|------|----------|
| **Supervisor** | oordinates the task, sets subgoals, approves final outputs, and ensures reasoning quality. Acts as governance, not task executor |
| **Router** | Enforces interaction order and protocol compliance. A **non-content** component enforcing message routing rules, interaction order, and termination constraints. It ensures that task flow follows the collaboration protocol without chaotic interactions |
| **Data Engineer (DE)** | Handles data acquisition, transformation, validation, and feature readiness. Maintains data integrity and transparency |
| **Data Scientist (DS)** | Statistical reasoning and hypothesis validation. Conducts analysis, modeling, and hypothesis testing. Bridges data signals with interpretable decisions. |
| **Machine Expert (ME)** | Domain validation and technical correctness. Injects domain knowledge and validates technical feasibility. Reduces hallucination risk through evidence-based reasoning |

---

## 5. Why These Roles? (Justification Table)

| Role | Necessity | Risk If Removed |
|------|-----------|------------------|
| Supervisor | Ensures alignment and decision integration | Fragmented reasoning, no final approval, agents diverge, premature or unverified answers |
| Router | Enforces reproducible communication topology, Prevents chaotic interaction | Interaction noise invalidates protocol comparison, Invalid topology analysis, no protocol control |
| Data Engineer | Guarantees valid data foundations | Hidden bias, untraceable data assumptions |
| Data Scientist | Introduces reasoning over metrics and evidence | Outputs lack analytical justification |
| Machine Expert | Validates technical correctness, Eliminates domain hallucinations | Domain errors and hallucinations increase |

This exact role set balances **minimality** (no redundancy) and **completeness** (covers necessary functions).

---

## 6. Why Not More Roles?
Roles such as *Critic, Judge, Planner,* or *Summarizer* were considered but excluded because:

- They introduce redundancy (Supervisor already performs review).
- They conflate responsibility boundaries.
- They increase complexity without experimental value.
- They risk confounding the effect of collaboration protocols.

> ✱ Principle: **Roles must remain constant** while **protocols generate behavioral differences**.

---

## 7. Roles vs. Collaboration Protocols
A critical distinction in this thesis:

| Aspect | Fixed | Manipulated |
|--------|-------|-------------|
| **Roles (this document)** | ✅ Yes – fixed across all runs |
| **Collaboration Protocols** (Planner→Worker, Debate, Delphi) | ❌ No – intentionally varied |

The collaboration protocol changes **how roles interact**, not **what roles exist**.

---

## 8. Reproducibility, Control, and Experimental Validity
Without role definition:

- Metrics like **coordination centralization (C)** or **knowledge reuse** become untraceable.
- Failure analysis cannot attribute breakdowns.
- Collaboration effect dissolves into random behavior.
- **Benchmarking loses scientific validity**.

Therefore, this role system **enforces stable interaction topology**, making process analysis feasible and reproducible.

---

## 9. Alignment with Research Questions

| RQ | Role Contribution |
|----|--------------------|
| **RQ1** – Differences between protocols | Stable roles isolate protocol effects |
| **RQ2** – Process signals | Roles make behavioral metrics attributable |
| **RQ3** – Mediation mechanisms | Role architecture enables valid causal tracing |

The full role architecture is essential to answering **why strategies differ**, not just **which performs best**.

---

## 10. Limitations and Extensibility
- This role design assumes **cooperative** rather than adversarial interaction.
- Tasks requiring creativity or negotiation may require role extension.
- Future work may modularize role composition depending on task type.

---

### ✅ Conclusion
This role architecture establishes a **methodologically grounded**, **reproducible**, and **explainable** foundation for multi-agent experiments in this thesis. Roles represent **fixed control variables**, enabling meaningful analysis of **collaboration protocols as experimental factors**.

This document serves as a foundational reference for:
- Thesis Methodology (Chapter 3)
- Experimental Design (Chapter 5)
- Benchmark Reproducibility Appendix

