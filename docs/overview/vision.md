# DinoStack Product Vision (North Star)

**Status:** Ratified (committed 2026-06-28). This is the operator-owned product-intent layer - the
lens every review and design decision is measured against. Authored 2026-06-24; synthesized from
DinoStack's README/CLAUDE.md and the Helios vision
(`../helios/docs/overview/vision.md`), which DinoStack exists to serve.

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

## What it does

Provides the portable, evolving rule set + agent definitions that let an operator delegate
software work to sandboxed AE teams and receive results that are reviewed, gated, and ready to
trust — escalating to the human only for genuine decisions.

## Explicit non-goals

- **Not** a tool that requires the operator to watch it work or read everything it produces.
- **Not** capability-for-capability's-sake: features that raise attention tax without a
  proportional autonomy/verifiability gain are out of scope.
- **Not** a finished product — it is a living system meant to evolve as patterns improve.

## How to use this for PR alignment

A pull request is **aligned** if it advances at least one North Star pillar without regressing
another (especially the attention test). A PR is **misaligned** if it adds operator attention
tax for little autonomy/verifiability gain, makes outcomes harder to verify, increases friction
without justification, or pulls the methodology toward "human must babysit." Misalignment is a
*direction* signal for the operator — not necessarily a request-changes verdict on correctness.
