# bin/

Thirteen CLI entry points (12 Python, 1 Node) that the agentic-engineering
methodology exposes as PATH-wired commands. Each binary ships with a
module-manifest docstring (Purpose / Public API / Upstream deps / Downstream
consumers / Failure modes / Performance) that is the authoritative description
of that command. Read the binary itself for full detail; this file is the
module-group map, not a duplicate of those manifests.

## Entry points

| Command | Lang | One-line role |
|---|---|---|
| `agentic-calibrate` | Python | Render Skeptic calibration rollups (findings density, meta-Skeptic divergence rate) from `.agentic/events.jsonl`. |
| `agentic-cost` | Python | Token / wall-time / dollar rollups per agent, session, task, and developer team from `.agentic/events.jsonl` and session logs. |
| `agentic-disable` | Python | Append the opt-out marker to `AGENTS.md`; optionally update the global config. |
| `agentic-doctor` | Python | Inspect and repair global install health (symlinks, bin wrappers, hook paths in `settings.json`). |
| `agentic-emit` | Bash | Append one structured JSON event to `.agentic/events.jsonl` at orchestration boundaries. |
| `agentic-help` | Python | Print the static slash-command reference to stdout. Zero file I/O; never fails. |
| `agentic-identity` | Python | Manage per-developer identity files used by the Stop hook for session telemetry attribution. |
| `agentic-memory` | Python | Query `.agentic/events.jsonl`, `MEMORY.md`, and `.agentic/context.md`; return compact Markdown summaries. |
| `agentic-migrate` | Python | Apply additive project scaffolding migrations (`check` / `apply` / `diff` subcommands). |
| `agentic-parse-subagent-usage` | Python | Parse a Claude Code subagent transcript JSONL and emit `{tokens, model, wall_seconds}` for `spawn_complete` events. |
| `agentic-status` | Python | Read-only dump of the activation resolver state with provenance and plain-English explainer. |
| `agentic-update` | Python | Non-interactive updater: fetch origin, rebuild adapters, reset version-check cache, run `agentic-doctor --fix`. |
| `agentic-wrap-release-lock` | Node | Release the `/wrap` directory lock (`.agentic/wrap/lock`) safely where `rm -rf` is permission-denied. |

## Upstream dependencies

- Python 3 stdlib only - no third-party installs required for any Python binary.
- `agentic-wrap-release-lock` requires Node; loads `hooks/lib/wrap-marker.js` via `__dirname`-relative path (not `cwd`).
- `agentic-emit` shells out to `python3` and `date` for safe JSON assembly.
- `agentic-cost` soft-depends on `pyyaml` for `~/.agentic/pricing.yml`; absent = token-only output.
- `agentic-update` shells out to `git` and `bash <adapter>/install.sh`.
- `agentic-parse-subagent-usage` reads `~/.claude/projects/` transcript files.

## Downstream consumers

`content/commands/` slash-command specs; adapter install scripts (`.claude/install.sh`, `.codex/install.sh`, etc.) that symlink these onto `PATH`; `hooks/stop-context.js` for `agentic-identity` helpers; Activation preflight Step 6 for `agentic-migrate`.

## Failure-mode discipline

Every binary is fail-open: unexpected input, missing files, and permission
errors are swallowed and surfaced via non-zero exit codes or stderr lines,
never uncaught exceptions. Exit-code conventions are per-command in each
binary's `Public API` block. Conductors must not treat a non-zero exit as a
session-fatal error.
