# hooks/

Claude Code lifecycle hooks that enforce methodology rules at the harness
level and write session telemetry to disk. Twenty-four scripts in the table
below (14 Python PreToolUse/Stop enforcers, 7 Node lifecycle handlers, 3 Bash helpers).
`pre-commit` is also present but is a git hook, not a Claude Code lifecycle
hook, and is out of scope for this table. `lib/` holds shared utilities;
the repo-root resolver trio specifically (`lib/repo_root.py`/
`lib/repo-root.js`/`lib/repo-root.sh`, added by DS-171) is consumed by 10 JS
hooks, 5 Python hooks, 3 Bash hooks, and 6 `bin/` scripts respectively - see
the `lib/` table below for the three new rows and their exact consumer
lists. Other `lib/` modules have their own, different consumer counts
(round-3 rework, Major 5: this previously said "the JS hooks and one bin
script", stale since the trio was added; round-4 rework, Minor 1: the
"5/1/6" figures scoped this sentence to the trio only, since the same
sentence used to read as a `lib/`-wide claim and contradicted
`lib/enforcement_log.py`'s own row, which is consumed by all fourteen
enforce-*.py hooks, not five; DS-176 round-2 rework: bumped 7 JS -> 10 JS
and 1 Bash -> 3 Bash for the 3 new adapter hook consumers added by
DS-176's stop-context and session-start ports; this trio's 7/5/1/6 counts
have now drifted twice (once before this rework, once during it) with no
mechanical gate catching either. `_ENFORCER_SUBCOUNT_SITES` in
`bin/tests/test_tracker_writeback_ranking_spec.py` explicitly excludes
this trio by name ("a DIFFERENT fact about a different module... are
deliberately not derived here") because it derives its counts from a
uniform `hooks/enforce-*.py` glob, whereas this trio's consumers are
scattered across `hooks/`, `bin/`, and per-adapter directories with no
single glob or `require`/`source`/`import` discovery helper today - adding
one is a real, separate unit of work, not a cheap extension of the
existing sweep. Deferred, not silently dropped: counts corrected by hand
in this rework, mechanical enforcement left as a named gap). Each script
ships with a
module-manifest docstring; read the script for full detail. This file is the
module-group map.

## Entry points

| Script | Lang | Hook event | One-line role |
|---|---|---|---|
| `conductor-overreach-nudge.js` | Node | Stop | WARN-ONLY: read the real Stop payload (`session_id`, `transcript_path`, `cwd`), compute the conductor-vs-subagent tool-call overreach ratio via `lib/overreach-detector.js`, and on `ratio_trigger` append a `conductor_overreach` event to `.agentic/events.jsonl` plus an advisory `additionalContext` line. Never blocks the stop; no transcript-content suppression logic by design. |
| `enforce-askuserquestion-default.py` | Python | PreToolUse (AskUserQuestion) | Deny co-equal-ballot `AskUserQuestion` calls lacking a `(Recommended)` label. |
| `enforce-background-spawn.py` | Python | PreToolUse (Task/Agent) | (a) Deny `Task` spawns missing `run_in_background: true` (legacy Task tool only - `Agent` uses a separate asymmetric rule: deny only when `run_in_background` is explicitly `False`, since the harness omits the field entirely rather than stripping it when unset); (b) sentinel suppression: deny Task/Agent spawns and OMC Skills when `.agentic/teamrun/.active` is live. Foreground-exempt agents (wrap-ticket) bypass both checks. |
| `enforce-nested-worktree-spawn.py` | Python | PreToolUse (Task/Agent) | DS-190: ADVISORY-ONLY (never denies) - warns once per session when a Task/Agent spawn is issued from a conductor session whose own `cwd` is itself inside a git worktree (`lib/git_worktree.py`'s `is_git_worktree()`) rather than the primary checkout. Never fires on a subagent call (`agent_id` present) or when no `.git` worktree is detected. Fail-open, kill-switch `AE_NESTED_WORKTREE_GUARD_DISABLE=1`. |
| `enforce-no-abdication.py` | Python | Stop (main session only) | Block turns that end with permission-seeking interrogatives, a stalled surface-and-proceed commitment, OR a prose co-equal ballot (`## Operator decisions` block with 2+ unrecommended items); inject a two-exit directive (proceed now OR explicitly wait for authorization) for the first two, a revise-now directive for the ballot. Logs EVERY verdict path (not only blocks) to `.agentic/.enforcement-fires.jsonl` via `lib/enforcement_log.py`, each row carrying a `detail` object with the gate/classifier state - see the `lib/` table below for why this hook alone takes that posture. |
| `enforce-orchestrator-singularity.py` | Python | PreToolUse (Task/Agent) | Deny subagent spawns issued from inside a subagent context (no nested orchestration). |
| `enforce-planning-artifact-spawn.py` | Python | PreToolUse (Write/Edit) | WARN-ONLY: surface an advisory (never deny) when a `docs/planning/**` write has no architect spawn on record in the last 4h. |
| `enforce-shippable-edit.py` | Python | PreToolUse (Write/Edit/MultiEdit) | Deny a conductor-direct (`agent_id` absent) Write/Edit/MultiEdit against a shippable file inside the repo, per METHODOLOGY.md §Git Workflow's shippable/exempt classifier. Engineer subagent edits (`agent_id` present) always allow. |
| `enforce-skeptic-round-cap.py` | Python | PreToolUse (Task/Agent, `subagent_type == "skeptic"`) | Mechanically enforces the Skeptic round-budget policy's round count (content/sections/05-qa-gate.md §Re-route limits): denies a 4th Skeptic round for the same unit (keyed off a stable unit key supplied in, or normalized from, the reviewed-diff identity extracted from the spawn prompt's mandatory "Diff under review" line, never the conductor's own branch - `.agentic/skeptic-round-<unit-key>.json`) unless the conductor has recorded an explicit `ship` or `escalate` decision in that state file (each consumed on use, single-use like the other). This deny only fires when the "Diff under review" line is present and recognizable in one of the supported formats (numbered, hyphen/asterisk bullet, bold with or without a bullet, backticked) and carries a single unambiguous value; when it is absent, malformed (e.g. missing the colon, or an empty bolded field with nothing after the closing bold marker), or ambiguous (two differing values in one field), the hook fails open with no state written - it never falls back to a weaker key. Known residual, not a fail-open case: two DIFFERENT units both expressed as a bare `git diff <same-base-sha>..<hex-head-sha>` range with no branch or PR token anywhere in the value key off the same base-SHA token and share one round counter - see `_normalize_diff_identity()` in the hook for the accepted-tradeoff rationale. A second, separate residual: `_LOOKS_LIKE_FILE_PATH_RE` only rejects a first path with an extension-shaped suffix, so a first path lacking one (e.g. `LICENSE | a.py`, `.gitignore | a.sh`) still passes the stable-key shape gate and becomes a wrong-but-stable key shared with any other unit whose first path is identical - accepted, not fixed, for the same reason as the SHA-range residual above. A recorded `ship` decision while `unresolved_critical` is still true always denies - but `unresolved_critical` is conductor-attested (written by a plain Edit, never derived from an actual Skeptic finding), so this guards a recorded `ship` from silently overriding a flagged Critical, not an unflagged one. A `skeptic_strategy: multi-dimensional` parallel fan-out reviewing the same Worker output coalesces to one charged round via a content fingerprint, not a time window. Fail-open on any error (unextractable unit identity, unparsable state, write failure). |
| `enforce-ticket-batching.py` | Python | PreToolUse (`mcp__mcp-atlassian__jira_create_issue`, `mcp__linear__save_issue`, `Bash`) | Mechanically enforces a grace margin under the Follow-up Ticket Creation Discipline's batching rule (`content/references/delegation-detail.md` §Follow-up Ticket Creation Discipline): the 1st tracker-ticket creation this session allows silently, the 2nd allows with an advisory, the 3rd and every subsequent one denies. Classifies a creation across `jira_create_issue` (always), `linear__save_issue` (only when no `id` field - an id-bearing call is an update), and a `Bash` direct-API bypass (a Jira REST POST to `/rest/api/<n>/issue` not followed by `/<key>`, or Linear's `issueCreate` GraphQL mutation name). Session-wide exemption when the transcript carries a `/ds-feedback-triage` or `/ds-ticket-triage` command marker. Keyed per `<cwd>/.agentic/.ticket-batch-<session_id>.json`. Fail-open on any error, kill-switch `AE_TICKET_BATCH_GUARD_DISABLE=1`. |
| `enforce-tier.py` | Python | PreToolUse (Task/Agent) | Deny an explicit sub-Opus `model` downgrade on a mandated-Tier-3 review agent (security-auditor always; skeptic when the brief matches a Tier-3 escalation signal). Escalate-only, fail-open. |
| `enforce-turn-shape.py` | Python | Stop | Two checks with different postures (DS-156; DS-171 retired the other two): `_execution_prose_flag` (execution-turn structural shape) is BLOCKING and can block the stop; `_decision_item_sprawl_flag` (operator-decisions per-item shape) remains advisory-only and only logs, via `lib/enforcement_log.py`. `_answer_relevance_flag` (answer-turn opening-preamble/closing-recap phrasing), `_status_only_flag` (zero-warrant turns), and the turn-charge volume check are all DELETED (DS-171) - those rules now live in the `dinostack` Claude Code output style (`content/output-styles/dinostack.md`), not this hook. A two-layer loop guard (`stop_hook_active` silent-exit plus a per-`cwd` counter cap, machinery in `lib/loop_guard.py`) bounds how many times either remaining check can re-invoke the model on consecutive non-conforming turns - ONE shared counter/cap governs both. |
| `enforce-worktree-isolation-spawn.py` | Python | PreToolUse (Task/Agent; enforcement scoped to `tool_name == "Agent"` only - `Task` fails open, unproven predicate) | Deny an `Agent`-spawned `engineer`/`qa-engineer`/`release-orchestrator` whose `isolation` is not exactly `"worktree"` (including an absent key), per `content/sections/02-delegation.md`'s no-exception worktree-isolation mandate. Fail-open on every uncertain input, kill-switch `AE_WORKTREE_ISOLATION_GUARD_DISABLE=1` (reinstated round-3 - the mandate is absolute but its enforcement mechanism must stay recoverable; see §No gating on inferred session capability). No config-driven exemption list, unlike its worktree-read/write siblings - see the hook's own module docstring "Exemption-list decision". |
| `enforce-worktree-read.py` | Python | PreToolUse (Read) | Deny a worktree-isolated subagent's (`agent_id` present, `cwd` a proper subdirectory of `CLAUDE_PROJECT_DIR` AND a genuine linked git worktree per `lib/git_worktree.py`'s `is_git_worktree()` - not an ordinary subdirectory, submodule, or nested clone) `Read` that resolves inside the primary checkout instead of the agent's own worktree (DS-150). `caller_root` from the payload's `cwd`, `primary_root` from `CLAUDE_PROJECT_DIR`, both `realpath`-normalized before the containment test. Never fires on a main-session call or a non-isolated subagent. Config-driven exemption list (`worktree_read_guard_exemptions` in `<primary_root>/.agentic/config.json`) ships empty. Fail-open, kill-switch `AE_WORKTREE_READ_GUARD_DISABLE=1`. |
| `enforce-worktree-write.py` | Python | PreToolUse (Write/Edit/MultiEdit) | Write-side companion to `enforce-worktree-read.py`, sharing the same `lib/git_worktree.py::is_git_worktree()` discriminator: deny a worktree-isolated subagent's `Write`/`Edit`/`MultiEdit` that resolves inside the primary checkout instead of the agent's own worktree. Catches the case `enforce-shippable-edit.py` cannot - a subagent that has silently fallen back to the primary checkout still carries a present `agent_id` and passes that guard's agent_id-absence check. Same `caller_root`/`primary_root` derivation and `realpath` normalization as the read guard. SEPARATE config-driven exemption list (`worktree_write_guard_exemptions` in `<primary_root>/.agentic/config.json`) ships empty. Fail-open, kill-switch `AE_WORKTREE_WRITE_GUARD_DISABLE=1`. |
| `post-tool-use-capture-nudge.js` | Node | PostToolUse (Task/Agent) | Surface an in-session capture-gap nudge when a learning-worthy event has no captured learning. Stdin read via `lib/stdin-guard.js` (bounded, never blocks). |
| `pre-tool-use-spawn-emit.js` | Node | PreToolUse (Task/Agent) | Append a `spawn_start` event to `.agentic/events.jsonl` on every subagent spawn (populates telemetry in ad-hoc sessions), with a self-generated `data.spawn_id` correlation key plus best-effort `data.tool_use_id`/`data.parent_agent_id`, and write the `.last-architect-spawn` sentinel on architect spawns. Stdin read via `lib/stdin-guard.js` (bounded, never blocks). |
| `session-end-wrap.js` | Node | SessionEnd | Finalize the deferred-`/ds-wrap` pending-to-ready marker transition and optionally launch `wrap-daemon.js` detached. Stdin read via `lib/stdin-guard.js` (bounded, never blocks). |
| `session-start-version-check.sh` | Bash | (sub-script, not wired directly) | Emit a "newer version available" `systemMessage` via the version-check core; called by `session-start-wrap.sh`. |
| `session-start-wrap.sh` | Bash | SessionStart | Compose EIGHT concerns into one fail-open handler: version notice, hooks-snapshot staleness nudge, auth-failure notice, artifact migration, guarded daemon launch, a deferred-work open-count nudge, a worktree-accumulation nudge, and an opt-in machine-wide worst-project nudge. |
| `skill-auto-load-check.sh` | Bash | UserPromptSubmit / BeforeAgent / SessionStart | Emit the skill-load instruction when `skill_auto_load=true` in the global config. |
| `stop-context.js` | Node | Stop | Write session context to `.agentic/context.md`, mark active loops interrupted, write per-developer telemetry, run capture-gap backstop. |
| `subagent-stop-spawn-emit.js` | Node | SubagentStop | DS-160: append a `spawn_complete` event to `.agentic/events.jsonl` deterministically when a subagent actually finishes (unlike PostToolUse, which fires at spawn launch). Pairs back to the matching `spawn_start` via `data.spawn_id` (FIFO/tool_use_id heuristic, session-scoped) and computes real `data.wall_seconds` (`null` with `data.suspect:true` when the computed duration exceeds 86400s). Replaces reliance on the conductor LLM remembering to emit `spawn_complete` inline. Stdin read via `lib/stdin-guard.js` (bounded, never blocks); events.jsonl read is bounded on both bytes (tail-read, not full-file) and lines. |
| `wrap-daemon.js` | Node | (launched detached by SessionEnd/SessionStart) | Background daemon that drains the deferred-`/ds-wrap` ready-marker queue by headlessly resuming forgotten sessions. |

