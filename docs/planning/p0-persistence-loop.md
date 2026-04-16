# P0 Persistence Loop - Design Plan

## Problem statement

`/implement-ticket` is a one-shot command: it runs Engineer -> Skeptic -> QA once and then exits, leaving re-routing on Critical and Major findings as ad-hoc prose scattered across Phase 5, 6, and 6b. The current wording says "route back to a fresh engineer agent to fix; re-run Skeptic after" for Critical, and "route back to engineer unless there's a strong reason to defer; re-run Skeptic" for Major - but neither specifies how many times this may repeat, what state carries forward between attempts, or what happens if the loop diverges. In practice, the conductor makes a judgment call each time, which means the number of iterations is unbounded, prior findings may be re-raised on re-review (wasting review cycles), and there is no contract a user can rely on.

Without a first-class loop contract, two failure modes recur in practice: (1) loops that stall because each Skeptic re-raise of the same finding looks "new" to the next Engineer, so the root cause goes unaddressed; and (2) loops that never terminate because the conductor does not have an explicit bail-out condition and keeps issuing re-routes in the hope the problem resolves. The persistence loop design below closes both gaps by making iteration a named protocol primitive with explicit state, accumulation rules, and a hard termination condition.

## Scope

**In scope:**
- Formalizing the Engineer -> Skeptic -> QA loop within a single `/implement-ticket` session
- Defining the max-iteration cap and its rationale
- Per-iteration state tracking (what carried forward, what was attempted, what failed, what was fixed)
- Findings accumulation rules to prevent re-litigation of closed findings
- Specific phase-by-phase changes to `/implement-ticket`
- Clarifying when the loop terminates cleanly vs. escalates to the human

**Explicitly out of scope:**
- Cross-session resume (save loop state to disk and restart after a rate limit or session expiry) - this is P2
- Rate-limit handling or `omc wait`-equivalent daemon - this is P2
- Shared task-state file (`.agentic/tasks.jsonl`) - this is P1
- Cost-aware model routing (Haiku for investigator, Opus for architect) - this is P2
- The parallel fan-out primitive for N independent subtasks - this is P1

## Current behavior (as-is)

**Phase 5 (Implement):** When parallel sub-branches produce a merge conflict, the current prose routes back to "a fresh engineer with instruction to implement the two units sequentially to resolve the conflict." This is a single ad-hoc re-route with no retry limit and no state carried forward beyond the conflict description.

**Phase 6 (Skeptic review):** The current findings handling section reads:
- Critical: "Route back to a fresh engineer agent to fix. Re-run Skeptic after."
- Major: "Route back to engineer unless there's a strong reason to defer. Re-run Skeptic."
- Minor: "Address inline or document as known limitation. No re-run needed."

There is no max-iteration cap. There is no mechanism to distinguish a finding that was genuinely addressed from one that was re-raised unchanged.

**What already exists in skeptic-protocol.md** (and is NOT a gap this P0 adds):
- Section 4 already defines a resolved-issues preflight list that the conductor prepends to the Skeptic brief on rounds 2+. The list prevents re-raising already-addressed findings as new Critical or Major items. The Skeptic may still contest a resolution, but must do so explicitly.
- Section 5 already defines an escalation rule for contested findings: if the same finding is contested for 2 or more re-routes without resolution, the conductor escalates to a human operator.

**What this P0 adds (the genuine gaps):**
- A numeric iteration cap with explicit cap-reached escalation (skeptic-protocol.md Section 5 has a re-route rule but no numeric cap; this loop formalizes 3 fix passes as the ceiling)
- Formal loop state tracking (findings_log schema, iteration counter, termination_reason)
- QA loop formalization with its own cap and failure schema
- Phase 7 quality gate failure handling (currently undefined)
- Engineer BLOCKED/NEEDS_CONTEXT handling within the loop
- Format re-invocation rules scoped to the loop context

**Phase 6b (QA Gate):** The current prose reads: "On failure, route back to engineer for fixes, then re-run Phase 6b. On pass, proceed to Phase 6c." Again, no cap, no state, no accumulation. The only termination condition is "pass."

