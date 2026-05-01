---
marp: true
theme: default
paginate: true
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    background: #faf8f3;
  }
  section.lead {
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
    background: #faf8f3;
    color: #1a1a1f;
  }
  section.lead h1 {
    font-size: 2.5em;
    margin-bottom: 0.2em;
    color: #224466;
  }
  section.lead p {
    font-size: 1.2em;
    opacity: 0.85;
  }
  section.highlight {
    background: #faf8f3;
  }
  .columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5em;
    margin-bottom: 0.8em;
  }
  .columns-3 {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 1em;
    margin-bottom: 0.8em;
  }
  .card {
    background: white;
    border-radius: 12px;
    padding: 1.2em;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    border-left: 4px solid #b5451f;
  }
  .stat {
    font-size: 2.5em;
    font-weight: bold;
    color: #b5451f;
  }
  .label {
    font-size: 0.9em;
    color: #666;
    margin-top: 0.2em;
  }
  .callout {
    background: #faf0e8;
    border-left: 4px solid #b5451f;
    padding: 0.8em 1.2em;
    border-radius: 0 8px 8px 0;
    margin: 0.4em 0 0.8em 0;
  }
  blockquote {
    border-left: 4px solid #b5451f;
    padding-left: 1em;
    color: #555;
    font-style: italic;
  }
  .numbered {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.5em 0.9em;
    align-items: baseline;
    margin: 0.3em 0 0.6em 0;
  }
  .numbered .n {
    font-weight: bold;
    color: #b5451f;
    font-size: 1.1em;
  }
---

<!-- _class: lead -->

# Planning Artifacts

Tiered Brief / Plan promotion gate

---

## The gap planning artifacts close

<style scoped>
  p { font-size: 0.9em; margin: 0.3em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.5em; }
  ul { font-size: 0.88em; }
  ul li { margin: 0.3em 0; }
</style>

Before planning artifacts, the methodology had three layers producing forward artifacts:

- **architect** - produces "what to build"
- **orchestration-planner** - produces "how to decompose it"
- **engineer** - implements the units

What was missing: a committed answer to "what problem are we solving and how will we know it is done?"

Without that commitment, multi-unit fan-out and cross-session resume suffered from drift - each engineer spawned against an informal interpretation of the original ticket rather than a locked problem statement, success criteria, and verification plan.

<div class="callout">
Planning artifacts add the missing layer: a gate that commits to the framing before the first engineer spawns and keeps that commitment alive through fan-out and resume.
</div>

---

## Where it sits in the flow

