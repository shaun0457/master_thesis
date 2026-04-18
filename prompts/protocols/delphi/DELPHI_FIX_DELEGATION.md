# 🚨 DELPHI CRITICAL FIX: Explicit Delegation Execution 🚨

**Problem:** Supervisor uses `target="Supervisor"` in every turn → agents never respond
**Impact:** 90% supervisor turns, only 1/3 agents participate, early termination
**Root Cause:** Missing explicit delegation sequence in phase opening

---

## CRITICAL ADDITION: Insert After Line 315 (Section B3.2)

### **B3.2.1 R1 Delegation Execution (MANDATORY SEQUENCE)**

**When opening R1 proposals phase, you MUST explicitly delegate to ALL THREE workers in sequence.**

#### Turn 0: Open Phase + Delegate to First Worker (DE)

```json
{
  "intent": "open_phase",
  "message": "Opening R1 proposals phase. Requirements: e_min=2 governed citations per key claim, deadline=turn+6. @DE: Please create your proposal analyzing data quality and feature engineering for this task.",
  "action": {
    "target": "DE",
    "task_id": "delphi_r1_de_proposal",
    "due": "next_turn",
    "rationale": "DE provides data foundation; all proposals need data context"
  },
  "blackboard_refs": ["bb://task/global_goal.json", "bb://plans/current.json"]
}
```

#### Turn 1: Delegate to Second Worker (DS)

**CRITICAL: Do NOT wait for DE to finish. Delegate to DS immediately.**

```json
{
  "intent": "moderate",
  "message": "@DS: Please create your proposal independently, focusing on statistical analysis and modeling approach for this task. You may start while DE works on data foundation.",
  "action": {
    "target": "DS",
    "task_id": "delphi_r1_ds_proposal",
    "due": "next_turn",
    "rationale": "DS provides analytical perspective; can work independently"
  },
  "blackboard_refs": ["bb://task/global_goal.json"]
}
```

#### Turn 2: Delegate to Third Worker (ME)

**CRITICAL: Do NOT wait. Delegate to ME immediately.**

```json
{
  "intent": "moderate",
  "message": "@ME: Please create your proposal independently, focusing on domain constraints and operational validation for this task. Work in parallel with DE and DS.",
  "action": {
    "target": "ME",
    "task_id": "delphi_r1_me_proposal",
    "due": "next_turn",
    "rationale": "ME provides domain perspective; independent of data/stats work"
  },
  "blackboard_refs": ["bb://task/global_goal.json"]
}
```

#### Turn 3+: Accept Proposals as They Arrive

**When workers submit proposals, validate and accept:**

```json
{
  "intent": "moderate",
  "message": "Received proposal from DE: validating evidence density... OK (3 governed refs). Accepted.",
  "action": {
    "target": "Supervisor",
    "task_id": "delphi_r1_tracking"
  },
  "blackboard_refs": ["bb://delphi/rounds/r1_proposals/DE_P1.json"]
}
```

**Continue accepting from DS and ME as they arrive.**

---

### **B3.2.2 Retry Mechanism (If Agent Doesn't Respond)**

**If an agent doesn't submit within 2 turns of delegation:**

#### Turn 3 (if DE hasn't responded since Turn 0):

```json
{
  "intent": "request_evidence",
  "message": "@DE: Reminder - your R1 proposal is due. Please submit with >=2 governed citations per key claim, or request clarification if needed.",
  "action": {
    "target": "DE",
    "task_id": "delphi_r1_de_reminder",
    "rationale": "DE hasn't responded within 2 turns, sending reminder"
  },
  "blackboard_refs": ["bb://plans/current.json"]
}
```

**If agent still doesn't respond after reminder (Turn 5):**

```json
{
  "intent": "recovery",
  "message": "DE proposal timeout. Proceeding with DS and ME proposals only (minimum quorum 2/3 satisfied).",
  "action": {
    "target": "Supervisor",
    "task_id": "delphi_r1_quorum_check",
    "rationale": "Agent non-response; proceeding with available proposals"
  },
  "blackboard_refs": ["bb://plans/current.json"]
}
```

---

### **B3.2.3 Minimum Quorum Rule**

**R1 Proposals:**
- Ideal: 3/3 workers submit proposals
- Minimum: 2/3 workers (can proceed with 2 proposals)
- Failure: <2 proposals → recovery, re-open R1 with extended deadline

**R2 Critiques:**
- Each available proposal must receive >=2 critiques
- Can proceed if >=2 workers participate in critique phase