**Summary of the gap:** Re-routes exist but are unstructured. Each iteration restarts cold. The loop can repeat indefinitely in theory, and the Skeptic and QA agent have no visibility into what prior iterations attempted.

## Proposed loop contract

### Inputs (loop entry conditions)

The loop is entered after Phase 5 (Engineer) completes on the initial implementation. It is re-entered after any Engineer fix pass within Phase 6 or 6b.

### Termination conditions (the loop exits cleanly when ALL hold)

1. Skeptic grants sign-off (no outstanding Critical or Major findings)
2. QA gate passes (or is not triggered - no `.claude/qa.md`, no matching trigger patterns)
3. Quality gate (`$QUALITY_CMD`) passes

The loop exits with escalation (routes to the human) when:
- Max iterations is reached without clean termination (see cap below)
- The Skeptic raises the same Critical finding unchanged after a claimed fix (convergence failure - see convergence threshold note below)
- The Engineer returns `Status: BLOCKED` citing a fundamental design conflict that the Skeptic's finding implies requires architectural re-work beyond the scope of a fix pass

**Convergence threshold - override of skeptic-protocol.md Section 5:** skeptic-protocol.md Section 5 requires 2 or more re-routes before escalating on a contested finding. This loop overrides that rule: 1 re-raise after a claimed fix is sufficient to trigger convergence failure escalation. Rationale: the iteration budget is already being consumed; a second Engineer attempt on an unaddressed finding is wasteful and signals a design-level conflict. The implementer of this loop MUST also update skeptic-protocol.md Section 5 to note that the loop contract (when active) overrides the 2-re-route rule for findings that have been through a claimed-fix cycle.

### Max-iteration cap

**Cap: 3 Engineer fix passes per loop (4 total Engineer invocations including the initial implementation).**

Rationale:
- Iteration 1 (initial): baseline implementation
- Iteration 2 (fix pass 1): address Critical/Major findings from first Skeptic review; most Critical findings are localized defects (off-by-one, missing null check, incorrect API usage) that a competent Engineer resolves in one pass
- Iteration 3 (fix pass 2): address residual findings or QA failures; a second fix pass is warranted when Phase 6 and 6b fire independently (Skeptic passes but QA fails, or Skeptic re-review after QA-introduced changes finds a new issue)
- Iteration 4 (fix pass 3): last resort; reaching this pass means either the Skeptic brief is mis-targeted, the Engineer is consistently misunderstanding the finding, or the underlying design is at fault

Three fix passes is the empirically-defensible ceiling for within-session work. Beyond 3, the marginal value of another unguided pass is low and the risk of scope creep on each "fix" is high. The right move at pass 3 is to surface the stall to the human rather than loop again.

**The cap applies per-phase independently:**
- Phase 6 Skeptic loop: up to 3 fix passes
- Phase 6b QA loop: up to 3 fix passes
- The two sub-caps are independent - exhausting the Skeptic cap does not consume QA cap budget

**Phase 6 and Phase 6b cap interaction:** If Phase 6 exits via `cap_reached` escalation, Phase 6b does NOT run. The ticket is already stalled - running QA on a Skeptic-rejected implementation is wasteful. The escalation from Phase 6 subsumes Phase 6b for that iteration. Phase 6b only runs when Phase 6 exits cleanly (Skeptic sign-off granted).

### Loop state object

See "Loop state schema" section below for the full schema. The conductor maintains loop state in-context across iterations; it is not written to disk (cross-session persistence is P2).

## Loop state schema

The conductor tracks the following per-loop invocation. This is in-context state (a structured block the conductor emits and updates between phases), not a file.

