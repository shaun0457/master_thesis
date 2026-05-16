# TEP Fault Diagnosis — Multi-Agent System

> A production-grade multi-agent AI system that diagnoses industrial process faults through collaborative reasoning between specialized AI experts.

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow)

---

## What Does This Do?

You send it a question like *"Reactor feed temperature is spiking — what fault is this?"*, and a team of AI agents collaborate to answer it:

- **Machine Expert** digs through technical PDFs and a knowledge graph
- **Data Engineer** queries historical sensor data via SQL
- **Data Scientist** runs statistical analysis and generates plots
- A **Supervisor** orchestrates all of them, routes between them, and synthesizes a final diagnosis

The domain is the **Tennessee Eastman Process (TEP)** — a well-known benchmark for industrial chemical process fault detection, with 21 labeled disturbances involving reactor temperature, flow rates, compressor surges, and more.

---

## Architecture

```
User Input (CLI or REST API)
        │
        ▼
┌─────────────────────────────────────────────────┐
│               Supervisor (LangGraph)            │
│  • Decides which experts to call                │
│  • Maintains shared Blackboard (facts/datasets) │
│  • Synthesizes final answer                     │
└──────────────┬──────────────────────────────────┘
               │  delegates via Router
       ┌───────┼────────────────┐
       ▼       ▼                ▼
  ┌─────────┐ ┌──────────────┐ ┌──────────────────┐
  │   ME    │ │     DE       │ │       DS         │
  │Machine  │ │Data Engineer │ │ Data Scientist   │
  │Expert   │ │              │ │                  │
  │         │ │ • SQL on TEP │ │ • Python analysis│
  │ • PDF   │ │   sensor DB  │ │ • Stats / plots  │
  │   RAG   │ │ • Dataset    │ │ • Cross-corr     │
  │ • Neo4j │ │   export     │ │ • Anomaly detect │
  │   KG    │ └──────────────┘ └──────────────────┘
  └─────────┘
       │
  ┌────┴──────────┐
  │  TEP PDF KG   │
  │  (Neo4j)      │
  │  • Parsed from│
  │    research   │
  │    PDFs       │
  └───────────────┘
```

### Component Map

| File / Folder | Role |
|---|---|
| `chat_cli.py` | Interactive CLI entrypoint |
| `api_server.py` | FastAPI REST server |
| `supervisor_workflow.py` | LangGraph supervisor graph |
| `router.py` | Delegation logic and expert dispatch |
| `me_workflow.py` / `me_tools.py` | Machine Expert agent |
| `de_workflow.py` / `de_tools.py` | Data Engineer agent |
| `ds_workflow_s2.py` / `ds_tools.py` | Data Scientist agent |
| `bb_tools.py` | Shared blackboard (inter-agent memory) |
| `diagnose_flow.py` | Batch/automated diagnosis pipeline |
| `context_assembler.py` | Prompt context builder |
| `llm_harness.py` / `llm_cache.py` | LLM call management and caching |
| `judge.py` / `metrics.py` | Answer quality scoring |
| `tep_pdf_kg/` | PDF → Neo4j knowledge graph pipeline |
| `eval/` | Golden QA evaluation + regression gate |
| `tests/` | Unit and integration test suite |

---

## Tennessee Eastman Process (TEP)

TEP is a widely used benchmark in industrial process control and fault detection research. It simulates a chemical plant with:

- **52 sensor variables** (temperatures, pressures, flow rates, levels)
- **21 labeled fault types** (IDV 1–21), ranging from step changes to valve failures
- **Continuous time-series data** representing normal and abnormal plant operation

This system treats TEP diagnosis as a multi-hop reasoning problem: the answer requires correlating live sensor anomalies with historical baselines, domain knowledge from technical literature, and statistical pattern analysis — tasks distributed across the three expert agents.

---

## Key Features

- **Multi-agent collaboration** via LangGraph `StateGraph` with typed state and interrupt-safe routing
- **Shared blackboard** — agents post facts, datasets, and citations that other agents can build on
- **Two interaction modes**: conversational CLI (`chat_cli.py`) and REST API (`api_server.py`)
- **Automated diagnosis pipeline** (`diagnose_flow.py`) for batch/streaming observations
- **Knowledge Graph from PDFs** — TEP research papers are parsed with Docling, chunked, and extracted into a Neo4j graph via Gemini
- **Evaluation framework** — golden QA dataset (`eval/golden_qa.json`) + regression gate (`eval/regression_gate.py`)
- **LLM response caching** to reduce API cost during development
- **Structured outputs** with Pydantic for reliable agent-to-agent data contracts
- **Rate limiting and health checks** in the API server for production readiness

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent framework | LangGraph, LangChain |
| LLM | Google Gemini (via `langchain-google-genai`) |
| API server | FastAPI + uvicorn |
| Knowledge graph | Neo4j |
| Sensor database | SQLite (`tep_combined.db`) |
| Data analysis | Pandas, NumPy, scikit-learn |
| Structured outputs | Pydantic v2 |
| PDF parsing | Docling / PyMuPDF |
| Testing | pytest |

---

## Getting Started

### 1. Install dependencies

```bash
conda create -n tep-mas python=3.11
conda activate tep-mas
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in: GOOGLE_API_KEY, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
```

### 3. Run the interactive CLI

```bash
python chat_cli.py
```

### 4. Run the REST API

```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
```

Then send a diagnosis request:

```bash
curl -X POST http://localhost:8000/diagnose \
  -H "Content-Type: application/json" \
  -d '{"observation_path": "datasets/sample_obs.parquet"}'
```

### 5. Run the evaluation suite

```bash
# Unit + integration tests
pytest tests/ -q

# Golden QA regression gate
python eval/regression_gate.py
```

---

## Example Questions

These are the kinds of questions the system is designed to answer. Each requires the Supervisor to coordinate multiple experts before producing an answer.

**Sensor anomaly diagnosis**
> *We observe sporadic, self-driven spikes in the Separator level (XMEAS_12) with no fault ID provided. Propose ≥3 mechanistic hypotheses, design falsifiable tests, run lead-lag / causal analysis, and publish a candidate DAG with confidences.*

**Process root-cause investigation**
> *We suspect cooling-loop mechanisms are driving reactor stability changes, but tag semantics for "cooling water inlet temperature" are uncertain. Build/update the tag map with evidence, run multi-window lead-lag scans, and provide mechanistic rationale with actionable interventions.*

**Optimization under constraints**
> *Management targets +5–10% throughput without materially increasing risk, under possible loop saturation or upstream composition variability. Specify mechanistic constraints, build a response surface via historical counterfactuals, and propose conservative/aggressive set-points with monitoring KPIs and rollback criteria.*

---

## Project Context

This system was built as the implementation artifact for a master's thesis on **multi-agent system design for industrial fault diagnosis**. The research investigates how different prompting strategies (standard, debate, Delphi, PTOW) affect diagnosis accuracy across TEP fault scenarios.

The codebase is designed to be research-grade but production-shaped:
- modular enough to swap LLMs or agent strategies
- observable via structured run logs and metrics
- regression-gated against a golden eval set

---

## Research Background

The thesis research behind this project is documented in [`docs/research_context/`](./docs/research_context/):

- **01_Motivation** — industrial relevance and the case for multi-agent fault diagnosis
- **02_Definitions** — key constructs: stability, cooperation quality, knowledge flow metrics
- **03_Methods** — experimental framework, metric definitions, blackboard architecture
- **04_Discussion** — transferability to manufacturing governance, limitations, future work

---

## License

MIT
