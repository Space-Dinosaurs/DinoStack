---
marp: true
theme: default
paginate: true
style: |
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;600;700;800;900&family=Nunito+Sans:wght@400;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap');
  section {
    font-family: 'Nunito Sans', system-ui, sans-serif;
    background-color: #02050C;
    background-image:
      radial-gradient(800px 480px at 14% -10%, rgba(24,224,255,0.12), transparent 60%),
      radial-gradient(680px 420px at 100% 0%, rgba(176,107,255,0.10), transparent 58%),
      radial-gradient(720px 560px at 70% 115%, rgba(24,224,255,0.05), transparent 60%);
    color: #eaf1fb;
    color-scheme: dark;
  }
  h1, h2, h3, h4, h5, h6 {
    font-family: 'Orbitron', system-ui, sans-serif;
    color: #ffffff;
    letter-spacing: 0.01em;
  }
  h1 { text-shadow: 0 0 30px rgba(24,224,255,0.35); }
  h2 {
    color: #eaf1fb;
    text-shadow: 0 0 18px rgba(24,224,255,0.20);
    border-bottom: 1px solid rgba(255,255,255,0.12);
    padding-bottom: 0.18em;
  }
  strong { color: #ffffff; }
  a { color: #18E0FF; text-decoration: none; }
  section.lead {
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
    color: #eaf1fb;
  }
  section.lead h1 {
    font-size: 2.6em;
    margin-bottom: 0.2em;
    color: #ffffff;
    text-shadow: 0 0 38px rgba(24,224,255,0.45);
  }
  section.lead p {
    font-size: 1.2em;
    color: rgba(234,241,251,0.78);
  }
  section.highlight {
    background-color: #02050C;
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
    background: #0A1020;
    border: 1px solid rgba(255,255,255,0.10);
    border-left: 4px solid #18E0FF;
    border-radius: 12px;
    padding: 1.2em;
    box-shadow: 0 2px 14px rgba(0,0,0,0.45), 0 0 22px rgba(24,224,255,0.06);
    color: #eaf1fb;
  }
  .stat {
    font-size: 2.5em;
    font-weight: bold;
    color: #18E0FF;
    font-family: 'Orbitron', system-ui, sans-serif;
  }
  .label {
    font-size: 0.9em;
    color: #9bb0cc;
    margin-top: 0.2em;
  }
  .callout {
    background: rgba(24,224,255,0.06);
    border-left: 4px solid #18E0FF;
    padding: 0.8em 1.2em;
    border-radius: 0 8px 8px 0;
    margin: 0.4em 0 0.8em 0;
    color: #eaf1fb;
  }
  blockquote {
    border-left: 4px solid #18E0FF;
    padding-left: 1em;
    color: rgba(234,241,251,0.78);
    font-style: italic;
  }
  code {
    font-family: 'JetBrains Mono', monospace;
    background: rgba(255,255,255,0.06);
    color: #9be9ff;
    padding: 0.1em 0.35em;
    border-radius: 4px;
  }
  pre {
    background: #04070F;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 8px;
    color: #eaf1fb;
  }
  pre code {
    background: transparent;
    color: #eaf1fb;
    padding: 0;
  }
  table {
    border-collapse: collapse;
    background: transparent;
  }
  table tr {
    background: transparent;
  }
  table tr:nth-child(2n) {
    background: rgba(255,255,255,0.03);
  }
  th, td {
    border: 1px solid rgba(255,255,255,0.12);
    padding: 0.4em 0.8em;
  }
  th {
    background: rgba(255,255,255,0.05);
    color: #ffffff;
    font-family: 'Nunito Sans', system-ui, sans-serif;
  }
  td {
    color: #eaf1fb;
  }
  section::after {
    color: #6a7c97;
  }
  mark {
    background: rgba(233,181,33,0.22);
    color: #ffffff;
  }
  kbd {
    background: rgba(255,255,255,0.08);
    color: #eaf1fb;
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 4px;
  }
  hr {
    background-color: rgba(255,255,255,0.12);
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
    color: #18E0FF;
    font-size: 1.1em;
  }
---

<!-- _class: lead -->

# Planning Artifacts

Tiered Brief / Plan promotion gate

---

## The gap planning artifacts close

<style scoped>
  p { font-size: 0.85em; margin: 0.2em 0; }
  .callout { font-size: 0.84em; padding: 0.4em 1em; margin-top: 0.4em; }
  ul { font-size: 0.84em; }
  ul li { margin: 0.2em 0; }
</style>

Before planning artifacts, three forward-producing layers existed:

- **architect** - produces "what to build"
- **orchestration-planner** - produces "how to decompose it"
- **engineer** - implements the units

What was missing: a committed answer to "what problem are we solving and how will we know it is done?"

Without that commitment, multi-unit fan-out and cross-session resume drifted - each engineer spawned against an informal interpretation rather than a locked problem statement, success criteria, and verification plan.

Also missing: operator participation in framing. The Brief was conductor-synthesized, not operator-negotiated. The `/brief` command adds operator negotiation before the architect spawns.

<div class="callout">
Planning artifacts add the missing layer: a gate that commits to the framing before the first engineer spawns, keeping that commitment alive through fan-out and resume.
</div>

---

## Where it sits in the flow

<style scoped>
  pre { font-size: 0.78em; background: #04070F; border-radius: 8px; padding: 0.8em 1.2em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.6em; }
</style>

```
[PRIMARY] operator runs /brief -> dialogue -> operator-confirmed Brief committed
                                           -> architect (brief_path pre-populated)

[BACKSTOP] Risk classified Elevated (no /brief session)
  -> architect
  -> Skeptic on architect plan
  -> Open Questions resolved
  -> orchestration-planner
  -> [PROMOTION CHECK]
       0-1 Elevated units:   no artifact (current behavior)
       2-5 Elevated units:   Brief -> Skeptic on Brief (full framing review)
       6+ Elevated units:    Plan  -> Skeptic on Plan
       cross-track / multi-session: Plan (+ ADR if arch-decision-constraining)

Both paths -> engineer(s) spawned with brief_path / plan_path in execution contract
```

<div class="callout">
Two entry points: /brief (preferred for features still being framed) and the mechanical promotion gate (backstop for well-specified tickets). The promotion check is downstream of the planner (unit count is known) and upstream of the first engineer spawn (no work has started). It is a gate, not a suggestion.
</div>

---

## Two paths to a Brief

<style scoped>
  .columns { gap: 0.8em; margin-bottom: 0.4em; }
  .card { font-size: 0.76em; line-height: 1.35; padding: 0.7em 0.85em; }
  ul li { margin: 0.15em 0; }
  h4 { margin-top: 0; }
  .callout { font-size: 0.74em; padding: 0.3em 0.8em; margin-top: 0.3em; }
</style>

<div class="columns">
<div>

**Interactive `/brief` path (preferred)**

<div class="card" style="border-left-color: #3ad99a;">

- Operator has exploratory framing ("I want to build...")
- Conductor auto-triggers or operator invokes `/brief [topic]`
- Multi-turn dialogue: intent, gray areas, Q&A, draft, iterate
- Brief committed to conductor's branch BEFORE architect spawns (no worktree)
- `brief_source: operator` - Skeptic does completeness-only review

</div>
</div>
<div>

**Mechanical promotion path (backstop)**

<div class="card" style="border-left-color: #ffffff;">

- Work arrives as a well-specified ticket; no /brief session
- architect -> Skeptic -> planner -> promotion check
- Brief authored by conductor from planner output (2-5 units)
- `brief_source: conductor` - Skeptic does full framing review
- Retroactive Brief possible if unit count escalates mid-work

</div>
</div>
</div>

<div class="callout">
Interactive path is preferred for features still being framed. Mechanical path is the backstop for well-specified tickets. Both converge on the same artifact: <code>docs/planning/&lt;slug&gt;.md</code>.
</div>

---

## Trigger table

<style scoped>
  table { font-size: 0.82em; width: 100%; border-collapse: collapse; margin-top: 0.3em; }
  th { background: rgba(255,255,255,0.05); padding: 0.4em 0.7em; text-align: left; }
  td { padding: 0.35em 0.7em; border-bottom: 1px solid rgba(255,255,255,0.12); vertical-align: top; }
  p { font-size: 0.84em; margin: 0.3em 0; }
  .callout { font-size: 0.78em; padding: 0.35em 0.9em; margin-top: 0.4em; }
</style>

| Condition | Artifact required |
|---|---|
| 0-1 Elevated units (or planner skipped) | None - architect plan only |
| 2-5 Elevated units | Brief + architect plan |
| 6+ Elevated units OR cross-track OR multi-session | Plan (Brief + assembled artifacts + 3 coverage docs) |
| Cross-track OR architecture-decision-constraining | Plan + ADR |

**Unit counting rule:** only units whose risk is Elevated or above count. Trivial units contribute zero.

**"Cross-track" (mechanical):** a depth-1 directory under the repo root with its own `AGENTS.md`. Nested `AGENTS.md` files (e.g. `helios/factory/AGENTS.md`) do not create new tracks.

<div class="callout">
All triggers are mechanical. Operator judgment is not a field. Evaluate after orchestration-planner returns.
</div>

---

## Cross-artifact alignment check

<style scoped>
  ul { font-size: 0.86em; }
  ul li { margin: 0.2em 0; }
  p { font-size: 0.86em; margin: 0.2em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

After orchestration-planner returns and before Skeptic-on-Brief runs, the conductor maps every Brief success criterion to at least one unit's `acceptance_criteria` in the planner JSONL:

- **Covered** - criterion maps to at least one unit. Proceed to Skeptic-on-Brief.
- **Uncovered** - criterion has no corresponding unit. Blocks Skeptic-on-Brief until resolved.

Resolution paths for uncovered criteria: re-spawn planner with the gap called out, or surface a descope/expand decision to the operator.

When no unit has non-empty `acceptance_criteria`, emit `[phase: cross-artifact-check-skipped | no criteria to map]` and proceed.

<div class="callout">
Mechanical and conductor-direct - no agent spawn needed. Complements the adversarial Skeptic-on-Brief; does not replace it. An uncovered criterion is a planning gap: the Brief commits to an outcome no unit is scoped to deliver.
</div>

---

## Brief template (fields 1-5)

<style scoped>
  pre { font-size: 0.67em; background: #04070F; border-radius: 8px; padding: 0.5em 0.9em; margin: 0.2em 0; line-height: 1.28; }
  p { font-size: 0.82em; margin: 0.15em 0; }
</style>

Canonical path: `docs/planning/<slug>.md`. Must fit on one screen (~15-20 lines).

```markdown
# Brief: <feature name>
**Problem:**           <1-2 sentences. Behavior gap in user/system terms, not implementation.>
**Success criteria:**  <Bulleted, observable from outside. Max 4 bullets.>
- <criterion 1>
- <criterion 2>
**Non-goals:**         <What this explicitly does NOT do. Max 3 bullets.>
- <non-goal 1>
**Constraints:**       <Hard constraints only - contracts, perf budgets, compat targets, deadlines.>
**Verification:**      <Non-skippable. Tests, gates, qa.md trigger patterns, and regression
                        tests from .agentic/findings.md. "Cannot specify" blocks sign-off.>
```

---

## Brief template (cont.) — fields 6-8

<style scoped>
  pre { font-size: 0.72em; background: #04070F; border-radius: 8px; padding: 0.6em 1em; margin: 0.25em 0; line-height: 1.35; }
  p { font-size: 0.84em; margin: 0.2em 0; }
</style>

```markdown
**Outcome rubric:**    <Pass/fail lines (max 6), each tagged
                        verification_type: deterministic | judgment.
                        Required for Elevated; absence is a Critical Skeptic finding.>
- [ ] <e.g. all existing tests pass with zero regressions> [deterministic]
- [ ] <e.g. the new flow is coherent from an operator perspective> [judgment]

**QA criteria:**       <Required for Elevated. YAML block: qa_skip (one of 5 valid
                        enums or null), qa_skip_rationale (if qa_skip != null),
                        viewport, scenarios[] (method in {browser, api,
                        runtime-required, visual_conformance, accessibility,
                        perceptual_diff, motion}), manual_smoke.
                        Absence on Elevated is a Critical Skeptic finding.>

**Linked artifacts:**  architect-plan: <path>; orchestration: <path or inline JSONL>
```

---

## Brief field guidance

<style scoped>
  .card { font-size: 0.75em; line-height: 1.35; padding: 0.65em 0.85em; }
  ul li { margin: 0.1em 0; }
  .callout { font-size: 0.72em; padding: 0.28em 0.8em; margin-top: 0.3em; }
</style>

<div class="card">

- **Problem** - behavior gap, not solution. If you wrote "add X", restate as "users cannot Y".
- **Success criteria** - pass/fail testable from outside. Drives Skeptic completion review.
- **Non-goals** - written to defeat the most likely scope-creep direction.
- **Constraints** - only what would change the architect's design if violated.
- **Verification** - non-skippable. Name the concrete tests, gates, qa.md trigger patterns, and regression tests from the findings flywheel. If verification cannot be specified, that is a planning gap - Brief is not Skeptic-eligible until it is named.
- **Outcome rubric** - distinct from Verification. Verification names gate commands; the Outcome rubric is the operator's semantic definition of done. Deterministic lines name a gate; judgment lines are graded adversarially by the Skeptic.
- **QA criteria** - required for Elevated. YAML block with `qa_skip` enum (or null) and `scenarios[]`. Absence on Elevated is a Critical Skeptic finding.
- **Linked artifacts** - makes the Brief auditable against its own inputs.

</div>

<div class="callout">
&lt;=20 lines total. If the Brief exceeds one screen, it is a mini-spec - rework it. The Brief is a commitment, not a design document.
</div>

---

## Plan-tier directory

<style scoped>
  pre { font-size: 0.82em; background: #04070F; border-radius: 8px; padding: 0.8em 1.2em; margin: 0.3em 0; }
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
  pre { font-size: 0.66em; background: #04070F; border-radius: 8px; padding: 0.45em 0.85em; margin: 0.15em 0; line-height: 1.25; }
  p { font-size: 0.82em; margin: 0.15em 0; }
  .callout { font-size: 0.74em; padding: 0.28em 0.85em; margin-top: 0.3em; }
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

<div class="card" style="border-left-color: #ff5d73;">

- Missing required artifact at any tier
- Brief or Plan has Skeptic findings open (Critical or Major)
- Open Questions section non-empty (same hard gate as architect plan; a non-empty Deferred defaults section does NOT trigger this gate)
- Verification gate field set to "cannot specify"

</div>
</div>
<div>

**Does NOT block:**

<div class="card" style="border-left-color: #3ad99a;">

- Risk class = Elevated single-unit (no Brief required - architect plan is the artifact; current behavior preserved)
- Trivial units in any plan
- Low-risk work (no Brief at any threshold)

</div>
</div>
</div>

---

## Worker contract additions

<style scoped>
  pre { font-size: 0.72em; background: #04070F; border-radius: 8px; padding: 0.5em 0.9em; margin: 0.2em 0; line-height: 1.3; }
  p { font-size: 0.84em; margin: 0.2em 0; }
  .callout { font-size: 0.76em; padding: 0.35em 0.9em; margin-top: 0.35em; }
  ol { font-size: 0.84em; margin: 0.2em 0; }
  ol li { margin: 0.15em 0; }
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
  p { font-size: 0.86em; margin: 0.2em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 0.9em; margin-top: 0.4em; }
  ul { font-size: 0.84em; }
  ul li { margin: 0.2em 0; }
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
"Retroactive" means the Brief was not written at the start because the shape wasn't yet known. Not a failure mode - it is the correct protocol for tasks whose scope expands during execution.
</div>

---

## 3rd-resume auto-promotion

<style scoped>
  p { font-size: 0.86em; margin: 0.2em 0; }
  .callout { font-size: 0.78em; padding: 0.35em 0.9em; margin-top: 0.35em; }
  ul { font-size: 0.84em; }
  ul li { margin: 0.15em 0; }
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

github.com/Space-Dinosaurs/DinoStack
