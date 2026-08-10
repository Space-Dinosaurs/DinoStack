# bin/

Seventeen CLI entry points (14 Python, 1 Bash, 2 Node) that the dinostack
methodology exposes as PATH-wired commands. Each binary ships with a
module-manifest docstring (Purpose / Public API / Upstream deps / Downstream
consumers / Failure modes / Performance) that is the authoritative description
of that command. Read the binary itself for full detail; this file is the
module-group map, not a duplicate of those manifests.

Every `ds-*` name below has a permanent `agentic-*` compat symlink (e.g.
`bin/agentic-cost` -> `bin/ds-cost`) - both invoke the same file and behave
identically. `ds-*` is the primary name; the `agentic-*` form is never
sunset (external cron jobs and shell aliases reference it).

## Entry points

| Command | Lang | One-line role |
|---|---|---|
| `ds-calibrate` | Python | Render Skeptic calibration rollups (findings density, meta-Skeptic divergence rate) from `.agentic/events.jsonl`. |
| `ds-cost` | Python | Token / wall-time / dollar rollups per agent, session, task, and developer team from `.agentic/events.jsonl` and session logs. |
| `ds-disable` | Python | Append the opt-out marker to `AGENTS.md`; optionally update the global config. |
| `ds-doctor` | Python | Inspect and repair global install health (symlinks, bin wrappers, hook paths in `settings.json`). |
| `ds-emit` | Bash | Append one structured JSON event to `.agentic/events.jsonl` at orchestration boundaries. |
| `ds-feedback` | Python | Manage the home-dir feedback store (`~/.agentic/feedback.jsonl`) - append/list/mark operator and agent friction items. |
| `ds-help` | Python | Print the static slash-command reference to stdout. Zero file I/O; never fails. |
| `ds-identity` | Python | Manage per-developer identity files used by the Stop hook for session telemetry attribution. |
| `ds-learning-shard` | Python | Manage the home-dir per-session learning shard store (`~/.agentic/learnings-shards/<repo-key>/<session-key>.jsonl`) - `append` one in-flight learning (capped at 5 per session, soft-fail), `rollup` the not-yet-folded raw entries idempotently, `list` for diagnostics. Performs no classification. |
| `ds-memory` | Python | Query `.agentic/events.jsonl`, `MEMORY.md`, and `.agentic/context.md`; return compact Markdown summaries. |
| `ds-migrate` | Python | Apply additive project scaffolding migrations (`check` / `apply` / `diff` subcommands). |
| `ds-parse-subagent-usage` | Python | Parse a Claude Code subagent transcript JSONL and emit `{tokens, model, wall_seconds}` for `spawn_complete` events. |
| `ds-status` | Python | Read-only dump of the activation resolver state with provenance and plain-English explainer. |
| `ds-tracker` | Python | Manage the project-local, gitignored `.agentic/tracker.yml` tracker-config overlay (`init` / `show` / `set` / `resolve` / `path`), merged field-by-field over the `AGENTS.md` tracker resolution chain. |
| `ds-update` | Python | Non-interactive updater: fetch origin, rebuild adapters, reset version-check cache, run `ds-doctor --fix`. |
| `ds-wrap-acquire-lock` | Node | Poll-wait (background) for the /ds-wrap directory lock, exiting when acquired, on a 20-minute timeout, or (`--no-wait`) immediately busy; publishes a role-tagged (`--role=agent\|daemon\|commit`) lock descriptor and structurally never removes a lock. |
| `ds-wrap-release-lock` | Node | Release the `/ds-wrap` directory lock (`.agentic/wrap/lock`) safely where `rm -rf` is permission-denied; owner-scoped - refuses removal when the descriptor names a live foreign-process PID, and refuses to touch anything at the lock path that isn't a lock directory it created. |

## Upstream dependencies

- Python 3 stdlib only - no third-party installs required for any Python binary.
- `ds-wrap-acquire-lock` and `ds-wrap-release-lock` require Node; both load `hooks/lib/wrap-marker.js` via `__dirname`-relative path (not `cwd`).
- `ds-emit` shells out to `python3` and `date` for safe JSON assembly.
- `ds-cost` soft-depends on `pyyaml` for `~/.agentic/pricing.yml`; absent = token-only output.
- `ds-update` shells out to `git` and `bash <adapter>/install.sh`.
- `ds-parse-subagent-usage` reads `~/.claude/projects/` transcript files.

## Downstream consumers

`content/commands/` slash-command specs; adapter install scripts (`.claude/install.sh`, `.codex/install.sh`, etc.) that symlink these onto `PATH`; `hooks/stop-context.js` for `ds-identity` helpers; Activation preflight Step 6 for `ds-migrate`; `content/commands/ds-wrap.md` Part D.5 and `content/commands/ds-feedback-triage.md` for `ds-feedback`.

## Failure-mode discipline

Every binary is fail-open: unexpected input, missing files, and permission
errors are swallowed and surfaced via non-zero exit codes or stderr lines,
never uncaught exceptions. Exit-code conventions are per-command in each
binary's `Public API` block. Conductors must not treat a non-zero exit as a
session-fatal error.

## Why polling belongs in a binary, not conductor prose

An LLM cannot reliably run a long foreground poll loop (foreground `sleep` is blocked in the harness). `/ds-wrap`'s lock-wait was once prose the conductor hand-ran ("poll every 5s for 20min") and reliably gave up after one or two checks. Fix pattern: move the poll loop into a small binary invoked as a background spawn (`run_in_background: true`) so the conductor stays available and gets notified with an exit code on completion - a background spawn on this harness does deliver a synchronous exit code on completion. This is why `ds-wrap-acquire-lock` exists as a binary rather than as conductor prose.
