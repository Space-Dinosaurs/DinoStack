<!-- corpora: minimal medium full -->
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
