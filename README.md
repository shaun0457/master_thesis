# Multi-Agent System for Industrial Process Analysis

A research-grade **Multi-Agent System (MAS)** built with [LangGraph](https://github.com/langchain-ai/langgraph) for intelligent analysis of the Tennessee Eastman Process (TEP) — a benchmark chemical plant simulation widely used in fault detection and process control research.

This system orchestrates a team of specialized AI agents that collaborate to answer complex, cross-domain questions about industrial process data, combining SQL querying, retrieval-augmented generation (RAG), and Python-based data science.

---

## Architecture Overview

```
User Query
    │
    ▼
┌─────────────────────────────────────────┐
│           Supervisor Agent              │  ← High-level planning & delegation
│  (Policy: strict / gentle / free)       │
└──────────────────┬──────────────────────┘
                   │ delegates
                   ▼
┌─────────────────────────────────────────┐
│              Router                     │  ← Dispatches to expert subgraphs
│   (P2P coordination between agents)     │  ← Manages inter-agent P2P requests
└────────┬──────────────┬─────────────────┘
         │              │              │
         ▼              ▼              ▼
   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │    ME    │   │    DE    │   │    DS    │
   │ Machine  │   │  Data    │   │  Data    │
   │ Expert   │   │ Engineer │   │Scientist │
   │  (RAG)   │   │  (SQL)   │   │(Python)  │
   └──────────┘   └──────────┘   └──────────┘
         │              │              │
         └──────────────┴──────────────┘
                        │
               ┌────────▼────────┐
               │   Blackboard    │  ← Shared asynchronous memory
               └─────────────────┘
```

### Key Architectural Patterns

| Pattern | Implementation |
|---|---|
| **Hierarchical Control** | Supervisor → Router → Expert Agents |
| **ReAct Loop** | Each expert agent runs an autonomous Reason-Act cycle |
| **P2P Delegation** | Agents can sub-delegate to peers (e.g., DE requests DS for analysis) |
| **Guarded Autonomy** | Correction node enforces behavioral guardrails on the Supervisor |
| **Policy-Driven Behavior** | `strict` / `gentle` / `free` modes control error tolerance |
| **Blackboard Pattern** | File-based shared memory for asynchronous inter-agent communication |

---

## Agent Roles

### Supervisor Agent
The top-level decision-maker. It receives user queries, decomposes them into sub-tasks, and delegates to the appropriate expert agents. A **Correction Node** enforces guardrails — for example, preventing the Supervisor from issuing a final answer before sufficient evidence has been gathered.

### Router
The execution bridge between the Supervisor and expert subgraphs. It handles:
- Direct delegation from Supervisor to experts
- **Peer-to-peer (P2P) delegation** between expert agents
- Loop detection and cycle prevention with configurable hop limits

### Machine Expert (ME) — RAG Specialist
Answers questions by retrieving information from domain documents (PDFs, technical manuals) using:
- PDF parsing with `pymupdf` and `camelot`
- TF-IDF based retrieval with cosine similarity ranking
- Citation-grounded responses

### Data Engineer (DE) — SQL Specialist
Queries the TEP SQLite database to extract time-series sensor data:
- Schema-aware SQL generation
- Dynamic query construction
- Exports datasets to the blackboard for downstream analysis

### Data Scientist (DS) — Python Specialist
Performs quantitative analysis on data provided by the DE:
- Executes sandboxed Python code via `PythonREPLTool`
- Statistical analysis, visualization, and anomaly detection
- Writes figures and results back to the blackboard

---

## Key Features

- **Multi-strategy Prompting**: Three prompt condition modes (`debate`, `delphi`, `ptow`) with 12 agent prompt cards, enabling controlled experiments on collaboration strategies.
- **Comprehensive Logging**: Structured run logs capture every agent action, tool call, and message for offline analysis and reproducibility.
- **Metrics Collection**: Tracks token usage, tool call counts, ME citation rates, and run duration per session.
- **Blackboard Memory**: A persistent, file-based shared store that decouples agents and enables asynchronous data passing.
- **Fault Injection Ready**: The TEP domain includes 21 fault types, allowing experiments on fault detection and diagnosis workflows.

---

## Tech Stack

| Category | Technology |
|---|---|
| Agent Framework | [LangGraph](https://github.com/langchain-ai/langgraph) |
| LLM Backend | Google Gemini via Vertex AI (`langchain-google-vertexai`) |
| Database | SQLite + SQLAlchemy |
| PDF Parsing | PyMuPDF, Camelot |
| Data Analysis | NumPy, Pandas, Scikit-learn, Matplotlib |
| Orchestration | Python 3.11+ |

---

## Project Structure

```
MT-phase-2/
├── chat_cli.py              # Entry point: interactive CLI for the MAS
├── supervisor_workflow.py   # Top-level LangGraph graph (Supervisor + Router + Correction)
├── router.py                # Delegation dispatcher & P2P coordination logic
├── delegate_tools.py        # Subgraph factory & expert invocation utilities
├── supervisor_tools.py      # Supervisor's delegation tools (delegate_to_me/de/ds)
│
├── me_workflow.py           # Machine Expert (ME) ReAct subgraph
├── me_tools.py              # ME tools: document search, retrieval, summarization
├── me_docs.py               # PDF indexing and TF-IDF retrieval engine
│
├── de_workflow.py           # Data Engineer (DE) ReAct subgraph
├── de_tools.py              # DE tools: SQL query, schema inspection
│
├── ds_workflow_s2.py        # Data Scientist (DS) ReAct subgraph
├── ds_tools.py              # DS tools: Python code execution
│
├── bb_tools.py              # Blackboard read/write tools
├── common.py                # Shared LLM config, AgentState definition, utilities
├── prompt_builder.py        # Dynamic prompt card loader
├── prompts.py               # Static prompt strings
├── run_logger.py            # Structured run event logger
├── metrics.py               # Per-run metrics collection
├── tee_logs.py              # Console log tee to file
│
├── compute_proxies.py       # TEP proxy variable computation
├── cross_corr_tool.py       # Cross-correlation analysis tool
├── runjson_to_events.py     # Log parsing and event extraction
├── agent_log_parser_template.py  # Template for offline log analysis
│
├── prompt/                  # Agent prompt cards (12 files: 4 agents × 3 conditions)
│   ├── supervisor_card_debate.md
│   ├── supervisor_card_delphi.md
│   ├── supervisor_card_ptow.md
│   ├── de_card_*.md
│   ├── ds_card_*.md
│   └── me_card_*.md
│
├── TEP_docs/                # Domain knowledge documents (PDFs + Markdown)
├── te_tag_map.csv           # TEP sensor tag name mapping
│
├── .env.example             # Environment variable template
├── requirements.txt
└── README.md
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- A Google Cloud project with Vertex AI API enabled
- A service account with Vertex AI User role

### Installation

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
cd YOUR_REPO_NAME

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your GCP project ID and service account credentials path
export GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
```

### Running

```bash
# Default: strict policy, debate prompt condition
python chat_cli.py

# Custom configuration
POLICY=gentle PROMPT_CONDITION=delphi python chat_cli.py

# With verbose logging disabled
MAS_VERBOSE=0 python chat_cli.py
```

### Example Queries

- *"What is the relationship between the reactor temperature and the recycle compressor work?"*
- *"Detect anomalies in the separator level sensor over the last 500 time steps."*
- *"What fault conditions are defined in the TEP specification, and which variables are most affected by Fault 4?"*

---

## Research Context

This system is developed as part of a master's thesis investigating multi-agent collaboration strategies for industrial process intelligence. The Tennessee Eastman Process serves as the experimental testbed due to its complexity (41 process variables, 12 manipulated variables, 21 fault types) and its status as a standard benchmark in process control and fault detection literature.

The three prompt conditions (`debate`, `delphi`, `ptow`) implement distinct collaboration strategies, enabling controlled comparison of how different interaction paradigms affect answer quality, convergence speed, and agent behavior.

---

## License

This project is for academic and research purposes.
