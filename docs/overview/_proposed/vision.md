# DinoStack Product Vision (North Star)

> **Staged proposal - not canonical.** Discovery draft in `docs/overview/_proposed/`. The operator-owned `docs/overview/vision.md` has not been written or modified. Review, edit, and promote this when it matches your intent.

**Status:** Condensed proposal derived from the ratified `docs/overview/vision.md` (2026-06-28).
Same eight pillars, same boundaries, fewer bytes.

## The problem

Code generation is cheap; the scarce resource is the **operator's attention**: deciding what to
build, trusting it was built correctly, and not babysitting the machine to find out. DinoStack is
the protocol layer that makes delegated work *trustworthy enough to ignore*: structured
delegation, risk classification, adversarial review (the Skeptic loop), code-quality gates, and
named agents.

## North Star (what every change should serve)

1. **Guard operator attention.** Surface decisions and work-stoppages, not status. A change that
   adds capability but increases what the operator must read, watch, or babysit is a regression,
   not a feature. (The "attention test" is the tie-breaker when trade-offs are unclear.)
2. **Produce verifiable outcomes autonomously.** Agents should drive work to a checkable result -
   tests/lints/gates passing, an adversarial Skeptic sign-off, a clear `ok | needs_human |
   blocked` exit - without a human in the loop for routine steps. Verifiability is what makes
   autonomy safe to trust. The conductor does not do the work - it orchestrates agents that do. A
   conductor that investigates, diagnoses, or asserts unverified conclusions has substituted its
   own unchecked judgment for the adversarial verification this pillar guarantees. (The
   "orchestration test": did this claim/artifact come from a subagent return or a conductor read
   verified against `origin/main`, or did the conductor manufacture it directly? The latter is not
   ready to spawn on.)
3. **Low friction.** Sensible defaults, minimal setup, global-default/per-project-override
   everywhere. The protocol should reduce ceremony, not add it.
4. **Works for everyone (universality).** Every rule, command, and agent must work for any
   operator, not just its author. No operator's identity, workspace, tracker, or local setup may
   be baked into shared behavior: resolve per-operator context at runtime (e.g. "my assigned
   tickets" via the tracker's own current-user, scoped to the configured project, never a
   hardcoded account or workspace), honor the global-default / per-project-override seam, and
   degrade gracefully when a capability isn't configured rather than breaking. (The "portability
   test": would this behave correctly for a teammate with different credentials, a different
   tracker, or a different harness?)
5. **Guard agent context.** Agent context is scarce exactly the way operator attention is; this
   pillar is the agent-facing counterpart to Pillar 1. Prefer changes that reduce what an agent
   must load or emit to do the same job at equal or better quality: cut duplicated prose,
   unconsumed return fields, always-loaded content that could be trigger-loaded instead, and
   narration that surfaces no decision. Efficiency is won only by removing waste. (The "efficiency
   test": does this change reduce what an agent must load or emit at the same correctness?)
6. **Shorten wall-clock time to a finished, verified result.** Pillar 1 is what the operator reads,
   Pillar 5 is what an agent loads; this is how long the operator waits. It can legitimately
   conflict with Pillar 5: parallel fan-out spends more tokens to finish sooner, a chain of small
   serial rounds spends fewer and takes far longer. When the two conflict, prefer the faster
   wall-clock outcome unless the token cost is disproportionate - state that lean explicitly so an
   agent can act on it without asking. Concretely: run independent units in parallel rather than
   serializing them, batch findings into one rework round rather than one round per finding, do not
   block behavior work behind infrastructure work, prefer same-PR rework over a fresh PR-and-CI
   cycle per round, and count CI cycle time as part of the cost of an extra round. (The "latency
   test": does this shorten the path from request to verified result without removing
   verification?)
7. **Prevent defects at the producing step, not just catch them at the reviewing step.** When a
   review check is mechanical - a grep, a diff, a count comparison, a lookup - give the producing
   agent that same check to run before it submits, so it never becomes a review round at all. This
   applies only to mechanical checks: judgment-based checks (logic errors, edge cases, an
   adversarial brief, a fabrication spot-check) require an independent reader and must NOT be
   left-shifted, because moving them to the author destroys the independence that makes them work.
   Left-shift is redundancy, not a handoff: the reviewer keeps running everything it ran before.
   (The "prevention test": does this move a mechanical check earlier without weakening the later
   one?)
8. **Machinery only as complicated as the benefit requires.** The methodology's own machinery -
   gates, hooks, count-pins, sweeps, counters, telemetry, and prose - is not exempt from Pillars 1,
   5, and 6: self-referential machinery that protects the methodology spends the same scarce
   attention, context, and wall-clock time as any other change, and is a cost charged against those
   pillars, not one outside them. No new gate, hook, count-pin, or enforcement mechanism ships
   without naming (a) a specific failure it would have caught and (b) the condition under which it
   retires - a permanent enforcement floor whose retirement condition is "never" satisfies (b) by
   naming it as such. An enumeration of banned shapes that grows by one entry per incident is a
   smell: the principle a mechanism should have generalized from is missing, not that the
   enumeration needs one more line. Binding prose lives at exactly one canonical site with pointers
   to it; a verbatim copy is justified only when the text is embedded directly into a spawn prompt
   (an agent cannot follow a pointer mid-task), is public-facing documentation serving a different
   audience than the methodology's own source, or is a one-to-two-sentence normative restatement at
   the point of use accompanied by a pointer to the canonical site. Simplification is won only by
   deleting non-floor machinery whose failure-catching is measured at zero yield. A mechanism with
   no named catch and no measured fires is not thereby a deletion candidate - it is first
   instrumented, or its measurement gap otherwise closed, so the question is answered by
   measurement, never by assumption. (The "simplicity test": can you name the specific failure this
   mechanism would have caught and the condition under which it retires? If either cannot be named,
   it does not ship.)

**The boundary shared by Pillars 5, 6, 7, and 8.** An enforcement floor is never removed to satisfy
a pillar, measured or not: it is not waste, it is never a pruning candidate however expensive it is
to run, and cutting a gate, review round, or verification step to save tokens, to finish sooner, or
to simplify is a regression against Pillar 2, never a win. This is the existing floor-vs-dial
precedent: capability and efficiency changes move the risk-profile dial, they never remove a floor.
Non-floor machinery is the separate case Pillar 8 governs: it becomes a deletion candidate only on
a measured zero yield, never on assumption alone. Left-shifting a mechanical check under Pillar 7
likewise never licenses weakening the reviewer's copy of it.

## What it does

Provides the portable, evolving rule set and agent definitions that let an operator delegate
software work to sandboxed AE teams and get back results that are reviewed, gated, and ready to
trust, escalating to the human only for genuine decisions.

## Explicit non-goals

- **Not** a tool that requires the operator to watch it work or read everything it produces.
- **Not** single-operator software: behavior hardwired to one person's identity, tracker,
  workspace, or machine has no place in the shared rule set.
- **Not** self-defending machinery: a gate/hook/pin whose only demonstrated catch is defects in
  other gates/hooks/pins is accretion, not protection - but removing an enforcement floor is never
  the remedy; the remedy is instrumentation or replacing the mechanism's justification, per Pillar
  8's boundary.

## How to use this for PR alignment

A pull request is **aligned** if it advances at least one pillar without regressing another
(especially the attention test). Run each pillar's parenthesized test against the diff; failing any
of them is misalignment, as is cutting a gate, review round, verification step, or enforcement
floor to save tokens, to finish sooner, or to simplify. Misalignment is a *direction* signal for
the operator, not necessarily a request-changes verdict on correctness.
