# hooks/

Claude Code lifecycle hooks that enforce methodology rules at the harness
level and write session telemetry to disk. Sixteen scripts in the table below
(8 Python PreToolUse/Stop enforcers, 5 Node lifecycle handlers, 3 Bash helpers).
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
| `enforce-no-abdication.py` | Python | Stop (main session only) | Block turns that end with permission-seeking interrogatives, a stalled surface-and-proceed commitment, OR a prose co-equal ballot (`## Operator decisions` block with 2+ unrecommended items); inject a two-exit directive (proceed now OR explicitly wait for authorization) for the first two, a revise-now directive for the ballot. |
| `enforce-orchestrator-singularity.py` | Python | PreToolUse (Task/Agent) | Deny subagent spawns issued from inside a subagent context (no nested orchestration). |
| `enforce-planning-artifact-spawn.py` | Python | PreToolUse (Write/Edit) | WARN-ONLY: surface an advisory (never deny) when a `docs/planning/**` write has no architect spawn on record in the last 4h. |
| `enforce-shippable-edit.py` | Python | PreToolUse (Write/Edit/MultiEdit) | Deny a conductor-direct (`agent_id` absent) Write/Edit/MultiEdit against a shippable file inside the repo, per METHODOLOGY.md §Git Workflow's shippable/exempt classifier. Engineer subagent edits (`agent_id` present) always allow. |
| `enforce-tier.py` | Python | PreToolUse (Task/Agent) | Deny an explicit sub-Opus `model` downgrade on a mandated-Tier-3 review agent (security-auditor always; skeptic when the brief matches a Tier-3 escalation signal). Escalate-only, fail-open. |
| `enforce-turn-shape.py` | Python | Stop | Advisory-only check of the conductor's final turn against the fixed-shape/warranted-turn rule; never blocks the stop, only logs via `lib/enforcement_log.py`. A two-layer loop guard (`stop_hook_active` silent-exit plus a per-`cwd` counter cap, machinery in `lib/loop_guard.py`) bounds how many times the advisory can re-invoke the model on consecutive non-conforming turns. |
| `post-tool-use-capture-nudge.js` | Node | PostToolUse (Task/Agent) | Surface an in-session capture-gap nudge when a learning-worthy event has no captured learning. Stdin read via `lib/stdin-guard.js` (bounded, never blocks). |
| `pre-tool-use-spawn-emit.js` | Node | PreToolUse (Task/Agent) | Append a `spawn_start` event to `.agentic/events.jsonl` on every subagent spawn (populates telemetry in ad-hoc sessions) and write the `.last-architect-spawn` sentinel on architect spawns. Stdin read via `lib/stdin-guard.js` (bounded, never blocks). |
| `session-end-wrap.js` | Node | SessionEnd | Finalize the deferred-`/ds-wrap` pending-to-ready marker transition and optionally launch `wrap-daemon.js` detached. Stdin read via `lib/stdin-guard.js` (bounded, never blocks). |
| `session-start-version-check.sh` | Bash | (sub-script, not wired directly) | Emit a "newer version available" `systemMessage` via the version-check core; called by `session-start-wrap.sh`. |
| `session-start-wrap.sh` | Bash | SessionStart | Compose version notice, hooks-snapshot staleness nudge, auth-failure notice, artifact migration, and guarded daemon launch into one fail-open handler, and a deferred-work open-count nudge. |
| `skill-auto-load-check.sh` | Bash | UserPromptSubmit / BeforeAgent / SessionStart | Emit the skill-load instruction when `skill_auto_load=true` in the global config. |
| `stop-context.js` | Node | Stop | Write session context to `.agentic/context.md`, mark active loops interrupted, write per-developer telemetry, run capture-gap backstop. |
| `wrap-daemon.js` | Node | (launched detached by SessionEnd/SessionStart) | Background daemon that drains the deferred-`/ds-wrap` ready-marker queue by headlessly resuming forgotten sessions. |

## Shared library (`lib/`)

