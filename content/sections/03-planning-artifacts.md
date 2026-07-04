<!--
Purpose: Defines the tiered planning-artifact protocol (Brief and Plan) that
         sits between orchestration-planner output and the first engineer
         spawn. Mechanically promotes multi-unit Elevated work to a written
         Brief or Plan with a verification gate before any worker is spawned.

Public API: This file is methodology prose, not code. It is consumed by the
            conductor at the promotion gate (post orchestration-planner,
            pre engineer spawn), by the Skeptic when reviewing Brief or
            Plan artifacts, and by /brief (content/commands/brief.md) which
            produces the Brief artifact via interactive dialogue before the
            promotion gate runs.

Upstream deps: METHODOLOGY.md §Delegation (architect plan + Skeptic gate, Open
               Questions hard gate, Worker preamble execution contract);
               METHODOLOGY.md §Risk Classification (Trivial/Elevated taxonomy,
               Declaration format); METHODOLOGY.md §Task Decomposition
               (orchestration-planner output as input to the promotion check);
               METHODOLOGY.md §Cross-session loop resume (loop-state.json
               schema for brief_path / plan_path / promotion_tier);
               content/rules/module-manifest.md (manifest header contract);
               content/agents/architect.md, content/agents/orchestration-planner.md
               (the acceptance_criteria array field from orchestration-planner
               JSONL output is consumed by the cross-artifact alignment step).

Downstream consumers: METHODOLOGY.md §Delegation (Worker preamble references
                      brief_path / plan_path); METHODOLOGY.md §Task
                      Decomposition (cites this section for Plan-tier
                      pre-worker authoring); METHODOLOGY.md §Cross-session
                      loop resume (records brief_path / plan_path /
                      promotion_tier); METHODOLOGY.md §Risk Classification
                      (Declaration format optionally includes Brief / Plan);
                      METHODOLOGY.md §Protocol Details (cross-link entry);
                      /implement-ticket command (Gate semantics step ordering
                      is referenced by Phase 3b cross-artifact alignment check).

Failure modes: Prose; does not execute. Drift between this section and the
               cross-references above is a Major Skeptic finding (stale
               manifest or stale cross-reference). Stale step numbering in
               Gate semantics causes misrouted cross-references across phases;
               update inline step references whenever steps are renumbered.
               Operator failure mode this section exists to prevent: multi-unit
               Elevated work proceeding without a committed problem statement,
               success criteria, non-goals, and verification plan.

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

The Brief is authored once the planner returns a unit count, so "do we need a Brief?" is a mechanical check. Full rationale (comprehension-artifact reasoning, what the Skeptic-on-Brief asks): `references/planning-artifacts.md` §Ordering rationale.

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

### Gate semantics

**Authoring sequence (Brief tier / Plan tier / ADR tier):** the full numbered steps - including the pre-existing-Brief check, cross-artifact alignment check position, and Skeptic-on-Brief variants - are in `references/planning-artifacts.md` §Authoring sequence (Brief and Plan tiers). The gate rules below (What blocks / What does not block) remain authoritative here.

**What blocks engineer spawn:**
- Missing required artifact at any tier.
- Brief or Plan Skeptic finds Critical or Major findings: same loop semantics as architect-plan Skeptic (re-route limits apply, max 3 fix passes).
- Brief or Plan Open Questions section non-empty: same hard gate as architect Open Questions (METHODOLOGY.md §Delegation). This section explicitly extends the existing rule rather than restating it. A non-empty "Deferred defaults" section does not trigger this gate.
- Verification gate field set to "cannot specify": blocks Skeptic sign-off until resolved.
- Cross-artifact alignment check has an unresolved UNCOVERED success criterion: blocks the Skeptic-on-Brief from running until resolved.

**What does not block:**
- Risk class = Elevated single-unit: no Brief required. The architect plan is the artifact. This preserves current behavior for the dominant Elevated case (single-file behavioral edits, single new file, single-config changes).

For the Brief template, Plan-tier directory layout, verification-gate template, promotion mechanics (mid-flight escalation, auto-promotion at 3rd resume), product-intent layer rules, and the canonical `qa_default_skip` definition, see `content/references/planning-artifacts.md`. Outcome rubric: operator-confirmed pass/fail lines, each tagged `verification_type: deterministic | judgment`; required for Elevated; full schema and field guidance in `content/references/planning-artifacts.md`.
