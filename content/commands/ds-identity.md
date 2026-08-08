# /ds-identity

Manage the developer identity used for session telemetry attribution.
Supports manual, automatic (GitHub-derived), and provisional-to-confirmed
identity flows. Identity drives per-project `.agentic/session-log/<dev>.jsonl`
and the global operator mirror at `~/.agentic/session-log/<dev>.jsonl`.

Implementation: `bin/ds-identity` (Python 3 stdlib + optional pyyaml).

## Usage

```
ds-identity init <handle> [--display-name <name>] [--force] [--scope {global,profile,project}] [--profile-dir <dir>]
ds-identity show [--scope {global,profile,project,effective}] [--profile-dir <dir>]
ds-identity auto [--force] [--scope {global,profile,project}] [--profile-dir <dir>]
ds-identity confirm [--scope {global,profile,project}] [--profile-dir <dir>]
```

## Subcommands

### init

```
ds-identity init <handle> [--display-name <name>] [--force] [--scope {global,profile,project}] [--profile-dir <dir>]
```

Set a developer identity manually. `<handle>` must match `^[a-z0-9._-]{1,64}$`.

- `--scope` defaults to `global`, preserving the existing default target path.
- `--scope global` writes `~/.agentic/identity.yml` (atomic tmp+rename).
- `--scope profile` writes `<active-config-dir>/identity.yml`. The active config
  dir is detected from `AGENTIC_CONFIG_DIR`, `CLAUDE_CONFIG_DIR`,
  `CODEX_HOME`, then `PI_CODING_AGENT_DIR`. `--profile-dir <dir>` overrides
  env detection. The resolved
  target must remain lexically under `$HOME`; symlinked parent components and
  outside-home paths are rejected.
- `--scope project` writes `<cwd>/.agentic/identity.yml` (the current repo root;
  exits `1` if `cwd` is not inside a git repo). The project file is gitignored
  by the existing `.agentic/*` umbrella - it is per-developer only and never
  lands in the repo by default.
- If a confirmed identity already exists at the target scope, `--force` is
  required to overwrite.
- If the existing identity is provisional, overwrites silently (no `--force`
  needed).
- After writing, flushes routed pending records (see "Provisional model"
  below) onto the new handle. The canonical `identity_scope` tag must match
  the confirmed target. Profile scope additionally matches `config_dir`;
  project scope matches `repo_root`. Other scopes' buffered sessions remain
  in the buffer.
- `--display-name` sets an optional human-readable name stored as
  `display_name` in the target identity file.

Exit codes: `0` success; `1` invalid handle, missing handle, rejected or
undetectable profile dir, flush error, or not in a git repo (project scope);
`2` confirmed identity exists without `--force`.

### show

```
ds-identity show [--scope {global,profile,project,effective}] [--profile-dir <dir>]
```

Print identity information without writing. A valid query exits `0`, including
an absent identity or an env-undetectable profile scope. A rejected explicit
`--profile-dir` returns exit `1`.

- `--scope global` (default): prints `~/.agentic/identity.yml`.
- `--scope profile`: prints `<active-config-dir>/identity.yml`;
  `--profile-dir <dir>` overrides env detection.
- `--scope project`: prints `<cwd>/.agentic/identity.yml`.
- `--scope effective`: resolves and prints the effective identity per the 6-tier
  ordering (see "Scope / effective identity resolution" below). Also prints a
  `scope:` field indicating which file won (`global`, `profile`, or `project`).

`--scope effective` is available on `show` only; it is rejected with exit `1`
on `init`, `auto`, and `confirm` (structural rejection; those subcommands write
to one explicit scope).

Example output (`--scope effective`, project identity active):

```
developer_id:  repo-handle
display_name:  Repo Handle
created_at:    2026-06-10T09:00:00Z
scope:         project
```

Example output (provisional):

```
developer_id:  jane.dev
display_name:  Jane Dev
created_at:    2026-06-04T10:00:00Z
provisional:   true
```

Example output (confirmed):

```
developer_id:  jane.dev
display_name:  Jane Dev
created_at:    2026-06-04T10:00:00Z
```