```
LOOP_STATE:
  phase: "skeptic" | "qa"
  iteration: <integer, starting at 1>
  max_iterations: 3
  findings_log:
    - id: <short slug, e.g. "null-deref-user-service">
      severity: Critical | Major | Minor
      first_raised: <iteration number>
      status: open | addressed | deferred | closed
      claimed_fix: <one-line summary of what the Engineer said it did to address this>
      re_raised: <boolean - true if Skeptic raised this same finding again after a claimed fix>
  last_engineer_summary: <free text - what the Engineer said it changed in this iteration>
  termination_reason: null | "clean" | "cap_reached" | "convergence_failure" | "blocked"
```

**QA failures schema** - the QA loop uses a parallel schema for `qa_failures_log`:

```
qa_failures_log:
  - id: <short slug, e.g. "checkout-button-disabled">
    description: <one-line description of the failing acceptance criterion>
    first_raised: <iteration number>
    status: open | addressed | closed
    claimed_fix: <one-line summary of what the Engineer said it did to address this>
    re_raised: <boolean - true if QA raised this same failure again after a claimed fix>
```

**QA brief section format on iteration 2+** - the QA engineer brief MUST include a "Prior QA failures" section on iteration 2 and beyond, mirroring the Skeptic's "Prior iteration findings" format:

```
## Prior QA failures

The following failures were identified and fix attempts were made in earlier iterations. For each:
- If the acceptance criterion now passes: mark it CLOSED with a one-line confirmation.
- If the criterion still fails: re-raise it using [PREV: <id>] prefix in the failure description.
- Do not re-raise failures that are confirmed fixed.

[paste qa_failures_log entries with status=open or status=addressed]
```

**What carries forward each iteration:**
- `findings_log` accumulates - findings are never removed, only status-updated
- `qa_failures_log` accumulates - failures are never removed, only status-updated
- `last_engineer_summary` is replaced each iteration (prior summaries are in the log)
- `iteration` counter increments

**What resets each iteration:**
- The Engineer's full brief (fresh context, bounded to the open findings + loop state)
- The Skeptic's diff (always the current `git diff origin/$BASE_BRANCH..HEAD`)
- The QA engineer's test context

**State emission format** - the conductor emits this block in its status update between phases so the human can read loop progress:

```
[loop: skeptic | iteration 2/3 | open findings: 1 Critical, 0 Major]
```

## Findings accumulation across iterations

### Core rule

A finding that was raised in a prior iteration and the Engineer claimed to address it MUST be re-evaluated by the Skeptic against the current diff before it can be re-raised. If the Skeptic concludes the claimed fix did not in fact address the finding, it MUST use the same finding ID in its output (format: `[PREV: <id>]`). This allows the conductor to detect re-raises mechanically, update `re_raised: true` in the loop state, and avoid sending the Engineer the same finding in identical prose a third time.

**Auto-close rule:** When the Skeptic raises zero new findings (grants sign-off), ALL findings_log entries with status=open or status=addressed are automatically closed (status set to `closed`). The absence of re-raise is an implicit confirmation that the fixes were accepted. The conductor applies this auto-close before proceeding to Phase 6b.

### Skeptic brief changes on iteration 2+

On the first iteration, the Skeptic receives a standard adversarial brief with no prior context.

On iteration 2 and beyond, the Skeptic brief MUST include an additional section. This extends the resolved-issues preflight list already defined in skeptic-protocol.md Section 4 - the findings_log entries map directly to the preflight list format:

```
## Prior iteration findings

The following findings were raised in earlier iterations. For each:
- If the current diff shows the finding was addressed: mark it CLOSED with a one-line confirmation.
- If the current diff does NOT show the finding was addressed: re-raise it using [PREV: <id>] prefix in the finding title.
- Do not re-raise findings that were resolved - do not invent new instances of a previously-closed finding without new evidence.

[paste findings_log entries with status=open or status=addressed]
```

This brief change has two effects: it tells the Skeptic what was already reviewed (reducing redundant catches of already-fixed issues), and it forces the Skeptic to explicitly confirm or deny each claimed fix rather than silently re-evaluating the whole diff from scratch.

### Format re-invocations and iteration counter

