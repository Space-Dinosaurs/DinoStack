---
description: /agentic-identity
agent: build
---
# /agentic-identity

Manage the developer identity used for session telemetry attribution.
Supports manual, automatic (GitHub-derived), and provisional-to-confirmed
identity flows. Identity drives per-project `.agentic/session-log/<dev>.jsonl`
and the global operator mirror at `~/.agentic/session-log/<dev>.jsonl`.

Implementation: `bin/agentic-identity` (Python 3 stdlib + optional pyyaml).

## Usage

```
agentic-identity init <handle> [--display-name <name>] [--force] [--scope {global,project}]
agentic-identity show [--scope {global,project,effective}]
agentic-identity auto [--force] [--scope {global,project}]
agentic-identity confirm [--scope {global,project}]
```

## Subcommands

### init

```
agentic-identity init <handle> [--display-name <name>] [--force] [--scope {global,project}]
```

Set a developer identity manually. `<handle>` must match `^[a-z0-9._-]{1,64}$`.

- `--scope` defaults to `global`, preserving all existing behavior byte-for-byte.
- `--scope global` writes `~/.agentic/identity.yml` (atomic tmp+rename).
- `--scope project` writes `<cwd>/.agentic/identity.yml` (the current repo root;
  exits `1` if `cwd` is not inside a git repo). The project file is gitignored
  by the existing `.agentic/*` umbrella - it is per-developer only and never
  lands in the repo by default.
- If a confirmed identity already exists at the target scope, `--force` is
  required to overwrite.
- If the existing identity is provisional, overwrites silently (no `--force`
  needed).
- After writing, flushes any pending buffer (see "Provisional model" below)
  onto the new handle. For `--scope project`, only pending records whose
  `repo_root` matches the current repo are flushed to the project handle;
  other repos' buffered sessions remain in the buffer.
- `--display-name` sets an optional human-readable name stored as
  `display_name` in the target identity file.

Exit codes: `0` success; `1` invalid handle, missing handle, flush error, or
not in a git repo (project scope); `2` confirmed identity exists without `--force`.

### show

```
agentic-identity show [--scope {global,project,effective}]
```

Print identity information. No writes, always exits `0`.

- `--scope global` (default): prints `~/.agentic/identity.yml`.
- `--scope project`: prints `<cwd>/.agentic/identity.yml`.
- `--scope effective`: resolves and prints the effective identity per the 4-tier
  ordering (see "Scope / effective identity resolution" below). Also prints a
  `scope:` field indicating which file won (`global` or `project`).

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
"No identity set. Run: agentic-identity init <handle>" when no file exists
at the requested scope.

Exit codes: `0` always.

### auto

```
agentic-identity auto [--force] [--scope {global,project}]
```

Derive a handle automatically from the GitHub CLI and write it as provisional.
`--scope` defaults to `global`. `--scope project` writes to `<cwd>/.agentic/identity.yml`
(exits `1` if not in a git repo).

Steps:
1. Calls `gh api user --jq .login` with a 5-second timeout.
2. Lowercases the result and validates against `^[a-z0-9._-]{1,64}$`.
3. Writes `provisional: true` and `derived_from: gh` to
   `~/.agentic/identity.yml` (atomic tmp+rename).

Behavior on edge cases:
- `gh` unavailable or unauthenticated: exits `1` with a hint to run
  `gh auth login`.
- Login fails the regex after lowercasing: exits `1` with a hint to use
  `agentic-identity init <handle>`.
- A confirmed (non-provisional) identity already exists: exits `2`
  (no overwrite without `--force`).
- A provisional identity already exists: overwrites silently (no `--force`
  needed).

`--force` bypasses the exit-`2` guard for confirmed identities.

A provisional identity does NOT activate telemetry writes. Session data is
instead buffered at `~/.agentic/session-log/.pending/` until confirmed (see
"Provisional model" below).

Exit codes: `0` success; `1` gh unavailable or invalid handle; `2` confirmed
identity exists without `--force`.

### confirm

```
agentic-identity confirm [--scope {global,project}]
```

Confirm a provisional identity and activate telemetry. `--scope` defaults to
`global`. `--scope project` confirms `<cwd>/.agentic/identity.yml` (exits `1`
if not in a git repo or if no project identity file exists).

Steps:
1. Strips `provisional:` and `derived_from:` from the target identity file
   (atomic tmp+rename). The identity is now confirmed.
2. Calls `flushPendingBuffer` - moves buffered pending sessions into the
   per-project and global session logs under the confirmed handle (see
   "Pending buffer" below). For `--scope project`, only records whose
   `repo_root` matches the current repo are attributed to the project handle.
3. Prints "Flushed N pending session(s)".

If the identity is already confirmed, `confirm` is a no-op (exits `0`).
If no identity file exists at the target scope, exits `1`.

Exit codes: `0` success or already confirmed; `1` no identity file or
flush error.

## Provisional model

When no confirmed identity exists, the Stop hook auto-derives a provisional
handle (via `auto`) and buffers session telemetry rather than writing it
to any log. This eliminates the one-session gap that existed before V1.

### Pending buffer

Location: `~/.agentic/session-log/.pending/<session-uuid>.json`

Each session produces one file, written atomically (tmp+rename) by the Stop
hook when the identity is provisional or absent. Format:

```json
{
  "schema_version": 1,
  "session_uuid": "<uuid>",
  "ts": "<ISO8601>",
  "project_slug": "<basename>",
  "repo_root": "<abs cwd>",
  "branch": "<branch>",
  "data": {
    "wall_seconds": 0,
    "tokens": { "input": 0, "output": 0, "cache_creation": 0, "cache_read": 0 },
    "spawn_count": 0,
    "by_agent": {}
  }
}
```

No `developer_id` field - sessions are unattributed until flushed.
`agentic-cost` does NOT read `.pending/` (the glob `*.jsonl` never reaches
the `.pending/` subdirectory).

Buffer cap: 100 files. When the cap is exceeded, the oldest file (by `ts`)
is dropped and a one-line notice is printed to stderr.

### Flush (`flushPendingBuffer`)

Called by both `confirm` and `init`. Race-safe: acquires an exclusive
`fcntl.flock` on `~/.agentic/session-log/.flush.lock` for the entire flush
loop (blocking acquire, 30-second timeout; on timeout prints a stderr warning
and exits cleanly with the buffer intact for the next run).

For each `.pending/*.json` record:
1. **Dedup** - scans the global `<dev>.jsonl` for a matching `session_uuid`.
   If found, unlinks the pending file and skips.
2. **Attribution** - builds an attributed log line (all pending fields plus
   `developer_id`; original `ts` preserved).
3. **Per-project write** - validates `repo_root` via
   `git -C <repo_root> rev-parse --show-toplevel` (3-second timeout) and
   checks that `basename(toplevel) == project_slug`. On success, appends to
   `<repo_root>/.agentic/session-log/<dev>.jsonl` (mkdir -p). On mismatch or
   failure, skips per-project with a one-line stderr warning.
4. **Global write** - always appends to
   `~/.agentic/session-log/<dev>.jsonl` (mkdir -p).
5. **Cleanup** - unlinks the pending file only after all attempted appends
   succeed. A global-write failure leaves the file for a future retry.

### First-session confirmation prompt

At the first user turn of a new session, the conductor surfaces a non-blocking
notice when a provisional identity is detected:

```
Tracking handle '<handle>' was auto-derived (provisional). Telemetry is
paused until you confirm. To confirm: agentic-identity confirm
To use a different handle: agentic-identity init <handle> --force
```

Telemetry continues to buffer (not lost). The prompt re-surfaces each session
until confirmed. CI/headless sessions never reach a user turn, so they stay
deferred and buffered automatically.

## Scope / effective identity resolution

A project-local identity file at `<repo>/.agentic/identity.yml` lets a developer
use a different handle for sessions in that repo without changing their global
default. The file is gitignored by the existing `.agentic/*` umbrella; it is
per-developer and never lands in the repo by default.

### 4-tier ordering

When the preflight, Stop hook, or `show --scope effective` resolves identity,
it applies this total ordering (higher tier wins):

| Tier | File | State |
|---|---|---|
| 1 (highest) | `<cwd>/.agentic/identity.yml` | confirmed (no `provisional: true`) |
| 2 | `~/.agentic/identity.yml` | confirmed |
| 3 | `<cwd>/.agentic/identity.yml` | provisional |
| 4 (lowest) | `~/.agentic/identity.yml` | provisional |
| none | neither file exists | - |

Key rules:
- A **confirmed global identity is not suppressed** by a provisional project
  file. Tier 2 beats Tier 3.
- A confirmed project identity beats a confirmed global (Tier 1 > Tier 2).
- `--scope project` requires the `cwd` to be inside a git repo; exits `1` if not.

### `agentic-cost` and two-handle attribution

A developer who uses a `--scope project` handle in repo A and their global handle
everywhere else will appear as **two separate rows** in `agentic-cost team` and
`agentic-cost operator` output - one row per distinct `developer_id`. This is
intentional: each handle is an independent identity. Cross-handle rollup is not
provided automatically; aggregate manually if needed.

## Identity schema

Files: `~/.agentic/identity.yml` (global) and optionally `<cwd>/.agentic/identity.yml`
(project-local, gitignored). Both files use the same schema.

| Field | Required | Notes |
|---|---|---|
| `developer_id` | yes | Validated handle `^[a-z0-9._-]{1,64}$` |
| `display_name` | no | Optional human-readable name |
| `created_at` | yes | ISO8601 UTC timestamp |
| `provisional` | no | Present and `true` only when auto-derived; absent means confirmed |
| `derived_from` | no | Source of the auto-derived handle; `gh` when set by `auto` |

**Back-compat:** An identity written by `agentic-identity init` before V1
has no `provisional` key. Absent `provisional` is treated as confirmed
(`provisional === false`). Existing manually-created identities need zero
migration and continue to work without change.

## Relationship to tracking

| Identity state | Telemetry destination |
|---|---|
| Confirmed | Per-project `.agentic/session-log/<dev>.jsonl` + global `~/.agentic/session-log/<dev>.jsonl` |
| Provisional | `~/.agentic/session-log/.pending/<uuid>.json` (buffered; flushed on confirm/init) |
| None | Same as provisional; Stop hook also appends an identity nudge to `.agentic/context.md` |

- `agentic-cost team` reads `.agentic/session-log/` (project-local) - aggregates
  all confirmed developer files for the current repo.
- `agentic-cost operator` reads `~/.agentic/session-log/*.jsonl` (global) -
  cross-repo rollup for the operator across all projects.
- Pending buffer is invisible to both commands until flushed.

## Exit codes (summary)

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Error: invalid/missing handle, `gh` unavailable, no identity file, flush error |
| `2` | A confirmed identity already exists; re-run with `--force` to overwrite |