`provisional: true` appears only when the identity is provisional. Prints
"No identity set. Run: ds-identity init <handle>" when no file exists
at the requested scope.

Exit codes: `0` for a valid scope, including an absent identity; `1` when an
explicit `--profile-dir` is rejected.

### auto

```
ds-identity auto [--force] [--scope {global,profile,project}] [--profile-dir <dir>]
```

Derive a handle automatically from the GitHub CLI and write it as provisional.
`--scope` defaults to `global`. Project scope writes
`<cwd>/.agentic/identity.yml` and exits `1` outside a git repo. Profile scope
writes `<active-config-dir>/identity.yml`; `--profile-dir <dir>` overrides env
detection and must resolve under `$HOME`.

Steps:
1. Calls `gh api user --jq .login` with a 5-second timeout.
2. Lowercases the result and validates against `^[a-z0-9._-]{1,64}$`.
3. Writes `provisional: true` and `derived_from: gh` to the selected scope's
   identity file (atomic tmp+rename).

Behavior on edge cases:
- `gh` unavailable or unauthenticated: exits `1` with a hint to run
  `gh auth login`.
- Login fails the regex after lowercasing: exits `1` with a hint to use
  `ds-identity init <handle>`.
- A confirmed (non-provisional) identity already exists: exits `2`
  (no overwrite without `--force`).
- A provisional identity already exists: overwrites silently (no `--force`
  needed).

`--force` bypasses the exit-`2` guard for confirmed identities.

A provisional identity does NOT activate telemetry writes. Session data is
instead buffered at `~/.agentic/session-log/.pending/` until confirmed (see
"Provisional model" below).

Exit codes: `0` success; `1` gh unavailable, invalid handle, invalid project
scope, or rejected/undetectable profile dir; `2` confirmed identity exists
without `--force`.

### confirm

```
ds-identity confirm [--scope {global,profile,project}] [--profile-dir <dir>]
```

Confirm a provisional identity and activate telemetry. `--scope` defaults to
`global`. Project scope confirms `<cwd>/.agentic/identity.yml`. Profile scope
confirms `<active-config-dir>/identity.yml`; `--profile-dir <dir>` overrides
env detection.

Steps:
1. Strips `provisional:` and `derived_from:` from the target identity file
   (atomic tmp+rename). The identity is now confirmed.
2. Calls `flushPendingBuffer` - moves only the selected scope's buffered
   sessions into the per-project and global session logs under the confirmed
   handle. The record's `identity_scope` must equal the confirmed scope.
   Profile confirmation additionally matches `config_dir`; project confirmation
   matches `repo_root`.
3. Prints "Flushed N pending session(s)".

If the identity is already confirmed, the identity file remains unchanged,
but pending routing and flush still run for the selected scope; the command
then exits `0`. If no identity file exists at the target scope, exits `1`.

Exit codes: `0` confirmation completed or the identity was already confirmed
after the scope's pending flush ran; `1` no identity file, invalid project
scope, rejected/undetectable profile dir, or identity-file write error.

## Provisional model

When no confirmed identity exists, the Stop hook auto-derives a provisional
handle (via `auto`) and buffers session telemetry rather than writing it
to any log. This eliminates the one-session gap that existed before V1.

### Pending buffer

Location: `~/.agentic/session-log/.pending/<session-uuid>.json`

Each session has one file. Repeated Stop turns atomically replace its safe
existing record with the latest cumulative totals through an exclusive,
unpredictable sibling temporary. Unsafe or substituted destinations are never
followed or modified. Concurrent writers serialize on the pinned pending
directory and an older timestamp cannot replace a newer record. The Stop hook
delegates this write to the bundled
`ds-identity write-hook` helper when identity is provisional or absent.
Format:

```json
{
  "schema_version": 1,
  "session_uuid": "<uuid>",
  "ts": "<ISO8601>",
  "project_slug": "<basename>",
  "repo_root": "<abs cwd>",
  "branch": "<branch>",
  "identity_scope": "<global|profile|project; winning provisional scope>",
  "config_dir": "<winning profile config dir; profile scope only>",
  "data": {
    "wall_seconds": 0,
    "tokens": { "input": 0, "output": 0, "cache_creation": 0, "cache_read": 0 },
    "spawn_count": 0,
    "by_agent": {}
  }
}
```