---

### **B3.3 R2 Delegation Execution (Critique Phase)**

#### Turn 8: Open R2 + Delegate First Critique

```json
{
  "intent": "open_phase",
  "message": "Opening R2 critiques phase. Requirements: k_min=2 critiques per reviewer, lambda_crossref=1, deadline=turn+4. @ME: Please critique DS proposal (bb://delphi/rounds/r1_proposals/DS_P1.json).",
  "action": {
    "target": "ME",
    "task_id": "delphi_r2_me_critique_ds",
    "rationale": "ME provides domain validation of DS statistical claims"
  },
  "blackboard_refs": ["bb://delphi/rounds/r1_proposals/DS_P1.json", "bb://plans/current.json"]
}
```

#### Turn 9: Delegate Second Critique

```json
{
  "intent": "moderate",
  "message": "@DS: Please critique ME proposal (bb://delphi/rounds/r1_proposals/ME_P1.json). Focus on statistical rigor of domain claims.",
  "action": {
    "target": "DS",
    "task_id": "delphi_r2_ds_critique_me",
    "rationale": "DS validates statistical aspects of ME domain reasoning"
  },
  "blackboard_refs": ["bb://delphi/rounds/r1_proposals/ME_P1.json"]
}
```

#### Turn 10: Delegate Third Critique

```json
{
  "intent": "moderate",
  "message": "@DE: Please critique both DS and ME proposals regarding data quality and feature validity.",
  "action": {
    "target": "DE",
    "task_id": "delphi_r2_de_critique",
    "rationale": "DE validates data assumptions in both proposals"
  },
  "blackboard_refs": ["bb://delphi/rounds/r1_proposals/DS_P1.json", "bb://delphi/rounds/r1_proposals/ME_P1.json"]
}
```

---

## ANTI-PATTERNS TO AVOID

### ❌ WRONG: Supervisor Targeting Self

```json
{
  "intent": "moderate",
  "message": "Moderating R1 phase...",
  "action": {"target": "Supervisor"}  // ❌ Agents never get work!
}
```

### ❌ WRONG: No Explicit Target

```json
{
  "intent": "open_phase",
  "message": "Opening R1, agents please submit proposals.",
  "action": {"target": null}  // ❌ No one knows who should act!
}
```

### ❌ WRONG: Waiting for Sequential Completion

```
Turn 0: Delegate to DE
Turn 1: Wait for DE...
Turn 2: Wait for DE...
Turn 3: DE finishes, then delegate to DS  // ❌ Too slow!
```

---

## CORRECT PATTERNS

### ✅ CORRECT: Parallel Delegation

```
Turn 0: open_phase + target="DE"
Turn 1: moderate + target="DS"    (DE still working)
Turn 2: moderate + target="ME"    (DE and DS still working)
Turn 3-6: Accept proposals as they arrive
```

### ✅ CORRECT: Explicit @mentions

```
"message": "@DE: Please create your proposal..."
```

### ✅ CORRECT: Clear Rationale

```
"action": {
  "target": "DE",
  "rationale": "DE provides data foundation; all proposals need data context"
}
```

---

## IMPLEMENTATION CHECKLIST

When opening any Delphi phase:

- [ ] **Turn N:** Open phase + delegate to first worker
- [ ] **Turn N+1:** Delegate to second worker (don't wait)
- [ ] **Turn N+2:** Delegate to third worker (don't wait)
- [ ] **Turn N+3 onwards:** Accept submissions, validate, track quorum
- [ ] **Turn N+5:** Send reminders to non-responders
- [ ] **Turn N+7:** Check minimum quorum (2/3), proceed or recover

---

## EXPECTED IMPACT

### Before Fix:
- Supervisor: 90% of turns
- Agents: 10% (only 1/3 participating)
- Intent: 80% "moderate" with no actual moderation
- Outcome: Early termination, no proposals

### After Fix:
- Supervisor: 40-50% of turns (phase opening, validation, synthesis)
- Agents: 50-60% (all 3 participating)
- Intent: 20-30% "moderate" (actual moderation), 40-50% "work" (agents)
- Outcome: All 3 proposals generated, 6+ critiques, successful synthesis

---

**Status:** Ready for integration into supervisor.md
**Priority:** P0 - CRITICAL (blocks all Delphi runs)
**Testing:** Smoke test required before full batch

**Created:** 2025-10-31
**Author:** Claude (Delphi Fix)
