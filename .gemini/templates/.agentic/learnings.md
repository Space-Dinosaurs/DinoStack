# Learnings

Structured learnings captured across sessions. Two entry types coexist in this
file. Classification rules and guardrail-first precedence are in
`content/references/capture-classification.md`.

## Entry types

**`LRN-YYYYMMDD-XXX`** - bug-fix learning. Produced by `learnings-agent`
(on `skeptic-resolved` / `error-fixed` events) and `learning-extractor`
(Phase 6 clean exit). Fields: Discovered, Severity, Domain, Pattern, Fix, Source.

**`KNW-YYYYMMDD-XXX`** - knowledge learning. Produced by `learnings-agent`
(on `tool-failure-workaround`, `architectural-decision`, `cross-component-gotcha`,
`user-pattern` events). No Severity field. Fields: Discovered, Domain, Fact,
Why-it-matters, Source.

`LRN-` and `KNW-` maintain independent per-day counters. On the same day the
first LRN is `LRN-20260613-001` and the first KNW is `KNW-20260613-001`.

## Format

```markdown
## [LRN-YYYYMMDD-XXX] <title>

**Discovered:** YYYY-MM-DD (ticket: ID | session)
**Severity:** Critical | Major | Minor
**Domain:** <domain-tag>
**Pattern:** <symptom + root cause, 1-2 sentences>
**Fix:** <actionable "when you see X, do Y", 1-2 sentences>
**Source:** <path:line | PR | context>

## [KNW-YYYYMMDD-XXX] <title>

**Discovered:** YYYY-MM-DD (ticket: ID | session)
**Domain:** <domain-tag>
**Fact:** <env/tooling fact, dead-end, where-things-live, or decision+rationale>
**Why-it-matters:** <the future-token cost this saves>
**Source:** <path:line | command | URL | context>
```

## Entries

<!-- Append new entries at the bottom. Target: under 50 entries total.
     Prune entries whose pattern has been absorbed into AGENTS.md or MEMORY.md. -->
