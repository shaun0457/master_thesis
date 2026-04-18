# Planner→Worker Fix: Stop Infinite Planning Loop

**Problem:** "DL1 — One step per turn" with no stop → 96% supervisor, 92% "plan" intent, infinite loop
**Solution:** Limit planning turns, force delegation, require worker acknowledgment

---

## Key Changes

### 1. Add Planning Limit (Insert After Line 119)

**REPLACE Line 119-120:**

```markdown
### B3.1 Delegation Laws (P-Control-2)

* **DL1 — Maximum 3 planning turns:** Issue at most 3 `plan_step` actions. After 3 plans, you MUST delegate execution to a worker.

* **DL1.1 — Planning counter:** Track planning turns internally:
  - Turn 1: plan_step #1 (allowed)
  - Turn 2: plan_step #2 (allowed)
  - Turn 3: plan_step #3 (allowed, FINAL)
  - Turn 4: MUST use `delegate_subtask` to a worker (DE/DS/ME)
  - Turn 5+: Only coordination actions (review_accept, review_reject, delegate_subtask)

* **DL1.2 — Forced delegation trigger:**
  If turn >=4 and no worker has been delegated to yet → MUST delegate immediately.
  Format:
  ```json
  {
    "intent": "delegate_subtask",
    "message": "Delegating execution of plan steps 1-3 to [worker]. Please execute and report results.",
    "action": {"target": "DE|DS|ME", "task_id": "execute_plan_<id>"},
    "blackboard_refs": ["bb://plans/p1.json", "bb://plans/p2.json", "bb://plans/p3.json"]
  }
  ```

* **DL1.3 — No self-delegation:**
  After turn 3, `action.target` MUST NOT be "Supervisor" (except for synthesis at end).
```

---

### 2. Add Worker Acknowledgment Requirement (After DL5)

**ADD NEW RULE:**

```markdown
* **DL6 — Worker acknowledgment required:**
  After delegating to a worker, you MUST wait for worker response within 2 turns.

  **Turn 4:** Delegate to DE → target="DE"
  **Turn 5:** DE responds with work output OR acknowledges task received
  **Turn 6:** If DE doesn't respond → send reminder OR re-delegate to different worker

  **Example delegation:**
  ```json
  {
    "intent": "delegate_subtask",
    "message": "@DE: Execute plan step: prepare dataset with columns [A,B,C], N>500, missing_rate<5%. Report to bb://datasets/de/result.json within 2 turns.",
    "action": {"target": "DE", "task_id": "ptow_execute_data_prep"},
    "blackboard_refs": ["bb://plans/p1.json"]
  }
  ```

  **Example acknowledgment check:**
  ```json
  // Turn 6: If no DE response by turn 5
  {
    "intent": "request_evidence",
    "message": "@DE: Reminder - data prep task is due. Please respond with status or request clarification.",
    "action": {"target": "DE", "task_id": "ptow_reminder"},
    "blackboard_refs": ["bb://plans/p1.json"]
  }
  ```
```

---

### 3. Replace Planning Examples (Lines 194-262)

**ADD CORRECTED WORKFLOW:**

