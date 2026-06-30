---
description: "Read-only inspection of the agentic-engineering activation resolver."
---
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
- `<cwd>/.agentic/config.json` (project config; surfaces the `deferred_wrap_daemon` toggle - prints its value, or `false` when the file or key is absent)

## Output

```
agentic-engineering status
  global config: /Users/<you>/.claude/agentic-engineering.json (found)
  mode: opt-out (source: global config)
  profile: default (source: global)
  preset: none (source: none)
  set_at: 2026-04-15T12:00:00Z
  project marker file: /path/to/project/AGENTS.md
  marker: none
  active: yes (mode=opt-out + marker=none -> active: opt-out activates everywhere unless a project opts out)
  sentinel: .agentic/.activated (present)
  deferred_wrap_daemon: false (source: .agentic/config.json; out-of-session daemon for deferred /wrap jobs)

What this means
  Active here: yes. The methodology governs how work gets done in this project.
  Profile 'default': single-file behavioral edits run directly with a self-check;
    multi-file changes, new files, shared utilities, config, and anything risky
    spawn a Worker plus an independent Skeptic review.
  (relaxed: single-file behavioral edits AND small pure-UI multi-file changes run
    directly - lighter review, faster iteration.)
  (strict: UI-copy tweaks, file renames, and targeted wording fixes are all treated
    as Elevated and get Worker + Skeptic - broadest review coverage.)

How to adjust
  Change the profile for THIS project:
    add a line to /path/to/project/AGENTS.md:  agentic-engineering-profile: relaxed   (or default / strict)
  Change the profile GLOBALLY:
    edit /Users/<you>/.claude/agentic-engineering.json  ->  "profile": "relaxed" | "default" | "strict"
  Turn the skill OFF for this project:        /agentic-disable
  Turn it off EVERYWHERE:                      /agentic-disable --global
  Use a preset instead of a raw profile:
    project: agentic-engineering-preset: lean|standard|strict in AGENTS.md
    global:  "preset": "lean" | "standard" | "strict" in the JSON config
  See every command:                           /agentic-help

Note: deleting the sentinel re-arms the first-activation notice only.
To opt out, use /agentic-disable.
```

The `source` annotation on `mode`, `profile`, and `preset` records where
the effective value came from:

- `mode` source: `global config` - the mode was read from a valid
  `~/.claude/agentic-engineering.json`; `global config (default; file missing)`
  - the config file is missing or malformed, so `mode` falls back to its
  `opt-out` default.
- `global` - the profile or preset value comes from
  `~/.claude/agentic-engineering.json`.
- `project` - the value comes from an `agentic-engineering-profile:` or
  `agentic-engineering-preset:` line in `AGENTS.md`.
- `preset-resolved` - the profile was resolved from a preset (e.g.
  `lean -> relaxed`).
- `none` - no preset is in effect.
- `.agentic/config.json` - the `deferred_wrap_daemon` line comes from the
  project config file; when the file or the key is absent, the line prints the
  documented default (`false`).

The `active` line carries the derivation that produced the active state -
the `(mode=... + marker=... -> active|inactive: <reason>)` clause - so it is
self-explanatory why the project is or is not governed. The "What this means"
block then explains the resolved profile's review behavior (with the other
two profiles shown as parenthetical contrast), and the "How to adjust" block
lists the exact edits to change the profile, swap to a preset, or turn the
skill off.

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
