# O-MAS: Observable Multi-Agent System

Code submission for Master's Thesis: *Analyzing Prompt Strategies for Improving Stability and Cooperation Quality in Multi-Agent Systems*

**Author:** Cheng-Ting Chen
**Institution:** Technische Universität Darmstadt
**Supervisor:** Ann-Kathrin Bischoff

---

## Overview

O-MAS (Observable Multi-Agent System) is a research framework for evaluating LLM-based multi-agent collaboration under different coordination protocols. Four specialized agents — Supervisor, Data Engineer, Data Scientist, and Machine Expert — communicate through a shared blackboard and are governed by a protocol-aware router. All interactions are logged as structured events, enabling post-hoc extraction of behavioral and process metrics.

### Key Features

- **Four Collaboration Protocols:** Neutral, Planner-to-Worker, Debate, Delphi
- **Four Agent Roles:** Supervisor, Data Engineer, Data Scientist, Machine Expert
- **Blackboard Communication:** URI-based shared memory (`bb://topic/artifact`)
- **Structured Event Logging:** `run.turn.v2`, `router.event.v2`, `bb.write.v1`, `run.read.v1`
- **JSON Schema Validation:** All events validated before writing
- **Process Metrics:** Centralization, entropy, Gini, reuse, orphan, loop density, TDI
- **Test Suite:** 113 tests, 98% coverage on core modules

---

## Directory Structure

```
code_submission/
├── README.md
├── requirements.txt             # Python dependencies
├── schema/                      # JSON Schema definitions
│   ├── run.turn.v2.json         # Agent turn event schema
│   ├── router.event.v2.json     # Router event schema
│   ├── bb.write.v1.json         # Blackboard write event schema
│   └── run.read.v1.json         # Blackboard read event schema
├── mas/                         # Core MAS framework
│   ├── runtime/
│   │   └── loop.py              # Main orchestration loop
│   ├── blackboard/
│   │   └── store.py             # Blackboard storage (URI-based, atomic writes)
│   ├── core/
│   │   └── router.py            # Protocol router (P2P enforcement, violation tracking)
│   ├── logging/
│   │   └── event_writer.py      # Structured JSONL event writers
│   ├── tools/
│   │   └── __init__.py          # Tool stubs (SQLSandbox, RAGEngine, MLToolbox)
│   ├── io/
│   │   ├── metrics.py           # Metric computation
│   │   ├── event_reader.py      # Event log parser
│   │   └── utils.py             # Utilities
│   └── enrich/
│       ├── tdi.py               # Topic Drift Index
│       └── policy.py            # Policy adherence
├── agents/                      # Agent implementations
│   ├── base.py                  # BaseAgent (LLM call, blackboard I/O, prompt loading)
│   ├── supervisor.py
│   ├── de.py                    # Data Engineer (SQL sandbox integration)
│   ├── ds.py                    # Data Scientist (ML toolbox integration)
│   └── me.py                    # Machine Expert (RAG integration)
├── prompts/                     # Prompt templates
│   ├── roles/                   # Role card prompts
│   └── protocols/               # Protocol-specific overlays
│       ├── neutral/
│       ├── planner_to_worker/
│       ├── debate/
│       └── delphi/
├── analysis/                    # Statistical analysis scripts
│   ├── run_models.py            # GLMM and mediation analysis
│   └── scripts/
│       └── extract_metrics.py
├── cli/
│   └── run_experiment.py        # Batch experiment CLI
├── tools/
│   ├── make_result.py
│   └── make_leaderboard.py
├── facts/
│   └── references.bib
└── tests/                       # Pytest test suite (113 tests, 98% coverage)
    ├── test_schemas.py
    ├── test_tools_stubs.py
    ├── test_router.py
    ├── test_event_writer.py
    └── test_base_agent.py
```

---

## Installation

```bash
# Clone the repository
git clone https://github.com/shaun0457/master_thesis.git
cd master_thesis

# Install dependencies
pip install -r requirements.txt

# Set your Gemini API key
export GEMINI_API_KEY=your_key_here
```

**Python 3.10+ required.**

> **Note:** The `SQLSandbox`, `RAGEngine`, and `MLToolbox` components require proprietary TEP datasets that are not included in this public release. The codebase degrades gracefully — agents print a warning and continue without those tools.

---

## Quick Start

### Run a Single Experiment

```python
from pathlib import Path
from mas.runtime.loop import run_experiment

summary = run_experiment(
    protocol='debate',
    query_path=Path('queries/diagnosis_task.md'),
    run_id='debate-s42-20241115',
    seed=42,
    model_cfg={'model_name': 'gemini-2.5-pro', 'temperature': 0.25},
    max_turns=20
)
print(f"Completed: {summary['completed']} in {summary['turns']} turns")
print(f"Violations: {summary['violations']}")
```

### Run from CLI

