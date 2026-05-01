---
description: /agentic-disable
agent: build
---
# /agentic-disable

Append the agentic-engineering opt-out marker to the project
`AGENTS.md` (creating it if absent). Optionally also updates the global
config. Refuses to overwrite an existing opt-in marker without
`--force`.

Implementation: `bin/agentic-disable` (Python 3 stdlib).

## Usage

```
agentic-disable                # write opt-out to project AGENTS.md
agentic-disable --global       # also update ~/.claude/agentic-engineering.json
agentic-disable --force        # remove existing opt-in marker first, then append opt-out
agentic-disable --global --force
```

## Behavior

The script resolves the project `AGENTS.md` (following `CLAUDE.md`
`@AGENTS.md` import if present) and:

1. **Opt-in conflict gate.** If `AGENTS.md` contains a whole-line
   `agentic-engineering: opt-in` (case-insensitive, optional `- `
   prefix), the command exits non-zero (exit code 2) without modifying
   any file. The error message names the absolute path and line number
   of the existing marker. Pass `--force` to remove the opt-in line
   first, then append opt-out.
2. **Idempotency.** If `AGENTS.md` already contains a whole-line
   `agentic-engineering: opt-out`, the command is a no-op (exit 0)
   and prints the existing marker location.
3. **Append insertion point.** When opt-out is appended, the script
   guarantees a blank line separates it from the prior content:
   - File ending in `\n\n` or empty: append `agentic-engineering: opt-out\n`.
   - File ending in `\n` but not `\n\n`: append `\nagentic-engineering: opt-out\n`.
   - File not ending in `\n`: append `\n\nagentic-engineering: opt-out\n`.
   Atomic write via tmp + rename - partial writes cannot leave
   `AGENTS.md` corrupted.
4. **Missing AGENTS.md auto-create.** If `AGENTS.md` does not exist,
   the script creates it with a single line: `agentic-engineering: opt-out\n`.
   Rationale: the user invoked `/agentic-disable`, an explicit opt-out
   signal; creating `AGENTS.md` with the marker is the
   minimum-blast-radius way to record that intent.

## `--global`

Updates `~/.claude/agentic-engineering.json` with `mode=opt-out` and a
fresh `set_at` ISO8601 UTC timestamp. **Preserves existing keys
verbatim**: the helper writes back the same set of keys it read; absent
keys remain absent. The script will not invent `profile`, `preset`, or
any other key not already present in the file.

If the config file is missing, it is created with the minimal shape
`{"mode": "opt-out", "set_at": "<iso>"}`.

## `--force`

When an `agentic-engineering: opt-in` line is present in `AGENTS.md`,
`--force` removes the entire line (including its trailing newline,
leading whitespace, and any `- ` list prefix) before appending the
opt-out marker. The removed line is recoverable via git. The
confirmation output prepends a `--force: removed existing 'opt-in'
marker at line <N>.` line to the standard write summary.

## Exit codes

- `0` - success or idempotent no-op
- `1` - I/O error (read-only filesystem, permission denied, etc.)
- `2` - opt-in conflict and `--force` was not passed; no files modified

## Reversibility

`/agentic-disable` is reversible: the marker is one line in a tracked
file, and the JSON edit is round-trippable. `--force` is also
reversible because the removed `opt-in` line is recoverable from git.
The command is direct-action eligible - no extra confirmation prompt.
