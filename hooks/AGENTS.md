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
| `enforce-background-spawn.py` | Python | PreToolUse (Task/Agent) | (a) Deny `Task` spawns missing `run_in_background: true` (legacy Task tool only - harness strips this field for Agent); (b) sentinel suppression: deny Task/Agent spawns and OMC Skills when `.agentic/teamrun/.active` is live. Foreground-exempt agents (wrap-ticket) bypass both checks. |
| `enforce-no-abdication.py` | Python | Stop (main session only) | Block turns that end with permission-seeking interrogatives; inject a "proceed" directive. |
| `enforce-orchestrator-singularity.py` | Python | PreToolUse (Task/Agent) | Deny subagent spawns issued from inside a subagent context (no nested orchestration). |
| `enforce-tier.py` | Python | PreToolUse (Task/Agent) | Deny an explicit sub-Opus `model` downgrade on a mandated-Tier-3 review agent (security-auditor always; skeptic when the brief matches a Tier-3 escalation signal). Escalate-only, fail-open. |
| `post-tool-use-capture-nudge.js` | Node | PostToolUse (Task/Agent) | Surface an in-session capture-gap nudge when a learning-worthy event has no captured learning. |
| `session-end-wrap.js` | Node | SessionEnd | Finalize the deferred-`/wrap` pending-to-ready marker transition and optionally launch `wrap-daemon.js` detached. |
| `session-start-version-check.sh` | Bash | (sub-script, not wired directly) | Emit a "newer version available" `systemMessage` via the version-check core; called by `session-start-wrap.sh`. |
| `session-start-wrap.sh` | Bash | SessionStart | Compose version notice, hooks-snapshot staleness nudge, auth-failure notice, artifact migration, and guarded daemon launch into one fail-open handler. |
| `skill-auto-load-check.sh` | Bash | UserPromptSubmit / BeforeAgent / SessionStart | Emit the skill-load instruction when `skill_auto_load=true` in the global config. |
| `stop-context.js` | Node | Stop | Write session context to `.agentic/context.md`, mark active loops interrupted, write per-developer telemetry, run capture-gap backstop. |
| `wrap-daemon.js` | Node | (launched detached by SessionEnd/SessionStart) | Background daemon that drains the deferred-`/wrap` ready-marker queue by headlessly resuming forgotten sessions. |

## Shared library (`lib/`)

| File | Role |
|---|---|
| `lib/capture-gap.js` | Detect learning-worthy sessions with no captured learning; used by `post-tool-use-capture-nudge.js` and `stop-context.js`. |
| `lib/version-check-core.sh` | Adapter-neutral core for the "newer version available" SessionStart notice: resolves clone dir, reads behind-count cache, kicks off throttled detached git-fetch refresh; used by `session-start-version-check.sh` and `session-start-wrap.sh`. |
| `lib/wrap-marker.js` | Single source of truth for all deferred-`/wrap` marker reads, transitions, lock acquire/release, and PID helpers; used by `session-end-wrap.js`, `session-start-wrap.sh`, `stop-context.js`, `wrap-daemon.js`, and `bin/agentic-wrap-release-lock`. |
| `lib/hooks-staleness-core.sh` | DS-54: classifies the methodology checkout's hooks-snapshot state (`never_migrated` / `half_applied` / `stale_but_stable` / `current`, evaluation order in that order - mutually exclusive by construction) and prints at most one nudge line; used by `session-start-wrap.sh`. Fail-open, always exits 0. |
| `../../scripts/lib/hooks-snapshot.sh` | DS-54: lives outside `hooks/` (shared with the adapter `install.sh`/`uninstall.sh` scripts, not just hook code) but is the load-bearing dependency both `hooks-staleness-core.sh` and every in-scope adapter installer source. Owns hooks-snapshot key/dir resolution, the source-hash function, `sync_hooks_snapshot`/`remove_hooks_snapshot` (bounded-delete guarded), and `hooks_config_points_at_snapshot`. |

## Upstream dependencies

- Python hooks: Python 3 stdlib only (`json`, `sys`, `os`).
- Node hooks: Node built-ins only (`fs`, `path`, `child_process`) plus `lib/wrap-marker.js` and `lib/capture-gap.js` (no npm packages).
- Bash hooks: `bash`, `python3` (for JSON escaping), `jq` (with grep/sed fallback), `node`.
- All hooks read `[cwd]/.agentic/` state files; none read outside the project root except identity files at `~/.agentic/`.

## Downstream consumers

Hook commands are NOT wired directly at this checkout's `hooks/` (DS-54).
`.claude/install.sh` (and the equivalent `.codex/install.sh`,
`.gemini/install.sh`, `.kimi/install.sh` installers) first sync `hooks/` plus
each in-scope adapter's own hook sources into a session-stable per-checkout
snapshot at `$HOME/.agentic/hooks-snapshot/<key>/` via
`scripts/lib/hooks-snapshot.sh`, then wire `~/.claude/settings.json` (and the
Codex/Gemini/Kimi equivalents) to point at that snapshot dir, not the live
checkout. This is why a bare `git pull` cannot silently change what an
already-running session's hooks do: the wired command resolves to the
snapshot copy, which only changes when an installer re-syncs it. Re-running
the relevant `install.sh` refreshes the snapshot in place and an open
session picks it up on its next tool call; a snapshot that has drifted from
the live checkout surfaces as a SessionStart nudge
(`lib/hooks-staleness-core.sh`, composed into `session-start-wrap.sh`).
`bin/agentic-wrap-release-lock` depends on `lib/wrap-marker.js`.
`content/sections/` methodology prose documents the rules these hooks
enforce.

## Failure-mode discipline

Every hook is fail-open: parse errors, missing files, and unexpected payloads
exit 0 without denying the triggering action. Enforcement gaps are preferable
to blanket blocks. Hooks never raise to the Claude Code harness; non-fatal
errors are swallowed or written to stderr. The only intentional side effects
are append-only writes to `.agentic/` files and deny decisions on clearly
violating tool calls.

## Fail-open on absent tool_input fields

A PreToolUse hook that gates on a `tool_input` field must fail OPEN (exit 0 /
allow) when that field is entirely ABSENT from the payload for the guarded
`tool_name` - this is distinct from present-but-false, which MAY deny. A
field that is present and `false` is a real signal from the harness; a field
that never appears in the payload at all is not a signal - it means this
harness/tool-name combination does not emit that field, and denying on its
absence blocks every call unconditionally.

Cautionary example: `enforce-background-spawn.py` originally denied any
`Task`/`Agent` spawn missing `run_in_background: true`. The Claude Code
harness strips `run_in_background` from the `Agent` tool's PreToolUse
payload entirely (confirmed by live payload capture: `tool_input` keys for
an `Agent` spawn are exactly `['description', 'prompt', 'subagent_type']`) -
`Agent` is background-by-default at the harness level and the field simply
never arrives. The hook denied every `Agent` spawn until this was found and
fixed; enforcement was scoped back to the legacy `Task` tool only, where the
field genuinely is present in the payload.

**Discipline before gating on a field:** capture or obtain one real
`PreToolUse` payload for the guarded `tool_name` and confirm the field is
actually present in that harness's real shape. Do not assume a field
documented for one tool name (or one harness) is present for a related tool
name or a different harness - verify per tool_name.