```bash
# Single run
python -m mas.runtime.loop \
    --query queries/diagnosis_task.md \
    --protocol debate \
    --seed 42 \
    --max-turns 20

# Batch across all protocols and seeds
python cli/run_experiment.py \
    --protocols neutral planner_to_worker debate delphi \
    --seeds 1 2 3 4 5 \
    --query queries/diagnosis_task.md
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      run_experiment()                   │
│                                                         │
│  ┌──────────┐   turn_message    ┌──────────┐            │
│  │Supervisor│ ◄────────────────►│  Router  │            │
│  └──────────┘                   └──────────┘            │
│       │                              │                  │
│  delegate                     route + log               │
│       │                              │                  │
│  ┌────▼─────────────────────────┐    │                  │
│  │  DE  │  DS  │  ME            │    │                  │
│  └──────┴──────┴────────────────┘    │                  │
│       │                              │                  │
│  bb:// read/write              event_writer             │
│       │                              │                  │
│  ┌────▼───────────────────────────────▼───────────────┐ │
│  │           BlackboardStore  /  JSONL Logs           │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Communication Protocols

| Protocol | P2P Workers | Violation Action | Use Case |
|----------|-------------|-----------------|----------|
| `neutral` | Allowed | None | Baseline |
| `planner_to_worker` | Blocked → Supervisor | Hard violation | Hierarchical coordination |
| `debate` | Allowed with warning | Warning only | Adversarial deliberation |
| `delphi` | Allowed | None | Anonymous consensus |

### Event Schema

All agent interactions produce structured events validated against JSON Schemas:

| Event | File | Description |
|-------|------|-------------|
| `run.turn.v2` | `run.turn.v2.jsonl` | Agent turn (message, intent, action) |
| `router.event.v2` | `router.event.v2.jsonl` | Routing decision, violations |
| `bb.write.v1` | `bb.write.v1.jsonl` | Blackboard artifact creation |
| `run.read.v1` | `run.read.v1.jsonl` | Blackboard artifact access |

---

## Process Metrics

### Topology
| Metric | Symbol | Formula |
|--------|--------|---------|
| Centralization | C | Freeman's degree centralization [0,1] |
| Handoff Entropy | H | Shannon entropy of delegations |
| Ownership Gini | G | Inequality in turn authorship [0,1] |

### Knowledge Flow
| Metric | Symbol | Description |
|--------|--------|-------------|
| Reuse Rate | reuse | Fraction of writes read by others |
| Orphan Rate | orphan | Fraction of writes never read |
| Response Speed | resp | 1 − (t_first_read / t_ceiling) |

### Stability
| Metric | Symbol | Description |
|--------|--------|-------------|
| Loop Density | L | Cyclic paths / total paths [0,1] |
| Topic Drift Index | TDI | Semantic drift from goal embedding |

### Composite Outcomes
| Outcome | Formula |
|---------|---------|
| Process Stability (PSI) | 0.50×(1−L) + 0.50×(1−C) |
| Operational Efficiency (OEI) | 1 − min(turns/50, 1.0) |
| Cooperation Quality (Y₂) | 0.35×reuse + 0.30×(1−G) + 0.20×resp + 0.15×H_norm |

---

## Output Files

```
data/runs/{run_id}/
├── run.turn.v2.jsonl      # Agent turn events
├── router.event.v2.jsonl  # Router validation events
├── bb.write.v1.jsonl      # Blackboard write events
├── run.read.v1.jsonl      # Blackboard read events
├── stdout.txt             # Full execution log
├── final_output.txt       # Extracted final report
└── result.json            # Computed metrics (after extract_metrics.py)
```

---

## Tests

```bash
# Install test dependencies (included in requirements.txt)
pip install pytest pytest-cov

# Run full test suite
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=mas --cov=agents --cov-report=term-missing
```

### Coverage (core modules)

| Module | Coverage |
|--------|---------|
| `mas/tools/__init__.py` | 100% |
| `mas/core/router.py` | 100% |
| `mas/logging/event_writer.py` | 99% |
| `agents/base.py` | 97% |
| `agents/__init__.py` | 100% |
| **Average (5 core modules)** | **98%** |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | — | Required for LLM calls |
| `GEMINI_MODEL` | `gemini-2.5-pro` | Model identifier |
| `GEMINI_TEMP` | `0.25` | Sampling temperature |
| `BB_ROOT` | `data/blackboard` | Blackboard storage root |
| `RUNS_ROOT` | `data/runs` | Event log output root |

---

## References

See `facts/references.bib` for complete bibliography.

- Freeman, L. C. (1978). Centrality in social networks
- Hayes-Roth, B. (1985). A blackboard architecture for control
- Wooldridge, M. & Jennings, N. R. (1995). Intelligent agents: theory and practice

---

## License

Internal research use only. All rights reserved.

---

## Contact

**Cheng-Ting Chen**
Technische Universität Darmstadt