Format-noncompliant Skeptic re-invocations (skeptic-protocol.md Section 11 permits up to 3) do NOT increment the `iteration` counter. They are administrative retries, not new review rounds. The iteration counter only increments when an Engineer fix pass has been spawned and returned. The conductor must not increment `iteration` when spawning a format re-invocation Skeptic.

### Deferral rules

- Minor findings: the conductor may mark them `deferred` after the first pass if the Engineer's fix pass note explains why addressing them would exceed the ticket scope. Deferred Minors do not re-enter the loop. They are documented in the PR description.
- Major findings: may NOT be deferred without explicit human approval. **Loop-context override:** the base skeptic-protocol.md permits deferral of Majors with "a compelling documented reason." Within the loop, this is tightened to require explicit human approval - the conductor escalates rather than accepting an Engineer's self-declared deferral. Rationale: inside a bounded loop the human is already being notified at cap or convergence failure; a Major deferral mid-loop warrants the same gate.
- Critical findings: never deferred. The loop cannot exit cleanly with an open Critical.

## Engineer BLOCKED and NEEDS_CONTEXT handling within the loop

When the Engineer fix pass returns a non-DONE status inside the loop, the following transitions apply:

**BLOCKED:** Treat as immediate `cap_reached` escalation regardless of current iteration count. BLOCKED means the Engineer hit a hard blocker requiring architecture decisions or human judgment - it is a design-level problem that more iterations cannot resolve. The conductor emits the escalation format with `termination_reason: blocked` and waits for human direction. The iteration counter is NOT incremented (a BLOCKED pass is not a "fix attempt").

**NEEDS_CONTEXT:** The conductor re-supplies the missing context (from the codebase, session context, or by asking the human) and re-spawns the Engineer with the same findings brief and the added context. The iteration counter does NOT increment - it is not a new fix attempt, it is a context-supply step. If the conductor cannot supply the needed context, escalate to the human with the Engineer's stated gap.

**DONE_WITH_CONCERNS:** Proceed normally. The Engineer's stated concerns become additional context for the next Skeptic spawn (include them alongside the adversarial brief). The iteration counter increments as normal.

## Changes required to /implement-ticket

### Phase 5 (Implement) - minor change

After the merge conflict re-route block, add a note that the conflict re-route counts as iteration 1 of the Phase 6 loop if the re-routed Engineer's output then goes through Skeptic review. This prevents double-counting.

### Phase 6 (Skeptic review) - significant restructure

Replace the current findings handling prose with the following loop contract block:

**Before the loop starts**, emit loop state initialization:
```
LOOP_STATE initialized:
  phase: skeptic
  iteration: 1
  max_iterations: 3
  findings_log: []
```

**Loop entry (repeat until termination):**

1. Spawn Skeptic with adversarial brief. On iteration 2+, prepend the "Prior iteration findings" block to the brief (see Findings accumulation section). Format re-invocations (up to 3 per skeptic-protocol.md Section 11) do not increment `iteration`.

2. Receive Skeptic output. Classify findings. Update `findings_log`.

3. **Termination check:**
   - If no Critical or Major findings: auto-close all open/addressed findings_log entries (see auto-close rule). Exit loop cleanly. Proceed to Phase 6b.
   - If `iteration == max_iterations` AND Critical or Major findings remain: exit loop with `termination_reason: cap_reached`. Escalate to human (see Escalation section below). Phase 6b does NOT run.
   - If any Critical finding carries `re_raised: true` (same finding re-raised after claimed fix): exit loop with `termination_reason: convergence_failure`. Escalate to human.

4. **Engineer fix pass:** Spawn a fresh `engineer` agent with:
   - The open Critical and Major findings from `findings_log` (status=open)
   - The `last_engineer_summary` from the prior iteration
   - Instruction: "Address only the findings listed below. Do not expand scope. For each finding, confirm in your summary what you changed and why it addresses the finding."
   - The branch name and repo path
   - Instruction to run `$QUALITY_CMD` before finishing

