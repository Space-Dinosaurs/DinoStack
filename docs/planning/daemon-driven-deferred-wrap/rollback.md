# Rollback: Daemon-Driven Deferred `/wrap`

*Plan-tier artifact. Blast radius is low by construction: the feature is opt-in (`deferred_wrap_daemon: false` default) and inert when off - no daemon spawns, no marker staged, hooks fail-open.*

## Primary rollback: the toggle
The feature is gated behind `.agentic/config.json` `deferred_wrap_daemon` (default `false`). Setting it to `false` (or leaving the default) **stops all daemon spawns and marker staging immediately**, with zero effect on synchronous `/wrap`. This is the intended rollback for a behavioral problem found in the field - no code revert needed.

## Triggers (when to revert source, not just toggle)
- The integration Skeptic or G-E2E shows a `pending->ready` promotion outside SessionEnd, a daemon claim of a live session, or context.md clobbered.
- A hook regression breaks the normal (feature-off) Stop/SessionStart path - caught by `hooks/tests/`.
- The daemon leaks worktrees/markers or wedges on a hung child despite the timeout.

## Procedure
1. **Pre-merge (feature branch):** abandon the branch - nothing shipped. The branch is `feature/deferred-background-wrap` (evolving PR #184).
2. **Post-merge, behavioral issue:** flip `deferred_wrap_daemon: false` (config-only; instant). The daemon stops; `/wrap` Step 0a stages nothing.
3. **Post-merge, code defect:** `git revert` the offending unit's squash-merge commit (each unit is a distinct file set), regenerate adapters (`*/build.sh`), open a revert PR. The marker/sentinel/pid/heartbeat files are gitignored runtime artifacts - safe to remove: `rm -rf .agentic/wrap-pending-*.json .agentic/wrap/claude-host .agentic/wrap-daemon.pid .agentic/.heartbeats .agentic/wrap-daemon-auth-failed`.

## Partial-landing safety (the 10-unit merge order)
Every prefix of the merge order is safe because the daemon path is toggle-gated (default off) and the units write disjoint file sets:
- **U1 (marker-lib)** merged alone: stop-context.js stages per-session v3 markers, but with the toggle off and no daemon (U3 not merged), nothing consumes them. Fail-open; revertible in one commit. Schema v1->v3 is forward-harmless (a stray v1 single-file marker does not match the daemon's `wrap-pending-*.json` glob).
- **U8 (config)** merged alone: adds keys (default off) + doc count bumps. Inert.
- **U2/U3/U4 (hooks + daemon)** merged before the toggle is enabled: the SessionEnd/SessionStart hooks fire but the guarded launch is skipped when `deferred_wrap_daemon` is false. Inert until enabled.
- **U5 (wrap.md)** merged: `/wrap` is sync-default; Step 0a stages only when sentinel + toggle + non-guard all hold. With toggle off -> byte-identical.
- **U6 (wrap-enrichment removal)** merged: pure removal; the in-session enrichment path is gone (its only trigger - async `/wrap` - is removed by U5). No dangling consumer.
- **U9 (adapter regen)** is terminal: a half-regenerated adapter set is caught by the build-verification gate before U9 merges.

There is no urgent rollback pressure during a partial landing: the toggle-default-off means a half-merged feature is inert.
