<!--
Purpose: Operator-facing guide to the trigger catalog - the three ways a
         conductor flow can start and the open-goal loop contract that governs
         iterative, measured-condition loops. Covers the yolo-guard: triggers
         fire the conductor, they do not bypass risk classification or Skeptic
         review.

Public API: Operator-facing prose. Entry point for operators who want to
            automate AE on CI/CD, scheduled runs, or webhook events, or who
            want to understand the safety guarantees around automated start.
            The full internal spec lives in
            content/references/trigger-catalog.md.

Upstream deps: content/references/trigger-catalog.md (authoritative spec);
               content/sections/07-cross-session-loop-resume.md
               (loop-state resume semantics);
               content/references/skeptic-protocol.md
               (re-route limits and convergence-failure rules).

Downstream consumers: docs site root index.

Failure modes: Stale if open-goal loop contract, hard-stop rules, or
               yolo-guard semantics change. Update alongside
               content/references/trigger-catalog.md.

Performance: Standard.
-->

# Trigger catalog

Three ways to start a conductor flow, and the safety contract that governs all
three.

## The three trigger types

**Manual** is the default. The operator invokes `/ds-implement-ticket` directly.
All conductor behavior applies unchanged. Every other trigger type is an
extension of this baseline, not a replacement.

**Scheduled** runs the existing conductor flow at a predetermined interval via
a cron entry, a CI scheduled workflow, or an external `/schedule` skill. AE
contributes the entry-point contract and risk discipline; the scheduling
infrastructure is outside AE scope.

**Action-triggered** fires the conductor in response to a repository event -
PR opened, push to a branch, CI status check going green - via CI or webhook
at the harness layer. AE contributes the entry-point convention and risk
discipline; the CI and webhook plumbing is outside AE scope.

All three trigger types enter the conductor at the same point: the start of the
standard `/ds-implement-ticket` flow. From there, the methodology applies without
exception.

## Open-goal loops

An open-goal loop is an iterative conductor flow where the operator declares a
goal condition rather than a fixed list of units. Each iteration produces one
or more units of work through the standard sequence (architect ->
orchestration-planner -> engineer -> Skeptic). The loop continues until the
condition is met or a hard stop fires.

The four required parts:

**Trigger**: one of the three trigger types above starts the loop.

**Action**: the conductor runs `/ds-implement-ticket` with `goal_mode=open_goal`.

**Measured condition**: an operator-declared `goal_condition` string evaluated
after each Skeptic sign-off iteration. When it is true, the loop exits cleanly.
Example: `"zero open Critical findings in content/references/"`.

**Hard stop**: the loop exits on whichever fires first:
- `goal_condition` evaluates to true.
- Re-route cap reached: 3 fix passes on a single Skeptic finding with it still
  open. Escalates to the operator per
  `content/references/skeptic-protocol.md`.
- Convergence failure: the same Skeptic finding re-raised unchanged after the
  engineer claimed to fix it. Escalates immediately.
- A hard blocker: permission denial, missing credential, irreversible action
  without authorization, or a fundamental scope conflict.

The open-goal loop reuses the per-ticket `loop-state-<LOOP_KEY>.json` (legacy:
`.agentic/loop-state.json`), cross-session resume, and
clean-exit exactly as documented in
`content/sections/07-cross-session-loop-resume.md`. No new loop engine is
introduced.

## The yolo-guard

This section is structural, not advisory.

**A trigger fires the conductor. It does not bypass risk classification or
Skeptic review.** The conductor receives the trigger as input and then applies
the standard risk-classification table before spawning any worker. An
action-triggered flow enters the conductor at the same entry point as a manual
invocation.

**Each iteration of an open-goal loop is a fresh Elevated-eligible task.** It
gets a fresh risk declaration. For any Elevated unit, it gets a fresh
independent Skeptic - not the same Skeptic instance that reviewed the previous
iteration. `goal_mode=open_goal` relaxes no existing review obligation.

**Auditability.** Each iteration records a `risk_declared` field in
`batch-state.json.open_goal` - the durable outer-loop cursor - as evidence that
risk classification was performed. It is deliberately NOT held in a
`loop-state-<LOOP_KEY>.json`, which Phase 12 clears every iteration and which
therefore cannot hold cross-iteration audit state. An iteration with no
`risk_declared` is a protocol violation.

**What this buys.** The trigger removes the human from the START of each
iteration, never from the REVIEW. Every unit that goes through an automated
loop gets the same adversarial Skeptic review as a manually triggered unit.
Automated start does not imply automated approval.

## Setting one up

Automated triggering is outside AE scope at the harness level, but the
entry-point contract is simple: invoke the existing `/ds-implement-ticket`
conductor flow from your CI or scheduler, and the methodology handles
everything from there.

The following is illustrative only - not production-ready CI. Authentication,
runner setup, Claude Code invocation method, and secret management are all
outside AE scope:

```yaml
# ILLUSTRATIVE ONLY - not production-ready CI.
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  ae-conductor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run AE conductor (action-triggered)
        # The trigger invokes the existing /ds-implement-ticket flow.
        # The conductor applies standard risk classification before
        # spawning any workers - the trigger does not bypass review.
        run: |
          claude --project . /ds-implement-ticket "${{ github.event.pull_request.title }}"
```

## Companion config toggle

`auto_merge_on_ci_green` (boolean, default `false`) in `.agentic/config.json`
enables unsupervised merge when an action-triggered flow completes CI-green.
When `true`, `/ds-implement-ticket` Phase 12 squash-merges the PR after all CI
checks pass, the PR is marked ready, and no reviewer has requested changes.
Documented in `content/sections/04-risk-classification.md` §Project config.

## Related references

- `content/references/trigger-catalog.md` - full internal spec: open-goal
  loop contract, hard-stop rules, yolo-guard, and entry-point examples
- `content/sections/07-cross-session-loop-resume.md` - loop-state persistence
  and resume semantics the open-goal loop inherits
- `content/references/skeptic-protocol.md` - re-route limits and
  convergence-failure escalation rules
