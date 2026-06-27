# hooks/

Claude Code lifecycle hooks that enforce methodology rules at the harness
level and write session telemetry to disk. Twelve scripts in the table below
(5 Python PreToolUse/Stop enforcers, 4 Node lifecycle handlers, 3 Bash helpers).
`pre-commit` is also present but is a git hook, not a Claude Code lifecycle
hook, and is out of scope for this table. `lib/` holds shared utilities
consumed by the JS hooks and one bin script. Each script ships with a
module-manifest docstring; read the script for full detail. This file is the
module-group map.

## Entry points

| Script | Lang | Hook event | One-line role |
|---|---|---|---|
| `enforce-askuserquestion-default.py` | Python | PreToolUse (AskUserQuestion) | Deny co-equal-ballot `AskUserQuestion` calls lacking a `(Recommended)` label. |
| `enforce-background-spawn.py` | Python | PreToolUse (Task/Agent) | Deny subagent spawns missing `run_in_background: true`; allow documented foreground-exempt agents. |
| `enforce-no-abdication.py` | Python | Stop (main session only) | Block turns that end with permission-seeking interrogatives; inject a "proceed" directive. |
| `enforce-orchestrator-singularity.py` | Python | PreToolUse (Task/Agent) | Deny subagent spawns issued from inside a subagent context (no nested orchestration). |
| `enforce-tier.py` | Python | PreToolUse (Task/Agent) | Deny an explicit sub-Opus `model` downgrade on a mandated-Tier-3 review agent (security-auditor always; skeptic when the brief matches a Tier-3 escalation signal). Escalate-only, fail-open. |
| `post-tool-use-capture-nudge.js` | Node | PostToolUse (Task/Agent) | Surface an in-session capture-gap nudge when a learning-worthy event has no captured learning. |
| `session-end-wrap.js` | Node | SessionEnd | Finalize the deferred-`/wrap` pending-to-ready marker transition and optionally launch `wrap-daemon.js` detached. |
| `session-start-version-check.sh` | Bash | (sub-script, not wired directly) | Emit a "newer version available" `systemMessage` via the version-check core; called by `session-start-wrap.sh`. |
| `session-start-wrap.sh` | Bash | SessionStart | Compose version notice, auth-failure notice, artifact migration, and guarded daemon launch into one fail-open handler. |
| `skill-auto-load-check.sh` | Bash | UserPromptSubmit / BeforeAgent / SessionStart | Emit the skill-load instruction when `skill_auto_load=true` in the global config. |
| `stop-context.js` | Node | Stop | Write session context to `.agentic/context.md`, mark active loops interrupted, write per-developer telemetry, run capture-gap backstop. |
| `wrap-daemon.js` | Node | (launched detached by SessionEnd/SessionStart) | Background daemon that drains the deferred-`/wrap` ready-marker queue by headlessly resuming forgotten sessions. |

## Shared library (`lib/`)

| File | Role |
|---|---|
| `lib/capture-gap.js` | Detect learning-worthy sessions with no captured learning; used by `post-tool-use-capture-nudge.js` and `stop-context.js`. |
| `lib/version-check-core.sh` | Adapter-neutral core for the "newer version available" SessionStart notice: resolves clone dir, reads behind-count cache, kicks off throttled detached git-fetch refresh; used by `session-start-version-check.sh` and `session-start-wrap.sh`. |
| `lib/wrap-marker.js` | Single source of truth for all deferred-`/wrap` marker reads, transitions, lock acquire/release, and PID helpers; used by `session-end-wrap.js`, `session-start-wrap.sh`, `stop-context.js`, `wrap-daemon.js`, and `bin/agentic-wrap-release-lock`. |

## Upstream dependencies

- Python hooks: Python 3 stdlib only (`json`, `sys`, `os`).
- Node hooks: Node built-ins only (`fs`, `path`, `child_process`) plus `lib/wrap-marker.js` and `lib/capture-gap.js` (no npm packages).
- Bash hooks: `bash`, `python3` (for JSON escaping), `jq` (with grep/sed fallback), `node`.
- All hooks read `[cwd]/.agentic/` state files; none read outside the project root except identity files at `~/.agentic/`.

## Downstream consumers

`~/.claude/settings.json` wired by `.claude/install.sh`; equivalent adapter
configs for Codex, Gemini, and Kimi. `bin/agentic-wrap-release-lock` depends
on `lib/wrap-marker.js`. `content/sections/` methodology prose documents the
rules these hooks enforce.

## Failure-mode discipline

Every hook is fail-open: parse errors, missing files, and unexpected payloads
exit 0 without denying the triggering action. Enforcement gaps are preferable
to blanket blocks. Hooks never raise to the Claude Code harness; non-fatal
errors are swallowed or written to stderr. The only intentional side effects
are append-only writes to `.agentic/` files and deny decisions on clearly
violating tool calls.
