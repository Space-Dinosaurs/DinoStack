# Configuration reference

Every user-facing setting in the agentic-engineering methodology, with its
default value and where to set it. This is the complete catalog - if you only
want to tune Skeptic overhead, you need only `profile`. See
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

Committed to the repo. Seeded with defaults by `/init-project`. Absent file =
all defaults, no behavior change. The 16 behavioral toggles plus 6 tuning
parameters are listed below. The file also carries a `scaffolding_version` key
that is installer/migration-managed (used by `/migrate-project` as the
source-of-truth stamp for "has this project been migrated to vN") - do not edit
it manually.

### Behavioral toggles

| Key | Default | Valid | Effect |
|---|---|---|---|
| `debugger_on_failure` | `false` | bool | When `true` and path is Elevated, interposes a Debugger before each Phase-7 fix pass on a quality-gate failure |
| `qa_default_skip` | reserved/inert | reserved | Schema placeholder only; does not alter QA-gate behavior |
| `model_profile` | `"default"` | `"default"`, `"budget"` | `budget` routes eligible spawns to Tier 1 to reduce cost; **never applies to `security-auditor` or any mandated Tier-3 spawn** |
| `auto_merge_on_ci_green` | `false` | bool | When `true`, Phase 12 squash-merges after CI green + ready + no change-requests |
| `capability_preflight_mode` | `"blocking"` | `"advisory"`, `"blocking"` | `advisory` warns and proceeds on a missing dep; `blocking` refuses the spawn. Default is `blocking` (all agent manifests are populated as of P2). Note: METHODOLOGY.md prose says `advisory` - that text is stale; `blocking` is the canonical default. |
| `perceptual_diff_enabled` | `false` | bool | qa-engineer runs pixelmatch against committed baselines |
| `theme_aware` | `false` | bool | qa-engineer runs scenarios in both light and dark themes |
| `storybook_enabled` | `false` | bool | qa-engineer targets Storybook iframe for isolated component verification |
| `motion_aware` | `false` | bool | qa-engineer runs CDP-emulated reduced-motion checks |
| `storybook_version` | `7` | `6`, `7` | Storybook URL format (`6` = `?selectedKind=&selectedStory=`); set automatically by `/init-project` |
| `commit_telemetry` | `true` | bool | Phase 8 commits the per-developer session-log file as a separate PR commit; set to `false` to opt out |
| `deferred_wrap_daemon` | `false` | bool | Opt-in for out-of-session daemon to run deferred `/wrap` jobs (tuned by the `deferred_wrap_*` params below) |
| `abdication_guard_enabled` | `false` | bool | Stop hook blocks conductor turns that end by asking permission for a non-destructive next step; kill-switch: `AE_ABDICATION_GUARD_DISABLE=1` |
| `skill_candidate_detection` | `true` | bool | Master toggle for the skill-candidate detector; `false` disables all layers |
| `skill_candidate_nudge` | `false` | bool | In-session nudge when a domain crosses the candidate threshold (requires `skill_candidate_detection: true`) |
| `ticket_driven` | absent-key: `offer` if tracker connected, `off` if not | `"off"`, `"offer"`, `"require"` | Controls ticket-creation gate before first implementer spawn; **absent key resolves based on tracker connection, not to a fixed default** |

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
| `AGENTIC_QUIET=1` | output enabled | Version-check hook user-facing output |
| `AGENTIC_WRAP_DAEMON=1` | (unset) | **INTERNAL** - set by the deferred-wrap daemon only; users must not set this |

Platform variables (not AE-owned): `CLAUDE_CODE_SUBAGENT_MODEL` (highest-
precedence subagent model override); `GRAPHIFY_OUT` (overrides graph output
directory; setting it to a non-root path disables the graph risk signal).

---

## 5. Identity files

`.agentic/identity.yml` (project-scoped, gitignored) and `~/.agentic/identity.yml`
(global). Used for telemetry attribution.

| Field | Default | Valid values |
|---|---|---|
| `developer_id` | required if file exists | string handle |
| `provisional` | `false` (absent = confirmed) | `true`, `false` |

**4-tier precedence:** project-confirmed > global-confirmed >
project-provisional > global-provisional > none.

Commands: `agentic-identity auto` (derive from GitHub login, writes provisional
global), `agentic-identity init <handle> [--scope project]` (manual),
`agentic-identity confirm` (strip provisional flag, flush pending telemetry).

---

## 6. Cross-harness teams: `.agentic/team.yml`

Committed. Enables dispatching Workers to other CLI harnesses. Absent file =
feature off.

| Field | Default | Type | Notes |
|---|---|---|---|
| `enabled` | required | bool | `true`/`false`; absent file treated as `false` |
| `default_harness` | optional | string | `codex`, `gemini`, `cursor-agent`, `kimi`, `pi`, `omp`, `claude` |
| `roles` | optional | map | Maps role name to `{harness, model}` |
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

## Advanced / less-common surfaces

These are rarely needed outside of custom deployment or cross-harness tuning:

- **`~/.agentic/agentic-engineering-config.json`** (`AE_CONFIG`) - holds
  `repo_dir` (path to the AE checkout); used by the version-check and
  `pull-and-install` commands.
- **`~/.agentic/tier-map.yml`** or **`.agentic/tier-map.yml`** - Codex/Gemini
  tier routing overrides. See `content/references/tier-map-example.yml`.
- **`~/.agentic/role-models.yml`** or **`.agentic/role-models.yml`** - Pi/omp
  role-to-model mapping. See `content/references/role-models.md`.
