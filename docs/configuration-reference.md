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
all defaults, no behavior change. The 22 behavioral toggles plus 6 tuning
parameters are listed below. The file also carries a `scaffolding_version` key
that is installer/migration-managed (used by `/ds-migrate-project` as the
source-of-truth stamp for "has this project been migrated to vN") - do not edit
it manually.

### Behavioral toggles

| Key | Default | Valid | Effect |
|---|---|---|---|
| `debugger_on_failure` | `false` | bool | When `true` and path is Elevated, interposes a Debugger before each Phase-7 fix pass on a quality-gate failure |
| `qa_default_skip` | reserved/inert | reserved | Schema placeholder only; does not alter QA-gate behavior |
| `model_profile` | `"default"` | `"default"`, `"budget"` | `budget` routes eligible spawns to Tier 1 to reduce cost; **never applies to `security-auditor` or any mandated Tier-3 spawn** |
| `auto_merge_on_ci_green` | `false` | bool | When `true`, Phase 12 squash-merges after CI green + ready + no change-requests |
| `capability_preflight_mode` | `"blocking"` | `"advisory"`, `"blocking"` | `advisory` warns and proceeds on a missing dep; `blocking` refuses the spawn. Default is `blocking` (all agent manifests are populated as of P2). |
| `perceptual_diff_enabled` | `false` | bool | qa-engineer runs pixelmatch against committed baselines |
| `theme_aware` | `false` | bool | qa-engineer runs scenarios in both light and dark themes |
| `storybook_enabled` | `false` | bool | qa-engineer targets Storybook iframe for isolated component verification |
| `motion_aware` | `false` | bool | qa-engineer runs CDP-emulated reduced-motion checks |
| `storybook_version` | `7` | `6`, `7` | Storybook URL format (`6` = `?selectedKind=&selectedStory=`); set automatically by `/ds-init-project` |
| `commit_telemetry` | `true` | bool | Phase 8 commits the per-developer session-log file as a separate PR commit; set to `false` to opt out |
| `knowledge_commit_on_pr` | `true` | bool | Phase 11e commits changed `MEMORY.md` / `decisions.md` / `.agentic/learnings.md` onto the ticket's PR branch; set to `false` to opt out |
| `deferred_wrap_daemon` | `false` | bool | Opt-in for out-of-session daemon to run deferred `/ds-wrap` jobs (tuned by the `deferred_wrap_*` params below) |
| `abdication_guard_enabled` | absent → guard inert; `/ds-init-project` template sets `true` | bool | Stop hook blocks conductor turns that end by asking permission for a non-destructive next step, announcing a surface-and-proceed default and then not acting on it, or presenting a prose co-equal ballot in an `## Operator decisions` block; requires an explicit `true` to run; kill-switch: `AE_ABDICATION_GUARD_DISABLE=1` |
| `skill_candidate_detection` | `true` | bool | Master toggle for the skill-candidate detector; `false` disables all layers |
| `skill_candidate_nudge` | `false` | bool | In-session nudge when a domain crosses the candidate threshold (requires `skill_candidate_detection: true`) |
| `ticket_driven` | absent-key: `offer` if tracker connected, `off` if not | `"off"`, `"offer"`, `"require"` | Controls ticket-creation gate before first implementer spawn; **absent key resolves based on tracker connection, not to a fixed default** |
| `rework_detection` | `true` | bool | Disables the Phase 9 ledger write, Phase 1 detection, the notice, the `/ds-ticket-triage` badge, and the escalation with a single flag when `false` |
| `pending_merge_sweep` | `true` | bool | Controls the session-start pending-merge sweep that pushes the dev-complete transition (`TRACKER_STATE_DEV_COMPLETE`, which defaults to the resolved `TRACKER_STATE_DONE` value) to the tracker once a ticket's PR merges; set `false` to disable |
| `tracker_state_diagnostic` | `true` | bool | Controls whether the tracker writeback subagent emits a live diagnostic naming currently-available states when a configured `TRACKER_STATE_*` name cannot be used; set `false` to disable |
| `turn_shape_guard_enabled` | `true` | bool | Stop hook (`hooks/enforce-turn-shape.py`) checks the conductor's final turn against the fixed-shape/warranted-turn rule. As of DS-156 NOT uniformly advisory: the execution-turn structural check (`_execution_prose_flag`) is BLOCKING and can block the stop; the answer-turn phrasing check (`_answer_relevance_flag`) remains advisory-only and only logs. **DS-156 CONTRACT, NOT YET SHIPPED:** the currently shipped hook remains uniformly advisory until Unit 2 implements `_execution_prose_flag`. Absent key resolves to on; kill-switch: `AE_TURN_SHAPE_GUARD_DISABLE=1` |
| `worktree_read_guard_exemptions` | `[]` | list of strings | Path prefixes (relative to the primary checkout root) exempted from the worktree-isolation `Read` guard (`hooks/enforce-worktree-read.py`); ships empty. Kill-switch: `AE_WORKTREE_READ_GUARD_DISABLE=1` |

