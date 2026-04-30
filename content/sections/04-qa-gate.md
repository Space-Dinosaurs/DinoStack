## QA Gate

**Post-Skeptic QA for UI-visible changes.** After Skeptic sign-off on any Elevated unit, check whether the project has a qa.md (resolved via `.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback) with a `## QA triggers` section containing file patterns. If the reviewed diff includes files matching any trigger pattern, spawn `qa-engineer` before declaring the unit complete. QA failure blocks completion - the conductor spawns a fix engineer, then re-runs QA.

**When QA is skipped:**
- No qa.md exists at either resolver path (`.agentic/qa.md` or legacy `.claude/qa.md`)
- The resolved qa.md has no `## QA triggers` section
- No files in the reviewed diff match any trigger pattern
- The change is Low risk (direct action)

**QA gate flow:**
1. Skeptic grants sign-off (minor fixes applied if any)
2. Conductor checks the resolved qa.md trigger patterns against the diff (resolver: `.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback)
3. If matched: spawn `qa-engineer` with the unit's acceptance criteria and the qa.md config
4. QA engineer opens the dev server in a browser, verifies functionality, returns pass/fail report
5. On PASS: unit is complete
6. On FAIL: spawn fix engineer for each bug, then re-run QA

**Phase breadcrumb:** `[phase: qa-review]`

### Re-route limits

**Re-route limits.** Within any loop (Skeptic re-route or QA re-route), the conductor applies a max of 3 fix passes before escalating to the human. This applies to loops inside `/implement-ticket` Phase 6 and 6b, and to any ad-hoc Skeptic loop the conductor runs outside that command. The conductor tracks re-route count in-context. When the cap is reached with open findings, the conductor does not spawn another Engineer - it surfaces the stall with the open findings list and waits for human direction.

**Convergence failure.** A convergence failure occurs when a Skeptic raises the same finding unchanged after the Engineer claimed to have addressed it. Convergence failures bypass the remaining iteration budget and escalate immediately. They indicate either a misunderstanding between the Engineer and the finding, or a design-level conflict that requires human arbitration. Within the persistence loop, one re-raise after a claimed fix is sufficient (overrides the 2-re-route rule in skeptic-protocol.md Section 5 - see that section for the override note).
