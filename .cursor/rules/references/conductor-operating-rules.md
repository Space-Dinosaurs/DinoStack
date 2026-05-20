<!--
Purpose: Conductor operating rules extracted from content/sections/02-delegation.md.
         Covers anti-patterns, common rationalizations, permission-blocked fallback,
         methodology-file editing routing, parallel Investigator pattern, wrap-ticket
         writer carve-out, and learnings-agent background capture.

Public API: Read-only reference. Load on trigger when conductor encounters a
            stop-or-act ambiguity, permission-blocked Worker return,
            methodology-file edit request, multi-surface investigation need,
            wrap-ticket sequencing question, or learnings-agent first event.

Upstream deps: content/sections/02-delegation.md (parent section; gate rules,
               spawn threshold, and stop-frequency table live there).
               content/agents/wrap-ticket.md, content/agents/learnings-agent.md.

Downstream consumers: content/sections/02-delegation.md (inline pointers from
                      each extracted block).

Failure modes: Prose reference; does not auto-execute. Permission-blocked
               fallback requires immediate Skeptic on the applied edit -
               skipping that Skeptic is the critical failure mode. learnings-
               agent session file (.agentic/learnings-agent.session) is
               removed by Stop hook on exit; a missed removal blocks re-spawn.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Delegation. Read that section first for the core conductor rules, spawn threshold, and stop-frequency table.

# Conductor operating rules - full reference

## Anti-patterns

- Stopping after one unit of a multi-unit plan to ask if the next unit should be done. The plan is the answer.
- Asking permission to fix a broken test discovered during work. Fix it.
- Asking permission to create an obvious dependency (a missing import, type definition, or upstream endpoint a downstream task is waiting on). Create it.
- Asking permission to look something up. Look it up.
- Presenting the user with 2+ options and asking which to pick. If there are options, pick the best one using the default-and-proceed protocol and note the choice.
- Returning BLOCKED from a Worker over a design-taste call. Pick the option that best matches surrounding code and return DONE with the choice noted.

## Common rationalizations to reject

- "Looks simple" - not a Low signal
- "Following the spirit, not the letter" - violating the letter is violating the spirit
- "Only one file / few lines" - line count is not a risk signal
- "I already reviewed it myself" - self-review is for Low risk only
- "Moving fast, can skip this once" - speed is not a Low signal
- "The Skeptic will catch any mistakes" - the Skeptic reviews Worker output; it does not excuse skipping risk classification or spawning a Worker
- "This change is too minor to bother with a Worker" - delegate on risk signals, not on size; the Worker overhead is small, the cost of an unreviewed error is not
- "I can figure out the task structure / parallelization myself" or "this is obviously a single-unit task" - conductor does not self-assess task structure, unit count, or parallelization; delegate that reasoning to the orchestration-planner; the only valid skip is when a preceding agent has already returned a single atomic unit
- "The change is obviously fine and a Skeptic would just rubber-stamp it" - that gut feel is itself a **cognitive-surrender flag**, not a green light. The instinct that review is unnecessary is precisely when independent review is most valuable. Reclassify as Elevated and spawn the Skeptic anyway.

## Permission-blocked fallback

This fallback applies exclusively to protocol/infrastructure files that are NOT methodology documents - installer scripts (`install.sh`, `build.sh`), git hooks, project configs, and `settings.json`. It does NOT apply to any file under `~/agentic-engineering/` - those are governed by `/update-agentic-engineering` (see that command for the authoritative process). The boundary is physical location - any file under `~/agentic-engineering/` is governed by /update-agentic-engineering regardless of its role; any infrastructure file outside that path is governed by this fallback.

When all three conditions are met:

1. A Worker was spawned to apply an Edit to an infrastructure file outside `~/agentic-engineering/`.
2. The Worker's return output begins with or contains a BLOCKED status explicitly citing an Edit permission denial by the Claude Code permission system (exact form observed in practice: "BLOCKED - Edit permission was denied by the permission system").
3. No other unblocked edit path is available.

Then: the main session may apply the edit directly, followed immediately by spawning a Skeptic on the applied diff before any further action.

## Editing methodology files

Always route through `/update-agentic-engineering` for edits to `content/**`, `.codex/skill/**`, the build scripts (`.claude/build.sh`, `.codex/build.sh`, `.cursor/build.sh`), `hooks/**`, or `.codex/hooks/**`. These are the methodology and tooling source files; the command exists to handle the git sync (pull before edit, commit+push after) that prevents cross-machine conflicts. Note: `.claude/skills/agentic-engineering/**` files are hardlinks into `content/` (same inodes) - editing them is functionally editing `content/` and they remain in scope via the `content/**` rule. Files outside those paths - docs/, README, top-level config, and regenerated build artifacts under `.claude/commands/`, `.codex/commands/`, `.cursor/commands/` - may be edited directly under the normal Trivial/Elevated tiers; no special routing needed. If you find yourself about to Edit a methodology file in one of the in-scope paths, stop and invoke `/update-agentic-engineering` instead.

## Parallel Investigators

When investigation spans multiple independent surfaces (e.g., backend data layer, frontend components, and database schema each require separate mapping), the conductor MAY spawn multiple Investigators in a single message (parallel, background). Each Investigator scopes to one surface. The conductor then merges their briefs into a single input for one Architect. The Architect receives all surface findings together and makes design decisions on the complete picture. Example: a feature touching API routes, UI components, and a migration can fan out three Investigators (routes, UI, schema) in one message, then pass all three briefs to the Architect. The single-Architect rule still holds - do not spawn separate Architects per surface, as cross-surface consistency is the Architect's job.

## wrap-ticket writer carve-out

wrap-ticket is the **automated writer in Phase 11b** for `MEMORY.md`, `decisions.md` (resolver: AGENTS.md convention -> ./decisions.md -> docs/decisions.md -> docs/adr/ -> create at cwd), and `.agentic/context.md` (append-merge under `## Recent Focus` only). Operators retain manual write rights for these files. The Stop hook retains its `.agentic/context.md` auto-write. `/wrap` retains its own write paths and serializes with wrap-ticket via `.agentic/wrap.lock` (both acquire the same lock; concurrent runs are not permitted). wrap-ticket MUST NOT touch `.agentic/findings.md` (findings-curator owns), `.agentic/qa.md` (qa-engineer owns), `.agentic/tasks.jsonl` / `.agentic/loop-state.json` / `.agentic/batch-state.json` (conductor sole-writer), or any `AGENTS.md` (`/wrap` owns). wrap-ticket failure is soft-fail and NEVER blocks Phase 12 cleanup or PR completion.

## learnings-agent background capture

The conductor spawns `learnings-agent` in the background with `run_in_background: true` the first time a learning-worthy event occurs in a session. Before spawning, the conductor checks `.agentic/learnings-agent.session`; if present and its `session_id` matches the current session, the agent is already active and the conductor sends the event message to the running agent. Learning-worthy events: Skeptic finding resolved (after sign-off), error->fix cycles (especially after multiple attempts), tool failure with workaround discovered, architectural decision made during implementation, cross-component gotcha discovered, user explicitly calling out a reusable pattern. The conductor's message contains: `event_type`, `description`, `resolution`, `domain_tag`, `severity`. The agent writes immediately to `.agentic/learnings.md` (and optionally to `MEMORY.md` for project-affecting decisions); no batching. The Stop hook removes `.agentic/learnings-agent.session` on session exit. This is additive - `/wrap` still handles AGENTS.md updates, rolling session labels, compression, and full session wrap. If the learnings-agent fails, the conductor warns and proceeds (soft-fail).
