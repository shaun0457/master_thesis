# O-MAS: Observable Multi-Agent System

Code submission for Master's Thesis: *Analyzing Prompt Strategies for Improving Stability and Cooperation Quality in Multi-Agent Systems*

**Author:** Cheng-Ting Chen
**Institution:** Technische Universität Darmstadt
**Supervisor:** Ann-Kathrin Bischoff

---

## Overview

This repository contains the implementation of the O-MAS (Observable Multi-Agent System) framework for evaluating LLM-based multi-agent collaboration. The system enables systematic comparison of collaboration protocols through behavioral signal extraction and process metric analysis.

### Key Features

- **Four Collaboration Protocols:** Neutral, Planner-to-Worker, Debate, Delphi
- **Four Agent Roles:** Supervisor, Data Engineer, Data Scientist, Machine Expert
- **Blackboard Communication:** Shared memory pattern for agent coordination
- **Event Logging:** Complete observability pipeline for metric extraction
- **Process Metrics:** Centralization, entropy, Gini, reuse, orphan, loop density, TDI

---

## Directory Structure

```
code_submission/
├── README.md                    # This file
├── mas/                         # Core MAS framework
│   ├── runtime/
│   │   └── loop.py              # Main execution loop
│   ├── blackboard/
│   │   ├── __init__.py
│   │   └── store.py             # Blackboard storage backend
│   ├── logging/
│   │   ├── __init__.py
│   │   └── event_writer.py      # Event logging functions
│   ├── io/
│   │   ├── metrics.py           # Metric computation functions
│   │   ├── event_reader.py      # Event log parser
│   │   └── utils.py             # Utility functions
│   └── enrich/
│       ├── tdi.py               # Topic Drift Index computation
│       └── policy.py            # Policy adherence computation
├── agents/                      # Agent implementations
│   ├── __init__.py
│   ├── supervisor.py            # Supervisor agent
│   ├── de.py                    # Data Engineer agent
│   ├── ds.py                    # Data Scientist agent
│   └── me.py                    # Machine Expert agent
├── analysis/                    # Analysis scripts
│   ├── run_models.py            # GLMM and mediation analysis
│   └── scripts/
│       └── extract_metrics.py   # Metric extraction from logs
├── tools/                       # Utility tools
│   ├── make_result.py           # Generate result.json
│   └── make_leaderboard.py      # Generate leaderboard
├── cli/
│   └── run_experiment.py        # Experiment execution CLI
├── prompts/                     # Prompt templates
│   ├── roles/                   # Role card prompts
│   │   ├── supervisor.md
│   │   ├── data_engineer.md
│   │   ├── data_scientist.md
│   │   └── machine_expert.md
│   └── protocols/               # Protocol-specific prompts
│       ├── neutral/
│       ├── planner_to_worker/
│       ├── debate/
│       └── delphi/
└── facts/
    └── references.bib           # Bibliography (BibTeX)
```

---

## Core Components

### 1. Runtime Loop (`mas/runtime/loop.py`)

The main orchestration logic for running multi-agent experiments:

```python
from mas.runtime.loop import run_experiment

summary = run_experiment(
    protocol='debate',
    query_path=Path('queries/task.md'),
    run_id='debate-s42-20241115',
    seed=42,
    model_cfg={'model_name': 'gemini-2.5-pro', 'temperature': 0.25},
    max_turns=20
)
```

### 2. Blackboard Store (`mas/blackboard/store.py`)

Shared memory for agent communication using URI-based addressing:

```python
from mas.blackboard import BlackboardStore

store = BlackboardStore(root=Path("data/blackboard"), run_id="run-001")
store.write_json("bb://analysis/stats.json", {"mean": 42.5})
data = store.read_json("bb://analysis/stats.json")
```

### 3. Event Logging (`mas/logging/event_writer.py`)

Structured event logging for observability:

```python
from mas.logging.event_writer import write_turn, write_bb_write

write_turn(store, {
    "turn_index": 5,
    "role": "supervisor",
    "message": "Delegating analysis to DS...",
    "intent": "delegate"
})
```

### 4. Metric Computation (`mas/io/metrics.py`)

Extract behavioral signals from event logs:

```python
from mas.io.metrics import (
    compute_centralization,
    compute_handoff_entropy,
    compute_ownership_gini,
    compute_loop_density,
    compute_reuse_and_orphan
)

C = compute_centralization(router_events)
H = compute_handoff_entropy(router_events)
G = compute_ownership_gini(turn_events)
L = compute_loop_density(router_events)
```

---

## Collaboration Protocols

### Neutral (Baseline)
- Minimal coordination rules
- Agents self-organize
- No structured deliberation

### Planner-to-Worker (P2W)
- Supervisor creates work plans
- Workers execute assigned tasks
- Hierarchical coordination

### Debate
- Adversarial argumentation
- Supervisor acts as judge
- Resolution through synthesis

### Delphi
- Anonymous iterative feedback
- Convergence toward consensus
- Reflective rounds

---

## Process Metrics

### Topology Metrics
| Metric | Symbol | Description |
|--------|--------|-------------|
| Centralization | C | Freeman's degree centralization [0,1] |
| Handoff Entropy | H | Shannon entropy of delegations |
| Ownership Gini | G | Inequality in turn authorship [0,1] |

### Knowledge-Flow Metrics
| Metric | Symbol | Description |
|--------|--------|-------------|
| Reuse Rate | reuse | Fraction of writes that were read |
| Orphan Rate | orphan | Fraction of writes never read |
| Response Speed | resp | 1 - (t_first_read / t_ceiling) |

### Stability Metrics
| Metric | Symbol | Description |
|--------|--------|-------------|
| Loop Density | L | Cyclic paths / total paths [0,1] |
| Topic Drift Index | TDI | Semantic drift from goal |

### Composite Outcomes
| Metric | Symbol | Formula |
|--------|--------|---------|
| Process Stability | PSI | 0.50×(1-L) + 0.50×(1-C) |
| Operational Efficiency | OEI | 1 - min(turns/50, 1.0) |
| Cooperation Quality | Y₂ | 0.35×reuse + 0.30×(1-G) + 0.20×resp + 0.15×H_norm |

---

## Running Experiments

### Single Run
```bash
python -m mas.runtime.loop \
    --query queries/diagnosis_task.md \
    --protocol debate \
    --seed 42 \
    --max-turns 20
```

### Batch Execution
```bash
python cli/run_experiment.py \
    --protocols neutral planner_to_worker debate delphi \
    --seeds 1 2 3 4 5 \
    --query queries/diagnosis_task.md
```

---

## Output Files

After each run, the following files are generated:

```
data/runs/{run_id}/
├── run.turn.v2.jsonl      # Turn events (agent actions)
├── router.event.v2.jsonl  # Router decisions
├── bb.write.v1.jsonl      # Blackboard writes
├── run.read.v1.jsonl      # Blackboard reads
├── stdout.txt             # Complete execution log
├── final_output.txt       # Extracted final report
└── result.json            # Computed metrics
```

---

## Dependencies

- Python 3.10+
- networkx (graph analysis)
- numpy (numerical computation)
- pandas (data manipulation)
- jsonschema (validation)
- google-generativeai (LLM API)

---

## References

See `facts/references.bib` for complete bibliography.

Key references:
- Freeman, L. C. (1978). Centrality in social networks
- Hayes-Roth, B. (1985). A blackboard architecture for control
- Wooldridge, M. (1995). Intelligent agents: theory and practice

---

## License

Internal research use only.

---

## Contact

For questions about this implementation:
- Author: Cheng-Ting Chen
- Institution: Technische Universität Darmstadt
