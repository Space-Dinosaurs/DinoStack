<!--
Purpose: Authoritative reference for the Capture Classification system - the
         mandatory protocol gate that governs WHEN and WHETHER to write a
         learning entry versus write a guardrail. Replaces discretionary
         learnings capture with a mechanical two-gate bar and a precedence
         chain that makes prose learning the LOWEST tier of capture.

Public API: Read-only reference document. The table, guardrail-first
            precedence chain, and decision rule are the consumable interface.
            Cross-referenced from:
              content/references/conductor-operating-rules.md §learnings-agent
              (mandatory triggers + per-trigger Capture declaration);
              content/references/regression-test-obligation.md
              (guardrail-first tie-in; a regression test IS the capture for
              code-testable failure modes).

Upstream deps: content/references/regression-test-obligation.md (defines
               what counts as a guardrail at the code level);
               content/references/conductor-operating-rules.md §learnings-agent
               (mandatory trigger list and per-trigger declaration format;
               owned by U3 in the learnings-capture-system plan).

Downstream consumers: conductor (applies guardrail-first precedence at each
                      mandatory trigger; emits Capture: MUST/SKIP declaration);
                      learnings-agent (applies the table to classify incoming
                      events before writing LRN or KNW entries);
                      Stop-hook backstop (hooks/stop-context.js;
                      detectCaptureGap uses the MUST tier signals to decide
                      whether to nudge at session exit).

Failure modes: Prose; does not execute. When this reference drifts from
               the actual trigger list in conductor-operating-rules.md
               §learnings-agent, agents may mis-classify and either under-
               capture (MUST cases silently skipped) or over-capture (SKIP
               cases written as entries). Stale entry is worse than missing.

Performance: Standard.
-->

> Parent: METHODOLOGY.md §Events log and conductor-operating-rules.md §learnings-agent.
> Read those sections for writer scope and mandatory trigger list before applying this table.

# Capture Classification

## Guardrail-first precedence (runs BEFORE the table)

A learning entry is the lowest tier of capture. Before applying the classification
table, run this three-step check in order:

**(a) Can this be a guardrail?**
If the knowledge can be encoded as a regression test, type annotation, lint rule,
schema constraint, assertion, or CI check - write the guardrail instead. The guardrail
IS the capture. Add a learning only for the residual that a guardrail cannot express:
the WHY, the dead-ends, the root-cause reasoning that a passing test does not make visible.
See `content/references/regression-test-obligation.md` for what counts as a valid guardrail
at the code level.

**(b) Already covered?**
If an existing guardrail, AGENTS.md entry, MEMORY.md entry, glossary term, or the diff
itself already encodes the knowledge - SKIP. Do not duplicate.

**(c) Else apply the table.**
Only reach here when (a) and (b) both fail to resolve. Apply the two-gate bar below.

## Classification table

| Tier | Signal | Action | Declaration |
|---|---|---|---|
| MUST | BOTH gates hold: (1) expensive for a future agent to re-derive AND (2) no better home as a guardrail or existing doc | Capture `LRN` (bug-fix residual) or `KNW` (knowledge/env fact/dead-end/architectural rationale) | Stated at the trigger: `Capture: MUST - [signal]. Writing KNW/LRN entry.` |
| SHOULD | One gate strong, the other marginal | Capture if cheap; prefer promoting to AGENTS.md/MEMORY.md at next /wrap | Stated at the trigger |
| SKIP | Any of: test/type/lint/CI already enforces it; visible in the diff, code, AGENTS.md, or MEMORY.md; a one-off that will not recur; a restatement of protocol already in context | Do not write | Silent |

**SKIP exclusion list (do not write a learning when any of these hold):**

- A regression test, type, lint rule, schema, or CI check already enforces the constraint.
- The fact is visible by reading the diff or the code directly.
- The fact is already in AGENTS.md, MEMORY.md, or the project glossary.
- It is a one-off tied to a specific environment or timestamp that will not recur.
- It restates a methodology rule already loaded in the agent's context.

## Two-gate bar

MUST tier requires BOTH conditions to hold:

1. **Expensive to re-derive** - a future agent starting cold would need non-trivial tool calls,
   failed attempts, external lookups, or multi-step diagnosis to rediscover it.
2. **No better home** - a guardrail (test, type, lint, assertion, CI check) cannot encode it,
   AND it is not already in AGENTS.md / MEMORY.md / the diff.

If either gate fails, drop to SHOULD or SKIP.

## Decision rule

> *"If I had to figure it out, the next agent shouldn't have to - but if a guardrail can stop
> them needing to figure it out at all, write the guardrail."*

## Dual entry schema

Two entry types live in `.agentic/learnings.md`. Brief summary; full schemas are in the
template at `content/templates/.agentic/learnings.md`:

- **`LRN-YYYYMMDD-XXX`** - bug-fix learning. Fields: Discovered, Severity, Domain, Pattern,
  Fix, Source. Used for bug-shaped findings from the Skeptic loop and error-fix loops.
- **`KNW-YYYYMMDD-XXX`** - knowledge learning. Fields: Discovered, Domain, Fact,
  Why-it-matters, Source. No Severity field. Used for env facts, dead-ends, architectural
  rationale, tool-failure workarounds, and cross-component gotchas. LRN and KNW maintain
  independent per-day counters.

`learnings-agent` emits both types based on `event_type`. `learning-extractor` emits LRN
only. KNW promotion to MEMORY.md happens at /wrap.

## Mandatory triggers and per-trigger declaration

Mandatory triggers and the per-trigger `Capture:` declaration format are owned by
`content/references/conductor-operating-rules.md §learnings-agent` (implemented in U3
of the learnings-capture-system plan). Cross-reference that section for the trigger list,
the `tool_failure_workaround` emit protocol, and the Stop-hook backstop that detects
capture gaps at session exit.

Per-trigger declaration mirrors the Risk block:

```
Capture: MUST - [signal]. Writing KNW/LRN entry.
Capture: SKIP - [guardrail added | already in AGENTS.md | one-off].
```

A trigger event with no declaration is a protocol gap; the Stop-hook backstop
(`hooks/stop-context.js` `detectCaptureGap`) is the mechanical catch.
