## QA Gate

**Concurrent QA + Skeptic for UI-visible changes.** When a unit's `qa_criteria` indicates QA fires (Brief/architect plan present, `qa_skip == null`, scenarios non-empty), spawn `qa-engineer` IN PARALLEL with the Skeptic in a single message (both background). Sign-off requires both to pass. This eliminates the sequential Skeptic-then-QA delay for UI-visible changes and aligns with the parallel-by-default philosophy.

For changes whose `qa_criteria` does not match the concurrent path (or where the diff is unknown at planning time), the post-Skeptic QA flow described below remains in effect.

**Pre-spawn trigger check:** Before spawning Workers, the conductor inspects the unit's `qa_criteria` (from the Brief or, if no Brief, from the architect plan). If `qa_criteria` is present AND `qa_skip == null` AND `scenarios[]` is non-empty, mark the unit for concurrent QA at review time. The architect's `qa_criteria` is the authoritative trigger - the qa.md trigger patterns are a SUPPLEMENTAL match-set: when both `qa_criteria` and a qa.md trigger match exist, qa-engineer receives both inputs (the scenarios as the test plan, and any matched qa.md project-knowledge entries as supplemental context). qa.md triggers can SUPPLEMENT but CANNOT override `qa_skip != null`. If `qa_criteria` is absent at planning time and the diff is unknown, defer the check to post-Worker (standard flow).

**When QA is skipped:**
- The change is Trivial risk (direct action; existing carve-out preserved).
- `qa_skip` is one of the 5 valid enum values: `pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only`. The rationale is logged in the Brief / architect plan; QA does not fire.

Note: a project having no qa.md is NOT a reason to skip QA. The default is QA fires for every Elevated unit unless the architect explicitly committed to one of the 5 `qa_skip` enum values. qa.md is supplemental project-knowledge that qa-engineer reads for context (dev server config, project quirks); its absence does not change the QA gate decision. The `qa_default_skip` key in `.agentic/config.json` is a reserved, documented-but-inert schema key (canonical definition in §Planning Artifacts); it does NOT override or weaken this invariant.

**QA gate flows.** UI-visible units: qa-engineer spawns IN PARALLEL with the Skeptic; both must pass. Non-UI: QA fires after Skeptic sign-off. Full step lists: `references/qa-gate.md` §QA gate flows (concurrent and post-sign-off).

**Phase breadcrumb:** `[phase: qa-review]`

### Per-ticket, in-flow (anti-pattern: end-of-batch QA sweep)

**Phase 6b is a per-ticket, in-flow gate. Conductor MUST NOT aggregate Phase 6b across multiple tickets to run as a final batch step.** Each ticket's QA fires inside that ticket's own loop, before Phase 7. If runtime QA cannot run for ticket N at the moment of its Phase 6b - dev server fails to boot, env file missing, preview deploy is blocked, no working URL - that is a blocker for ticket N specifically, not deferred work to triage at batch end.

When QA cannot run for ticket N, set the unit's QA result to `qa_blocked` and surface the blocker to the operator with the specific cause and the three options:

- **Provide the missing input** (env file, credentials, working preview URL) and re-run Phase 6b.
- **Accept INCONCLUSIVE** with `qa_unverified=true` recorded on the unit (see classification rules below). The PR can still merge, but the ticket carries a known unverified-runtime flag.
- **Abandon the ticket** - close the PR or revert.

Per-ticket QA scales via parallel-by-worktree (see below) - that is the mechanism for "many tickets in flight without a serial QA queue", not batching.

### Conductor preflight before any qa-engineer spawn

Before spawning `qa-engineer` for any unit, the conductor verifies the project env file exists at the path that the dev server will load. The exact path and pull command come from the resolved qa.md (`env_file:` and `env_pull_command:` fields if present) or from project config (e.g. an `env:pull:<app>` script in `package.json`). If the env file is missing, do NOT spawn qa-engineer. Instead surface the verbatim message to the operator:

```
QA env preflight FAILED: <env_file> is missing.
Pull it with: <env_pull_command>
Then re-run Phase 6b for this ticket.
```

Wait for the operator to provide the env file (or accept INCONCLUSIVE per the classification rules below) before proceeding. Spawning qa-engineer just to discover the env is missing wastes a worker turn - the dev server will fail to boot and the qa-engineer will return BLOCKED with no useful signal.

### INCONCLUSIVE classification (no static-only auto-pass)

Static-only QA on an Elevated UI-visible change is approximately zero signal. When the qa-engineer cannot reach a runtime path, the unit's QA result is **INCONCLUSIVE** with `qa_unverified=true`, NOT a pass. The conductor MUST NOT auto-promote INCONCLUSIVE to PASS, and MUST NOT silently proceed to Phase 7 with `qa_unverified=true` set; the operator must explicitly accept that state before merge. Full rationale and the operator options: `content/references/qa-gate.md` §INCONCLUSIVE classification (full rationale).

For parallel-by-worktree multi-PR fan-out commands, architect-plan-driven scenarios deep prose, and the dev-server boot pattern (curl-until loop, boot command resolution order), see `content/references/qa-gate.md`.

### Diff-read rule and review ordering

**For Elevated correctness, security, auth, crypto, or payments units, the Skeptic MUST read the diff in full before sign-off. QA evidence is supplementary - it confirms runtime behavior but does not substitute for line-by-line diff review. On these units the review order is fixed: diff first, QA evidence second.**

For behavior-visible Elevated units that are not in the exclusion set above (UI changes, behavioral feature additions), the Skeptic SHOULD read the diff AND the QA evidence. When both are present, the Skeptic may use QA evidence as the primary signal for UI correctness claims, but diff review remains required for logic, side effects, and security surface.

For Low or Trivial units, the Skeptic applies its inline self-check. QA is not spawned for Trivial units (direct action path); QA for Low units follows the standard flow above.

**Reading 'diff is secondary' as 'diff is optional' on any Elevated unit is a protocol violation.** The diff obligation is unconditional for Elevated units; only the ordering and primary-signal weight differ by risk class.

### Re-route limits

**Re-route limits.** Within any loop (Skeptic re-route or QA re-route), the conductor applies a max of 3 fix passes before escalating to the human. This applies to loops inside `/implement-ticket` Phase 6 and 6b, and to any ad-hoc Skeptic loop the conductor runs outside that command. The conductor tracks re-route count in-context. When the cap is reached with open findings, the conductor does not spawn another Engineer - it surfaces the stall with the open findings list and waits for human direction.

**Convergence failure.** A convergence failure occurs when a Skeptic raises the same finding unchanged after the Engineer claimed to have addressed it. Convergence failures bypass the remaining iteration budget and escalate immediately. They indicate either a misunderstanding between the Engineer and the finding, or a design-level conflict that requires human arbitration. Within the persistence loop, one re-raise after a claimed fix is sufficient (overrides the 2-re-route rule in skeptic-protocol.md Section 5 - see that section for the override note).
