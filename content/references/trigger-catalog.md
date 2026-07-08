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

**Action**: the conductor runs `/implement-ticket` with `goal_mode=open_goal`. Each iteration produces one or more units of work, which go through the standard architect -> orchestration-planner -> engineer -> Skeptic sequence. `goal_mode=open_goal` invocations MUST also declare `max_iterations` (positive integer) and `max_wallclock_min` (positive integer) - see Hard-stop rule 5. No default; an invocation missing either is refused before Phase 1.

**Measured condition**: an operator-declared `goal_condition` string evaluated after each iteration. Example: `"zero open Critical findings in content/references/"`. When an iteration's `risk_declared` is `elevated` and produced a clean Skeptic sign-off, the conductor spawns `goal-condition-evaluator` (Tier 1/haiku default; see `content/agents/goal-condition-evaluator.md`) to check the condition cheaply rather than spending conductor-tier reasoning on every iteration. The evaluator is read-only and returns only `GOAL_MET: true|false` plus a one-line evidence quote - it makes no correctness or safety judgment and never substitutes for the Skeptic (see §Risk and review discipline (b) and (e), neither of which this evaluator's existence relaxes). When an iteration's `risk_declared` is `low` or `trivial` (no Skeptic sign-off exists to spawn after - per (b), the fresh-independent-Skeptic requirement scopes to Elevated units only), the conductor evaluates `goal_condition` itself directly and never spawns the evaluator for that iteration. The same conductor-direct evaluation is also the fallback whenever the evaluator is spawned but is unavailable, times out, returns a malformed result, or returns `BLOCKED`: none of those outcomes routes to the generic BLOCKED-is-`cap_reached` escalation semantics in `content/references/subagent-protocol.md` §Loop transition rules - they route to conductor-direct evaluation, and the loop proceeds exactly as it would have before this role existed. When the condition is true (evaluator-confirmed or conductor-direct), the loop exits cleanly.

**Hard-stop**: the loop exits on whichever of these is hit first:
- `goal_condition` evaluates to true (success).
- The existing re-route cap is reached: 3 fix passes per Skeptic loop, or an immediate convergence failure (same finding re-raised unchanged after the engineer claimed to have fixed it). See `content/references/skeptic-protocol.md` for the exact rules.
- A hard blocker is encountered: permission denial, missing credential, irreversible destructive action without authorization, or fundamental scope conflict.

The open-goal loop REUSES `loop-state.json`, resume, and clean-exit exactly as documented in `content/sections/07-cross-session-loop-resume.md`. No new loop engine is introduced. Cross-session resume, interruption recovery, and batch-state coexistence all apply unchanged.

## Hard-stop rules

Exits are non-negotiable. The loop MUST stop when any of these fire:

1. `goal_condition` is true after an iteration's review-gate clean-exit (Skeptic sign-off for Elevated iterations; conductor-direct evaluation for Low/Trivial).
2. Re-route cap reached: conductor has made 3 fix passes on a single Skeptic finding and it is still open. Escalate to human per `content/references/skeptic-protocol.md` §Re-route limits.
3. Convergence failure: a Skeptic raises the same finding unchanged after the engineer claimed to have fixed it. Escalate immediately; bypass remaining iteration budget per `content/references/skeptic-protocol.md` §Convergence failure.
4. Hard blocker: permission denial, missing credential, irreversible destructive action without authorization, or fundamental scope conflict. Return BLOCKED.
5. **Cap exhaustion (mandatory, no default).** The operator MUST declare `max_iterations` (positive integer) and `max_wallclock_min` (positive integer) at `goal_mode=open_goal` invocation time; an optional `dry_run` boolean (default `false`) may also be declared. Neither cap field has a default - an invocation missing either is refused before Phase 1 with the verbatim message: `"goal_mode=open_goal requires max_iterations and max_wallclock_min to be declared - no unbounded default is permitted. Re-invoke with both fields set."` The loop exits with `termination_reason: cap_reached_iterations` or `cap_reached_wallclock` when EITHER (a) `batch-state.json.open_goal.iteration` reaches `max_iterations`, or (b) wallclock elapsed since `batch-state.json.wallclock_started_at` reaches `max_wallclock_min`. **The outer-loop cursor lives in `batch-state.json`, not `loop-state.json` - `loop-state.json` is cleared every iteration by Phase 12 and cannot hold cross-iteration state.** This cap sits above rules 2-3 (which bound Skeptic/QA fix-passes INSIDE a single iteration).

State is written to `loop-state.json` at every phase transition. On interruption or session exit, `status: "interrupted"` is written and the loop can resume per `content/sections/07-cross-session-loop-resume.md`.

## Risk and review discipline

