# Rollback: Deferred / Background `/wrap`

**Blast radius is low by construction.** The feature is inert when no `/wrap` is running: every new hook branch is gated behind `wrap.lock` presence, and only `/wrap` creates that lock. With the lock absent (the steady state), `stop-context.js` and the OpenCode plugin behave byte-identically to today. All hook additions are fail-open (`exit 0`, try/catch → false), so a bug degrades to "no deferred-wrap" rather than a crash.

## Trigger (when to roll back)
- The integration Skeptic's manual two-session E2E shows context.md clobbered, a lost session, or a marker that never clears.
- A hook regression breaks the normal (lock-absent) context.md write — caught by `hooks/tests/`.

## Procedure
1. **Pre-merge (still on the feature branch):** abandon the branch — `git checkout main && git branch -D feature/deferred-background-wrap`. Nothing shipped.
2. **Post-merge:** revert the squash-merge commit — `git revert -m 1 <merge_sha>`, open a revert PR, regenerate adapters (`*/build.sh`), merge. The revert restores the prior `stop-context.js`, `wrap.md`, plugin, and references.
3. **Runtime state cleanup (any machine that ran the new code):** the marker/sentinel/spillover files are gitignored runtime artifacts and safe to remove — `rm -f .agentic/wrap-pending.json .agentic/.last-wrap .agentic/.stop-deferred-activity.jsonl*`. No committed state to undo.

## Partial-landing safety
If only some of the 6 units merged before a rollback decision, each is independently revertible (distinct files). The `wrap.lock`-gating means a half-landed hook change is inert until `/wrap` async runs, so there is no urgent rollback pressure.
