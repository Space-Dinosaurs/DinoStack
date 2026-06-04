# Rollback Plan: Auto-Identity V1

All changes are additive and gated; rollback is low-risk.

## Per-PR revert
- **PR1 (behavioral, U1+U2+U3)**: `git revert` the squash merge. `bin/agentic-identity` regains old `init`/`show` only; `hooks/stop-context.js` regains old gate (writes session-log for any non-null identity, no pending buffer, no global mirror); `bin/agentic-cost` loses `operator`. No data migration to undo.
- **PR2 (content+adapters, U4+U5+U6+U8+U9)**: `git revert` the squash merge, then re-run all 8 adapter builds + baseline regen on the revert commit (otherwise adapter-sync/drift go red on the revert itself). Docs return to prior wording; `content/commands/agentic-identity.md` (new file) is removed by the revert.

## Runtime/state rollback
- `~/.agentic/identity.yml`: additive `provisional`/`derived_from` keys are ignored by old code (it reads only `developer_id`). No cleanup required. A provisional identity simply behaves as a normal identity under reverted code.
- `~/.agentic/session-log/.pending/`: orphaned pending files are inert under reverted code (nothing reads them). Safe to leave or `rm -rf` the `.pending/` dir.
- `~/.agentic/session-log/<dev>.jsonl` (global mirror) and `.flush.lock`: inert under reverted code. Leave in place.
- Committed per-project `.agentic/session-log/<dev>.jsonl` lines: already valid session-log lines; remain readable by `agentic-cost team`. No rollback needed.

## Forward-fix preference
Because the feature is gated (provisional) and additive, prefer forward-fix over revert for any single-unit defect found post-merge. Full revert only if a behavioral unit (U1/U2) corrupts session-log output for confirmed identities.
