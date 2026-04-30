<!--
Purpose: Defines the tiered planning-artifact protocol (Brief and Plan) that
         sits between orchestration-planner output and the first engineer
         spawn. Mechanically promotes multi-unit Elevated work to a written
         Brief or Plan with a verification gate before any worker is spawned.

Public API: This file is methodology prose, not code. It is consumed by the
            conductor at the promotion gate (post orchestration-planner,
            pre engineer spawn) and by the Skeptic when reviewing Brief or
            Plan artifacts.

Upstream deps: METHODOLOGY.md §Delegation (architect plan + Skeptic gate, Open
               Questions hard gate, Worker preamble execution contract);
               METHODOLOGY.md §Risk Classification (Trivial/Elevated taxonomy,
               Declaration format); METHODOLOGY.md §Task Decomposition
               (orchestration-planner output as input to the promotion check);
               METHODOLOGY.md §Cross-session loop resume (loop-state.json
               schema for brief_path / plan_path / promotion_tier);
               content/rules/module-manifest.md (manifest header contract);
               content/agents/architect.md, content/agents/orchestration-planner.md.

Downstream consumers: METHODOLOGY.md §Delegation (Worker preamble references
                      brief_path / plan_path); METHODOLOGY.md §Task
                      Decomposition (cites this section for Plan-tier
                      pre-worker authoring); METHODOLOGY.md §Cross-session
                      loop resume (records brief_path / plan_path /
                      promotion_tier); METHODOLOGY.md §Risk Classification
                      (Declaration format optionally includes Brief / Plan);
                      METHODOLOGY.md §Protocol Details (cross-link entry);
                      /implement-ticket command (follow-on unit, out of scope
                      here).

Failure modes: Prose; does not execute. Drift between this section and the
               cross-references above is a Major Skeptic finding (stale
               manifest or stale cross-reference). Operator failure mode
               this section exists to prevent: multi-unit Elevated work
               proceeding without a committed problem statement, success
               criteria, non-goals, and verification plan.

Performance: Standard.
-->

## Planning Artifacts

The promotion gate that sits between orchestration-planner output and the first engineer spawn. The architect produces "what to build", the orchestration-planner produces "how to decompose it"; this section produces "what problem are we actually solving and how will we know it is solved" - a commitment that survives multi-unit fan-out and cross-session resume.

### Ordering

The promotion check is downstream of architect+planner, upstream of engineer:

```
Risk classified Elevated
  -> architect (existing behavior; investigator-before-architect rules apply)
  -> Skeptic on architect plan (METHODOLOGY.md §Delegation)
  -> Open Questions on architect plan resolved (METHODOLOGY.md §Delegation)
  -> orchestration-planner (METHODOLOGY.md §Task Decomposition)
  -> [PROMOTION CHECK] count Elevated-or-above units, check track span, check session span
       -> 0-1 Elevated units: no Brief required (current behavior)
       -> 2-5 Elevated units: author Brief, Skeptic the Brief, then engineer
       -> 6+ Elevated units OR cross-track OR multi-session OR auto-promote-at-3rd-resume: assemble Plan, Skeptic the Plan, then engineer
  -> engineer(s) spawned with brief_path / plan_path in execution contract
```

The Brief is authored after the planner has returned a unit count, so "do we need a Brief?" is a mechanical check, not a guess. The architect plan and planner output are inputs the conductor uses to draft the Brief - the Brief is not asking the conductor to predict what will exist; it is asking the conductor to commit to the framing now that the shape is known.

### Trigger table

All triggers are mechanical. Operator judgment is not a field. Triggers are evaluated after orchestration-planner returns.

| Condition | Artifact required |
|---|---|
| Risk = Trivial or Low | None |
| Risk = Elevated AND orchestration-planner returns 0-1 Elevated-or-above units (or planner skipped per the existing single-unit exception) | None (architect plan only - current behavior) |
| Risk = Elevated AND orchestration-planner returns 2-5 Elevated-or-above units | Brief + architect plan |
| Risk = Elevated AND orchestration-planner returns 6+ Elevated-or-above units | Plan (Brief + architect + orchestration JSONL + risk register + rollback + verification gate) |
| Any unit's `output_paths` spans 2+ tracks (see "Track" definition below) | Plan |
| Work spans 2+ sessions (declared at planning time, OR auto-promoted when `.agentic/loop-state.json` resumes a Brief-tier task into a third session) | Plan |
| Cross-track OR triggers an "Architecture decision constraining future choices" risk signal | Plan + ADR |

