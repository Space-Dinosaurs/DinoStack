## QA Gate

**Concurrent QA + Skeptic for UI-visible changes.** When a unit's `qa_criteria` indicates QA fires (Brief/architect plan present, `qa_skip == null`, scenarios non-empty), spawn `qa-engineer` IN PARALLEL with the Skeptic in a single message (both background). Sign-off requires both to pass. This eliminates the sequential Skeptic-then-QA delay for UI-visible changes and aligns with the parallel-by-default philosophy.

For changes whose `qa_criteria` does not match the concurrent path (or where the diff is unknown at planning time), the post-Skeptic QA flow described below remains in effect.

**Pre-spawn trigger check:** Before spawning Workers, the conductor inspects the unit's `qa_criteria` (from the Brief or, if no Brief, from the architect plan). If `qa_criteria` is present AND `qa_skip == null` AND `scenarios[]` is non-empty, mark the unit for concurrent QA at review time. The architect's `qa_criteria` is the authoritative trigger - the qa.md trigger patterns are a SUPPLEMENTAL match-set: when both `qa_criteria` and a qa.md trigger match exist, qa-engineer receives both inputs (the scenarios as the test plan, and any matched qa.md project-knowledge entries as supplemental context). qa.md triggers can SUPPLEMENT but CANNOT override `qa_skip != null`. If `qa_criteria` is absent at planning time and the diff is unknown, defer the check to post-Worker (standard flow).

**When QA is skipped:**
- The change is Trivial risk (direct action; existing carve-out preserved).
- `qa_skip` is one of the 5 valid enum values: `pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only`. The rationale is logged in the Brief / architect plan; QA does not fire.

Note: a project having no qa.md is NOT a reason to skip QA. The default is QA fires for every Elevated unit unless the architect explicitly committed to one of the 5 `qa_skip` enum values. qa.md is supplemental project-knowledge that qa-engineer reads for context (dev server config, project quirks); its absence does not change the QA gate decision.

**QA gate flow (UI-visible - concurrent):**
1. Worker returns. Conductor confirms `qa_criteria` indicates QA fires for this unit (`qa_skip == null` and scenarios non-empty).
2. If yes: spawn Skeptic AND `qa-engineer` in a single message (parallel, background). Both receive the diff and the unit's `qa_criteria`. qa-engineer auto-detects qa.md trigger matches at spawn time and pulls supplemental context from any matched entries.
3. Wait for both to return.
4. If both pass: unit is complete.
5. If Skeptic raises Critical/Major: enter standard Skeptic fix loop. QA re-runs after Skeptic sign-off is achieved.
6. If QA fails (Skeptic already signed off): spawn fix engineer, then re-run QA only.

**QA gate flow (non-UI - post-sign-off):**
1. Skeptic grants sign-off (minor fixes applied if any)
2. Conductor inspects the unit's `qa_criteria` (from Brief or architect plan).
3. If `qa_criteria` is present AND `qa_skip == null` AND scenarios non-empty: spawn `qa-engineer` with the unit's `qa_criteria` and ticket context. qa-engineer auto-detects qa.md trigger matches at spawn time and pulls supplemental context from any matched entries.
4. QA engineer opens the dev server in a browser (or invokes API/runtime checks per the scenarios' `method`), verifies functionality, returns pass/fail report.
5. On PASS: unit is complete.
6. On FAIL: spawn fix engineer for each bug, then re-run QA.

**Phase breadcrumb:** `[phase: qa-review]`

### Re-route limits

**Re-route limits.** Within any loop (Skeptic re-route or QA re-route), the conductor applies a max of 3 fix passes before escalating to the human. This applies to loops inside `/implement-ticket` Phase 6 and 6b, and to any ad-hoc Skeptic loop the conductor runs outside that command. The conductor tracks re-route count in-context. When the cap is reached with open findings, the conductor does not spawn another Engineer - it surfaces the stall with the open findings list and waits for human direction.

**Convergence failure.** A convergence failure occurs when a Skeptic raises the same finding unchanged after the Engineer claimed to have addressed it. Convergence failures bypass the remaining iteration budget and escalate immediately. They indicate either a misunderstanding between the Engineer and the finding, or a design-level conflict that requires human arbitration. Within the persistence loop, one re-raise after a claimed fix is sufficient (overrides the 2-re-route rule in skeptic-protocol.md Section 5 - see that section for the override note).
