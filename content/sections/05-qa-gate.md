## QA Gate

**Concurrent QA + Skeptic for UI-visible changes.** When a diff matches QA trigger patterns (UI, frontend routes, visible behavior), spawn `qa-engineer` IN PARALLEL with the Skeptic in a single message (both background). Sign-off requires both to pass. This eliminates the sequential Skeptic-then-QA delay for UI changes and aligns with the parallel-by-default philosophy.

For non-UI changes, the post-Skeptic QA flow described below remains in effect: check trigger patterns after Skeptic sign-off and spawn QA only if matched.

**Pre-spawn trigger check:** Before spawning Workers, the conductor resolves the qa.md (`.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback) and checks whether the planned diff is likely to match any `## QA triggers` pattern. If yes, mark the unit for concurrent QA at review time. If the diff is unknown at planning time, defer the check to post-Worker (standard flow).

**When QA is skipped:**
- No qa.md exists at either resolver path (`.agentic/qa.md` or legacy `.claude/qa.md`)
- The resolved qa.md has no `## QA triggers` section
- No files in the reviewed diff match any trigger pattern
- The change is Low risk (direct action)

**QA gate flow (UI-visible - concurrent):**
1. Worker returns. Conductor checks trigger patterns against the diff.
2. If matched: spawn Skeptic AND `qa-engineer` in a single message (parallel, background). Both receive the diff and the unit's acceptance criteria.
3. Wait for both to return.
4. If both pass: unit is complete.
5. If Skeptic raises Critical/Major: enter standard Skeptic fix loop. QA re-runs after Skeptic sign-off is achieved.
6. If QA fails (Skeptic already signed off): spawn fix engineer, then re-run QA only.

**QA gate flow (non-UI - post-sign-off):**
1. Skeptic grants sign-off (minor fixes applied if any)
2. Conductor checks the resolved qa.md trigger patterns against the diff
3. If matched: spawn `qa-engineer` with the unit's acceptance criteria and the qa.md config
4. QA engineer opens the dev server in a browser, verifies functionality, returns pass/fail report
5. On PASS: unit is complete
6. On FAIL: spawn fix engineer for each bug, then re-run QA

**Phase breadcrumb:** `[phase: qa-review]`

### Re-route limits

**Re-route limits.** Within any loop (Skeptic re-route or QA re-route), the conductor applies a max of 3 fix passes before escalating to the human. This applies to loops inside `/implement-ticket` Phase 6 and 6b, and to any ad-hoc Skeptic loop the conductor runs outside that command. The conductor tracks re-route count in-context. When the cap is reached with open findings, the conductor does not spawn another Engineer - it surfaces the stall with the open findings list and waits for human direction.

**Convergence failure.** A convergence failure occurs when a Skeptic raises the same finding unchanged after the Engineer claimed to have addressed it. Convergence failures bypass the remaining iteration budget and escalate immediately. They indicate either a misunderstanding between the Engineer and the finding, or a design-level conflict that requires human arbitration. Within the persistence loop, one re-raise after a claimed fix is sufficient (overrides the 2-re-route rule in skeptic-protocol.md Section 5 - see that section for the override note).
