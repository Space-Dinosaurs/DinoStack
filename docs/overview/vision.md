# DinoStack Product Vision (North Star)

**Status:** Ratified (committed 2026-06-28). This is the operator-owned product-intent layer - the
lens every review and design decision is measured against. Authored 2026-06-24.

## The problem

Agentic engineering has made code generation cheap. The scarce resource is now the **operator's
attention** — the cost of deciding what to build, trusting that it was built correctly, and not
having to babysit the machine to find out. DinoStack is the protocol layer that makes delegated
work *trustworthy enough to ignore*: structured delegation, risk classification, adversarial
review (the Skeptic loop), code-quality gates, and named agents, so an operator can hand off a
task and get back a verifiable outcome.

## North Star (what every change should serve)

1. **Guard operator attention.** Surface decisions and work-stoppages, not status. A change that
   adds capability but increases what the operator must read, watch, or babysit is a regression,
   not a feature. (The "attention test" is the tie-breaker when trade-offs are unclear.)
2. **Produce verifiable outcomes autonomously.** Agents should drive work to a checkable result
   — tests/lints/gates passing, an adversarial Skeptic sign-off, a clear `ok | needs_human |
   blocked` exit — without a human in the loop for routine steps. Verifiability is what makes
   autonomy safe to trust.
3. **Low friction.** Sensible defaults, minimal setup, global-default/per-project-override
   everywhere. The protocol should reduce ceremony, not add it.
4. **Works for everyone (universality).** The protocol is a shared, portable package — every
   rule, command, and agent must work for any operator, not just its author. No operator's
   identity, workspace, tracker, or local setup may be baked into shared behavior: resolve
   per-operator context at runtime (e.g. "my assigned tickets" via the tracker's own
   current-user, scoped to the configured project — never a hardcoded account or workspace),
   honor the global-default / per-project-override seam, and degrade gracefully when a
   capability isn't configured rather than breaking. A change that only works for its author's
   setup is a regression. (The "portability test": would this behave correctly for a teammate
   with different credentials, a different tracker, or a different harness?)
5. **Guard agent context.** Agent context is a scarce resource, exactly the way operator
   attention is - this pillar is the agent-facing counterpart to Pillar 1. Prefer changes that
   reduce what an agent must load or emit to do the same job at equal or better quality: cut
   duplicated prose, unconsumed return fields, always-loaded content that could be trigger-loaded
   instead, and narration that surfaces no decision. That boundary is exact, not a matter of
   degree: efficiency is won only by removing waste. It is never won by removing a gate, a review
   round, a verification step, or an enforcement floor - an enforcement floor is not waste, and
   trimming verification to save tokens is a regression against Pillar 2, not a win against this
   one. This matches existing precedent: capability and efficiency changes move the risk-profile
   dial, they never remove an enforcement floor. (The "efficiency test": does this change reduce
   what an agent must load or emit to do the same job at the same correctness? A single session
   once found 21 subagent return fields with no downstream consumer and 15 of 17 agent contracts
   with no output-length constraint - waste of exactly this shape.)
6. **Shorten wall-clock time to a finished, verified result.** This is distinct from the other
   two resource pillars: Pillar 1 is what the operator must read, Pillar 5 is what an agent must
   load, this pillar is how long the operator waits. It can legitimately conflict with Pillar 5,
   and this vision says so rather than pretending they always align: parallel fan-out spends more
   total tokens to finish sooner, while a chain of small serial rounds spends fewer tokens and
   takes far longer. When the two conflict, prefer the faster wall-clock outcome unless the token
   cost is disproportionate - state that lean explicitly so an agent can act on it without asking.
   Concretely: run independent units in parallel rather than serializing them, batch findings into
   one rework round rather than one round per finding, do not block behavior work behind
   infrastructure work, prefer same-PR rework over a fresh PR-and-CI cycle per round, and count CI
   cycle time as part of the cost of an extra round. The same boundary as Pillar 5 applies just as
   exactly here: speed is won only by removing serialization and waste, never by removing a gate,
   a review round, a verification step, or an enforcement floor - shipping unverified work is not
   fast, it defers the cost. (The "latency test": does this change shorten the path from request
   to verified result without removing verification? A single session once took roughly 10 hours
   and 15 review rounds on one change, with independent units run serially, one review round per
   individual finding, and three units blocked behind an infrastructure-only unit that shipped no
   user-visible behavior.)

## What it does

Provides the portable, evolving rule set + agent definitions that let an operator delegate
software work to sandboxed AE teams and receive results that are reviewed, gated, and ready to
trust — escalating to the human only for genuine decisions.

## Explicit non-goals

- **Not** a tool that requires the operator to watch it work or read everything it produces.
- **Not** capability-for-capability's-sake: features that raise attention tax without a
  proportional autonomy/verifiability gain are out of scope.
- **Not** a finished product — it is a living system meant to evolve as patterns improve.
- **Not** single-operator software: behavior hardwired to one person's identity, tracker,
  workspace, or machine has no place in the shared rule set.
- **Not** a license to cut verification for token savings: a gate, review round, or enforcement
  floor removed to reduce context cost is a regression against verifiability, never a win for
  context efficiency.
- **Not** speed at the cost of verification: a gate, review round, or enforcement floor removed
  to finish sooner is a regression against verifiability, never a win for wall-clock time.

## How to use this for PR alignment

A pull request is **aligned** if it advances at least one North Star pillar without regressing
another (especially the attention test). A PR is **misaligned** if it adds operator attention
tax for little autonomy/verifiability gain, makes outcomes harder to verify, increases friction
without justification, pulls the methodology toward "human must babysit," fails the
portability test (works only for the author's identity, tracker, or setup), or grows
always-loaded surface, duplicates binding prose, or adds an unconsumed output field without a
proportional gain (fails the efficiency test), or needlessly serializes independent work, spends
a full review cycle on a single non-blocking finding, or otherwise adds wall-clock delay without
a proportional gain (fails the latency test). Symmetrically, a PR that cuts a gate, review round,
verification step, or enforcement floor to save tokens or to finish sooner is also misaligned,
regardless of how it scores on the efficiency or latency test - that trade-off is never on the
table. Misalignment is a *direction* signal for the operator — not necessarily a request-changes
verdict on correctness.
