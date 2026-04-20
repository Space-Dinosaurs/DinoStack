# architect fixtures

Tier 1 eval fixtures for the `architect` named subagent
(`content/agents/architect.md`). Each fixture is a `fixture.yaml` with
`inputs.task_description` + `inputs.codebase_context` + `inputs.constraints`
and an `expected` block read by `evals/scoring/architect_lite.py`.

## What this measures vs. what it does NOT measure

**Measures:** the architect's ability to produce the 7-section plan skeleton
mandated by `content/agents/architect.md` (Approach, Codebase context, Data
model, API / interface design, Implementation steps, Trade-offs and
constraints, Open questions), commit to a single approach using the
enumerated vocabulary, surface the right API symbols and file paths, list
alternatives, and avoid anti-patterns (full rewrites on a hot-path fix,
mutable state in an event-sourced system, etc.).

**Does NOT measure** the architect's actual codebase-reading behavior.
Fixtures do not seed a live repository the agent can explore with Read,
Glob, and Grep. Instead `inputs.codebase_context` is authoritative inline
prose describing what the agent would otherwise discover. This is a
**prose-scoring proxy** for real codebase exploration, analogous to the
`/wrap` fixtures using a synthetic session transcript (see
`evals/LEARNINGS.md` Phase 5 session-transcript proxy caveat). A maintainer
edit to `architect.md` that changes exploration heuristics (e.g. "read entry
points first") cannot move fixture scores because there is no codebase to
explore. Edits to sectioning, vocabulary, commitment language, and output
structure ARE measurable.

**Bash tool caveat.** The architect's frontmatter grants Bash (read-only:
`find`, `cat`, `ls`, `grep`). Under Tier 1 isolation the runner drops Bash
from the allowed-tools list (`evals/runner/invoker.py` `_ALLOWED_TOOLS =
"Read,Grep,Glob,Task"`); the architect can still satisfy the read-only
contract via Read / Grep / Glob. If a future fixture genuinely depends on
Bash-shaped inspection it would need a tier upgrade, not a tool-list
widening under Tier 1.

## Fixture corpus

| id     | scenario                                  | expected approach_class  | headroom    |
|--------|-------------------------------------------|--------------------------|-------------|
| ar-001 | additive GET endpoint to Express API      | `additive_endpoint`      | ceiling-capable baseline |
| ar-002 | no-downtime schema migration + backfill   | `online_backfill`        | below-ceiling (SLA, dual-read post-mortem) |
| ar-003 | insert auth middleware into existing chain| `middleware_insertion`   | API-fidelity heavy |
| ar-004 | optimize CPU-hot ranker function          | `algorithmic_rewrite`    | below-ceiling (anti-pattern: full rewrite) |
| ar-005 | add feature to event-sourced booking svc  | `event_sourced_append`   | below-ceiling (anti-pattern: mutable table) |

## approach_class enum

The scorer does exact substring matching (underscore-or-space tolerant,
case-insensitive) against this closed set - enforced at the prompt layer via
`evals/runner/prompt.py:build_architect_prompt`:

```
in_place_migration
online_backfill
dual_write
middleware_insertion
algorithmic_rewrite
event_sourced_append
additive_endpoint
```

Adding a new class means editing both the prompt-builder enum AND
`_ARCHITECT_APPROACH_CLASSES` in `evals/runner/loader.py`. No synonym maps
in the scorer - vocabulary enforcement belongs in the prompt (LEARNINGS
22-26).

## Cold-reader check

Each fixture was drafted so a reader who has never seen
`content/agents/architect.md` cannot trivially guess the expected
`approach_class` from the task statement alone - the class must be inferred
from constraints + codebase conventions in `codebase_context`. Reword the
fixture if a cold reader can telegraph the answer (LEARNINGS 28-36).