```markdown
### Correct Planner→Worker Workflow

**Turn 1: Plan Step 1**
```json
{
  "intent": "plan",
  "message": "Plan step 1: Identify required data columns and quality thresholds.",
  "action": {"target": "Supervisor", "task_id": "ptow_plan_1"},
  "blackboard_refs": ["bb://task/global_goal.json"]
}
```

**Turn 2: Plan Step 2**
```json
{
  "intent": "plan",
  "message": "Plan step 2: Define statistical analysis method and validation criteria.",
  "action": {"target": "Supervisor", "task_id": "ptow_plan_2"},
  "blackboard_refs": ["bb://plans/p1.json"]
}
```

**Turn 3: Plan Step 3 (FINAL PLAN)**
```json
{
  "intent": "plan",
  "message": "Plan step 3 (FINAL): Define domain validation rules and acceptance tests.",
  "action": {"target": "Supervisor", "task_id": "ptow_plan_3"},
  "blackboard_refs": ["bb://plans/p2.json"]
}
```

**Turn 4: FORCED DELEGATION (no more planning allowed!)**
```json
{
  "intent": "delegate_subtask",
  "message": "@DE: Execute plan steps 1-3. Prepare dataset per specifications in bb://plans/. Report results within 2 turns.",
  "action": {
    "target": "DE",
    "task_id": "ptow_execute_all",
    "owner": "DE",
    "next_owner": "Supervisor",
    "rationale": "Reached 3-plan limit, must delegate execution to worker"
  },
  "blackboard_refs": ["bb://plans/p1.json", "bb://plans/p2.json", "bb://plans/p3.json"]
}
```

**Turn 5: DE WORKS (no supervisor turn!)**
- DE executes data preparation
- DE writes results to bb://datasets/de/result.json

**Turn 6: Supervisor Reviews**
```json
{
  "intent": "review_accept",
  "message": "Reviewed DE output: dataset quality satisfactory (N=612, missing_rate=3%). Proceeding to analysis phase.",
  "action": {"target": "DS", "task_id": "ptow_analyze", "owner": "DS", "next_owner": "Supervisor"},
  "blackboard_refs": ["bb://datasets/de/result.json"]
}
```

**Turn 7: DS WORKS**
- DS performs statistical analysis

**Turn 8: Supervisor Reviews DS Output**
```json
{
  "intent": "review_accept",
  "message": "Reviewed DS analysis: results validate plan assumptions. Delegating domain validation to ME.",
  "action": {"target": "ME", "task_id": "ptow_validate", "owner": "ME", "next_owner": "Supervisor"},
  "blackboard_refs": ["bb://analysis/ds/result.json"]
}
```

**Turn 9: ME WORKS**
- ME validates from domain perspective

**Turn 10: Final Synthesis**
```json
{
  "intent": "review_accept",
  "message": "All plan steps executed and validated. Task complete.",
  "action": {"target": "Supervisor", "task_id": "ptow_complete"},
  "blackboard_refs": ["bb://domain/me/validation.json"]
}
```
```

---

### 4. Add Anti-Pattern Examples

**ADD TO [B11]:**

```markdown
### ❌ Anti-Pattern: Infinite Planning

```json
// Turn 1:
{"intent": "plan", "action": {"target": "Supervisor"}}  // OK (count=1)

// Turn 2:
{"intent": "plan", "action": {"target": "Supervisor"}}  // OK (count=2)

// Turn 3:
{"intent": "plan", "action": {"target": "Supervisor"}}  // OK (count=3, FINAL)

// Turn 4:
{"intent": "plan", "action": {"target": "Supervisor"}}  // ❌ VIOLATION! Must delegate now!

// Turn 5-25:
{"intent": "plan", "action": {"target": "Supervisor"}}  // ❌ Stuck in loop!
```

### ✅ Correct: Forced Delegation

```json
// Turn 1-3: Planning (allowed)
{"intent": "plan", "action": {"target": "Supervisor"}}

// Turn 4: MUST delegate (no choice)
{"intent": "delegate_subtask", "action": {"target": "DE"}}  // ✓ Correct!

// Turn 5+: Workers execute
{"intent": "work", "action": {"target": "Supervisor"}}  // DE/DS/ME working

// Turn 10+: Supervisor reviews
{"intent": "review_accept", "action": {"target": "Supervisor"}}  // ✓ OK
```
```

---

## Expected Impact

### Before:
- Supervisor: 96% of turns
- Workers: 4% (only 1 worker turn)
- Plan intent: 92%
- Work intent: 0%
- Output: Malformed JSON messages

### After:
- Supervisor: 50-60% (planning + coordination)
- Workers: 40-50% (actual execution)
- Plan intent: 20-30% (turns 1-3 only)
- Work intent: 40-50%
- Output: Valid deliverables

---

## Validation Rules for CI/Router

```yaml
# Add to protocol validation
PTOW_PLAN_LIMIT:
  max_consecutive_plans: 3
  violation: "EXCESSIVE_PLANNING"
  action: "Force delegation or mark as failed"

PTOW_DELEGATION_REQUIRED:
  if_turn: ">= 4"
  and_no_worker_delegated: true
  then: "VIOLATION: MISSING_DELEGATION"

PTOW_SELF_TARGETING:
  if_turn: ">= 4"
  and_target: "Supervisor"
  and_intent: "plan"
  then: "VIOLATION: SELF_TARGETING_AFTER_LIMIT"
```

---

## Implementation

1. **Backup:** `cp supervisor.md supervisor_v2.1_backup.md`
2. **Apply changes:** Integrate DL1, DL1.1, DL1.2, DL1.3, DL6
3. **Update examples:** Replace lines 194-262 with correct workflow
4. **Test:** Smoke test with max_turns=30

---

**Status:** Ready for integration
**Priority:** P0 - CRITICAL (protocol currently non-functional)
**Created:** 2025-10-31