## Shared library (`lib/`)

| File | Role |
|---|---|
| `lib/capture-gap.js` | Detect learning-worthy sessions with no captured learning; used by `post-tool-use-capture-nudge.js` and `stop-context.js`. |
| `lib/version-check-core.sh` | Adapter-neutral core for the "newer version available" SessionStart notice: resolves clone dir, reads behind-count cache, kicks off throttled detached git-fetch refresh; used by `session-start-version-check.sh` and `session-start-wrap.sh`. |
| `lib/repo-dir-fallback.sh` | Shared `AE_REPO_DIR` resolver (`resolve_ae_repo_dir_with_fallback`): tries `scripts/lib/repo-dir.sh`'s `resolve_repo_dir` first, falls back to an inline config-read + git-validate + `$HOME/DinoStack` default when that lib is absent (the deployed hooks-snapshot layout, where `scripts/` is never copied). Extracted from a prior duplication between `lib/version-check-core.sh` and `session-start-wrap.sh`; used by both. |
| `lib/wrap-marker.js` | Single source of truth for all deferred-`/ds-wrap` marker reads, transitions, lock acquire/release, and PID helpers; used by `session-end-wrap.js`, `session-start-wrap.sh`, `stop-context.js`, `wrap-daemon.js`, and `bin/ds-wrap-release-lock`. |
| `lib/stdin-guard.js` | Shared bounded-stdin reader (`readStdinGuarded`) with a first-byte timeout, a re-armed inactivity timeout, a one-shot absolute deadline, a max-bytes cap, and early-completion-by-parse (gated behind a cheap tail precheck), so a stdin-blocking hook cannot hang a harness's shutdown path when the spawning process never closes stdin; wired into all 10 consumers: `stop-context.js`, `post-tool-use-capture-nudge.js`, `session-end-wrap.js`, `pre-tool-use-spawn-emit.js`, `subagent-stop-spawn-emit.js`, the `.codex/hooks/stop-context-codex.js`, `.gemini/hooks/stop-context-gemini.js`, and `.copilot/hooks/stop-context-copilot.js` ports, the `.cursor/hooks/stop-context-cursor.js` port, plus the generated `.github/hooks/stop-context-copilot.js` mirror. |
| `lib/hooks-staleness-core.sh` | DS-54: classifies the methodology checkout's hooks-snapshot state (`never_migrated` / `half_applied` / `stale_but_stable` / `current`, evaluation order in that order - mutually exclusive by construction) and prints at most one nudge line; used by `session-start-wrap.sh`. Fail-open, always exits 0. |
| `../../scripts/lib/hooks-snapshot.sh` | DS-54: lives outside `hooks/` (shared with the adapter `install.sh`/`uninstall.sh` scripts, not just hook code) but is the load-bearing dependency both `hooks-staleness-core.sh` and every in-scope adapter installer source. Owns hooks-snapshot key/dir resolution, the source-hash function, `sync_hooks_snapshot`/`remove_hooks_snapshot` (bounded-delete guarded), and `hooks_config_points_at_snapshot`. |
| `lib/enforcement_log.py` | Shared fire-logging helper: appends one line to `.agentic/.enforcement-fires.jsonl`. Dynamically imported (best-effort, fails open to a no-op), lazily from inside each caller's logging branch, by all fourteen enforce-*.py hooks. Two caller postures: ACTION-ONLY (thirteen hooks) logs only a non-passthrough action - a deny, or an allow-with-advisory-reason - and a silent allow never calls it; EVERY-VERDICT (`enforce-no-abdication.py` alone) also logs plain `"allow"` rows for every verdict path reached after its enablement gate, because action-only logging leaves "this guard never fires" unfalsifiable. The every-verdict posture is safe only for a Stop hook (once per conductor turn); do not copy it to a PreToolUse hook, which runs at tool-call volume. Accepts an optional keyword-only `detail` dict for structured discriminators, omitted from the line entirely when absent so every action-only caller's row stays byte-identical to the canonical 4-field schema. `enforce-no-abdication.py` additionally keeps its own pre-existing `.abdication-guard-fire-count` counter file, which this module never touches. Resolves the write target through `lib/git_worktree.py::resolve_worktree_primary_root()` in addition to `lib/repo_root.py`, so a fire from inside a linked isolation worktree lands in the PRIMARY checkout's fire log, not a discarded worktree-local copy - see "Failure-mode discipline" above. |
| `lib/git_worktree.py` | Shared `is_git_worktree(caller_root)` discriminator: True only when `caller_root`'s `.git` entry is a FILE whose gitdir pointer contains `/worktrees/` (a genuine linked git worktree), False for an ordinary subdirectory, a submodule (`/modules/` gitdir), an independent nested clone (`.git` as a real directory), or any unparseable/unreadable `.git`. Fails to False on every ambiguity - only ever narrows a caller's deny path, never widens it. Dynamically imported (best-effort, fails open to `False`) by both `enforce-worktree-read.py` and `enforce-worktree-write.py`. Also exposes `resolve_worktree_primary_root(caller_root)`, the same discriminator but returning the PRIMARY checkout root (parsed from the gitdir pointer's `.git/worktrees/<name>` admin-dir path) instead of a bool, or `None` on any non-worktree shape; consumed by `lib/enforcement_log.py` only, to redirect fire-log writes. Not an `enforce-*.py` hook itself - no `main()`, never registered in `~/.claude/settings.json`, not subject to `bin/ds-doctor`'s `MANAGED_HOOK_BASENAMES` or any enforcer subcount. |
| `lib/repo_root.py` | DS-171: resolves the repo-root directory to anchor `.agentic/` state writes/reads instead of trusting a harness-payload `cwd` verbatim (`.git`-ancestor walk, existence-only, file-or-dir). `resolve_agentic_cwd_with_diagnostics(start_dir)` returns `{root, drift_levels, found_git_ancestor}`; `resolve_agentic_cwd(start_dir)` returns just `root`. Consumed via a lazy `importlib.util` dynamic loader (best-effort, fails open to `None`/raw cwd depending on caller) by all 13 of: 8 Python hooks-side files (`enforce-no-abdication.py`, `enforce-turn-shape.py`, `enforce-skeptic-round-cap.py`, `enforce-planning-artifact-spawn.py`, `enforce-ticket-batching.py`, `enforce-background-spawn.py` (DS-175), `lib/enforcement_log.py`, `lib/loop_guard.py`) and 5 `bin/` scripts (`bin/ds-agentic-repair`, `bin/ds-cost`, `bin/ds-identity`, `bin/ds-status`, `bin/ds-memory`). `enforce-shippable-edit.py` has its own `_resolve_repo_root()` and is NOT a consumer; `bin/ds-codex-dispatch` and `bin/ds-cleanup-worktrees` likewise have their own local `repo_root()`/kwarg and are NOT consumers. Most callers use the plain `.git`-only result and never fall back further; two callers (`enforce-skeptic-round-cap.py`'s round-counter state path and `bin/ds-identity`'s Stop-hook session-log `write-hook`/`resolve-hook`) genuinely SKIP the write/read entirely when `found_git_ancestor` is False, since a write at the wrong location would corrupt cross-session state - see the module's own Failure modes docstring section for the full caller-tier rationale. |
| `lib/repo-root.js` | Node port of `lib/repo_root.py` (same `.git`-ancestor walk, same `{root, drift_levels, found_git_ancestor}` diagnostics shape). Consumed by 10 JS hooks: `session-end-wrap.js`, `post-tool-use-capture-nudge.js`, `conductor-overreach-nudge.js`, `pre-tool-use-spawn-emit.js`, `subagent-stop-spawn-emit.js`, `stop-context.js`, `wrap-daemon.js`, plus DS-176's `.copilot/hooks/stop-context-copilot.js`, `.github/hooks/stop-context-copilot.js`, and `.cursor/hooks/stop-context-cursor.js` (`.opencode/plugins/session-context.ts` is NOT a consumer - a standalone TS reimplementation, not a `require()` of this file; see this file's own module docstring). |
| `lib/repo-root.sh` | Bash port of `lib/repo_root.py`/`lib/repo-root.js`, consumed by 3 Bash hooks: `session-start-wrap.sh`, plus DS-176's `.copilot/hooks/session-start-copilot.sh` and `.github/hooks/session-start-copilot.sh`; every `.agentic/` write it guards is conditioned on `-n "$resolved_root"`/`-n "$CWD"` (zero fallback on resolution failure - the strict-skip tier, same discipline as `enforce-skeptic-round-cap.py` and `bin/ds-identity`'s write-hook above). |
| `lib/loop_guard.py` | Shared two-layer loop-guard machinery for the two Stop hooks that act on the conductor's final message (`enforce-no-abdication.py` and `enforce-turn-shape.py`): the `stop_hook_active` primary guard is checked by the hooks themselves, and this module supplies the Layer-2 counter-cap backstop (CC bug #54360) - per-hook counter filename + cap, `read_counter`/`write_counter`/`reset_counter` (pid-suffixed tmp + atomic replace, fail-open toward allow), and `count_user_messages`/`is_genuine_user_turn`/`last_genuine_user_text` (filters out tool_result, meta, and harness-injected lines; `last_genuine_user_text` added DS-155 for `enforce-turn-shape.py`'s answer-warrant detector). Counter files: `.abdication-guard-fire-count` (cap 2) and `.turn-shape-guard-fire-count` (cap 2), both under `.agentic/`. |