No `developer_id` field - sessions are unattributed until flushed.
`identity_scope` is the canonical routing tag and comes from the effective
provisional identity, never merely from the active config directory.
`config_dir` is present only for a profile-scope winner. Both routing fields
are removed from the canonical attributed log line.
`ds-cost` does NOT read `.pending/` (the glob `*.jsonl` never reaches
the `.pending/` subdirectory).

Buffer cap: 100 files. Enumeration and processing are streamed and stop after
101 directory entries. When a safe oldest file is pruned, stderr reports
`ds-identity: pending buffer cap exceeded; pruned <N> oldest session(s).`

### Flush (`flushPendingBuffer`)

Called by both `confirm` and `init`. Race-safe: acquires an exclusive
`fcntl.flock` on `~/.agentic/session-log/.flush.lock` for the entire flush
loop. The lock is opened descriptor-relatively with `O_NOFOLLOW | O_NONBLOCK`
and must be a bounded, singly-linked, current-user-owned regular file without
group/world write bits before `flock` is attempted. Unsafe locks fail
immediately; contention has a 30-second timeout and exits cleanly with the
buffer intact for the next run.

For each `.pending/*.json` record:
1. **Scope routing** - requires canonical `identity_scope` to match the
   confirmed target before attribution. Profile confirmation additionally
   requires matching `config_dir`; project confirmation requires matching
   `repo_root`. Non-matching records stay buffered and cannot be reattributed
   by a later identity in another scope. Legacy records without
   `identity_scope` retain their historical filter behavior.
2. **Dedup** - scans the global `<dev>.jsonl` for a matching `session_uuid`.
   If found, unlinks the pending file and skips.
3. **Attribution** - builds an attributed log line (canonical pending fields
   plus `developer_id`; routing-only `config_dir` is omitted; original `ts`
   preserved).
4. **Per-project write** - validates `repo_root` via
   `git -C <repo_root> rev-parse --show-toplevel` (3-second timeout) and
   checks that `basename(toplevel) == project_slug`. On success, appends to
   `<repo_root>/.agentic/session-log/<dev>.jsonl` (mkdir -p). On mismatch or
   failure, skips per-project with a one-line stderr warning.
5. **Global write** - always appends to
   `~/.agentic/session-log/<dev>.jsonl` (mkdir -p).
6. **Cleanup** - unlinks the pending file only after all attempted appends
   succeed. A global-write failure leaves the file for a future retry.

### First-session confirmation prompt

At the first user turn of a new session, the conductor surfaces a non-blocking
notice when a provisional identity is detected:

```
Tracking handle '<handle>' was auto-derived (provisional). Telemetry is
paused until you confirm.
To confirm: ds-identity confirm --scope <scope>
To use a different handle:
  ds-identity init <handle> --force --scope <scope>
```

The conductor substitutes the winning scope. Profile scope uses the active
config-dir env automatically; append `--profile-dir <dir>` only when needed.
Telemetry continues to buffer (not lost). The prompt re-surfaces each session
until confirmed. CI/headless sessions never reach a user turn, so they stay
deferred and buffered automatically.

## Scope / effective identity resolution

A project-local identity file at `<repo>/.agentic/identity.yml` lets a developer
use a different handle for sessions in that repo. A profile identity at
`<active-config-dir>/identity.yml` applies to one harness profile or tenant.
The project file is gitignored by the existing `.agentic/*` umbrella; both
overrides are per-developer.

### Profile config-dir resolution

The active config dir is the first non-empty qualifying environment value in
this order:

1. `AGENTIC_CONFIG_DIR`
2. `CLAUDE_CONFIG_DIR`
3. `CODEX_HOME`
4. `PI_CODING_AGENT_DIR`