5. Receive Engineer output.
   - If BLOCKED: set `termination_reason: blocked`, emit escalation format, stop. Do NOT increment `iteration`.
   - If NEEDS_CONTEXT: re-supply context and re-spawn without incrementing `iteration`.
   - Otherwise: update `last_engineer_summary`. Update finding statuses to `addressed` for findings the Engineer claims to have fixed. Increment `iteration`. Go to step 1.

**Escalation format (cap_reached, convergence_failure, or blocked):**
```
LOOP STALLED - [reason: cap_reached | convergence_failure | blocked]
Iteration: [N] of 3

Open findings that could not be resolved:
[list findings_log entries with status=open]

[If convergence_failure]: The following finding was re-raised after a claimed fix:
[finding id, original raise, claimed fix, Skeptic's re-raise note]

[If blocked]: Engineer returned BLOCKED with the following description:
[Engineer's blocker description verbatim]

Recommended action: review the open findings above and either:
(a) Provide clarifying direction to the Engineer on how to address [finding id], or
(b) Accept the finding as a known limitation and confirm deferral, or
(c) Scope the fix as a follow-on ticket.
```

### Phase 6b (QA Gate) - moderate restructure

**Phase 6b only runs if Phase 6 exits cleanly (Skeptic sign-off granted).** If Phase 6 exits via cap_reached escalation, Phase 6b is skipped.

Replace the current single-sentence re-run prose with a parallel loop contract:

**Before the loop starts**, emit loop state initialization:
```
LOOP_STATE initialized:
  phase: qa
  iteration: 1
  max_iterations: 3
  qa_failures_log: []
```

**Loop entry:**

1. Spawn `qa-engineer` with ticket context, diff, and `.claude/qa.md` config. On iteration 2+, prepend the "Prior QA failures" section to the brief (see QA failures schema above).

2. Receive QA output.

3. **Termination check:**
   - If PASS: exit loop cleanly. Proceed to Phase 6c.
   - If `iteration == max_iterations` AND still failing: escalate to human with the qa_failures_log.
   - If same failure recurs unchanged after claimed fix (re_raised: true): escalate with convergence note.

4. **Engineer fix pass:** Spawn engineer with the QA failure description, prior fix summary, and instruction to fix only the failing acceptance criteria. Apply the same BLOCKED/NEEDS_CONTEXT handling as Phase 6 (BLOCKED = immediate escalation, NEEDS_CONTEXT = context re-supply without incrementing iteration).

5. Receive Engineer output. If neither BLOCKED nor NEEDS_CONTEXT: update `qa_failures_log`. Increment `iteration`. Go to step 1.

### Phase 7 (Quality gate) - restructured

If `$QUALITY_CMD` fails after Phase 6 and 6b loops exit cleanly, this does NOT continue the Phase 6 iteration counter. Instead:

1. Spawn one Engineer fix pass to address the quality gate failure (outside the Phase 6 cap - the Skeptic already signed off on the implementation, so this is a targeted quality gate fix, not a Skeptic-loop re-entry).
2. Re-run Phase 7 (`$QUALITY_CMD`).
3. If Phase 7 passes: proceed to Phase 6c.
4. If Phase 7 still fails after one fix pass: escalate to human. The escalation format should include the quality gate output from both attempts.

**No unbounded loop:** Phase 7 failure only ever triggers one Engineer fix pass followed by one re-run. There is no retry loop at this phase. If the second run fails, escalate immediately.

**Tight-fix path interaction with Phase 7:** If the tight-fix path fired (Phase 6 guard bypassed the Skeptic entirely) and the Worker committed, then Phase 7 fails - this triggers the Phase 7 fix pass described above (one Engineer pass, one re-run, then escalate if still failing). It does NOT re-enter the Phase 6 Skeptic loop; the Skeptic already signed off on the implementation via the tight-fix path's pre-commit verification. The Phase 7 fix pass is scoped to quality gate failures only.

### Phase 6c (Promote findings) - no change

Fires after both Phase 6 and 6b loops exit. No structural change needed.

