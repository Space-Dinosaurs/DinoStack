# /agentic-status

Read-only inspection of the agentic-engineering activation resolver.
Dumps the resolved global config, project marker, profile, preset, and
first-activation sentinel state. Writes nothing. Always exits 0.

Implementation: `bin/agentic-status` (Python 3 stdlib).

## Usage

```
agentic-status
```

No subcommands, no flags. Reads:

- `~/.claude/agentic-engineering.json` (global config)
- `<cwd>/AGENTS.md` (project marker; resolves through `CLAUDE.md` `@AGENTS.md` import if present)
- `<cwd>/.agentic/.activated` (first-activation sentinel)

## Output

```
agentic-engineering status
  global config: /Users/<you>/.claude/agentic-engineering.json (found)
  mode: opt-out
  profile: default (source: global)
  preset: none (source: none)
  set_at: 2026-04-15T12:00:00Z
  project marker file: /path/to/project/AGENTS.md
  marker: none
  active: yes
  sentinel: .agentic/.activated (present)

Note: deleting the sentinel re-arms the first-activation notice only.
To opt out, use /agentic-disable.
```

The `source` annotation on `profile` and `preset` records where the
effective value came from:

- `global` - the value comes from `~/.claude/agentic-engineering.json`.
- `project` - the value comes from an `agentic-engineering-profile:` or
  `agentic-engineering-preset:` line in `AGENTS.md`.
- `preset-resolved` - the profile was resolved from a preset (e.g.
  `lean -> relaxed`).
- `none` - no preset is in effect.

## Sentinel as reset

The `.agentic/.activated` sentinel is the per-project record that the
first-activation notice has already been shown. Deleting it re-arms the
notice only - it does NOT change activation state, the global config,
or the project marker. To actually opt the project out, use
`/agentic-disable`.

## Exit code

- `0` - always. The command is read-only and never raises on missing or
  malformed input. Missing config, missing AGENTS.md, and parse errors
  all render as `missing` / `none` / defaults.
