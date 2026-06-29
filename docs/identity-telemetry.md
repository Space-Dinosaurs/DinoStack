# Identity and Telemetry

`agentic-cost` reports token and wall-time rollups per developer. For those rollups to be meaningful, each developer needs a registered handle so session logs are attributed correctly.

## Registering a handle (global)

The quickest path derives your handle from your GitHub login:

```bash
agentic-identity auto      # derives handle from `gh api user`, writes it provisional
agentic-identity confirm   # strips the provisional flag and flushes buffered sessions
```

Or set a handle manually:

```bash
agentic-identity init <handle>   # writes ~/.agentic/identity.yml directly as confirmed
```

Until you confirm, telemetry is buffered in `~/.agentic/session-log/.pending/` - no sessions are lost. Confirmation flushes the buffer and starts writing attributed logs.

Run `agentic-identity show` at any time to see your current identity.

## Per-project override

If you use a different handle for specific repos, set a project-scoped identity from inside that repo:

```bash
agentic-identity init <handle> --scope project   # writes <repo>/.agentic/identity.yml
agentic-identity confirm --scope project          # confirm a provisional project identity
```

The project file is covered by the existing `.agentic/*` gitignore umbrella - it is per-developer and never committed. The global identity is unchanged.

## Precedence

When both files exist, the most-confirmed identity wins:

**project-confirmed > global-confirmed > project-provisional > global-provisional > none**

A provisional project file never suppresses a working confirmed-global handle. To see which handle is active in the current repo:

```bash
agentic-identity show --scope effective
```

## agentic-cost attribution

`agentic-cost team` aggregates `.agentic/session-log/<dev>.jsonl` files for the current repo. A developer who uses two different handles across repos appears as two rows - this is expected. Per-developer session logs are committed to git via the Phase 8 telemetry commit when `commit_telemetry` is `true` (the default) and identity is confirmed, so a developer's telemetry becomes team-visible after merge and pull. `agentic-cost team` then aggregates any developer's session log that has landed on the current branch.