## Changes required to agent-methodology.md

### Re-route limits section (new subsection under QA Gate or as a standalone)

The methodology currently has no concept of a max re-route count. Add a short paragraph under the QA Gate section or as a new "Re-route limits" subsection:

> **Re-route limits.** Within any loop (Skeptic re-route or QA re-route), the conductor applies a max of 3 fix passes before escalating to the human. This applies to loops inside `/implement-ticket` Phase 6 and 6b, and to any ad-hoc Skeptic loop the conductor runs outside that command. The conductor tracks re-route count in-context. When the cap is reached with open findings, the conductor does not spawn another Engineer - it surfaces the stall with the open findings list and waits for human direction.

### Convergence failure definition (new)

Add a named concept for convergence failure:

> **Convergence failure.** A convergence failure occurs when a Skeptic raises the same finding unchanged after the Engineer claimed to have addressed it. Convergence failures bypass the remaining iteration budget and escalate immediately. They indicate either a misunderstanding between the Engineer and the finding, or a design-level conflict that requires human arbitration. Within the persistence loop, one re-raise after a claimed fix is sufficient (overrides the 2-re-route rule in skeptic-protocol.md Section 5 - see that section for the override note).

### Findings accumulation reference

In the existing "Skeptic loop orchestration" protocol details pointer, add a reference to the findings accumulation rules in `/implement-ticket` Phase 6.

## Changes required to skeptic-protocol.md

### Section 4 (Resolved issues preflight list) - extension

The existing preflight list format (raised finding + resolution) maps to this loop's `findings_log` schema. Add a note to Section 4:

> **Loop context extension:** When the Skeptic is invoked inside the `/implement-ticket` persistence loop, the conductor passes the findings_log entries (status=open or status=addressed) as the preflight list. The findings_log id field is used as the finding identifier for `[PREV: <id>]` tagging. The preflight list format is identical to the standard Section 4 format; the findings_log schema is the structured backing store.

### Section 5 (Escalation protocol) - loop override note

The current Section 5 rule requires 2 or more re-routes before escalation. Add a note:

> **Loop contract override:** When operating inside the `/implement-ticket` persistence loop (Phase 6), the loop contract overrides this rule. One re-raise after a claimed fix (convergence failure as defined in the loop contract) is sufficient to trigger escalation. The loop already consumes iteration budget on each fix pass; requiring a second re-raise would waste an additional pass on a finding the Engineer has already failed to address. Outside the loop context (ad-hoc Skeptic re-routes not inside a named loop), the 2-re-route rule applies unchanged.

## 7-surface audit for persistence loop primitive

Per MEMORY.md, adding a new protocol primitive requires auditing 7 surfaces. Audit results for the persistence loop:

1. **orchestration-planner.md** - No update needed. The planner maps task dependencies and returns an execution plan consumed by the conductor before any loop begins. It has no stake in what happens inside the loop after Phase 5.

2. **agent-team.md** - No update needed. agent-team.md describes which agents exist and how they compose into flows (feature, bug, security). The loop formalizes re-route behavior within an existing flow; it does not add agents or change the flows themselves.

3. **subagent-protocol.md** - UPDATE NEEDED. The phase vocabulary (Rule 6) should add `loop:skeptic` and `loop:qa` breadcrumbs. Format follows the existing `[phase: qa-review]` convention: `[loop: skeptic | iteration N/3 | open findings: X Critical, Y Major]`. Add a pointer to the loop contract in `/implement-ticket`. Also document the loop-specific BLOCKED/NEEDS_CONTEXT transitions under phase breadcrumb rules.

4. **agent-methodology.md** - UPDATE NEEDED. Add "Re-route limits" subsection and "Convergence failure" definition (see "Changes required to agent-methodology.md" section above).

5. **SKILL.md** - No update needed. SKILL.md provides the on-demand methodology summary for non-Claude adapters. The persistence loop is an orchestration detail within `/implement-ticket`; it does not change agent roster, named agent definitions, or the summary that SKILL.md delivers.