| File | Role |
|---|---|
| `lib/capture-gap.js` | Detect learning-worthy sessions with no captured learning; used by `post-tool-use-capture-nudge.js` and `stop-context.js`. |
| `lib/version-check-core.sh` | Adapter-neutral core for the "newer version available" SessionStart notice: resolves clone dir, reads behind-count cache, kicks off throttled detached git-fetch refresh; used by `session-start-version-check.sh` and `session-start-wrap.sh`. |
| `lib/repo-dir-fallback.sh` | Shared `AE_REPO_DIR` resolver (`resolve_ae_repo_dir_with_fallback`): tries `scripts/lib/repo-dir.sh`'s `resolve_repo_dir` first, falls back to an inline config-read + git-validate + `$HOME/DinoStack` default when that lib is absent (the deployed hooks-snapshot layout, where `scripts/` is never copied). Extracted from a prior duplication between `lib/version-check-core.sh` and `session-start-wrap.sh`; used by both. |
| `lib/wrap-marker.js` | Single source of truth for all deferred-`/ds-wrap` marker reads, transitions, lock acquire/release, and PID helpers; used by `session-end-wrap.js`, `session-start-wrap.sh`, `stop-context.js`, `wrap-daemon.js`, and `bin/ds-wrap-release-lock`. |
| `lib/stdin-guard.js` | Shared bounded-stdin reader (`readStdinGuarded`) with a first-byte timeout, a re-armed inactivity timeout, a one-shot absolute deadline, a max-bytes cap, and early-completion-by-parse (gated behind a cheap tail precheck), so a stdin-blocking hook cannot hang a harness's shutdown path when the spawning process never closes stdin; wired into all 9 consumers: `stop-context.js`, `post-tool-use-capture-nudge.js`, `session-end-wrap.js`, `pre-tool-use-spawn-emit.js`, the `.codex/hooks/stop-context-codex.js`, `.gemini/hooks/stop-context-gemini.js`, and `.copilot/hooks/stop-context-copilot.js` ports, the `.cursor/hooks/stop-context-cursor.js` port, plus the generated `.github/hooks/stop-context-copilot.js` mirror. |
| `lib/hooks-staleness-core.sh` | DS-54: classifies the methodology checkout's hooks-snapshot state (`never_migrated` / `half_applied` / `stale_but_stable` / `current`, evaluation order in that order - mutually exclusive by construction) and prints at most one nudge line; used by `session-start-wrap.sh`. Fail-open, always exits 0. |
| `../../scripts/lib/hooks-snapshot.sh` | DS-54: lives outside `hooks/` (shared with the adapter `install.sh`/`uninstall.sh` scripts, not just hook code) but is the load-bearing dependency both `hooks-staleness-core.sh` and every in-scope adapter installer source. Owns hooks-snapshot key/dir resolution, the source-hash function, `sync_hooks_snapshot`/`remove_hooks_snapshot` (bounded-delete guarded), and `hooks_config_points_at_snapshot`. |
| `lib/enforcement_log.py` | Shared fire-logging helper: appends one line to `.agentic/.enforcement-fires.jsonl` whenever an enforce-*.py hook takes a non-passthrough action (deny, or allow-with-advisory-reason); a silent allow never calls it. Dynamically imported (best-effort, fails open to a no-op), lazily from inside each caller's action branch, by seven of the eight enforce-*.py hooks - every one except `enforce-no-abdication.py`, which keeps its own pre-existing `.abdication-guard-fire-count` counter file unchanged. |
| `lib/loop_guard.py` | Shared two-layer loop-guard machinery for the two Stop hooks that act on the conductor's final message (`enforce-no-abdication.py` and `enforce-turn-shape.py`): the `stop_hook_active` primary guard is checked by the hooks themselves, and this module supplies the Layer-2 counter-cap backstop (CC bug #54360) - per-hook counter filename + cap, `read_counter`/`write_counter`/`reset_counter` (pid-suffixed tmp + atomic replace, fail-open toward allow), and `count_user_messages`/`is_genuine_user_turn`/`last_genuine_user_text` (filters out tool_result, meta, and harness-injected lines; `last_genuine_user_text` added DS-155 for `enforce-turn-shape.py`'s answer-warrant detector). Counter files: `.abdication-guard-fire-count` (cap 2) and `.turn-shape-guard-fire-count` (cap 2), both under `.agentic/`. |

## Upstream dependencies

- Python hooks: Python 3 stdlib only (`json`, `sys`, `os`, `importlib.util`
  for the seven enforce-*.py hooks' best-effort dynamic import of
  `lib/enforcement_log.py`).
- Node hooks: Node built-ins only (`fs`, `path`, `child_process`) plus `lib/wrap-marker.js`, `lib/capture-gap.js`, and `lib/stdin-guard.js` (no npm packages).
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
`bin/ds-wrap-release-lock` depends on `lib/wrap-marker.js`.
`content/sections/` methodology prose documents the rules these hooks
enforce.

