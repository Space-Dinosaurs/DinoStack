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

The Brief is authored after the planner has returned a unit count, so "do we need a Brief?" is a mechanical check, not a guess. The architect plan and planner output are inputs the conductor uses to draft the Brief - the Brief is not asking the conductor to predict what will exist; it is asking the conductor to commit to the framing now that the shape is known. This mechanical restatement is a comprehension-artifact step: the act of restating the architect and planner output forces the conductor to demonstrate it understood both. The Skeptic reviewing the Brief asks a different question than the Skeptic that reviewed the architect plan - not "is the design sound?" but "did the conductor actually understand what was produced upstream, and is the verification real?" This catches implicit architect assumptions that do not survive being stated plainly, planner units that do not compose coherently when described together, and verification criteria that seemed obvious until someone had to write them down.

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

**Authoring sequence (Brief tier):**
1. Architect runs (existing behavior).
2. Skeptic on architect plan.
3. Open Questions on architect plan resolved.
4. Orchestration-planner runs.
5. Promotion check against the trigger table.
6. If 2-5 Elevated-or-above units: check whether `.agentic/brief-session.json` exists with `status: complete` and `brief_source: operator` AND `brief_path` points to an existing file. If both conditions hold, the Brief is pre-existing and operator-confirmed - skip conductor authoring and go directly to step 8. If not, conductor authors Brief at `docs/planning/<slug>.md` using architect output, planner output, and the original ticket as inputs.
7. **Cross-artifact alignment check (conductor-direct).** When a Brief exists and the orchestration-planner returned at least one unit with a non-empty `acceptance_criteria` array, the conductor mechanically maps every Brief success criterion to at least one unit's `acceptance_criteria`. Any UNCOVERED criterion is resolved (re-spawn planner with the gap called out, or surface a descope/expand decision to the operator) before the Skeptic-on-Brief runs. When no unit has non-empty `acceptance_criteria`, emit `[phase: cross-artifact-check-skipped | no criteria to map]` and proceed. Full procedure in `/implement-ticket` Phase 3b "Cross-artifact alignment check". This mechanical check complements — does not replace — the adversarial Skeptic-on-Brief.
8. Spawn Skeptic on the Brief. When the Brief is pre-existing and operator-confirmed (`brief_source: operator`), use the operator-confirmed Skeptic variant (completeness-only review - see `content/commands/brief.md` Section 6 for the exact brief text). When the Brief was conductor-authored, use the standard "Document synthesis, architecture, and planning" adversarial brief; the verification field is part of the Skeptic's review surface in both cases. The `QA criteria` field is also part of the Skeptic's review surface: for Elevated tickets, the Skeptic must validate that the field is present, that `qa_skip` is one of the 5 valid enum values or null, that `qa_skip_rationale` is populated when `qa_skip != null`, and that `scenarios[]` is non-empty when `qa_skip == null`. Absence on Elevated is a Critical finding; an invalid `qa_skip` enum is a Major finding.
9. On Brief sign-off (and after any Open Questions in the Brief are resolved per the Open Questions hard gate in METHODOLOGY.md §Delegation), engineer(s) spawn with `brief_path` populated in their execution contract.

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
- Cross-artifact alignment check has an unresolved UNCOVERED success criterion: blocks the Skeptic-on-Brief from running until resolved.

**What does not block:**
- Risk class = Elevated single-unit: no Brief required. The architect plan is the artifact. This preserves current behavior for the dominant Elevated case (single-file behavioral edits, single new file, single-config changes).

For the Brief template, Plan-tier directory layout, verification-gate template, promotion mechanics (mid-flight escalation, auto-promotion at 3rd resume), product-intent layer rules, and the canonical `qa_default_skip` definition, see `content/references/planning-artifacts.md`. Outcome rubric: operator-confirmed pass/fail lines, each tagged `verification_type: deterministic | judgment`; required for Elevated; full schema and field guidance in `content/references/planning-artifacts.md`.
