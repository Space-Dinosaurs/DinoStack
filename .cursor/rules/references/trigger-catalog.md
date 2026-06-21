<!--
Purpose: Documents the three trigger types that can start a conductor flow and
         the open-goal loop contract that governs iterative, measured-condition
         loops. Includes the yolo-guard: structural rule that triggers fire the
         conductor, not worker-spawn bypasses.

Public API: Reference document consumed by the conductor, architects, and any
            external harness (CI, scheduler, webhook handler) that wants to
            invoke the AE methodology programmatically.

Upstream deps: content/sections/07-cross-session-loop-resume.md (loop-state
               resume semantics), content/sections/04-risk-classification.md
               (risk classification table and Project config), and
               content/references/skeptic-protocol.md (re-route limits and
               convergence-failure rules).

Downstream consumers: content/sections/12-protocol-details.md (trigger entry),
                      METHODOLOGY.md (open-goal loop section cross-reference).

Failure modes: This is a read-only reference. No side effects. Misreading the
               yolo-guard section and assuming a trigger bypasses risk
               classification is a protocol violation - see §Risk and review
               discipline.

Performance: Static document; no runtime cost.
-->

# Trigger catalog

Three ways a conductor flow can start, and the contract governing iterative open-goal loops.

## Trigger types

**Manual** (default): the operator invokes `/implement-ticket` directly. All existing conductor behavior applies unchanged. This is the baseline; every other trigger type is an extension of it, not a replacement.

**Scheduled**: a time-based external or harness-layer trigger - a cron entry, a user-global `/schedule` skill, a CI scheduled workflow, etc. - invokes the existing conductor flow at a predetermined interval. AE contributes the entry-point contract and risk discipline; scheduling infrastructure is outside AE scope. Note: `/schedule` is an external user-global Claude Code skill, not an AE methodology command - this catalog documents the contract it must satisfy, not the skill itself.

**Action-triggered**: a repository event (PR opened, push to a branch, CI-green status check) fires the workflow via CI or webhook at the harness layer, which in turn invokes the conductor. AE's contribution is the entry-point convention and risk discipline; the CI/webhook plumbing is outside AE scope. Note: `/loop` is similarly an external user-global skill - this catalog documents the contract it must satisfy.

All three trigger types enter the conductor at the same point: the start of the standard `/implement-ticket` flow. From that point, normal methodology rules apply without exception.

## Open-goal loop contract

An open-goal loop is an iterative conductor flow where the operator declares a measured goal condition rather than a fixed unit list. It has four parts:

**Trigger**: one of the three trigger types above fires the conductor.

**Action**: the conductor runs `/implement-ticket` with `goal_mode=open_goal`. Each iteration produces one or more units of work, which go through the standard architect -> orchestration-planner -> engineer -> Skeptic sequence.

**Measured condition**: an operator-declared `goal_condition` string evaluated after each Skeptic sign-off iteration. Example: `"zero open Critical findings in content/references/"`. The conductor evaluates this condition after each clean-exit iteration. When it is true, the loop exits cleanly.

**Hard-stop**: the loop exits on whichever of these is hit first:
- `goal_condition` evaluates to true (success).
- The existing re-route cap is reached: 3 fix passes per Skeptic loop, or an immediate convergence failure (same finding re-raised unchanged after the engineer claimed to have fixed it). See `content/references/skeptic-protocol.md` for the exact rules.
- A hard blocker is encountered: permission denial, missing credential, irreversible destructive action without authorization, or fundamental scope conflict.

The open-goal loop REUSES `loop-state.json`, resume, and clean-exit exactly as documented in `content/sections/07-cross-session-loop-resume.md`. No new loop engine is introduced. Cross-session resume, interruption recovery, and batch-state coexistence all apply unchanged.

## Hard-stop rules

Exits are non-negotiable. The loop MUST stop when any of these fire:

1. `goal_condition` is true after a Skeptic clean-exit.
2. Re-route cap reached: conductor has made 3 fix passes on a single Skeptic finding and it is still open. Escalate to human per `content/references/skeptic-protocol.md` §Re-route limits.
3. Convergence failure: a Skeptic raises the same finding unchanged after the engineer claimed to have fixed it. Escalate immediately; bypass remaining iteration budget per `content/references/skeptic-protocol.md` §Convergence failure.
4. Hard blocker: permission denial, missing credential, irreversible destructive action without authorization, or fundamental scope conflict. Return BLOCKED.

State is written to `loop-state.json` at every phase transition. On interruption or session exit, `status: "interrupted"` is written and the loop can resume per `content/sections/07-cross-session-loop-resume.md`.

## Risk and review discipline

This section is the yolo-guard. It is structural, not advisory.

**(a) A trigger is an input to the conductor, not a worker-spawn bypass.** The trigger fires the conductor, which THEN applies the standard risk-classification table before spawning any worker. The trigger never spawns workers directly. An action-triggered flow enters the conductor at the same entry point as a manual invocation; it does not skip or short-circuit any step.

**(b) Each iteration of an open-goal loop is treated as a new Elevated-eligible task.** It gets a fresh risk declaration, and for any Elevated unit, a fresh independent Skeptic. `goal_mode=open_goal` relaxes or suspends no existing review obligation. The Skeptic that validates this iteration is independent - it is not the same Skeptic instance that reviewed the previous iteration.

**(c) Auditability.** An open-goal iteration records a `risk_declared` field in `loop-state.json` (evidence that risk classification was performed that iteration). An iteration with no `risk_declared` is a protocol violation. The field may be set to `"low"`, `"elevated"`, or `"trivial"` to match the classification outcome.

**(d) This is what separates an action-triggered / open-goal loop from the rejected "yolo-mode"**: the trigger removes the human from the START, never from the REVIEW. Every unit that goes through an automated loop is subject to the same adversarial Skeptic review as a manually-triggered unit. Automated start does not imply automated approval.

## Entry-point example

The following illustrates how an action-triggered flow might invoke the conductor. It is ILLUSTRATIVE ONLY, not production-ready CI. Actual harness wiring - authentication, runner setup, Claude Code invocation method, secret management - is outside AE methodology scope.

```yaml
# ILLUSTRATIVE ONLY - not production-ready CI.
# Actual harness wiring is outside AE methodology scope.
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  ae-conductor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run AE conductor (action-triggered)
        # This step invokes the existing /implement-ticket conductor flow.
        # The conductor then applies standard risk classification before
        # spawning any workers - the trigger does not bypass review.
        run: |
          claude --project . /implement-ticket "${{ github.event.pull_request.title }}"
```

`/schedule` and `/loop` are external user-global Claude Code skills, not AE methodology commands. This catalog documents the contract they must satisfy (trigger fires conductor, conductor applies risk classification, every Elevated unit gets a fresh Skeptic), not the skills themselves.

## Related config

`auto_merge_on_ci_green` (boolean, default `false`) in `.agentic/config.json` is the companion toggle that enables unsupervised merge when an action-triggered flow completes CI-green. When `true`, `/implement-ticket` Phase 12 squash-merges the PR after all CI checks pass, the PR is marked ready, and no reviewer has requested changes. Documented in `content/sections/04-risk-classification.md` §Project config.

`content/sections/07-cross-session-loop-resume.md` documents the loop-state persistence and resume semantics that the open-goal loop inherits: `loop-state.json` writes at every phase transition, resumable phases, and the interruption recovery protocol. The `goal_mode`, `goal_condition`, and `risk_declared` fields are contract-level fields introduced by this catalog - they would be added to the `loop-state.json` schema if and when the open-goal mode is implemented; they are not present in sections/07 today.