6. **init-project.md** - No update needed. init-project.md scaffolds project structure at setup time (AGENTS.md, release.md, qa.md). It does not reference loop behavior or session-time orchestration.

7. **wrap.md** - No update needed. wrap.md captures stable session facts and promotes findings at wrap time. Loop state is in-context only (cross-session persistence is P2 scope), so wrap.md has nothing new to capture from the loop.

**Summary of required surface updates:** agent-methodology.md, skeptic-protocol.md (Sections 4 and 5), subagent-protocol.md (phase vocabulary), and /implement-ticket (Phases 6, 6b, 7). The other four surfaces are unaffected.

8. **Docs and slides** - UPDATE REQUIRED.
   - `docs/agentic-engineering.html` - add persistence loop to the feature list or methodology overview section. Note that `/implement` is now loop-aware with an explicit termination contract.
   - `docs/slides/how-it-works-slides.md` - update the Engineer -> Skeptic -> QA flow slide to show the loop as a named primitive (cap of 3 iterations, findings_log, convergence failure condition). This is a core methodology change that the how-it-works deck must reflect.
   - `docs/slides/skeptic-protocol-slides.md` - update to show findings_log accumulation and the loop-specific override of the 2-re-route rule (one re-raise = convergence failure inside the loop).
   - `docs/slides/quality-assurance-slides.md` - update to show the QA loop (Phase 6b) as a parallel loop primitive with its own iteration cap.
   - **New deck consideration:** A standalone `docs/slides/persistence-loop-slides.md` may be warranted once the feature ships - it teaches the loop contract (state machine, max-iteration cap, convergence failure, escalation path) as a first-class concept. Assess at implementation time based on teaching demand.

## Edge cases and failure modes

**1. Infinite loop via finding mutation.** The Skeptic could technically raise a "new" finding each iteration that is substantively the same as a prior closed finding but worded differently. The `[PREV: <id>]` tagging convention is advisory - the Skeptic is a language model and may not comply precisely. Mitigation: the conductor should compare newly raised findings against `findings_log` by semantic similarity, not only by ID prefix. If a newly-raised Critical looks like a re-phrasing of a closed finding, the conductor should treat it as a convergence failure rather than a new finding.

**2. Engineer scope creep on fix passes.** An Engineer given "fix finding X" may introduce new bugs outside the finding's scope. The Skeptic's next-iteration brief includes a "Prior iteration findings" section but does not explicitly constrain the Skeptic to look only at finding X. The adversarial Skeptic will review the full diff, which is correct - new bugs introduced by a fix pass should be caught. However, this means the iteration count does not decrease even if finding X was fixed if a new Critical was introduced. This is correct behavior: the loop should not exit with a new Critical even if the original finding was addressed. The loop state must track all open findings, not just the ones from iteration 1.

**3. QA loop and Skeptic loop interleave.** If Phase 6 Skeptic loop exits cleanly on iteration 2, then Phase 6b QA loop fails, then the Engineer's QA fix introduces a regression the Skeptic would catch - the Skeptic loop does not re-fire automatically. The QA loop operates on functional acceptance criteria; it does not re-invoke the Skeptic. If a QA fix is substantial enough that the conductor judges it Skeptic-worthy, the conductor should route back through Phase 6 explicitly. This is a conductor judgment call; the design does not attempt to automate it.

**4. Conflicting Skeptic and QA findings.** The Skeptic may approve an implementation that QA subsequently rejects because a user-visible behavior is wrong. This is expected and healthy - they test different properties. The fix loop for QA failures runs after Skeptic sign-off, so QA fix passes do not require re-running the Skeptic unless the fix is substantial (conductor judgment).

**5. Worker scope creep on re-routes.** The fix-pass Engineer brief must be tightly scoped to the open findings. Without explicit scoping instruction, the Engineer may "clean up" unrelated code, expanding the diff on the next Skeptic review and causing new findings. The fix-pass brief must include the explicit constraint: "Address only the findings listed below. Do not refactor, rename, or clean up code outside the finding scope."

