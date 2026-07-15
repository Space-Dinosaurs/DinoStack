# /ds

Activate, deactivate, or inspect agentic-engineering for the current project.
DinoStack ships **dormant by default**: its globally-registered hooks stay
installed but no-op instantly in projects that never opted in. `/ds` is how a
project opts in (or back out).

Implementation: `bin/agentic-ds` (Python 3 stdlib; thin CLI over
`bin/_activation.py`, which owns the marker writes and the resolver the
`hooks/lib/activation.{sh,py,js}` guards read).

## Usage

```
/ds activate [--tier=minimal|medium|full] [--session]
/ds deactivate [--forget]
/ds status
```

## Activation layers (first hit wins)

The guards and this command resolve activation identically:

1. `<cwd>/.agentic/active` - explicit, persistent (written by `/ds activate`).
2. `<cwd>/.agentic/active.session` - explicit, this session only
   (`/ds activate --session`; SessionEnd cleans it up).
3. `<cwd>/.agentic/dormant` - explicit tombstone (`/ds deactivate`); overrides
   auto-detect.
4. `<cwd>/.agentic/` directory exists - zero-migration auto-detect: any existing
   DinoStack project is active without running `/ds`.
5. `<cwd>` listed in `~/.agentic/activation.list` - installer/allowlist entry
   (the flat mirror of `~/.agentic/activation.json`).
6. none of the above - **dormant**: hooks no-op.

## Subcommands

### `activate [--tier=X] [--session]`

Writes `<cwd>/.agentic/active` (JSON `{tier, activated_at, by}`), removes any
`dormant` tombstone, and adds the project to `~/.agentic/activation.list`.
`--tier` records the methodology tier (default `minimal`; see `/agentic-config`).
`--session` writes `active.session` instead (tagged with `CLAUDE_SESSION_ID`
when set), so activation lasts only for the current session.

### `deactivate [--forget]`

Writes the `<cwd>/.agentic/dormant` tombstone and removes `active` /
`active.session`. All other `.agentic/` data (events, session logs, config) is
left intact - deactivation is reversible with `/ds activate`. `--forget` also
drops the project from `~/.agentic/activation.list`.

### `status`

Prints resolved state, the layer that decided it, the tier (when an active
marker records one), and total resident `.agentic/` bytes:

```
agentic-engineering: active
  project: /path/to/project
  reason: active-file
  tier: medium
  resident .agentic/ bytes: 84
```

`reason` is one of `active-file`, `session-file`, `tombstone`, `auto-detect`,
`allowlist`, or `dormant`.

## Fail-ACTIVE guard contract

The hook guards fail **ACTIVE** on any stat error or missing guard lib: a guard
bug can only ever leave the methodology running for an already-active user, never
silently disable it. An indeterminate cwd (hook payload without `cwd`) is treated
as active for the same reason.

## Exit codes

- `0` - success, including `status`.
- `2` - usage error (unknown subcommand or flag).