**Unit counting rule.** Only units whose own risk classification is Elevated or above count toward the 2-5 / 6+ thresholds. Trivial units in a mixed-risk plan do not count - they are routed per the standard Trivial conductor rule and contribute zero to promotion.

**"Track" definition (mechanical).** A track is a depth-1 directory under the repo root that contains its own `AGENTS.md` file (per the conventions in `content/rules/conventions.md`). Nested `AGENTS.md` files (e.g. `helios/factory/AGENTS.md`) do not create new tracks - they are sub-context within their parent track.

- Worked example A: a repo with `agentic-engineering/AGENTS.md`, `helios/AGENTS.md`, `agentic-factory/AGENTS.md`, `models/AGENTS.md` at depth 1. A unit touching `helios/factory/foo.ts` is in the `helios` track. A change touching both `helios/...` and `agentic-engineering/...` is cross-track and triggers Plan + ADR.
- Worked example B: a change touching `helios/factory/foo.ts` and `helios/ui/bar.tsx` is single-track (`helios`); the nested `factory/AGENTS.md` does not split the track.

**Other notes:**
- Unit count comes from the orchestration-planner's JSONL output, counted by `unit_slug` entries with risk >= Elevated.
- Track span is computed by mapping each `output_paths` entry to its depth-1 ancestor and checking for `AGENTS.md` at that depth.
- Session span is initially declared, then auto-promoted by the resume hook when the threshold is hit (see Promotion mechanics below).
- A task can be promoted upward mid-work. It cannot be demoted.

### Brief template

**Canonical path:** `docs/planning/<slug>.md` (slug = kebab-case feature name, prefixed with priority tag if the project uses one, e.g. `p2-foo.md`).

**Template (must fit on one screen; ~15-20 lines):**

```markdown
# Brief: <feature name>

**Problem:** <1-2 sentences. Behavior gap in user/system terms, not implementation terms.>

**Success criteria:** <Bulleted, observable from outside. Max 4 bullets.>
- <criterion 1>
- <criterion 2>

**Non-goals:** <What this explicitly does NOT do. Max 3 bullets. Write "none plausible" if none.>
- <non-goal 1>

**Constraints:** <Hard constraints only - existing contracts, perf budgets, compat targets, deadlines. Not preferences.>

**Verification:** <Single non-skippable line. The test(s), gate(s), qa.md trigger pattern(s), and any regression test mandated by `.agentic/findings.md` that prove this is done. "Cannot specify" is itself a planning gap and blocks Skeptic sign-off.>

**Linked artifacts:** architect-plan: <path>; orchestration: <path or inline JSONL block>
```

**Field guidance (one line each):**
- Problem: behavior gap, not solution. If you wrote "add X", restate as "users cannot Y".
- Success criteria: pass/fail testable from outside. Drives Skeptic completion review.
- Non-goals: written to defeat the most likely scope-creep direction.
- Constraints: list only what would change the architect's design if violated.
- Verification: non-skippable. Name the concrete tests, gates, qa.md trigger patterns, and regression tests required by the findings flywheel. If verification cannot be specified at planning time, that is itself a planning gap and must be flagged before the promotion gate passes - the Brief is not Skeptic-eligible until verification is named.
- Linked artifacts: makes the Brief auditable against its own inputs.

### Plan-tier directory

The Plan is primarily assembled from existing artifacts (architect plan, planner JSONL, Brief), with three short conductor-authored coverage documents. The "assembly" framing prevents the Plan from becoming a long-form design rewrite.

A "Plan" is a directory:

```
docs/planning/<slug>/
  brief.md                  # Brief template above (assembled)
  architect-plan.md         # architect's existing output, as-is (assembled)
  orchestration.jsonl       # orchestration-planner output, verbatim (assembled)
  risk-register.md          # <=10 lines, conductor-authored (coverage)
  rollback.md               # <=10 lines, conductor-authored (coverage)
  verification-gate.md      # see template below, conductor-authored (coverage)
```

**`verification-gate.md` owns the trigger (the signal that says "verification failed, time to roll back"); `rollback.md` owns the procedure (the steps to actually undo). They are complementary, not overlapping.**

**ADR carve-out:** for ADR-required work (cross-track or "Architecture decision constraining future choices"), add `adr-NNN.md` using the project's existing ADR convention. The Plan does not redefine ADR format.

**Coverage exception to "assembly":** risk register, rollback, and verification gate are conductor-authored because they exist nowhere upstream - the architect plan covers implementation, the planner covers structure, neither covers operational risk or verification. These three files are short by design (<=10 lines each plus the verification template); if any one exceeds the budget, the Plan is too large and should be split into multiple Briefs.