A leading `~` is expanded. Paths are normalized lexically, nonexistent suffixes
are preserved, and only paths under `$HOME` qualify. Existing symlinked
components are rejected rather than followed. Use
`--profile-dir <dir>` on `init`, `show --scope profile`, `auto`, or `confirm`
to override env detection. The explicit path must pass the same containment
check.

All identity reads open final targets with `O_NONBLOCK | O_NOFOLLOW` before
`fstat` and reject non-regular, multiply-linked, wrong-owner, oversized, or
invalid UTF-8 files. Display names containing any Unicode `Cc` control
character, including C1 controls U+0080 through U+009F, are rejected. Global,
profile, and project parent components are opened or validated without
following symlinks; writes use the same protected parent descriptor so
`--force` cannot rewrite an outside target. Stop-hook session logs use the same
descriptor-relative final-target checks and additionally reject unsafe modes
and oversized targets before append.

### 6-tier ordering

When the preflight, Stop hook, or `show --scope effective` resolves identity,
it applies this total ordering (higher tier wins):

| Tier | File | State |
|---|---|---|
| 1 (highest) | `<cwd>/.agentic/identity.yml` | confirmed (no `provisional: true`) |
| 2 | `<active-config-dir>/identity.yml` | confirmed |
| 3 | `~/.agentic/identity.yml` | confirmed |
| 4 | `<cwd>/.agentic/identity.yml` | provisional |
| 5 | `<active-config-dir>/identity.yml` | provisional |
| 6 (lowest) | `~/.agentic/identity.yml` | provisional |
| none | no usable identity file exists | - |

Key rules:
- A confirmed global identity is not suppressed by a provisional project or
  profile file. Tier 3 beats Tiers 4 and 5.
- A confirmed project identity beats confirmed profile and global identities.
- A confirmed profile identity beats a confirmed global identity.
- `--scope project` requires the `cwd` to be inside a git repo; exits `1` if not.

### `ds-cost` and multi-handle attribution

A developer who uses project, profile, and global handles can appear as separate
rows in `ds-cost team` and `ds-cost operator` output - one row per
distinct `developer_id`. This is intentional: each handle is an independent
identity. Cross-handle rollup is not provided automatically.

## Identity schema

Files: `~/.agentic/identity.yml` (global), optionally
`<active-config-dir>/identity.yml` (profile), and optionally
`<cwd>/.agentic/identity.yml` (project-local, gitignored). All files use the
same schema.

| Field | Required | Notes |
|---|---|---|
| `developer_id` | yes | Validated handle `^[a-z0-9._-]{1,64}$` |
| `display_name` | no | Optional human-readable name |
| `created_at` | yes | ISO8601 UTC timestamp |
| `provisional` | no | Present and `true` only when auto-derived; absent means confirmed |
| `derived_from` | no | Source of the auto-derived handle; `gh` when set by `auto` |

**Back-compat:** An identity written by `ds-identity init` before V1
has no `provisional` key. Absent `provisional` is treated as confirmed
(`provisional === false`). Existing manually-created identities need zero
migration and continue to work without change.

## Relationship to tracking

| Identity state | Telemetry destination |
|---|---|
| Confirmed | Per-project `.agentic/session-log/<dev>.jsonl` + global `~/.agentic/session-log/<dev>.jsonl` |
| Provisional | `~/.agentic/session-log/.pending/<uuid>.json` (buffered; flushed on confirm/init) |
| None | Same as provisional; Stop hook also appends an identity nudge to this session's `.agentic/context.d/` shard, which the derived `.agentic/context.md` rollup then carries |

- `ds-cost team` reads `.agentic/session-log/` (project-local) - aggregates
  all confirmed developer files for the current repo.
- `ds-cost operator` reads `~/.agentic/session-log/*.jsonl` (global) -
  cross-repo rollup for the operator across all projects.
- Pending buffer is invisible to both commands until flushed.

## Exit codes (summary)

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Error: invalid/missing handle, `gh` unavailable, invalid scope target, rejected/undetectable profile dir, no identity file, or flush error |
| `2` | A confirmed identity already exists; re-run with `--force` to overwrite |
