# Neutral Protocol (Baseline / Control Condition)

**Protocol Type:** Baseline (No special collaboration rules)
**Purpose:** Control condition for X-MAS experiments
**Router Enforcement:** None
**Prompt Modifications:** None

---

## Overview

The **Neutral** protocol represents the **baseline/control condition** in X-MAS experiments. It applies **no special collaboration rules** beyond basic role capabilities and anti-contamination policies.

This protocol serves as the **comparison baseline** to measure the effects of structured collaboration protocols (PTOW, Debate, Delphi).

---

## Protocol Characteristics

### What Neutral DOES

✅ **Uses base role cards:**
- `prompts/roles/supervisor.md`
- `prompts/roles/data_engineer.md`
- `prompts/roles/data_scientist.md`
- `prompts/roles/machine_expert.md`

✅ **Enforces basic policies:**
- Anti-contamination (no external URLs)
- Evidence-first (cite sources)
- Run isolation (blackboard namespaces)

✅ **Logs all events:**
- `run.turn.v2` events
- `router.event.v2` events
- Blackboard read/write events

### What Neutral DOES NOT Do

❌ **No protocol-specific rules:**
- No P2P handoff restrictions (unlike PTOW)
- No turn structure requirements (unlike Debate)
- No reflection rounds (unlike Delphi)

❌ **No intent restrictions:**
- Agents can use any valid intent
- No enforced debate/consensus flow

❌ **No coordination mandates:**
- Agents decide own next_owner freely
- No required Supervisor approval loops

---

## Router Behavior

**In `mas/core/router.py`:**

```python
def enforce_protocol(self, msg: dict, result: dict) -> None:
    if self.protocol == "planner_to_worker":
        self._enforce_ptow(msg, result)
    elif self.protocol == "debate":
        self._enforce_debate(msg, result)
    elif self.protocol == "delphi":
        self._enforce_delphi(msg, result)
    # neutral: no special rules
```

Router **only performs:**
1. Header validation
2. Anti-contamination check
3. Event logging

---

## Expected Behavioral Signals

### Process Metrics (Predicted)

| Metric | Expected Range | Rationale |
|--------|---------------|-----------|
| **Centralization (C)** | Low-Medium | Supervisor coordinates but no P2P ban |
| **Handoff Entropy (H)** | High | Free communication flow |
| **Ownership Gini** | Medium | Natural task distribution |
| **Reuse rate** | Variable | No mandated knowledge sharing |
| **P2P violations** | N/A | No P2P restrictions |

### Comparison with Other Protocols

| Protocol | C | H | P2P Ban | Structure |
|----------|---|---|---------|-----------|
| **Neutral** | ↓ | ↑ | ❌ | Free-form |
| **PTOW** | ↑↑ | ↓ | ✅ | Hub-spoke |
| **Debate** | ↔ | ↑ | ❌ | Round-based |
| **Delphi** | ↔ | ↔ | ❌ | Iterative |

---

## Usage in Experiments

### When to Use Neutral

✅ **As baseline/control:**
```bash
python cli/run_experiment.py --query queries/Q1.md --protocol neutral --seeds 42
```

✅ **For protocol comparison:**
- Run Neutral first to establish baseline
- Compare other protocols against Neutral

✅ **For debugging:**
- No protocol restrictions simplify troubleshooting
- Natural agent behavior is easier to understand

### Research Questions Alignment

**RQ1: How do protocols affect team structure?**
- Neutral provides the **unstructured baseline**
- Effect size = (Protocol X) - (Neutral)

**RQ2: How do structure/flow affect outcomes?**
- Neutral shows **natural correlation** without intervention

**RQ3: Are protocol effects mediated?**
- Neutral = no protocol manipulation
- Other protocols = mediation pathways active

---

## Implementation Notes

### No Protocol-Specific Prompts

Unlike other protocols, Neutral **does not have** agent-specific prompt files in this directory. This is intentional:

- ✅ Agents use **base role cards** only
- ✅ No protocol-specific instructions layered on top
- ✅ Simplest possible configuration

**Prompt loading logic:**
```python
# agents/base.py
def _load_role_card(self) -> str:
    role_file = f"prompts/roles/{self.role}.md"
    # No protocol-specific overlay for "neutral"
    return open(role_file).read()
```

### Why No Prompts Directory?

This design choice reflects the conceptual nature of Neutral:
- **It's not a protocol** in the sense of "structured collaboration"
- **It's the absence of protocol** - pure role-based interaction
- Having an empty directory would be misleading

---

## Validation Checklist

When running Neutral protocol experiments:

- [ ] No protocol violations logged (since no rules to violate)
- [ ] All valid intents accepted by Router
- [ ] Free P2P handoffs between DE ↔ DS, DE ↔ ME, DS ↔ ME
- [ ] Supervisor acts as coordinator but not gate-keeper
- [ ] Natural turn flow without enforced structure

---

## References

- **X-MAS Framework:** `docs/X-MAS_framework.md`
- **Router Implementation:** `mas/core/router.py` (line 161: "neutral: no special rules")
- **Base Role Cards:** `prompts/roles/*.md`

---

**End of Neutral Protocol Documentation**

**Status:** Baseline / Control Condition
**Enforcement:** None (by design)
**Purpose:** Enable measurement of protocol effects via comparison
