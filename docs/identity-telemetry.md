# Identity and Telemetry

`ds-cost` reports token and wall-time rollups per developer. For those rollups to be meaningful, each developer needs a registered handle so session logs are attributed correctly.

## Registering a handle (global)

The quickest path derives your handle from your GitHub login:

```bash
ds-identity auto      # derives handle from `gh api user`, writes it provisional
ds-identity confirm   # strips the provisional flag and flushes buffered sessions
```

Or set a handle manually:

```bash
ds-identity init <handle>   # writes ~/.agentic/identity.yml directly as confirmed
```

Until you confirm, telemetry is buffered in `~/.agentic/session-log/.pending/` - no sessions are lost. Confirmation flushes only pending records matching the confirmed effective scope and retains nonmatching records. Matching records start writing attributed logs; nonmatching records remain buffered for their own scope.

Pending records use `identity_scope` from the effective provisional identity.
An active profile cannot retag a global or project winner, so later profile
confirmation cannot reattribute that session. Identity reads and writes reject
symlinked parents and special, multiply-linked, wrong-owner, unsafe-mode, or
oversized target files. Display names containing Unicode control characters
are rejected. Stop-hook telemetry is persisted through the bundled
`ds-identity` helper, which applies the same descriptor-relative checks to
project and global logs. Pending records use exclusive unpredictable
temporaries and no-clobber publication. The flush lock is validated as a safe
regular file before bounded `flock` acquisition.

Run `ds-identity show --scope effective` at any time to see the identity
that wins for the current project and profile.

## Per-profile and per-project overrides

For separate harness tenants or config profiles, store the identity beside
that profile's configuration:

```bash
AGENTIC_CONFIG_DIR=~/.claude-client-a ds-identity auto --scope profile
AGENTIC_CONFIG_DIR=~/.claude-client-a ds-identity confirm --scope profile
```

Profile config-dir detection uses `AGENTIC_CONFIG_DIR`, then
`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, then `PI_CODING_AGENT_DIR`. You can instead pass
`--profile-dir <dir>`. Profile dirs must remain lexically under `$HOME` and
must not contain symlinked components.

Pi exposes `PI_CODING_AGENT_DIR` at runtime, so Pi profile identity follows
that binding. OMP has no native runtime config-dir binding; a flag-only
`.omp/install.sh --config-dir=...` install therefore keeps identity global
instead of creating an unreachable profile identity. Set
`AGENTIC_CONFIG_DIR` for both install and runtime when OMP profile identity is
required.

If you use a different handle for specific repos, set a project-scoped identity from inside that repo:

```bash
ds-identity init <handle> --scope project   # writes <repo>/.agentic/identity.yml
ds-identity confirm --scope project          # confirm a provisional project identity
```

The project file is covered by the existing `.agentic/*` gitignore umbrella - it is per-developer and never committed. The global identity is unchanged.

## Precedence

When multiple identity files exist, confirmation wins before scope:

**project-confirmed > profile-confirmed > global-confirmed > project-provisional > profile-provisional > global-provisional > none**

A provisional project or profile file never suppresses a working confirmed
identity. To see which handle is active in the current repo and profile:

```bash
ds-identity show --scope effective
```

## ds-cost attribution

`ds-cost team` aggregates `.agentic/session-log/<dev>.jsonl` files for the current repo. A developer who uses two different handles across repos appears as two rows - this is expected. Per-developer session logs are committed to git via the Phase 8 telemetry commit when `commit_telemetry` is `true` (the default) and identity is confirmed, so a developer's telemetry becomes team-visible after merge and pull. `ds-cost team` then aggregates any developer's session log that has landed on the current branch.