<style scoped>
  pre { font-size: 0.78em; background: #f0ede6; border-radius: 8px; padding: 0.8em 1.2em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.6em; }
</style>

```
Risk classified Elevated
  -> architect
  -> Skeptic on architect plan
  -> Open Questions resolved
  -> orchestration-planner
  -> [PROMOTION CHECK]  <-- new step
       0-1 Elevated units:   no artifact (current behavior)
       2-5 Elevated units:   Brief -> Skeptic on Brief
       6+ Elevated units:    Plan  -> Skeptic on Plan
       cross-track / multi-session: Plan (+ ADR if arch-decision-constraining)
  -> engineer(s) spawned with brief_path / plan_path in execution contract
```

<div class="callout">
The promotion check is downstream of the planner (unit count is known) and upstream of the first engineer spawn (no work has started). It is a gate, not a suggestion.
</div>

---

## Trigger table

<style scoped>
  table { font-size: 0.82em; width: 100%; border-collapse: collapse; margin-top: 0.4em; }
  th { background: #f0ede6; padding: 0.5em 0.8em; text-align: left; }
  td { padding: 0.45em 0.8em; border-bottom: 1px solid #e8e4da; vertical-align: top; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.6em; }
</style>

| Condition | Artifact required |
|---|---|
| 0-1 Elevated units (or planner skipped) | None - architect plan only |
| 2-5 Elevated units | Brief + architect plan |
| 6+ Elevated units OR cross-track OR multi-session | Plan (Brief + assembled artifacts + 3 coverage docs) |
| Cross-track OR architecture-decision-constraining | Plan + ADR |

**Unit counting rule:** only units whose risk is Elevated or above count. Trivial units in a mixed-risk plan contribute zero.

**"Cross-track" definition (mechanical):** a depth-1 directory under the repo root that has its own `AGENTS.md`. Nested `AGENTS.md` files (e.g. `helios/factory/AGENTS.md`) do not create new tracks.

<div class="callout">
All triggers are mechanical. Operator judgment is not a field. Evaluate after orchestration-planner returns.
</div>

---

## Brief template

<style scoped>
  pre { font-size: 0.78em; background: #f0ede6; border-radius: 8px; padding: 0.8em 1.2em; margin: 0.3em 0; }
  p { font-size: 0.88em; margin: 0.25em 0; }
</style>

Canonical path: `docs/planning/<slug>.md`. Must fit on one screen (~15-20 lines).

```markdown
# Brief: <feature name>

**Problem:**           <1-2 sentences. Behavior gap in user/system terms, not implementation terms.>

**Success criteria:**  <Bulleted, observable from outside. Max 4 bullets.>
- <criterion 1>
- <criterion 2>

**Non-goals:**         <What this explicitly does NOT do. Max 3 bullets.>
- <non-goal 1>

**Constraints:**       <Hard constraints only - contracts, perf budgets, compat targets, deadlines.>

**Verification:**      <Single non-skippable line. Tests, gates, qa.md trigger patterns,
                        and regression tests required by .agentic/findings.md that prove this is done.
                        "Cannot specify" is itself a planning gap and blocks Skeptic sign-off.>

**Linked artifacts:**  architect-plan: <path>; orchestration: <path or inline JSONL block>
```

---

## Brief field guidance

<style scoped>
  .card { font-size: 0.85em; line-height: 1.5; }
  ul li { margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

<div class="card">

- **Problem** - behavior gap, not solution. If you wrote "add X", restate as "users cannot Y".
- **Success criteria** - pass/fail testable from outside. Drives Skeptic completion review.
- **Non-goals** - written to defeat the most likely scope-creep direction.
- **Constraints** - list only what would change the architect's design if violated.
- **Verification** - non-skippable. Name the concrete tests, gates, qa.md trigger patterns, and regression tests required by the findings flywheel. If verification cannot be specified at planning time, that is a planning gap - the Brief is not Skeptic-eligible until verification is named.
- **Linked artifacts** - makes the Brief auditable against its own inputs.

</div>

<div class="callout">
<=20 lines total. If the Brief exceeds one screen, it is not a Brief - it is a mini-spec and should be reworked. The Brief is a commitment, not a design document.
</div>

---

## Plan-tier directory

<style scoped>
  pre { font-size: 0.82em; background: #f0ede6; border-radius: 8px; padding: 0.8em 1.2em; margin: 0.3em 0; }
  p { font-size: 0.88em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

```
docs/planning/<slug>/
  brief.md                  # Brief template (assembled)
  architect-plan.md         # architect's existing output, as-is (assembled)
  orchestration.jsonl       # orchestration-planner output, verbatim (assembled)
  risk-register.md          # <=10 lines, conductor-authored (coverage)
  rollback.md               # <=10 lines, conductor-authored (coverage)
  verification-gate.md      # see template, conductor-authored (coverage)
```

Most of the Plan is stapled artifacts. Only 3 short files are conductor-authored:

- `risk-register.md` - operational risk, not covered by the architect plan
- `rollback.md` - procedure to undo, not covered anywhere upstream
- `verification-gate.md` - trigger for rollback; owns the "how we know it failed" signal

<div class="callout">
If any of the three authored files exceeds 10 lines, the Plan is too large. Split into multiple Briefs.
</div>

---

## Verification gate

<style scoped>
  pre { font-size: 0.76em; background: #f0ede6; border-radius: 8px; padding: 0.8em 1.2em; margin: 0.3em 0; }
  p { font-size: 0.88em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

`verification-gate.md` template:

```markdown
# Verification Gate

**Tests that must pass:**
- Unit: <commands or "n/a">
- Integration: <commands or "n/a">
- E2E: <commands or "n/a">

**qa-engineer triggered?** <yes/no>. If yes, list qa.md trigger patterns and the units they apply to.

**Manual smoke check:** <single paragraph or "none">

**Rollback signal:** <how we know post-merge this needs revert - what alarm, metric, or user signal.
                      This hands off to rollback.md.>

**New regression tests required by findings flywheel?** <yes/no>. If yes, list .agentic/findings.md
                      entry IDs and the test files that will hold the regression.
```

<div class="callout">
<strong>Split of responsibility:</strong> verification-gate.md owns the trigger (the signal that says "something went wrong"). rollback.md owns the procedure (the steps to undo). They are complementary, not overlapping.
</div>

---

## Gate semantics

<style scoped>
  .columns { gap: 1.2em; }
  .card { font-size: 0.82em; line-height: 1.5; }
  ul li { margin: 0.3em 0; }
</style>

<div class="columns">
<div>

**Blocks engineer spawn:**

<div class="card" style="border-left-color: #c0392b;">

- Missing required artifact at any tier
- Brief or Plan has Skeptic findings open (Critical or Major)
- Open Questions section non-empty (same hard gate as architect plan)
- Verification gate field set to "cannot specify"

</div>
</div>
<div>

**Does NOT block:**

<div class="card" style="border-left-color: #2d5a3d;">

- Risk class = Elevated single-unit (no Brief required - architect plan is the artifact; current behavior preserved)
- Trivial units in any plan
- Low-risk work (no Brief at any threshold)

</div>
</div>
</div>

---

## Worker contract additions

<style scoped>
  pre { font-size: 0.8em; background: #f0ede6; border-radius: 8px; padding: 0.8em 1.2em; margin: 0.3em 0; }
  p { font-size: 0.88em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

Two new optional fields in the execution contract:

```
- outputs: ...
- budget: ...
- tool_scope: ...
- completion_conditions: ...
- output_paths: ...
- brief_path: docs/planning/<slug>.md        <-- new (Brief tier)
- plan_path:  docs/planning/<slug>/          <-- new (Plan tier)
```

When populated, the engineer:

1. Reads the Brief or Plan before starting any implementation.
2. Treats success criteria and verification gate as authoritative alongside the architect plan.
3. Returns `BLOCKED` on Brief-vs-architect-plan conflict (rather than guessing).

<div class="callout">
brief_path and plan_path are populated by the conductor at spawn time. Workers do not discover or locate these themselves.
</div>

---

## Mid-flight retroactive Brief

<style scoped>
  p { font-size: 0.9em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
  ul { font-size: 0.88em; }
  ul li { margin: 0.3em 0; }
</style>

A task can be promoted upward mid-work. It cannot be demoted.

When escalation fires (e.g., a 3-unit Brief-tier task is re-planned into 8 units):

- The in-flight engineer is allowed to return.
- Already-completed units are **not** retroactively re-reviewed.
- The retroactive Brief (or Plan) is authored **before** the next engineer spawn.
- The retroactive artifact governs all subsequent units.
- The Skeptic pass on the retroactive artifact runs to completion before the next worker spawns.
- `.agentic/loop-state.json` `promotion_tier` is updated to reflect the new tier.

<div class="callout">
"Retroactive" means the Brief was not written at the start because the shape wasn't yet known. It is not a failure mode - it is the correct protocol for tasks whose scope expands during execution.
</div>

---

## 3rd-resume auto-promotion

<style scoped>
  p { font-size: 0.9em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
  ul { font-size: 0.88em; }
  ul li { margin: 0.3em 0; }
</style>

Trigger: `.agentic/loop-state.json` records a third resume of a Brief-tier task.

When it fires, the conductor authors the missing Plan-tier artifacts before the next worker spawn:

- `risk-register.md`
- `rollback.md`
- `verification-gate.md`

The trigger is **mechanical** - tracked by resume-count in the loop-state file. It fires regardless of whether the operator notices the session span.

Rationale: anything that has survived three resume cycles is demonstrably multi-session work. The risk register and rollback procedure exist precisely because multi-session tasks have higher blast radius when they go wrong.

<div class="callout">
Auto-promotion is not a penalty. It is an acknowledgment that the task's actual scope exceeded the initial estimate, and the artifact set should match the real scope.
</div>

---

<!-- _class: lead -->

# Plan once. Resume often. Verify always.

github.com/Solara6/agentic-engineering
