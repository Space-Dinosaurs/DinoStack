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
               content/references/planning-artifacts.md (trigger table,
               gate-semantics authoring sequences, and Brief/Plan templates
               that this section's body defers to for authoring detail).

Downstream consumers: METHODOLOGY.md §Delegation (Worker preamble references
                      brief_path / plan_path); METHODOLOGY.md §Task
                      Decomposition (cites this section for Plan-tier
                      pre-worker authoring); METHODOLOGY.md §Cross-session
                      loop resume (records brief_path / plan_path /
                      promotion_tier); METHODOLOGY.md §Risk Classification
                      (Declaration format optionally includes Brief / Plan);
                      METHODOLOGY.md §Protocol Details (cross-link entry).

Failure modes: Prose; does not execute. Drift between this section and the
               cross-references above is a Major Skeptic finding (stale
               manifest or stale cross-reference). Operator failure mode this
               section exists to prevent: multi-unit Elevated work proceeding
               without a committed problem statement, success criteria,
               non-goals, and verification plan.

Performance: Standard.
-->

## Planning Artifacts

The promotion gate that sits between orchestration-planner output and the first engineer spawn: 0-1 Elevated units -> no Brief; 2-5 -> Brief; 6+ or cross-track or multi-session -> Plan. See `content/references/planning-artifacts.md` for the trigger table, track definition, gate-semantics authoring sequences, Brief template, Plan-tier directory layout, promotion mechanics, and `qa_default_skip` definition.

**What blocks engineer spawn:**
- Missing required artifact at any tier.
- Brief or Plan Skeptic finds Critical or Major findings: same loop semantics as architect-plan Skeptic (re-route limits apply, max 3 fix passes).
- Brief or Plan Open Questions section non-empty: same hard gate as architect Open Questions (METHODOLOGY.md §Delegation).
- Verification gate field set to "cannot specify": blocks Skeptic sign-off until resolved.
- Cross-artifact alignment check has an unresolved UNCOVERED success criterion: blocks the Skeptic-on-Brief from running until resolved.

**What does not block:**
- Risk class = Elevated single-unit: no Brief required. The architect plan is the artifact.
- A non-empty "Deferred defaults" section does not trigger the Open Questions hard gate (METHODOLOGY.md §Delegation).