### Tuning parameters

| Key | Default | Type | Effect |
|---|---|---|---|
| `storybook_url` | `"http://localhost:6006"` | string | Storybook dev-server URL |
| `deferred_wrap_idle_minutes` | `15` | int | Idle time before daemon picks up a deferred wrap job |
| `deferred_wrap_heartbeat_seconds` | `120` | int | Daemon heartbeat interval |
| `deferred_wrap_timeout_minutes` | `10` | int | Max time for a single wrap job before timeout |
| `deferred_wrap_inprogress_reclaim_minutes` | `30` | int | Time before an in-progress job is reclaimed |
| `deferred_wrap_pending_ttl_days` | `7` | int | Days before a pending job expires |

---

## 4. Environment kill-switches

Unset by default. Set to `1` to disable the named guard for a session.

| Variable | Default (unset) | What it disables |
|---|---|---|
| `AE_ABDICATION_GUARD_DISABLE=1` | guard active | Abdication guard Stop hook (only relevant when `abdication_guard_enabled: true`) |
| `AE_SINGULARITY_GUARD_DISABLE=1` | guard active | Orchestrator-singularity hook (prevents subagents from spawning subagents) |
| `AE_TIER_GUARD_DISABLE=1` | guard active | Tier-enforcement hook (prevents sub-Opus on mandated Tier-3 spawns) |
| `AE_TURN_SHAPE_GUARD_DISABLE=1` | guard active | Turn-shape guard - both the blocking structural check and the advisory phrasing check (only relevant when `turn_shape_guard_enabled: true`) |
| `AE_WORKTREE_READ_GUARD_DISABLE=1` | guard active | Worktree-isolation Read guard (`hooks/enforce-worktree-read.py`) |
| `AGENTIC_QUIET=1` | output enabled | Version-check hook user-facing output |
| `AGENTIC_WRAP_DAEMON=1` | (unset) | **INTERNAL** - set by the deferred-wrap daemon only; users must not set this |

Platform variables (not AE-owned): `CLAUDE_CODE_SUBAGENT_MODEL` (highest-
precedence subagent model override); `GRAPHIFY_OUT` (overrides graph output
directory; setting it to a non-root path disables the graph risk signal).

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

---

## 8. Tracker config file: `.agentic/tracker.yml`

Project-local, gitignored, pure data (never executes). Merged field-by-field, overlay winning, over the `AGENTS.md` `## Tracker` / `## Linear` resolution chain used by `/ds-implement-ticket` Setup and its deferring consumers.

| Key | Required | Maps to | Notes |
|---|---|---|---|
| `tracker` | always | `TRACKER` | `jira` \| `linear`; any other value = unusable |
| `prefix` | when sole source | `TICKET_PREFIX` | |
| `base_url` | when sole source + jira | `JIRA_BASE_URL` | |
| `workspace` | when sole source + linear | `LINEAR_WORKSPACE` | |
| `qa_assignee` | no | `JIRA_QA_ASSIGNEE_ACCOUNT_ID` / `LINEAR_QA_ASSIGNEE_ID` | |
| `jira_qa_transition` | no | `JIRA_QA_TRANSITION` | jira only |
| `state_in_progress` / `state_in_review` / `state_qa` / `state_dev_complete` / `state_blocked` / `state_done` | no | `TRACKER_STATE_*` | defaults match the live step-4 chain, except `state_dev_complete`, which defaults to the RESOLVED `state_done` value rather than a literal; `state_dev_complete` is the automatic merge target, `state_done` is terminal and never written automatically |
| `pipeline_order` | no | `TRACKER_PIPELINE_ORDER` | comma ordering of `IN_PROGRESS, IN_REVIEW, QA` with optional `DEV_COMPLETE` (implied trailing when omitted); warns and defaults on malformed |

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
