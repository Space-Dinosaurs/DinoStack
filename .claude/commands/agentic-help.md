> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.

# /agentic-help

Static, zero-token command reference for the agentic-engineering skill.
Prints every slash command with a one-line description, grouped by intent,
plus usage patterns for inspecting, deliberately invoking, and tuning the
skill. Writes nothing. Always exits 0.

Implementation: `bin/agentic-help` (Python 3 stdlib).

## Usage

```
agentic-help
```

No subcommands, no flags. The help text is a compile-time constant; the
command reads no files and depends on no environment state.

## Output

A fixed reference block: the command inventory grouped under "Inspect &
configure", "Plan & build" (includes `/brief`, `/implement-ticket`,
`/ticket-triage`, `/init-project`, `/skeptic`), "Maintain & curate", and
"Audit & improve the methodology", followed by a "Usage patterns" section
covering how to inspect current config, deliberately invoke the skill when
it is disabled or in opt-in mode, change the workflow strictness, and turn
the skill off.

## Exit code

- `0` - always. The command is static and read-only; it has no inputs to
  validate and never raises.
