# /memory-update fixtures

Tier 2 command-mode eval for `content/commands/memory-update.md`.

## What this measures

The single durable side-effect: the contents and existence of
`.agentic/memory/MEMORY.md` after the command finishes. The scorer checks
six axes: file presence, bullet-count delta shape (new / update / noop),
required substrings, forbidden substrings, header well-formedness, and
absence of paths listed in `must_not_exist`.

## What this does NOT measure (proxy caveat)

`/memory-update` in production is a thin main-agent dispatcher that
spawns a BACKGROUND `general-purpose` Worker (`run_in_background: true`)
to do the relevance filter, verification, drafting, and write. The main
agent returns to the user immediately and the Worker writes out-of-band.

The eval has no way to reproduce the background-spawn channel under a
redirected HOME, so the prompt builder collapses the main-agent dispatch
and the Worker brief into a single inline session. The scorer therefore
does not measure:

- Whether a real invocation spawns the Worker in the background (vs
  blocking the user-facing conversation)
- Whether the main agent returns silently while the Worker writes
- Any signalling / escalation path between main agent and Worker

A maintainer edit to the main-agent-dispatch language that does not
change the Worker's verify/draft/write behaviour may not move any
fixture score. This is the same proxy category as the /wrap
session-transcript proxy (LEARNINGS Phase 5) and should be kept in mind
when reading TSV deltas.

## Fixture corpus

| ID | Scenario | Expected shape | Ceiling |
|---|---|---|---|
| mu-001 | New entry happy path (PostgreSQL + JSONB event store) | new | ceiling |
| mu-002 | Update in place (rate limit 100 -> 250 rps) | update | ceiling |
| mu-003 | No-op: decision already captured (Alembic migrations) | noop | below-ceiling |
| mu-004 | Does not qualify: conversational meeting scheduling | n/a (must_not_exist) | ceiling |
| mu-005 | Verification discipline: claim contradicts src/cache.ts | new | below-ceiling |

### Below-ceiling fixtures

- **mu-003.** The seeded MEMORY.md already captures the Alembic decision.
  A strict Worker returns "No-op: decision already captured" and leaves
  the file unchanged. A lenient Worker may still append a fuzzy-duplicate
  bullet (delta >= 1 -> shape="new", scoring 0.5 via the noop<->update
  adjacency gradient rather than the full 1.0 credit for a correct noop).

- **mu-005.** The decision context asserts a 900-second TTL and a
  10,000-entry cap, but `src/cache.ts` (seeded in the repo) defines
  `PROFILE_TTL_SECONDS = 300` and `PROFILE_MAX_ENTRIES = 5000`. Part 2
  of the Worker brief ("Verify your claims") requires reading the
  referenced files and softening or omitting unverifiable claims. A
  Worker that writes the numbers verbatim will be flagged by
  `forbidden_substrings`. A Worker that verifies and writes softened
  language (or omits the numbers entirely) scores ceiling on this axis.

## Invocation caveat

Slash commands are not discoverable under the redirected HOME used by
Tier 2 (see `evals/LEARNINGS.md` line ~99). The prompt builder inlines
the verbatim body of `content/commands/memory-update.md` into the
`claude -p` prompt, alongside a synthetic auto-memory banner, a
fixture-context preface, the decision context (as a substitute for
`$ARGUMENTS`), and a non-interactivity directive that tells the Worker
to write directly via Write / Edit rather than attempt a Task spawn.
