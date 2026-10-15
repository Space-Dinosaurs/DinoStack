# Configuration reference

Every user-facing setting in the dinostack methodology, with its
default value and where to set it. This is the complete catalog - if you only
want to tune Skeptic overhead, you need only `profile`. Change settings
interactively with `/ds-config` (guided prompts). See
[safe-configuration.md](safe-configuration.md) for the cost/rigor tradeoff
and recommended starting points.

---

## 1. Global: `~/.claude/agentic-engineering.json`

Written by the installer. Controls activation and the session-wide risk profile.

| Key | Default | Valid values | Effect |
|---|---|---|---|
| `mode` | `"opt-out"` | `"opt-in"`, `"opt-out"` | Activation mode: `opt-out` runs everywhere unless a project opts out; `opt-in` stays dormant until a project opts in |
| `profile` | `"default"` | `"relaxed"`, `"default"`, `"strict"` | Session-wide risk profile (see [Risk profiles](#risk-profiles)) |
| `set_at` | n/a | ISO8601 string | Metadata timestamp written by installer; do not edit |
| `cache_keepalive` | absent (on) | bool | Machine-wide fallback for the [cache keepalive](#cache-keepalive); a project's `.agentic/config.json` value wins. Write it with `ds-config cache_keepalive false --scope global` |

Absent file resolves to `mode=opt-out`, `profile=default`.

### Risk profiles

Per-project markers (Section 2) override global values.

**Profile effects:**

- **`relaxed`** - single-file locally-scoped behavioral edits and multi-file
  pure-UI-only changes are Low (no Skeptic).
- **`default`** - single-file locally-scoped behavioral edits are Low;
  everything else follows standard Elevated signals.
- **`strict`** - UI-only copy changes, file renaming, and targeted wording fixes
  are Elevated; diagnostic-only and docs-only changes require a self-check.

---

## 2. AGENTS.md project markers

Add any of these lines to the project's root `AGENTS.md` to override global
values for that project. Case-insensitive; whole-line match with optional
leading `- `.

| Marker | Default (absent) | Valid values | Effect |
|---|---|---|---|
| `agentic-engineering:` | none | `opt-in`, `opt-out` | Per-project activation override |
| `agentic-engineering-profile:` | falls to global profile | `relaxed`, `default`, `strict` | Overrides global profile for this project |

If both `opt-in` and `opt-out` appear in the same file, the first one wins and
a warning is printed.

---

## 3. Project: `.agentic/config.json`

Committed to the repo. Seeded with defaults by `/ds-init-project`. Absent file =
all defaults, no behavior change. The 25 behavioral toggles plus 6 tuning
parameters are listed below. The file also carries a `scaffolding_version` key
that is installer/migration-managed (used by `/ds-migrate-project` as the
source-of-truth stamp for "has this project been migrated to vN") - do not edit
it manually.

### Behavioral toggles

| Key | Default | Valid | Effect |
|---|---|---|---|
| `debugger_on_failure` | `false` | bool | When `true` and path is Elevated, interposes a Debugger before each Phase-7 fix pass on a quality-gate failure |
| `qa_default_skip` | reserved/inert | reserved | Schema placeholder only; does not alter QA-gate behavior |
| `model_profile` | `"default"` | `"default"`, `"budget"` | `budget` passes a model one tier below each role's default; **never applies to `security-auditor` or any mandated Tier-3 spawn** |
| `auto_merge_on_ci_green` | `false` | bool | When `true`, Phase 12 squash-merges after CI green + ready + no change-requests; also governs a broader auto-merge rule (see conventions-detail.md) |
| `capability_preflight_mode` | `"blocking"` | `"advisory"`, `"blocking"` | `advisory` warns and proceeds on a missing dep; `blocking` refuses the spawn. Default is `blocking` (all agent manifests are populated as of P2). |
| `perceptual_diff_enabled` | `false` | bool | qa-engineer runs pixelmatch against committed baselines |
| `theme_aware` | `false` | bool | qa-engineer runs scenarios in both light and dark themes |
| `storybook_enabled` | `false` | bool | qa-engineer targets Storybook iframe for isolated component verification |
| `motion_aware` | `false` | bool | qa-engineer runs CDP-emulated reduced-motion checks |
| `storybook_version` | `7` | `6`, `7` | Storybook URL format (`6` = `?selectedKind=&selectedStory=`); set automatically by `/ds-init-project` |
| `commit_telemetry` | `true` | bool | Phase 8 commits the per-developer session-log file as a separate PR commit; set to `false` to opt out |
| `knowledge_commit_on_pr` | `true` | bool | Phase 11e commits changed `MEMORY.md` / `decisions.md` / `.agentic/learnings.md` / `AGENTS.md` / `.agentic/tracking.md` onto the ticket's PR branch; set to `false` to opt out |
| `knowledge_commit_exclude` | `[]` | list of strings | Each entry must exactly match one of the five knowledge-commit candidate-set strings to exclude that file from Phase 11e and `/ds-wrap` Part G commits; a non-matching entry is a silent no-op |
| `deferred_wrap_daemon` | `false` | bool | Opt-in for out-of-session daemon to run deferred `/ds-wrap` jobs (tuned by the `deferred_wrap_*` params below) |
| `abdication_guard_enabled` | absent → guard inert; `/ds-init-project` template sets `true` | bool | Stop hook blocks conductor turns that end by asking permission for a non-destructive next step, announcing a surface-and-proceed default and then not acting on it, or presenting a prose co-equal ballot in an `## Operator decisions` block; requires an explicit `true` to run; kill-switch: `AE_ABDICATION_GUARD_DISABLE=1` |
| `skill_candidate_detection` | `true` | bool | Master toggle for the skill-candidate detector; `false` disables all layers |
| `skill_candidate_nudge` | `false` | bool | In-session nudge when a domain crosses the candidate threshold (requires `skill_candidate_detection: true`) |
| `ticket_driven` | absent-key: `offer` if tracker connected, `off` if not | `"off"`, `"offer"`, `"require"` | Controls ticket-creation gate before first subagent spawn (exemptions apply); **absent key resolves based on tracker connection, not to a fixed default** |
| `rework_detection` | `true` | bool | Disables the Phase 9 ledger write, Phase 1 detection, the notice, the `/ds-ticket-triage` badge, and the escalation with a single flag when `false` |
| `pending_merge_sweep` | `true` | bool | Controls the session-start pending-merge sweep that pushes the dev-complete transition (`TRACKER_STATE_DEV_COMPLETE`, which defaults to the resolved `TRACKER_STATE_DONE` value) to the tracker once a ticket's PR merges; set `false` to disable |
| `tracker_state_diagnostic` | `true` | bool | Controls whether the tracker writeback subagent emits a live diagnostic naming currently-available states when a configured `TRACKER_STATE_*` name cannot be used; set `false` to disable |
| `turn_shape_guard_enabled` | `true` | bool | Stop hook (`hooks/enforce-turn-shape.py`) checks the conductor's final turn against the fixed-shape/warranted-turn rule. As of DS-156 NOT uniformly advisory: the execution-turn structural check (`_execution_prose_flag`) is BLOCKING and can block the stop; the operator-decisions per-item shape check (`_decision_item_sprawl_flag`) remains advisory-only and only logs. As of DS-ANSWERFIRST the zero-warrant status-only check (`_status_only_flag`) is RESTORED to this hook and BLOCKING, gated on three structural conditions (zero warrants; the turn is NOT the first assistant turn following a genuine operator message - i.e. a separate, earlier COMPLETED assistant turn sits between the operator's last real message and now, so the turn is unprompted; and the body is not answer-shaped prose). The second suppressor is a transcript-POSITION predicate (`_has_intervening_assistant_turn`), NOT a test of the operator's grammar or message length: an earlier version asked whether the last operator message was question-shaped (`_looks_like_question`) and produced two measured false positives, and was replaced rather than widened. The check is fail-open - any exception, an unreadable transcript, or an unavailable loop-guard module returns a silent allow, never a block. The same ticket added `SLOT_LINE_MAX_COUNT` (3), a blocking count/duplicate-label bound on the general branch's status slot lines. Two checks stay retired from this hook: the answer relevance check (`_answer_relevance_flag`, opening-preamble/closing-recap) and the whole-message turn-volume check (`_turn_charge`/`_volume_flag`). Their always-loaded carrier is the kernel paragraph in `content/sections/02-delegation.md`, which reaches every harness - NOT the `dinostack` output style, which `.claude/install.sh` installs but never selects, so it carried nothing on an unconfigured machine (`ds-doctor` now WARNs on exactly that state). The style remains a real second carrier once selected via `/config`, and additionally carries two rules with no hook-mechanized form - the output style additionally carries two rules with no prior hook-mechanized form: self-narrating candor, and editorial addenda (the ban on any conductor-selected item that carries none of the four turn warrants, in any position in the turn and whether or not it is bundled - a labelled package of such observations is the canonical form, not the boundary). Absent key resolves to on; kill-switch: `AE_TURN_SHAPE_GUARD_DISABLE=1` |
| `worktree_read_guard_exemptions` | `[]` | list of strings | Path prefixes (relative to the primary checkout root) exempted from the worktree-isolation `Read` guard (`hooks/enforce-worktree-read.py`); ships empty. Kill-switch: `AE_WORKTREE_READ_GUARD_DISABLE=1` |
| `worktree_write_guard_exemptions` | `[]` | list of strings | Path prefixes (relative to the primary checkout root) exempted from the worktree-isolation `Write`/`Edit`/`MultiEdit` guard (`hooks/enforce-worktree-write.py`); SEPARATE key from `worktree_read_guard_exemptions`; ships empty. Kill-switch: `AE_WORKTREE_WRITE_GUARD_DISABLE=1` |
| `memory_shard_mode` | `false` | bool | Opt-in; ships inert - the memory-shard compiler (`bin/ds-memory-shard`) exists but no writer reads this toggle yet |
| `cache_keepalive` | absent (on) | bool | Prompt-cache keepalive for idle conductor sessions (`hooks/cache-keepalive.py`); see [Cache keepalive](#cache-keepalive). Not seeded by `/ds-init-project`, so a machine-wide `false` still applies; a project value wins when set. Only a literal `false` disables it; lookup is this file, then `~/.claude/agentic-engineering.json`, then on. Kill-switch: `AE_CACHE_KEEPALIVE_DISABLE=1` |

### Tuning parameters

| Key | Default | Type | Effect |
|---|---|---|---|
| `storybook_url` | `"http://localhost:6006"` | string | Storybook dev-server URL |
| `deferred_wrap_idle_minutes` | `15` | int | Idle time before daemon picks up a deferred wrap job |
| `deferred_wrap_heartbeat_seconds` | `120` | int | Daemon heartbeat interval |
| `deferred_wrap_timeout_minutes` | `10` | int | Max time for a single wrap job before timeout |
| `deferred_wrap_inprogress_reclaim_minutes` | `30` | int | Time before an in-progress job is reclaimed |
| `deferred_wrap_pending_ttl_days` | `7` | int | Days before a pending job expires |

### Cache keepalive

`hooks/cache-keepalive.py` (UserPromptSubmit) keeps an idle conductor session's 1-hour prompt cache warm, so the request after the operator comes back reads the prefix from cache instead of re-writing it. Claude Code only. It acts only in a project the activation preflight resolves to active (global `mode` plus the AGENTS.md `agentic-engineering:` marker, resolved by `bin/ds-status`; a no-op project, or a resolver that fails to load, gets no keepalive), and only in an interactive, attended main session that has spawned a subagent (a `subagents/` directory beside its transcript), with a 1-hour cache TTL and a prefix of at least 50,000 tokens.

- **Creation.** On a prompt in an eligible session with no live keepalive cron, the hook adds a note asking the model to load the Cron tools with one ToolSearch and create one session-only cron (`7,27,47 * * * *`, durable false). That costs 2 extra requests inside that turn. **Auto permission mode:** Claude Code's auto-mode classifier denies a hook-requested CronCreate as "Unauthorized Persistence" (measured 2 of 2), so an `auto`-mode session gets no keepalive and the model says so in one line; to enable it there, add `CronCreate`, `CronList` and `CronDelete` to `permissions.allow` in your settings (measured: creation and the full wrap then ran with no prompt). In `default`, `acceptEdits` and `bypassPermissions` creation needs no allow rule. The note states its origin, purpose and opt-out, and the job is never hidden: the model may add one line to its reply naming the job and `cache_keepalive: false` (measured on opus with the shipped text: every creation, 3 of 3). The model may also decline or ignore the note (opus created the cron in 3 of 4 sessions, and declined both times a 1-minute test cadence was stated; over 2.3 days of one conductor session, 17 of 28 notes led to a cron). An unanswered note is repeated on the next turn, a subagent's completion notice or hand-back included, until 3 notes have gone unanswered; a denied CronCreate stops it at once. A first note is added only on a prompt you typed, so a release is never undone by a completion notice while you are away. A compaction does not count as a new process, so it never asks for a second cron beside a live one.
- **Each fire** (every 20 minutes, only while the REPL is idle) is decided from the transcript. If the last request is 38 to 58 minutes old, the fire pings: the model replies with one line the hook supplies, such as `keepalive: cache warmed (idle 40m, next check 4:28pm)` (time since the last non-ping request, and when the next fire is checked), 1 request, 3 terminal lines. A ping is followed 20 minutes later by a blocked fire: one cron expression cannot skip it, and a ping there would cost a request the cache does not need. If the last request is more recent, or the cache is presumed cold (58 minutes or more) or a rate limit hit, the fire is blocked before any request: 0 requests, 2 terminal lines, about 220 context tokens added to the next request. If the session is no longer eligible, or has spent its per-session cost cap, the hook attaches a release note naming the live keepalive job ids and the model deletes them: 2 requests, then no further fires. The ping's own text asks for nothing beyond `ok` without a note attached to that same turn, so a blocked fire left in context is never read as an instruction later (with the earlier ping text, which said to delete the cron when no note was attached, every one of 14 deletes outside a ping turn followed a blocked fire). If that delete is denied or ignored, the remaining fires in that idle stretch are blocked, so it costs one fire, not one per fire.
- **Wrap.** After 2h idle with no subagents in flight, a conductor session in the `auto` or `bypassPermissions` permission mode wraps itself and deletes its keepalive cron, so it prints nothing further. In `default` and `acceptEdits` the cron deletes itself at 2h instead and there is no wrap: measured with no allow rules, the wrap's Read of the command file and both of its Bash calls raise a permission prompt there, which would leave an unattended session waiting at a prompt. Creation, pings and the self-delete (ToolSearch, CronCreate, CronDelete) raised no prompt in any of the four measured modes (`default`, `acceptEdits`, `auto`, `bypassPermissions`). The hook asks for the same self-delete in every other mode, including `plan` and `dontAsk`, where prompt behaviour was not measured. Its last line reads `Session wrapped (idle 2h). Run /exit, then resume with: claude 'Resume wrapped session <id>: ...'` - exit the session when you return, then paste that command to continue. The fresh session reads `.agentic/context.md`, then `.agentic/resume/<id>.md` (goal, next step, pending decisions verbatim, PRs/branches/worktrees, artifact paths, recently returned agents), and picks up from the next step. Lost the line? Run `claude` in the repo and paste: `Resume my last wrapped session: read .agentic/context.md first, then the newest file in .agentic/resume/ (not consumed/). Restate its Next step and Pending operator decisions verbatim, move it to .agentic/resume/consumed/, then continue from the Next step.` Start fresh rather than `claude --resume <id>`: the fresh session costs about 60k tokens of new prefix where a cold resume re-writes the whole old one. The wrap follows `content/commands/ds-wrap-deferred.md` §In-session mode: the model supplies the text and `bin/ds-keepalive-wrap` does every write (wrap lock, directories, atomic renames, 14-day resume prune, lock release), only under `.agentic/` at the repository root above the directory the session was launched from (its nearest ancestor holding `.git`). The resume command names that `.agentic/` by absolute path, so the fresh session's file reads do not depend on where it starts; `claude` itself still starts in whatever directory your shell is in. If any step fails it writes nothing further and the session ends with `Session wrap failed: <reason>` and no resume command; a busy wrap lock ends it with `Session wrap skipped (wrap lock busy)`. The process keeps running until you exit it. Measured: about 4 requests on opus, about 0.3 of one cold re-write at the median 259k-token prefix, and 19-23 terminal lines for the wrap turn. A subagent or background task still in flight keeps the session pinging past 2h (bounded by the cost cap) and wraps after its completion notice plus 2h idle. Only tasks launched by the running process count, and a task ends at its completion notice (also when that notice is queued while the model is busy) or at a successful `TaskStop`; a task from before a restart or `--resume` never holds release.
- **Noise.** At most one disclosed line when the cron is created, then about 6 keepalive lines an hour while you work (blocked fires) and 7.5 an hour while idle-pinging. A 2h idle that ends in a wrap leaves about 35 lines: about 12 from the fires plus the 19-23-line wrap turn.
- **Economics.** Over 30 days of the operator's conductor sessions, at the median ping cost (`0.1*S + 2*854 + 5*193` input-token units; a live measurement gave 446 and 39 on only 5 pings, so the larger corpus medians are kept as the conservative figure), the keepalive alone is worth +15.6M to +62.3M base-input-token equivalents, depending on how many abandoned sessions stay open (positive in every case). The in-session wrap adds +169.0M when the operator starts fresh, against 49.7M of wrap cost on returns and up to 75.0M on abandoned-open sessions. Resuming the wrapped session cold instead turns it negative (-109.1M with every abandoned session left open). `bin/ds-cache-keepalive-sim` re-derives every figure from your own transcripts and prints `keep RELEASE_AFTER_S=<s>` or `opt-out (EV_worst<=0)`. Re-tune by running it and changing the constants in `hooks/lib/cache_keepalive.py` in a PR; retire the hook when it prints opt-out, or when Claude Code ships its own idle-cache keepalive or a longer main-session TTL. On a subscription the real cost is usage limits, which these token figures only approximate.
- **Bounds.** If the hook's library fails to load, every fire is blocked (0 requests). If the hook is uninstalled while a session runs, that session's cron keeps firing with no note and the ping's text asks only for `ok`: 1 request per fire until the session exits (the cron is session-only).
- **Limitations.** 5-minute-TTL sessions, non-conductor sessions and other harnesses are not covered. Cron jobs expire after 7 days. Once a session has been idle past 58 minutes without a ping landing (for example after the machine slept), the cache is presumed cold and every later fire is blocked, never deleted: the cron prints 2 lines and adds about 220 context tokens every 20 minutes until your next prompt or the 7-day expiry. A hung subagent keeps the session pinging up to the cost cap, then the cron deletes itself without a wrap. In `auto` mode Claude Code can refuse to evaluate the wrap's survey call (1 of 3 trials on the final text); the session then writes nothing, deletes its cron and ends with `Session wrap failed: no output`. The in-session wrap skips AGENTS.md updates (it writes them as Watch Out For bullets), takes PR state as a snapshot, and lists branches only when `gh` is unavailable. Unconsumed resume files are pruned after 14 days. Ping turns run the Stop hooks' per-turn side effects (`stop-context.js`).

---

## 4. Environment kill-switches

Unset by default. Set to `1` to disable the named guard for a session.

| Variable | Default (unset) | What it disables |
|---|---|---|
| `AE_ABDICATION_GUARD_DISABLE=1` | guard active | Abdication guard Stop hook (only relevant when `abdication_guard_enabled: true`) |
| `AE_CACHE_KEEPALIVE_DISABLE=1` | keepalive active | Cache keepalive (`hooks/cache-keepalive.py`): no new keepalive cron, and a live one deletes itself at its next warm fire. Same effect as `cache_keepalive: false` |
| `AE_BROWSER_REAPER_DISABLE=1` | reaper active | agent-browser reaper SubagentStop/SessionEnd hook (`hooks/reap-agent-browsers.py`), which closes sessions the ending agent provably opened and sweeps orphaned automation Chrome; disabled runs still log `verdict=disabled` to `~/.agentic/browser-reaper.log` |
| `AE_NESTED_WORKTREE_GUARD_DISABLE=1` | guard active | Nested-worktree-spawn advisory hook (`hooks/enforce-nested-worktree-spawn.py`) |
| `AE_PLANNING_GUARD_DISABLE=1` | guard active | Planning-artifact spawn advisory hook (`hooks/enforce-planning-artifact-spawn.py`) |
| `AE_RM_GUARD_DISABLE=1` | guard active | Guarded-rm hook denying an `rm` whose operand expands an unguarded variable (`hooks/enforce-guarded-rm.py`). Set it before the session starts: the hook reads its own process environment, so writing it inline in a Bash command does not disable it |
| `AE_SHIPPABLE_GUARD_DISABLE=1` | guard active | Shippable-edit guard denying conductor-direct shippable edits (`hooks/enforce-shippable-edit.py`) |
| `AE_SINGULARITY_GUARD_DISABLE=1` | guard active | Orchestrator-singularity hook (prevents subagents from spawning subagents) |
| `AE_SKEPTIC_NEUTRALITY_GUARD_DISABLE=1` | guard active | Skeptic-brief neutrality hook - enforces two bounded surfaces only, not the full neutrality rule, which is now the general recipient-neutral rule at `content/references/subagent-protocol.md` §11 "Spawn-brief provenance" (`hooks/enforce-skeptic-neutrality.py`) |
| `AE_TEAM_ROUTING_DISABLE=1` | guard active | Cross-harness team-routing branch of the background-spawn guard (`hooks/enforce-background-spawn.py`) |
| `AE_TICKET_BATCH_GUARD_DISABLE=1` | guard active | Ticket-batching guard denying agent-initiated tracker-ticket creation without an operator grant (`hooks/enforce-ticket-batching.py`) |
| `AE_TIER_GUARD_DISABLE=1` | guard active | Tier-enforcement hook (prevents sub-Tier-3 downgrades on mandated Tier-3 spawns; accepts `opus` or `fable`, DS-226) |
| `AE_TURN_SHAPE_GUARD_DISABLE=1` | guard active | Turn-shape guard - all three of the hook's checks as of DS-ANSWERFIRST: the blocking structural check (`_execution_prose_flag`, including its `SLOT_LINE_MAX_COUNT` slot-line count and duplicate-label bound), the blocking zero-warrant status-only check (`_status_only_flag`, restored by DS-ANSWERFIRST), and the advisory operator-decisions per-item check (`_decision_item_sprawl_flag`). There is no per-check kill switch (only relevant when `turn_shape_guard_enabled: true`) |
| `AE_WORKTREE_ISOLATION_GUARD_DISABLE=1` | guard active | Worktree-isolation-spawn enforcement hook (`hooks/enforce-worktree-isolation-spawn.py`) |
| `AE_WORKTREE_READ_GUARD_DISABLE=1` | guard active | Worktree-isolation Read guard (`hooks/enforce-worktree-read.py`) |
| `AE_WORKTREE_REAP_DISABLE=1` | reap active | Session-start automatic worktree reap (`content/references/worktree-lifecycle.md` §Session-start prune script, invoking `bin/ds-cleanup-worktrees`) - a session-start-script kill switch, not a hook-enforced guard |
| `AE_WORKTREE_WRITE_GUARD_DISABLE=1` | guard active | Worktree-isolation Write/Edit/MultiEdit guard (`hooks/enforce-worktree-write.py`) |
| `AGENTIC_QUIET=1` | output enabled | Version-check hook user-facing output |
| `AGENTIC_WRAP_DAEMON=1` | (unset) | **INTERNAL** - set by the deferred-wrap daemon only; users must not set this |

Every kill-switch above except `AGENTIC_WRAP_DAEMON` (deliberately set
mid-flight by the deferred-wrap daemon itself, not a static session
setting) is effectively fixed for the life of a session: each `enforce-
*.py`/`enforce-*.sh` hook is a fresh, separate process per invocation, and
a conductor `export` in a Bash tool call sets that variable only in the
*conductor's own shell environment* - it never mutates the environment
the hook-runner subsequently launches its process with, so the hook never
observes it. This is not a "read once at process launch" detail (every
hook process launch already re-reads its own environment fresh); it is
that the two processes' environments are never the same environment to
begin with. For `AE_TICKET_BATCH_GUARD_DISABLE`, `bin/ds-ticket-grant` is
the mid-session alternative: it writes a one-shot exception (a 10-minute
TTL, not a persisting bypass) the hook itself reads, validates, and
atomically consumes on the next denied creation, rather than disabling
the guard outright. Its `reason` field is mechanically enforced (must be
a non-empty string, echoed back in the hook's decision and its
`.enforcement-fires.jsonl` entry) but not verified against anything an
operator actually said - nothing structurally distinguishes a genuine
operator-authorized grant from a conductor self-grant at this trust
boundary. What it buys over the env-var kill switch: a deliberate,
per-create, one-shot, logged act with a quotable justification, instead
of a standing bypass with no audit trail. See
`content/references/delegation-detail.md` §Follow-up Ticket Creation
Discipline, "Operator-granted mid-session exception".

Platform variables (not AE-owned): `CLAUDE_CODE_SUBAGENT_MODEL` (highest-
precedence subagent model override); `GRAPHIFY_OUT` (overrides the graph output
directory; the investigator's optional graph-assisted blast-radius step reads
the graph from there).

---

## 5. Identity files

`.agentic/identity.yml` (project-scoped, gitignored),
`<active-config-dir>/identity.yml` (profile-scoped), and
`~/.agentic/identity.yml` (global). Used for telemetry attribution. The active
profile config dir resolves from `AGENTIC_CONFIG_DIR`, `CLAUDE_CONFIG_DIR`,
`CODEX_HOME`, then `PI_CODING_AGENT_DIR`; profile-scope subcommands accept `--profile-dir <dir>` as
an override.

| Field | Default | Valid values |
|---|---|---|
| `developer_id` | none (absent file = no attribution) | string handle |
| `provisional` | `false` (absent = confirmed) | `true`, `false` |

**Absent file / absent `developer_id`:** no telemetry is attributed; session
logs are not written. The effective default is no identity. Use
`ds-identity auto` to auto-derive a provisional handle from the GitHub
login (lowest-friction starting point).

**6-tier precedence:** project-confirmed > profile-confirmed >
global-confirmed > project-provisional > profile-provisional >
global-provisional > none.

Commands: `ds-identity auto` (derive from GitHub login, writes provisional
global), `ds-identity init <handle> [--scope profile|project]` (manual),
`ds-identity confirm [--scope global|profile|project]` (strip provisional
flag and flush only pending telemetry routed to that scope).

---

## 6. Cross-harness teams: `.agentic/team.yml`

Committed. Enables dispatching Workers to other CLI harnesses. Absent file =
feature off.

| Field | Default | Type | Notes |
|---|---|---|---|
| `enabled` | `false` (absent file = feature off) | bool | Must be explicitly `true` to activate dispatch; absent file is equivalent to `enabled: false` |
| `default_harness` | none (absent = no harness fallback) | string | `codex`, `gemini`, `cursor-agent`, `kimi`, `pi`, `omp`, `claude`; absent means unrouted roles fall through to native spawn |
| `roles` | none (absent = empty map, no per-role routing) | map | Maps role name to `{harness, model}` |
| `dispatch.timeout_seconds` | `1800` | int | Per-Worker timeout |
| `dispatch.output_format` | `"json"` | `"json"`, `"text"` | Worker output format |

See `content/references/cross-harness-teams.md` for the full dispatch table.

---

## 7. Permissions: `.claude/settings.json`

Covers `defaultMode`, the `permissions.allow` list, and the `permissions.deny`
list. The recommended configuration, the eight canonical deny rules, and the
rationale for each are documented in
[safe-configuration.md](safe-configuration.md). This section does not repeat
them here.

Key points:
- `defaultMode: "bypassPermissions"` is recommended for smooth agent operation.
- `settings.local.json` is gitignored; use it for secrets and local env values.
- Hooks are wired by the installer into `~/.claude/settings.json`; do not move
  or rename them.
- The installer wires `hooks/session-start-memory.py` on SessionStart. It acts
  only in a repo whose root `CLAUDE.md` carries the line
  `<!-- dinostack:memory-main-only -->` in place of an import of `MEMORY.md`,
  and then adds root `MEMORY.md` (or its head plus a directive for the rest:
  Read it in full when small, else grep on demand and Read bounded windows) to
  the main session's context at startup, resume, compact and clear.
  It has no config key or kill switch; a repo without the marker is untouched.
- The installer wires `hooks/cache-keepalive.py` on UserPromptSubmit (default
  on; see [Cache keepalive](#cache-keepalive)). It never writes; `cache_keepalive:
  false` or `AE_CACHE_KEEPALIVE_DISABLE=1` turns it off.
- The installer also offers to set `env.AGENT_BROWSER_IDLE_TIMEOUT_MS` to
  `"600000"` (10 minutes), so an `agent-browser` daemon a run leaves behind
  shuts itself and its browser down once no command has arrived for that long.
  The prompt defaults to declining, so an unattended install leaves the
  variable unset. The installer separately wires the reaper hook
  `hooks/reap-agent-browsers.py` on SubagentStop and SessionEnd, which closes a
  session an agent provably opened when that agent ends; a daemon it cannot
  attribute stays unbounded without the timeout. It sets the key into the existing
  `env` object and leaves every other key there alone. A value already present
  is reported and left as it is, whatever it is, so raising it is a durable
  change rather than one the next install undoes. Cost, and the way back, are
  in [`.claude/README.md`](../.claude/README.md) under Recommended Tools.

---

## 8. Tracker config file: `.agentic/tracker.yml`

Project-local, gitignored, pure data (never executes). Merged field-by-field, overlay winning, over the `AGENTS.md` `## Tracker` / `## Linear` resolution chain used by `/ds-implement-ticket` Setup and its deferring consumers.

| Key | Required | Maps to | Notes |
|---|---|---|---|
| `tracker` | always, except for `transitions` alone | `TRACKER` | `jira` \| `linear`; any other value (including absent) makes every OTHER key unusable - `transitions` is the sole exception, see its own row |
| `prefix` | when sole source | `TICKET_PREFIX` | |
| `base_url` | when sole source + jira | `JIRA_BASE_URL` | |
| `workspace` | when sole source + linear | `LINEAR_WORKSPACE` | |
| `qa_assignee` | no | `JIRA_QA_ASSIGNEE_ACCOUNT_ID` / `LINEAR_QA_ASSIGNEE_ID` | |
| `jira_qa_transition` | no | `JIRA_QA_TRANSITION` | jira only |
| `state_in_progress` / `state_in_review` / `state_qa` / `state_dev_complete` / `state_blocked` / `state_done` | no | `TRACKER_STATE_*` | defaults match the live step-4 chain, except `state_dev_complete`, which defaults to the RESOLVED `state_done` value rather than a literal; `state_dev_complete` is the automatic merge target, `state_done` is terminal and never written automatically |
| `pipeline_order` | no | `TRACKER_PIPELINE_ORDER` | comma ordering of `IN_PROGRESS, IN_REVIEW, QA` with optional `DEV_COMPLETE` (implied trailing when omitted); warns and defaults on malformed |
| `transitions` | no | `TRACKER_TRANSITIONS_MODE` | `auto` (default) \| `manual`, case-insensitive; kill switch - `manual` stops the Tracker Writeback Helper from performing any transition at any call site, returning a report-only `skipped_transitions_manual` instead; warns and defaults to `auto` on any other value; not tracker-specific and the ONLY key here that still resolves regardless of which tracker is configured or whether the overlay's tracker-specific configuration is usable at all - no `tracker:` key, an unknown `tracker:` value, or a sole-source overlay missing its declared tracker's required fields; `ds-tracker show --scope effective` and `ds-tracker resolve` both print the resolved value, with its consequence spelled out when it is `manual` |

Any key matching a credential-shaped pattern (`token`, `secret`, `password`, `api_key`, `credential`, `cookie`, `bearer`, `pat`) rejects the **entire file** - this is not a secret scanner, only a key-name guard; a short token pasted under an allowlisted key is still accepted.

Commands: `ds-tracker init --tracker {jira,linear} --prefix P [--base-url U] [--workspace W]`, `ds-tracker show [--scope project|effective]`, `ds-tracker set <key> <value>`, `ds-tracker resolve [--json]`, `ds-tracker path`.

`ds-tracker init`/`set` refuse to write at a path git would track: an unignored path (fix: add a `.gitignore` line), an already-tracked path (fix: `git rm --cached`, since a `.gitignore` line alone does not untrack an indexed file), or an indeterminate ignore state (fails closed). `--force-unignored` downgrades any of the three refusals to a warning and proceeds. Note: `git check-ignore` also honors `~/.gitignore_global` (`core.excludesFile`) and `.git/info/exclude`, so the guard can pass for one operator on a machine-local exclude while refusing a teammate in the same repo - harmless (git still will not track it for that operator), but worth knowing before filing a support question.

---

## Advanced / less-common surfaces

These are rarely needed outside of custom deployment or cross-harness tuning:

- **`~/.agentic/agentic-engineering-config.json`** (`AE_CONFIG`) - holds
  `repo_dir` (path to the AE checkout); used by the version-check and
  `/ds-update` commands.
- **`~/.agentic/tier-map.yml`** or **`.agentic/tier-map.yml`** - Codex/Gemini
  tier routing overrides. See `content/references/tier-map-example.yml`.
- **`~/.agentic/role-models.yml`** or **`.agentic/role-models.yml`** - Pi/omp
  role-to-model mapping. See `content/references/role-models.md`.
- **`DS_CLEANUP_MIN_AGE_HOURS`** - a VALUE-carrying environment variable (not
  a kill-switch, which is why it is here and not in §4): the age floor in
  hours that `/ds-cleanup-worktrees` Step 2 passes through as
  `--min-age-hours`. Unset or empty means "not supplied". Since DS-245 the
  binary's own `--min-age-hours` is off unless supplied, so an
  operator-typed `/ds-cleanup-worktrees` applies no creation-age gate at
  all. Two things supply one anyway, and neither needs an operator to set
  this variable: `--archive-unproven` implies 24h in the binary, and Step 2
  itself applies 24h whenever `<cwd>/.agentic/wrap/lock` is present, which
  is how the unattended `/ds-wrap` Step 5 path gets a floor (shell state
  does not survive between tool calls, so an exported variable could not
  carry it there). Set this variable only to override that default in the
  same shell invocation as Step 2 - it takes precedence over the wrap-lock
  default. Distinct from `AE_WORKTREE_REAP_DISABLE` in §4, which is a
  boolean kill-switch for the session-start reap rather than a value.
