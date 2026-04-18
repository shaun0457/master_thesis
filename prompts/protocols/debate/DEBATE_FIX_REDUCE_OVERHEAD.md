# Debate Protocol Fix: Reduce Supervisor Overhead

**Problem:** Supervisor accepts/rejects every single thesis and critique → 76% supervisor turns
**Solution:** Batch validation at round transitions, let agents debate directly

---

## Key Changes

### 1. Remove Per-Message Accept/Reject (Lines 143-232)

**OLD BEHAVIOR (causing overhead):**
```
Turn 1: Supervisor opens round → target="DE"
Turn 2: DE submits thesis
Turn 3: Supervisor: accept_thesis for DE → target="DS"  ← Overhead!
Turn 4: DS submits thesis
Turn 5: Supervisor: accept_thesis for DS → target="ME"  ← Overhead!
```

**NEW BEHAVIOR:**
```
Turn 1: Supervisor opens round → target="DE"
Turn 2: DE submits thesis to blackboard (no supervisor intervention)
Turn 3: DS submits thesis to blackboard (no supervisor intervention)
Turn 4: ME submits thesis to blackboard (no supervisor intervention)
Turn 5: Supervisor: close_round (batch validates all 3) → start R2
```

---

### 2. Replace Section [B3] with Streamlined Rules

**Add after Line 110:**

```markdown
### B3.1 Round 1 Workflow (Streamlined)

**Supervisor actions:**
1. **Turn 1:** `open_round` + delegate to first agent
2. **Turns 2-N:** Agents submit theses directly (no supervisor mediation)
3. **Turn N+1:** `close_round` when 3 theses received, batch validate evidence

**Agent actions (no supervisor gate-keeping):**
- Submit thesis directly to `bb://debate/round_1/t_<id>.json`
- Include required fields: evidence_refs, assumptions, limits
- Cite governed sources only

**Supervisor validation (at round close only):**
- Check: All 3 theses have >=2 governed evidence_refs?
- Check: No external URLs or contamination?
- If validation fails: `recovery` + request fixes
- If validation passes: `close_round` + open R2

**Delegation pattern:**
Turn 1: open_round → target="DE"
Turn 2: DE submits (supervisor: no action)
Turn 3: DS submits (supervisor: no action)
Turn 4: ME submits (supervisor: no action)
Turn 5: close_round → start R2 → target="ME" (first critic)
```

---

### 3. Replace Round 2 Workflow

**Add after B3.1:**

```markdown
### B3.2 Round 2 Workflow (Streamlined)

**Supervisor actions:**
1. **Turn N:** `open_round` (R2) + delegate to first critic
2. **Turns N+1 onwards:** Agents submit critiques directly
3. **Turn M:** `close_round` when >=1 critique per thesis

**Agent actions (direct critique posting):**
- Critique any thesis from R1
- Post to `bb://debate/round_2/c_<id>.json`
- Include: target_thesis, critique_type, evidence_refs

**Cross-critique allowed:**
- ME can critique DS thesis directly (no supervisor mediation)
- DS can counter-critique ME's critique directly
- Increases handoff entropy H (X-MAS signal)

**Delegation pattern:**
Turn 6: open_round (R2) → target="ME"
Turn 7: ME critiques DS thesis (supervisor: no action)
Turn 8: DS counter-critiques ME (supervisor: no action, direct exchange!)
Turn 9: DE critiques ME thesis (supervisor: no action)
Turn 10: close_round → synthesize
```

---

### 4. Update Example Turn Sequence (Lines 172-252)

**REPLACE with streamlined examples:**

```markdown
### Example Turn Sequence (Streamlined)

**Turn 1 - Open R1:**
```json
{
  "intent": "open_round",
  "message": "Open Debate Round 1 (Thesis): DE/DS/ME please submit theses with >=2 governed evidence_refs each. No supervisor mediation required.",
  "action": {"target": "DE", "task_id": "debate_r1_all"},
  "blackboard_refs": ["bb://task/global_goal"]
}
```

**Turn 2-4 - Agents work (no supervisor turns!):**
- DE writes thesis to bb://debate/round_1/t_01.json
- DS writes thesis to bb://debate/round_1/t_02.json
- ME writes thesis to bb://debate/round_1/t_03.json

**Turn 5 - Batch validation + close:**
```json
{
  "intent": "close_round",
  "message": "Close Round 1: 3 theses received. Batch validation: all have >=2 evidence_refs ✓. Opening Round 2 for critiques.",
  "action": {"target": "ME", "task_id": "debate_r2_first_critique"},
  "blackboard_refs": ["bb://debate/round_1/"]
}
```

**Turn 6-9 - Agents critique directly:**
- ME critiques DS thesis → c_01.json
- DS counter-critiques ME → c_02.json
- DE critiques both → c_03.json, c_04.json
(All without supervisor mediation!)

**Turn 10 - Synthesis:**
```json
{
  "intent": "synthesize",
  "message": "Synthesis: DS thesis t_02 scores highest (E=0.90, Support=0.60, Refute=0.10).",
  "action": {"target": "Supervisor", "task_id": "debate_final"},
  "blackboard_refs": ["bb://debate/synthesis/s_01.json"]
}
```
```

---

## Expected Impact

### Before:
- Supervisor: 76% of turns (accept_thesis × 3, accept_critique × 6+)
- Agents: 24% (8% each)
- Work intent: 24%

### After:
- Supervisor: 30-40% (open_round, close_round, synthesize only)
- Agents: 60-70% (actual thesis/critique work)
- Work intent: 50-60%

---

## Implementation

1. **Backup current:** `cp supervisor.md supervisor_v3.0_backup.md`
2. **Apply patches:** Integrate above sections into [B3]
3. **Update intents:** Remove individual accept_thesis/reject_thesis from common use
4. **Test:** Smoke test with 1 run

---

**Status:** Ready for integration
**Priority:** P1 - High (reduces overhead significantly)
**Created:** 2025-10-31