**Merged is not live.** A hook fix merged to `main` does not take effect on
this machine until an installer re-syncs the snapshot - the SessionStart
nudge above only fires at a brand-new session's first tool call, never
mid-session and never at merge time, so a merge that lands while sessions are
already open (the common case) leaves the fix dormant indefinitely absent
some other trigger. Three mechanisms now close that gap, in order of how
reliably they fire: (1) `bin/ds-doctor`'s `check_hooks_snapshot_staleness`
check classifies staleness on demand (`never_migrated` / `half_applied` /
`stale_but_stable`) by shelling out to `lib/hooks-staleness-core.sh`, and
`--fix` calls `sync_hooks_snapshot` - the identical call every adapter
`install.sh` already makes unconditionally, so this introduces no new
mutation hazard under the DS-54 invariant (it only fires on an explicit
`--fix`, never a passive scan); (2) `bin/ds-base-sync` prints the same
staleness nudge as a non-blocking advisory note after every invocation,
independent of which project's repo it just synced - this is the one
guaranteed post-merge trigger point, since it runs unconditionally at
`/ds-implement-ticket` Phase 12; it is read-only and never calls
`sync_hooks_snapshot` itself; (3) `bin/ds-update` compares the live hooks/
source hash against the snapshot's stored hash even when nothing new was
pulled by that invocation (`_hooks_snapshot_diverged`, closing the gap where
an operator manually `git pull`ed a hooks change before running `ds-update`,
so there was no diff for `ds-update`'s own rebuild-trigger logic to see) and
forces the adapter-install loop when they diverge - both `ds-doctor --fix`
invocations that already run unconditionally on `ds-update`'s early-return
paths independently cover the rest. None of the three can auto-rewire a live
session's hooks from a passive trigger; only an explicit `--fix` or an
adapter `install.sh` run ever calls `sync_hooks_snapshot`.

**Adapter asymmetry.** Claude Code, Codex, Gemini, and Kimi are all
snapshotted (this section). `.cursor/install.sh` and `.opencode/install.sh`
instead symlink their hook config directly into the live checkout, so those
two harnesses pick up a hook change on the next `git pull` with no dormancy
gap and no snapshot-staleness concept at all - counterintuitively, the
primary harness (Claude Code) is the one subject to the dormancy gap this
section describes, not the exception to it.

## Two config layers: matcher registration vs snapshot script body

Hook configuration reaches a running session through two independent layers, and they refresh on different schedules. Both statements below are true; neither supersedes the other.

- **Matcher registration** (the hook entries in `~/.claude/settings.json`: which events, which `matcher` patterns, which command strings) resolves ONCE, per session, at session start. Subagents inherit the spawning session's already-resolved registration. A session therefore cannot observe its own edits to matcher registration - not directly, and not indirectly through the agents it spawns.
- **Snapshot script body** (the file each registered command points at, under `$HOME/.agentic/hooks-snapshot/<key>/`) is re-read from disk per tool call. This is the layer §Downstream consumers describes: re-running `install.sh` refreshes the snapshot in place and an already-open session picks up the new script body on its next tool call, with no restart.

Practical consequence: editing a hook's LOGIC is observable in the current session; adding, removing, or re-scoping a MATCHER is not, and needs a freshly started session to test. Establish a positive control before concluding a matcher is wrong - the DS-150 experiment appended a probe to the already-working `Bash` matcher and saw it fire 20 times for an unrelated live session while firing zero times for the editing session's own agents, which is what isolated the layer boundary. Do not use `ps` process start time to decide whether a session is "fresh": a daemon architecture (`claude daemon run`, `bg-pty-host`, `bg-spare`) serves new sessions from long-lived processes, so process age is unrelated to session age. Before mutating GLOBAL hook config at all, confirm no other Claude Code session is live - a global edit reaches every running session, and any probe left in place must be fail-open.

## Failure-mode discipline

Every hook is fail-open: parse errors, missing files, and unexpected payloads
exit 0 without denying the triggering action. Enforcement gaps are preferable
to blanket blocks. Hooks never raise to the Claude Code harness; non-fatal
errors are swallowed or written to stderr. The only intentional side effects
are append-only writes to `.agentic/` files and deny decisions on clearly
violating tool calls. Seven of the eight enforce-*.py hooks additionally
append a fire-log line to `.agentic/.enforcement-fires.jsonl` on every
non-passthrough action (via `lib/enforcement_log.py`); `enforce-no-abdication.py`
is the exception and keeps its own separate `.agentic/.abdication-guard-fire-count`
counter unchanged - see the `lib/` table above.

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

## No gating on inferred session capability

A hook may gate on what the payload states. It may not gate on what the *session
is capable of at runtime*: which tools the harness will actually honour, or what
an injected system prompt forbids. Neither has a payload representation, and
neither is derivable from an on-disk artifact - a settings file states the
operator's configured permission rules, which is not the same fact as what this
session's harness will honour, and a session-scoped state file can record that
something already happened, never that it is unavailable. A hook written
against an inferred capability is written against a predicate it cannot
evaluate; it will either never fire or fire unconditionally, and which one is a
coin toss at implementation time.

The corollary bounds deny scope. Before adding a deny, name the action the
agent is expected to take instead, and confirm that action is still permitted
under every other active guard. A guard that denies the last remaining
permitted action class is a deadlock, not stricter enforcement. The worked
instance - why no hook may deny conductor Read/Grep/Glob to force delegation -
is `content/references/delegation-detail.md` §Harness-Injected Instruction
Conflicts.

The non-hook layers were settled separately: see `content/references/delegation-detail.md` §Delegation suppression (Collision 2).

## Worktree isolation scope

Worktree isolation is enforced only on Bash git operations aimed at the shared checkout, not on reads. A plain `Read` of an absolute path into the conductor's checkout succeeds from inside an isolation worktree, including for files absent from that worktree (`.agentic/`, `docs/planning/`, `evals/`). Verified empirically. Isolation constrains where an agent can write and run git, not what it can see - so "the worktree cannot see it" is false for `Read` and true for `git`.

For a worktree-isolated subagent, `cwd` and `CLAUDE_PROJECT_DIR` name different roots and are not interchangeable. The payload's `cwd` is the agent's OWN worktree root (`<primary>/.claude/worktrees/agent-<id>`); `CLAUDE_PROJECT_DIR` is the PRIMARY checkout root. A hook detecting a cross-boundary read must therefore take `caller_root` from `cwd` and `primary_root` from `CLAUDE_PROJECT_DIR`, `realpath`-normalize both, and test relative containment - isolation worktrees live INSIDE the primary root, so an unnormalized prefix test is not sufficient. Sourcing `caller_root` from `CLAUDE_PROJECT_DIR` compares the primary root against itself and the guard never fires. Read the payload's `cwd` field, never `os.getcwd()`: the two are distinct by construction - the payload field is what the abdication guard threads through to its counter path (`enforce-no-abdication.py:1046` takes `cwd = data.get("cwd", "")`, passes it at `:1081` via `lg.read_counter(cwd, COUNTER_FILENAME)`, reaching `counter_path()` in `hooks/lib/loop_guard.py:154`), and test harnesses must set it explicitly. Them agreeing in one capture is not a licence to substitute one for the other.

## Spawn payload mechanics

PreToolUse hook mechanics for Agent/Task spawns: `tool_input` on a spawn call exposes `subagent_type`, `prompt`, `description`, `model` (absent - not null - when the spawner omitted it), `run_in_background`, and `isolation`; there is no env or metadata parameter, so a conductor cannot inject a marker into a subagent's payload. **That parameter list is read from the `Agent` tool's schema, not from a captured payload** - it differs from the live `Agent` capture recorded in KNW-20260707-001 and must be re-verified against a real `Agent`-spawn payload before any hook gates on it.

Independent of the tool name, the top-level payload key set is CONDITIONAL on the caller, and the difference is the discriminator. Measured on Claude Code v2.1.220 (4 records, Read and Bash calls, 2 sessions):

- **Subagent call - 12 keys:** `agent_id, agent_type, cwd, effort, hook_event_name, permission_mode, prompt_id, session_id, tool_input, tool_name, tool_use_id, transcript_path`. `agent_type` is present and correct (e.g. `engineer`), so a hook may scope enforcement by subagent role.
- **Main-session call - 10 keys:** the same list MINUS `agent_id` and `agent_type` - both keys are ABSENT, not present-with-null, so read them with `.get()` and branch on absence rather than indexing.

**The absence of `agent_id`/`agent_type` is the main-session marker.** This is the same signal `enforce-shippable-edit.py` (absent `agent_id` means conductor-direct) and `enforce-orchestrator-singularity.py` (present means subagent) already rely on, now corroborated by direct capture. Never code against an unconditional 12-key list, and never read `agent_type` outside the subagent branch. `Read` is a valid matcher and fires on real Read calls issued from inside an isolation worktree; a hookable `Read` paired with a reliable `agent_type` is what makes a role-scoped read guard mechanically enforceable rather than inferred. Every list above is a point-in-time observation - re-verify per the discipline in §Fail-open on absent tool_input fields before gating on any field.

To deny a spawn, print `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}` and exit 0. To warn without blocking (an advisory nudge), use `"permissionDecision":"allow"` with a `permissionDecisionReason` - this surfaces text to the model without a human prompt and without denying; it is the mechanism behind the planning-artifact advisory hook.