### Verification gate template

`verification-gate.md`:

```markdown
# Verification Gate

**Tests that must pass:**
- Unit: <commands or "n/a">
- Integration: <commands or "n/a">
- E2E: <commands or "n/a">

**qa-engineer triggered?** <yes/no>. If yes, list the qa.md trigger patterns that fire and the units they apply to.

**Manual smoke check:** <single paragraph or "none">

**Rollback signal:** <how we will know post-merge that this needs to be reverted - what alarm, what user signal, what metric. This is the trigger that hands off to `rollback.md`.>

**New regression tests required by findings flywheel?** <yes/no>. If yes, list the `.agentic/findings.md` entry IDs and the test files that will hold the regression.
```

The verification gate is non-skippable. **If verification cannot be specified at planning time, that is itself a planning gap and must be flagged before the promotion gate passes.** Any "cannot specify" entry blocks Skeptic sign-off; the operator resolves the gap by re-running architect, tightening the Brief, or descoping until verification is knowable.

### Gate semantics

**Authoring sequence (Brief tier):**
1. Architect runs (existing behavior).
2. Skeptic on architect plan.
3. Open Questions on architect plan resolved.
4. Orchestration-planner runs.
5. Promotion check against the trigger table.
6. If 2-5 Elevated-or-above units: conductor authors Brief at `docs/planning/<slug>.md` using architect output, planner output, and the original ticket as inputs.
7. Spawn Skeptic on the Brief using the "Document synthesis, architecture, and planning" adversarial brief. The verification field is part of the Skeptic's review surface.
8. On Brief sign-off (and after any Open Questions in the Brief are resolved per the Open Questions hard gate in METHODOLOGY.md §Delegation), engineer(s) spawn with `brief_path` populated in their execution contract.

**Authoring sequence (Plan tier):** identical to Brief tier through step 6, plus:
- Conductor authors `risk-register.md`, `rollback.md`, and `verification-gate.md`, and assembles the Plan directory.
- A second Skeptic pass reviews the assembled Plan as a whole (not the components individually - they were already reviewed). Scope: integration coherence, missing rollback for any high-blast-radius unit, risk register completeness, and verification gate completeness (no "cannot specify" entries).
- Workers spawn only after assembled-Plan sign-off, with both `brief_path` and `plan_path` in their execution contract.

**ADR tier:** ADR is authored alongside the Brief, not after, because the architectural decision shapes the Brief's constraints. ADR review follows the project's existing ADR process; if none exists, the ADR goes through the same "Document synthesis, architecture, and planning" Skeptic review as the Brief.

**What blocks engineer spawn:**
- Missing required artifact at any tier.
- Brief or Plan Skeptic finds Critical or Major findings: same loop semantics as architect-plan Skeptic (re-route limits apply, max 3 fix passes).
- Brief or Plan Open Questions section non-empty: same hard gate as architect Open Questions (METHODOLOGY.md §Delegation). This section explicitly extends the existing rule rather than restating it.
- Verification gate field set to "cannot specify": blocks Skeptic sign-off until resolved.

**What does not block:**
- Risk class = Elevated single-unit: no Brief required. The architect plan is the artifact. This preserves current behavior for the dominant Elevated case (single-file behavioral edits, single new file, single-config changes).

### Promotion mechanics

**Mid-flight escalation.** A task can be promoted upward mid-work (e.g., a 3-unit Brief-tier task that the architect re-plans into 8 units gets re-classified as Plan-tier; an Elevated-single task whose planner re-decomposition produces 3+ Elevated units gets promoted to Brief-tier). When this fires:

- The in-flight engineer is allowed to return.
- Already-completed units are not retroactively re-reviewed.
- The retroactive Brief (or Plan) is authored before the next engineer spawn and governs all subsequent units.
- The Skeptic pass on the retroactive artifact runs to completion before the next worker spawns.
- `.agentic/loop-state.json` `promotion_tier` is updated to reflect the new tier (see METHODOLOGY.md §Cross-session loop resume).

**Auto-promotion at 3rd resume.** When `.agentic/loop-state.json` records a third resume of a Brief-tier task, the conductor authors the missing Plan-tier artifacts (risk register, rollback, verification gate) before the next worker spawn. The trigger is mechanical - resume-count tracked in the loop-state file - and fires regardless of whether the operator notices the session span.

**Promotion is upward only.** A task cannot be demoted. Once a Brief or Plan exists, subsequent workers continue to read it.