## Upstream dependencies

- Python hooks: Python 3 stdlib only (`json`, `sys`, `os`, `importlib.util`
  for all fourteen enforce-*.py hooks' best-effort dynamic import of
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
enforce. `enforce-worktree-read.py` specifically is documented in
`content/references/delegation-detail.md` §Worktree-read hook, alongside
the singularity and tier-escalation hooks it sits next to. Its write-side
companion `enforce-worktree-write.py` is documented alongside it. Its
config key (`worktree_read_guard_exemptions`) and kill-switch
(`AE_WORKTREE_READ_GUARD_DISABLE`) are not both documented at every
additional site - README.md:226 and docs/configuration-reference.md
document BOTH; content/references/risk-config-and-tiers.md documents
BOTH; docs/safe-configuration.md documents the kill-switch ONLY;
content/references/conventions-detail.md, docs/components.md, and
content/commands/ds-init-project.md document the config key ONLY;
docs/index.html documents the kill-switch ONLY.

**Merged is not live.** A hook fix merged to `main` does not take effect on
this machine until an installer re-syncs the snapshot - the SessionStart
nudge above only fires at a brand-new session's first tool call, never
mid-session and never at merge time, so a merge that lands while sessions are
already open (the common case) leaves the fix dormant indefinitely absent
some other trigger. Three mechanisms now close that gap, in order of how
reliably they fire: (1) `bin/ds-doctor`'s `check_hooks_snapshot_staleness`
check classifies staleness on demand (`never_migrated` / `half_applied` /
`stale_but_stable`) by shelling out to `lib/hooks-staleness-core.sh` and
inspecting its exit code (a NONZERO exit is a WARN, never silently treated
as "current" - the classifier's own contract is "always exits 0", so a
nonzero return means it broke mid-run, not "nothing to report"); `--fix`
calls `sync_hooks_snapshot` - the identical call every adapter `install.sh`
already makes unconditionally, so this introduces no new mutation hazard
under the DS-54 invariant (it only fires on an explicit `--fix`, never a
passive scan). `sync_hooks_snapshot` only refreshes SNAPSHOT CONTENT, never
an adapter's own hook config, so it fully resolves `never_migrated` and
`stale_but_stable` but NOT `half_applied` (config still points at the
checkout) - `--fix` on `half_applied` still runs the sync, then reports the
finding unfixable with an actionable "re-run that adapter's install.sh"
message rather than silently claiming it resolved; (2) `bin/ds-base-sync`
prints the same staleness nudge as a non-blocking advisory note after every
invocation, independent of which project's repo it just synced - this is
the one guaranteed post-merge trigger point, since it runs unconditionally
at `/ds-implement-ticket` Phase 12; it is read-only and never calls
`sync_hooks_snapshot` itself; (3) `bin/ds-update` compares the live hooks/
source hash against the snapshot's stored hash even when nothing new was
pulled by that invocation (`_hooks_snapshot_diverged`, closing the gap where
an operator manually `git pull`ed a hooks change before running `ds-update`,
so there was no diff for `ds-update`'s own rebuild-trigger logic to see) and
forces the adapter-install loop when they diverge - both `ds-doctor --fix`
invocations that already run on `ds-update`'s early-return paths UNLESS the
operator passed `--no-doctor` independently cover the rest.
`scripts/update.js` (the interactive updater) has no direct equivalent of
`_hooks_snapshot_diverged` and relies entirely on its own unconditional
`runDoctor()` call to close this same gap transitively - a known,
intentional cross-language asymmetry. All three hashing call sites (the
sync writer, this classifier, and `ds-update`'s divergence check) call the
SOLE `hooks_source_paths` function in `scripts/lib/hooks-snapshot.sh` -
never a hand-copied path list, so the three can never independently drift
on what counts as "the hook source". Friction cost: any operator with
uncommitted local `hooks/` edits gets the full adapter-install loop forced
on every `ds-update` "already up to date" run, since the live hash then
differs from the last sync by construction - expected, not a bug. None of
the three can auto-rewire a live session's hooks from a passive trigger;
only an explicit `--fix` or an adapter `install.sh` run ever calls
`sync_hooks_snapshot`.

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
violating tool calls. All fourteen enforce-*.py hooks additionally
append a fire-log line to `.agentic/.enforcement-fires.jsonl` via
`lib/enforcement_log.py`: thirteen of them on every non-passthrough action only,
and `enforce-no-abdication.py` on every verdict path it reaches after its
enablement gate (including plain `"allow"`), so its allow/deny ratio is
measurable rather than inferred. That hook also keeps its own separate
`.agentic/.abdication-guard-fire-count` counter, unchanged - see the `lib/`
table above.

Fire-logging is strictly observability and is never allowed to change a
verdict. Every caller loads the helper lazily from inside its own logging
branch, calls it only AFTER the decision has already been printed, and
wraps the call in its own `try/except` - so a missing lib file, a
half-applied snapshot with a stale signature, or a raising `log_fire()`
all lose the telemetry row and nothing else.
`hooks/tests/_fire_log_test_helper.py` pins exactly that with an
unconditionally-raising stub.

`lib/enforcement_log.py` writes to the PRIMARY checkout's fire log even
when the firing hook is running inside a linked isolation worktree
(`.claude/worktrees/agent-<id>`), not a worktree-local copy. A worktree's
own `.git` is a FILE (existence-only, per `resolve_agentic_cwd()`), so the
plain repo-root walk used to stop right there; `log_fire()` now also
consults `lib/git_worktree.py::resolve_worktree_primary_root()` and, when
the resolved root is itself a genuine linked worktree, follows its
`gitdir:` pointer to the primary checkout before writing. Before this fix,
every fire from a subagent working inside an isolation worktree landed in
that worktree's own `.agentic/.enforcement-fires.jsonl` and was discarded
the moment the worktree was removed - `bin/ds-hook-fire-report` and every
other consumer of the primary log undercounted by an unbounded amount.
This is scoped to the fire log only (see `resolve_worktree_primary_root()`'s
docstring for why `resolve_agentic_cwd()` itself was deliberately left
unchanged - it is pinned against a shared cross-language fixture and other
callers may depend on its per-worktree scoping).

## Test-suite discipline: these tests are script-mode, not pytest

`hooks/tests/test-*.py` are SCRIPT-MODE suites. Their `test_*` functions
RETURN a failure count (`-> int`) and a `main()` sums those returns and sets
the exit code; they do not `assert` and they are not pytest tests. Run them
as `python3 hooks/tests/test-<name>.py` and read the exit code. This is the
contract the CI job uses.

**Known-live false-green class.** Collecting these files with `pytest`
DISCARDS the returned failure count, so a suite reports "N passed" while
every one of its checks failed. The files that currently have this property
are enumerated below - the list carries no cardinal on purpose, because a
hand-typed count of it goes stale silently the moment a new zero-arg `-> int`
returner appears. `bin/tests/test_tracker_writeback_ranking_spec.py` derives
the true set off disk and asserts this list matches it in both directions:

- `hooks/tests/test-doc-sync-abdication-guard.py` - all 7 `test_*` functions
  are zero-arg `-> int` failure-count returners.
- `hooks/tests/test-enforce-no-abdication.py::test_six_source_enumeration` -
  same shape, in an otherwise assert-based file.

This is recorded here rather than left in a commit message because a commit
message is not a surface anyone reads before running a suite, and it is
recorded in `hooks/AGENTS.md` rather than only in those files because
the person misled by the false green is running the suite, not necessarily
reading it. It is deliberately NOT fixed: converting them to `assert` is a
different contract with a different fix, out of scope for whatever change
brought you here. It is also not silent - pytest emits
`PytestReturnNotNoneWarning` for each one, which is the signal to check the
exit code instead of the summary line. Do not add new `-> int` returners;
new hook tests should assert.

## Registering a new enforce-*.py hook: the Pillar-8 naming obligation

Per `docs/overview/vision.md` Pillar 8, a new `enforce-*.py` hook does not ship
without naming a specific failure it would have caught and the condition
under which it retires. This is the naming obligation only, not the full
registration procedure - the mechanical steps (the guarded
`test -f <path> && python3 <path> || exit 0` wiring form documented in each
new hook's own module manifest, adding the basename to `bin/ds-doctor`'s
`MANAGED_HOOK_BASENAMES`, and updating every site in
`bin/tests/test_tracker_writeback_ranking_spec.py`'s `_ENFORCER_SUBCOUNT_SITES`)
live at those symbols directly, not restated here.

## Fail-open on absent tool_input fields

A PreToolUse hook that gates on a `tool_input` field must fail OPEN (exit 0 /
allow) when that field is entirely ABSENT from the payload for the guarded
`tool_name` - this is distinct from present-but-false, which MAY deny. A
field that is present and `false` is a real signal from the harness; a field
that never appears in the payload at all is not a signal by default - it
usually means this harness/tool-name combination does not emit that field,
and denying on its absence blocks every call unconditionally.

**Narrow evidence-gated exception:** a hook MAY deny on a field's absence
ONLY IF a real per-`tool_name` `PreToolUse` payload capture has proven, for
that exact `tool_name`, that the field is present-when-explicitly-set and
omitted-when-unset (i.e. the harness genuinely never sends the field until
the caller sets it, as opposed to stripping or renaming it unconditionally)
- and the gating hook's own docstring cites that capture at the point where
it makes the deny decision. Absent that proof, the general prohibition above
stands unchanged: gating on an unproven absent field is exactly the
unverified-predicate deny this section exists to prevent, and remains
prohibited regardless of how confident the guard's author is. This exception
narrows an established rule with measured evidence; it does not create a
default, and it must never be read as license to deny on an unverified
field. `enforce-worktree-isolation-spawn.py`'s `isolation` field on
`tool_name == "Agent"` is an audited instance of this exception - §Spawn
payload mechanics below records the capture (2026-08-23) proving
`isolation` is present-when-set/omitted-when-unset for `Agent`
specifically - but it is not the only deny-on-absent gate in the repo.
`enforce-background-spawn.py` also denies a `Task` spawn whose
`run_in_background` key is entirely absent (verified by execution: a
`{"tool_name":"Task","tool_input":{"subagent_type":"engineer", ...}}`
payload with no `run_in_background` key is denied), and it predates this
exception's evidence requirement - no per-`tool_name` capture exists
proving `Task` omits `run_in_background` only when unset (as opposed to
stripping it unconditionally). Treat it as grandfathered debt, not as
compliant precedent: do not cite it to justify a new unverified deny-on-
absent gate, and do not assume its `Task` behavior is safe without
obtaining the capture. A future engineer extending this exception to a
new field or hook must obtain and cite an equally real capture, scoped to
the exact `tool_name` being gated - never generalize a capture from one
`tool_name` to a "related" one, and never point to an ungrandfathered gate
as evidence the bar has already been met.

An exception satisfied by a single self-produced capture, or by prose
alone, does not meet the bar above. At minimum: both the present-when-
explicitly-set and omitted-when-unset shapes must actually have been
observed for the exact `tool_name` being gated (not inferred from a
schema or from a different `tool_name`); the observed `tool_input` key
lists must be transcribed into the gating hook's own docstring, not left
only in a gitignored capture log a reviewer or worktree-isolated engineer
cannot read; and the citing text must say explicitly that the capture
does not generalize to any other `tool_name`.

Cautionary example: `enforce-background-spawn.py` originally denied any
`Task`/`Agent` spawn missing `run_in_background: true`. The Claude Code
harness OMITS `run_in_background` from the `Agent` tool's PreToolUse
payload entirely WHEN THE SPAWNER LEAVES IT UNSET (confirmed by live
payload capture, 2026-08-23: `tool_input` keys for an unset-isolation,
unset-`run_in_background` `Agent` spawn were exactly `['description',
'prompt', 'subagent_type']`) - `Agent` is background-by-default at the
harness level, so an unset field simply never arrives. This is present-
when-explicitly-passed, omitted-when-unset, the SAME shape as `isolation`
(§Spawn payload mechanics below) - it is NOT stripped from the `Agent`
payload unconditionally; a spawn that explicitly passes
`run_in_background: false` DOES carry the key (a real `Agent` spawn with
`run_in_background: false` was denied by this hook in-session, which is
only possible if the key was present in that payload). The hook denied
every `Agent` spawn missing the field until this was found and fixed;
enforcement was scoped back to the legacy `Task` tool only. Whether
`Task` genuinely omits the field only when unset (as opposed to
stripping it unconditionally) has never been captured - see the
grandfathered-debt paragraph above.

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

Worktree isolation is enforced on Bash git operations aimed at the shared checkout, and, as of DS-150, on `Read` too. Historically (pre-DS-150) a plain `Read` of an absolute path into the primary checkout succeeded unconditionally from inside an isolation worktree, including for files absent from that worktree (`.agentic/`, `docs/planning/`, `evals/`) - isolation constrained where an agent could write and run git, not what it could see. `hooks/enforce-worktree-read.py` (see §Entry points and content/references/delegation-detail.md §Worktree-read hook) now denies a worktree-isolated subagent's `Read` when the target resolves inside the primary checkout rather than the agent's own worktree, closing that gap for the `Read` tool specifically. Grep/Glob remain unguarded by design (scope was fixed to `Read`, the only tool confirmed as a working PreToolUse matcher for this purpose by live capture) - a worktree-isolated agent can still discover the existence of primary-checkout paths via those tools even though reading their content through `Read` is now denied. This hook never denies a main-session (conductor) `Read`, only a worktree-isolated subagent's.

The write-side gap is closed by `hooks/enforce-worktree-write.py` (see §Entry points and content/references/delegation-detail.md §Worktree-write hook): a subagent whose worktree was cleaned up mid-task and silently fell back to the primary checkout (see the sequential-spawn worktree-cleanup note in `AGENTS.md`) still carries a present `agent_id`, so `enforce-shippable-edit.py`'s conductor-vs-subagent check never fires, and shippable edits land directly on the primary checkout - real instances landed on `main` this way (commits `1577c984`, `3142a803`, `530ad687`). `enforce-worktree-write.py` denies a worktree-isolated subagent's `Write`/`Edit`/`MultiEdit` when the target resolves inside the primary checkout rather than the agent's own worktree, using the same `caller_root`/`primary_root` derivation and `realpath` normalization as the read guard, and a SEPARATE config exemption key (`worktree_write_guard_exemptions`, not the read guard's `worktree_read_guard_exemptions`). Bash is an equally unguarded write path (e.g. a redirect or `sed -i` against a primary-checkout path) and should not be assumed covered.

A `cwd` that is a proper subdirectory of `CLAUDE_PROJECT_DIR` is NOT by itself proof of worktree isolation: an ordinary repo subdirectory, a submodule, and an independent nested clone are all proper subdirectories too, and denying a `Read` or `Write`/`Edit`/`MultiEdit` from any of them is a false positive - a blocking hook denying a legitimate read or write is worse than the isolation gap it guards. Both `enforce-worktree-read.py` and `enforce-worktree-write.py` additionally require `caller_root`'s `.git` entry to match the genuine-linked-worktree shape via the shared `lib/git_worktree.py::is_git_worktree()` helper (gitdir pointer containing `/worktrees/`, as opposed to a submodule's `/modules/` gitdir, a nested clone's real `.git` directory, or an ordinary subdirectory with no `.git` at all) before treating it as isolated; failing that check fails open (ALLOW).

For a worktree-isolated subagent, `cwd` and `CLAUDE_PROJECT_DIR` name different roots and are not interchangeable. The payload's `cwd` is the agent's OWN worktree root (`<primary>/.claude/worktrees/agent-<id>`); `CLAUDE_PROJECT_DIR` is the PRIMARY checkout root. A hook detecting a cross-boundary read must therefore take `caller_root` from `cwd` and `primary_root` from `CLAUDE_PROJECT_DIR`, `realpath`-normalize both, and test relative containment - isolation worktrees live INSIDE the primary root, so an unnormalized prefix test is not sufficient. Sourcing `caller_root` from `CLAUDE_PROJECT_DIR` compares the primary root against itself and the guard never fires. Read the payload's `cwd` field, never `os.getcwd()`: the two are distinct by construction - the payload field is what the abdication guard threads through to its counter path (`enforce-no-abdication.py:1046` takes `cwd = data.get("cwd", "")`, passes it at `:1081` via `lg.read_counter(cwd, COUNTER_FILENAME)`, reaching `counter_path()` in `hooks/lib/loop_guard.py:154`), and test harnesses must set it explicitly. Them agreeing in one capture is not a licence to substitute one for the other.

## Spawn payload mechanics

PreToolUse hook mechanics for Agent/Task spawns: `tool_input` on a spawn call exposes `subagent_type`, `prompt`, `description`, `model` (absent - not null - when the spawner omitted it), `run_in_background`, and `isolation`; there is no env or metadata parameter, so a conductor cannot inject a marker into a subagent's payload. **That parameter list is read from the `Agent` tool's schema, not from a captured payload** - it differs from the live `Agent` capture recorded in KNW-20260707-001. `isolation` specifically HAS now been re-verified against real `Agent`-spawn payloads (project-scoped capture hook, first captured 2026-08-23; the log grows with every spawn, so the SHAPES below are the load-bearing evidence, not a pinned record count, which goes stale the next time anyone reads the live log): present with the exact string value `"worktree"` when the spawner set it, absent from `tool_input` entirely when unset - never present-with-null. `run_in_background` was absent from every captured record with `isolation` unset, consistent with present-when-set/omitted-when-unset, not evidence it is stripped from the `Agent` payload entirely. `model` and the remaining fields are still schema-derived only and still need their own re-verification before any hook gates on them.

Independent of the tool name, the top-level payload key set is CONDITIONAL on the caller, and the difference is the discriminator. Measured on Claude Code v2.1.220 (4 records, Read and Bash calls, 2 sessions):

- **Subagent call - 12 keys:** `agent_id, agent_type, cwd, effort, hook_event_name, permission_mode, prompt_id, session_id, tool_input, tool_name, tool_use_id, transcript_path`. `agent_type` is present and correct (e.g. `engineer`), so a hook may scope enforcement by subagent role.
- **Main-session call - 10 keys:** the same list MINUS `agent_id` and `agent_type` - both keys are ABSENT, not present-with-null, so read them with `.get()` and branch on absence rather than indexing.

**The absence of `agent_id`/`agent_type` is the main-session marker.** This is the same signal `enforce-shippable-edit.py` (absent `agent_id` means conductor-direct) and `enforce-orchestrator-singularity.py` (present means subagent) already rely on, now corroborated by direct capture. Never code against an unconditional 12-key list, and never read `agent_type` outside the subagent branch. `Read` is a valid matcher and fires on real Read calls issued from inside an isolation worktree; a hookable `Read` paired with a reliable `agent_type` is what makes a role-scoped read guard mechanically enforceable rather than inferred. Every list above is a point-in-time observation - re-verify per the discipline in §Fail-open on absent tool_input fields before gating on any field.

To deny a spawn, print `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}` and exit 0. To warn without blocking (an advisory nudge), use `"permissionDecision":"allow"` with a `permissionDecisionReason` - this surfaces text to the model without a human prompt and without denying; it is the mechanism behind the planning-artifact advisory hook.