**6. Cap reached on the final iteration before a bug is fixed.** When the cap is reached, the conductor must NOT commit the partial fix. The branch should be left in the state of the last Engineer output (which may be partially fixed). The human receives the escalation and decides whether to direct another fix pass manually, defer, or abandon the ticket.

**7. Phase 6 guard interaction (tight-fix path).** The tight-fix path (Phase 6 guard) bypasses the Skeptic entirely when all 6 checklist items pass. The persistence loop does not change this - the guard fires before the loop is initialized. If the tight-fix path fires, no loop is started. If the Worker returns `DONE_WITH_CONCERNS`, the loop is initialized at iteration 1 with the uncommitted diff as input to the Skeptic. If the tight-fix path fires and the Worker commits successfully but Phase 7 (quality gate) subsequently fails, the Phase 7 fix pass rule applies (one Engineer pass, one re-run, then escalate if still failing) - not the Phase 6 loop, since the Skeptic already signed off via the pre-commit verification.

**8. Zero-finding Skeptic with open findings_log items.** If the Skeptic raises zero new findings but findings_log has status=open items, the plan might imply a clean exit with inconsistent log state. Resolution: when the Skeptic raises zero new findings (grants sign-off), the conductor auto-closes ALL findings_log entries with status=open or status=addressed. The absence of re-raise is an implicit confirmation that the fixes were accepted. This auto-close fires before proceeding to Phase 6b.

## Open questions (resolved 2026-04-15)

1. **Phase 6 and 6b cap budget: INDEPENDENT (3+3).** Each phase gets its own 3-fix-pass budget. Rationale: Skeptic and QA test orthogonal properties (correctness vs functional acceptance); conflating them would punish legitimate orthogonal failures. A ticket may burn up to 6 total fix passes in the pathological case, but each sub-budget is evaluated independently. The per-phase 3-cap remains the stall signal - hitting 3 on either phase escalates that phase.

2. **`[PREV: <id>]` tagging: ADVISORY.** The Skeptic brief template in `skeptic-protocol.md` is NOT modified to enforce the tag format. The conductor performs semantic-similarity matching against `findings_log` on each Skeptic return as the safety net (per Edge case 1). Rationale: keeping the global brief template untouched minimizes downstream effect on every Skeptic invocation, and conductor-side matching already provides the necessary re-raise detection regardless of Skeptic compliance.

3. **Convergence failure escalation: ALWAYS ESCALATE to human.** The conductor does NOT synthesize or suggest a fix direction. It emits the escalation format with the raw finding history and waits for human direction. Rationale: the whole point of convergence failure is "the loop cannot resolve this"; conductor speculation on top of a failed loop undermines the signal and risks sending the human down a wrong path. The escalation format stays as currently specified.

4. **Loop state surfacing: BREADCRUMB + FILE.** The conductor emits both the `[loop: ...]` breadcrumb inline AND writes to `.agentic/loop-state.json` as a read-only observability log. File is overwritten per loop iteration (not append-only). Schema mirrors the in-context `LOOP_STATE` object verbatim. Rationale: the file is cheap, gives post-mortem visibility now, and lays the groundwork P2 cross-session resume will depend on - building it now avoids a later migration. **P2 dependency note:** P2 rate-limit resumer will READ this file for resume keying, so the file format becomes a stable contract from P0 onward. Any schema change post-P0 must consider P2 readers.

**File location and format:**
- Path: `.agentic/loop-state.json` (relative to repo root; parent dir auto-created if absent)
- Format: JSON serialization of the in-context `LOOP_STATE` schema defined in "Loop state schema" section above
- Lifecycle: written at loop entry, overwritten on each iteration state update, overwritten at loop exit with `termination_reason` set. Not deleted on clean termination - the last state is the post-mortem record until the next loop invocation overwrites it.
- `.agentic/` directory: NOT gitignored by default (implementer should verify and add to `.gitignore` if the project treats loop state as session-local; defer to project convention)
