# implement-ticket eval

Tier 2, command-mode. Measures the local-artifact subset of
`/implement-ticket` Phases 2-8 and Phase 12 against seeded single-unit
fixtures.

## What this measures

- Phase 2-3: reads codebase, produces a (possibly implicit) plan. The
  eval does not score plan shape directly - it scores the artifacts the
  plan drives (branch, diff, commit).
- Phase 4: branch creation (scored on `branch_prefix` match off the seed
  base branch).
- Phase 5: implementation diff (scored on `must_touch_any_of` and a
  scope-LOC envelope).
- Phase 6: Skeptic loop. In practice the single-unit fixtures in this
  corpus rarely induce Critical/Major findings - a clean pass is
  expected. The loop-state axis scores the well-formedness of
  `.agentic/loop-state.json` regardless of whether the loop actually
  iterated.
- Phase 7: quality gate. The scorer uses a tiered proxy (pass artifact
  in the commit message, or a clean termination_reason, or a second
  commit suggesting a fix pass).
- Phase 8: commit (HEAD commit message must contain the fixture's
  `commit_message_must_contain` substrings). Push is explicitly
  directed NOT to happen (fixture has no remote).
- Phase 12: loop-state cleanup. Writing the file is what the loop-state
  axis primarily rewards; cleanup to `complete` is the tier-1
  well-formedness signal.

## What this explicitly DOES NOT measure (proxy caveats)

- **Phases 9-11 are skipped.** The non-interactivity directive in the
  prompt tells the runner to skip `gh pr create`, CI Test URL polling,
  and tracker posting. These phases require network, auth, and a live
  GitHub repo the eval cannot provide.
- **No remote push.** Phase 8's `git push -u origin` step is directed
  to be elided; the fixture has no remote configured.
- **TRACKER=none only.** Fixtures do not seed a `## Tracker` or
  `## Linear` section. The prompt builder fails fast if a fixture's
  AGENTS.md does include one.
- **Single-unit plans only.** Phase 3b (orchestration-planner) is
  technically in scope, but no fixture in this corpus crosses the
  multi-unit threshold. Parallel fan-out (Phase 5 parallel path) is not
  exercised.
- **Live Skeptic/QA convergence.** The loop-state axis measures
  schema well-formedness, not whether findings genuinely converged. A
  Phase 6 cap_reached or blocked termination can still score full
  loop-state credit if the schema is correct.
- **Quality-gate runtime signal.** The scorer does not execute the
  archetype's actual QUALITY_CMD. The tiered quality axis infers gate
  behavior from commit-message hints and loop-state termination. A
  maintainer edit that changes how Phase 7 narrates the gate result may
  move fixture scores even though the underlying quality behavior is
  unchanged - this is a property of the proxy.

## Scorer axes and weights (v1)

| Axis | Weight | Shape | Vacuous? |
|---|---|---|---|
| branch | 0.10 | binary: starts with `branch_prefix` and != base | if `branch_prefix` absent, credit if HEAD != base |
| edit | 0.20 | binary: diff touches any `must_touch_any_of` path | if unset, credit if any diff exists |
| loop_state | 0.20 | tiered: full / exists-wrong / missing (1.0 / 0.5 / 0) | vacuous if `loop_state_required: false` |
| commit | 0.15 | fractional: substring hit rate against `commit_message_must_contain` | if unset, credit if non-empty message |
| quality | 0.15 | tiered: pass-artifact / fail-acceptable / vacuous (1.0 / 0.5 / 0) | vacuous if `quality_required: false` |
| scope | 0.10 | tiered: under / grace / over (1.0 / 0.5 / 0) on `max_loc` | vacuous if `max_loc` unset |
| forbidden | 0.10 | binary: no `must_not_exist` paths present | always applicable |

Weights sum to 1.0 exactly (runtime assertion).

Extras penalty (capped at 0.15):
- 0.10 if any forbidden path present
- 0.05 if an unexpected tracker reference (e.g. "Closes LINEAR-123",
  "linear.app", "atlassian.net") leaks into the commit message.

## Fixture corpus

- **it-001** node-ts, feature: add `isEven` helper (ceiling)
- **it-002** python, bugfix: percent() off-by-one (ceiling)
- **it-003** node-ts, scope-stressor: add `/healthz` handler but do NOT
  refactor sibling modules (below-ceiling ~0.80-0.90; tempts the worker
  to clean up `logger.ts`)
- **it-004** node-ts, quality-gate fix-path: strict lint banning `_tmp`
  (below-ceiling ~0.80; second-pass fix variance)
- **it-005** go, docs touch: add `## Run` to README (ceiling)

## Invocation-path caveat

`/implement-ticket` is a slash command. Under the Tier 2 HOME redirect
the slash command is not installed into the fake `~/.claude/`, so we
inline the verbatim body of `content/commands/implement-ticket.md` into
the `-p` prompt along with a synthetic auto-memory banner, a
fixture-context preface, a non-interactivity directive, a
pre-setup step (`git init` + seed commit), a required-outputs block,
and a `IMPLEMENT_TICKET_DONE` completion marker. See
`evals/LEARNINGS.md` "Slash commands are not discoverable under
redirected HOME" for why this is the right shape.

Tier 2 command-mode runs are raw-prompt by design; the runner does NOT
prefix `[raw-prompt]` on TSV rows for this mode.