This section is the yolo-guard. It is structural, not advisory.

**(a) A trigger is an input to the conductor, not a worker-spawn bypass.** The trigger fires the conductor, which THEN applies the standard risk-classification table before spawning any worker. The trigger never spawns workers directly. An action-triggered flow enters the conductor at the same entry point as a manual invocation; it does not skip or short-circuit any step.

**(b) Each iteration of an open-goal loop is treated as a new Elevated-eligible task.** It gets a fresh risk declaration, and for any Elevated unit, a fresh independent Skeptic. `goal_mode=open_goal` relaxes or suspends no existing review obligation. The Skeptic that validates this iteration is independent - it is not the same Skeptic instance that reviewed the previous iteration.

**(c) Auditability.** An open-goal iteration records a `risk_declared` field in `batch-state.json.open_goal` - the durable outer-loop cursor, not `loop-state.json`, which Phase 12 clears every iteration and therefore cannot hold cross-iteration audit state (evidence that risk classification was performed that iteration). An iteration with no `risk_declared` is a protocol violation. The field may be set to `"low"`, `"elevated"`, or `"trivial"` to match the classification outcome.

**(d) This is what separates an action-triggered / open-goal loop from the rejected "yolo-mode"**: the trigger removes the human from the START, never from the REVIEW. Every unit that goes through an automated loop is subject to the same adversarial Skeptic review as a manually-triggered unit. Automated start does not imply automated approval.

**(e) The goal-condition-evaluator is a cost lever, not a review lever, and never triggers the generic BLOCKED-escalation path.** Invariant (b) above states: *"Each iteration of an open-goal loop is treated as a new Elevated-eligible task. It gets a fresh risk declaration, and for any Elevated unit, a fresh independent Skeptic. `goal_mode=open_goal` relaxes or suspends no existing review obligation. The Skeptic that validates this iteration is independent - it is not the same Skeptic instance that reviewed the previous iteration."* `goal-condition-evaluator` (Tier 1/haiku default) does not touch this invariant, and its spawn is scoped by it: the conductor spawns the evaluator ONLY for an iteration whose `risk_declared` is `elevated` and which produced a clean Skeptic sign-off - the same iterations (b) already requires a fresh independent Skeptic for. For a `risk_declared: low` or `risk_declared: trivial` iteration (per invariant (c)), no Skeptic sign-off exists to run the evaluator after, so the conductor evaluates `goal_condition` itself directly instead of spawning the evaluator - this is the designed path for Skeptic-less iterations, not a failure path. Every Elevated iteration still gets its own fresh risk declaration and its own fresh independent Skeptic exactly as (b) requires, regardless of whether the evaluator is present, absent, or failing. The evaluator's sole output is continue-vs-stop the loop (`GOAL_MET: true|false` plus a one-line evidence quote, or a structural `BLOCKED` when spawned without a confirmed Skeptic sign-off); it is read-only and structurally forbidden from raising, waiving, or overriding a Skeptic finding, and from making any correctness or safety judgment of its own. Critically: an evaluator `BLOCKED` return is NOT the generic Worker-`BLOCKED`-means-immediate-`cap_reached`-escalation semantics defined in `content/references/subagent-protocol.md` §Loop transition rules - that rule governs Engineer status inside a Skeptic/QA fix-pass loop, not this evaluator. The conductor treats an evaluator `BLOCKED` exactly like evaluator unavailability, error, timeout, or malformed output: it falls back to conductor-direct evaluation of `goal_condition` and the loop proceeds - it does NOT halt the loop. Introducing this role changes WHO performs the cheap continuation check on Elevated iterations; it changes nothing about WHO gates correctness or safety, which remains the Skeptic, unconditionally, and it introduces no new way for a legitimate iteration to be halted.

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

`content/sections/07-cross-session-loop-resume.md` documents the loop-state persistence and resume semantics that the open-goal loop inherits: `loop-state.json` writes at every phase transition, resumable phases, and the interruption recovery protocol. As of DS-75 - newly wired, low field mileage - `goal_mode=open_goal` is a live invocation parameter. The outer-loop cursor (`active`, `goal_condition`, `iteration`, `max_iterations`, `risk_declared`, `termination_reason`, `dry_run`) lives in the DURABLE `batch-state.json.open_goal` object, not `loop-state.json` (which Phase 12 clears every iteration), alongside a `mode` discriminator (`"batch" | "open_goal" | "single_ticket_capped"`). See `content/commands/implement-ticket.md` "Phase 0a-open-goal", Phase 6 "Open-goal condition check", and Phase 12a for the wiring. The manual/scheduled/action-triggered TRIGGER plumbing (cron, CI, webhook infrastructure) remains outside AE scope, unchanged.
