# ADR: Project scaffolding auto-sync via Activation preflight

- Status: Proposed
- Date: 2026-05-28
- Authors: conductor
- Related: METHODOLOGY.md §Activation preflight, content/commands/init-project.md, docs/planning/team-telemetry-aggregation-adr.md (Stage 1 - the immediate motivating drift case)

## Context

`/init-project` scaffolds a fresh project's `.agentic/` layout, gitignore patterns, and AGENTS.md markers at the moment the operator runs it. From that point on the project's scaffolding is frozen at whatever the methodology shipped at init time.

The methodology continues to evolve. Stage 1 telemetry (just shipped) added two new gitignore lines that pre-existing projects do not have:

```
!.agentic/session-log/
!.agentic/session-log/**
```

Without those lines, the Stop hook writes session-log files but git silently ignores them. The operator gets zero telemetry, no error, no signal - just silent failure. The fix is a 30-second `.gitignore` edit, but the operator has no way to know it's needed unless they read every release note.

This is the same failure pattern documented in `docs/planning/telemetry-install-gap-analysis.md`: convention-based "operator manually patches their project to match the latest scaffolding" silently fails closed across long-running projects. The methodology grows; downstream projects diverge; nobody notices until something is mysteriously broken.

The adapter-sync CI gate catches drift WITHIN the agentic-engineering repo (source content/ vs adapter outputs). There is no equivalent for drift BETWEEN agentic-engineering and the downstream projects that use it.

## Decision

Add a project-scaffolding manifest plus a sync step inside the existing **Activation preflight** in METHODOLOGY.md. The preflight already runs once per session at the first skill invocation, already gates on "is AE active in this project", and already touches `.agentic/`. Folding scaffolding-sync into it gives us the right trigger surface for free.

### Components

**1. Scaffolding manifest** (`content/project-scaffolding.yml`):

A declarative file that enumerates everything a project should have, with a version stamp.

```yaml
scaffolding_version: 1
gitignore:
  - pattern: ".agentic/*"
    purpose: "umbrella ignore for .agentic/ runtime state"
  - pattern: "!.agentic/config.json"
    purpose: "committed: project methodology toggles"
  - pattern: "!.agentic/findings.md"
    purpose: "committed: known findings tracker"
  - pattern: "!.agentic/session-log/"
    purpose: "committed: per-developer session telemetry (Stage 1)"
  - pattern: "!.agentic/session-log/**"
    purpose: "committed: per-developer session telemetry (Stage 1) - directory contents"
files:
  - path: ".agentic/config.json"
    seed: "templates/.agentic/config.json"
    purpose: "project methodology toggles"
  - path: ".agentic/qa.md"
    seed: "templates/.agentic/qa.md"
    purpose: "QA triggers and project quirks"
  # ... other expected scaffolding files
markers:
  - file: "AGENTS.md"
    required_line: "agentic-engineering: opt-in"
    purpose: "explicit activation marker"
```

Version is monotonic. Each change to the manifest bumps `scaffolding_version`.

**2. Version stamp in `.agentic/config.json`**:

```json
{
  "scaffolding_version": 1,
  "debugger_on_failure": false,
  "qa_default_skip": null,
  "model_profile": "default",
  "auto_merge_on_ci_green": false
}
```

Existing `config.json` files without `scaffolding_version` are treated as `0`.

**3. Activation preflight extension (new step in METHODOLOGY.md)**:

After the existing preflight Step 5 (first-activation notice), add Step 6:

```
6. Scaffolding-sync check.
   a. Read content/project-scaffolding.yml from the agentic-engineering installation.
   b. Read .agentic/config.json scaffolding_version (default 0 if absent).
   c. If installed version >= manifest version: skip (no drift).
   d. If installed version < manifest version: enumerate the diff:
      - Missing gitignore lines: APPEND to .gitignore (additive, silent).
      - Missing .agentic/ files: WRITE from seed template (additive, silent).
      - Missing AGENTS.md markers: APPEND (additive, silent).
      - DESTRUCTIVE changes (modify existing tracked files, remove patterns,
        rename files): DO NOT apply. Surface as a banner in .agentic/context.md
        for the operator to review on next session.
   e. After successful additive migration, update .agentic/config.json
      scaffolding_version to the manifest version.
   f. Silent-fail discipline: any error swallowed, methodology proceeds.
```

The preflight remains fast: two file reads + a diff. Sub-100ms for any realistic manifest.

**4. `/migrate-project` slash command**:

Manual escape hatch. Shows the diff explicitly, allows the operator to dry-run, force-apply destructive migrations, or roll back a version stamp.

```
/migrate-project              # show diff, do not apply
/migrate-project --apply      # apply additive migrations + show destructive ones
/migrate-project --apply --include-destructive   # apply everything
/migrate-project --reset 0    # roll back version stamp
```

### Migration types (additive vs destructive)

| Type | Example | Auto-apply at preflight? |
|---|---|---|
| New gitignore line | `!.agentic/session-log/` | Yes (silent) |
| New `.agentic/` file with default seed | `.agentic/config.json` if absent | Yes (silent) |
| New AGENTS.md marker line | `agentic-engineering: opt-in` if missing | No (operator-owned file; surface via context.md banner) |
| Modified gitignore line | Change `.agentic/*` to `.agentic/**` | No (destructive; banner + `/migrate-project --include-destructive` to apply) |
| Removed gitignore line | Drop a no-longer-needed pattern | No (destructive) |
| Renamed scaffolding file | `.agentic/old.md` -> `.agentic/new.md` | No (destructive) |
| Modified contents of existing file | Update a seed template | No (destructive) |

The principle: **the preflight may only ADD. Anything that modifies or removes existing operator-touched state requires explicit consent.**

## Alternatives considered

1. **SessionStart hook in settings.json.** Rejected: fires for every Claude Code session regardless of AE activation; would silently modify projects that haven't opted into the methodology.
2. **Stop hook on every turn with sentinel-gating.** Rejected: more complex than activation-preflight, no real upside, runs in projects regardless of skill invocation.
3. **Operator runs `/migrate-project` manually each release.** Rejected: requires the operator to know the methodology has changed; identical failure mode to the status quo.
4. **Bundle scaffolding into adapter install.sh.** Rejected: install.sh is per-machine, runs at install/update time, has no concept of per-project state.
5. **Document the new lines in release notes only.** Rejected: this is exactly what shipped for Stage 1, and is exactly the failure mode this ADR exists to fix.

## Consequences

**Positive:**
- New methodology releases that add scaffolding lines/files automatically reach existing projects on next AE invocation. No operator action.
- Operators see destructive changes as a context.md banner, retaining control without manual diff inspection.
- Version stamp gives a clear "what version of the methodology is this project on" answer for support/debugging.
- Reuses existing preflight machinery - no new hook to install, no new file to ship to user systems beyond the manifest itself.

**Negative:**
- New protocol surface to maintain: every methodology change that adds scaffolding requires a manifest bump.
- A bug in the migration logic could silently corrupt project state. Mitigation: additive-only at preflight (no overwrites), banner-and-prompt for destructive, comprehensive test coverage on the migration engine.
- Operators may be surprised when `.gitignore` shows modified after a session - documentation must explain this clearly in METHODOLOGY.md and the first-activation notice.

**Neutral:**
- Activation preflight gains ~50-100ms in the drift case (manifest read + diff). No-op case (versions match) adds only the version-read overhead - negligible.

## Open questions

1. **Manifest location for downstream projects.** Where does the preflight read the manifest from? Options: (a) the installed agentic-engineering checkout path stored in `~/.agentic/agentic-engineering-config.json` (set by bootstrap), (b) ship a copy of the manifest into each adapter install (`.claude/skills/agentic-engineering/project-scaffolding.yml`). Recommendation: (b) - already-replicated surface, no path resolution needed at preflight time, automatic version-pinning per adapter install.
2. **Seed-template storage.** Where do template file contents (`.agentic/config.json` default, `.agentic/qa.md` default, etc.) live? Recommendation: ship under `content/templates/.agentic/` in the source repo; adapter builds replicate to `.claude/skills/agentic-engineering/templates/`. Manifest references them by relative path.
3. **Migration audit trail.** Should each migration leave a one-line record (in `.agentic/scaffolding-log.jsonl` or appended to `.agentic/context.md`) so the operator can see what happened? Recommendation: yes, brief one-line append to `.agentic/context.md` per migration applied - matches the existing "operator sees this on next session start" pattern.
4. **Rollback path for failed migrations.** If a migration starts but crashes mid-way, the project is in a partial state. Recommendation: atomic-per-rule (apply each rule independently with try/catch; partial completion is fine; preflight re-runs the diff next session and picks up where it left off). Do not update `scaffolding_version` until all additive rules succeeded.
5. **`init-project` integration.** When `/init-project` scaffolds a new project, it must write the current `scaffolding_version` to the seed `config.json`. Otherwise newly-init'd projects look "old" and trigger spurious migrations. Recommendation: yes, mandatory.

## Implementation sketch

Three units, each independently shippable:

1. **Manifest schema + initial v1 manifest** (`content/project-scaffolding.yml`, `content/templates/.agentic/*`): define the schema, write the v1 manifest covering known drift (session-log gitignore, config.json seed, qa.md seed, AGENTS.md markers), ship via adapter build chain. Tier 2 engineer task.
2. **Preflight integration + migration engine** (`METHODOLOGY.md §Activation preflight` Step 6, new helper module at `bin/agentic-migrate` consumed by the preflight): write the diff/apply logic, version-stamp update, audit-log append, silent-fail discipline. Tier 2.
3. **`/migrate-project` slash command + init-project integration** (`content/commands/migrate-project.md`, `content/commands/init-project.md` Step that writes `scaffolding_version` to seed config): manual escape hatch + ensure new projects start version-stamped. Tier 1-2.

Each unit gets its own Brief; the bundle is Brief-tier (3 Elevated units, single-track, single-session).

## Verification

- Preflight on a fresh project (no `.agentic/` at all) is unchanged (no drift to apply).
- Preflight on a v0 project (existing config.json without `scaffolding_version`) silently applies the v1 manifest's additive rules, writes `scaffolding_version: 1`, appends one-line audit to context.md, methodology proceeds.
- Preflight on a v1 project (current) is a no-op (versions match).
- Destructive change in a future manifest version surfaces a context.md banner rather than auto-applying.
- `/migrate-project` dry-run shows the diff. `--apply` matches preflight behavior. `--include-destructive` applies the banner-flagged items.
- Silent-fail discipline: corrupt manifest, missing template, ENOSPC on write - all swallowed, methodology proceeds without crashing.
- `init-project` writes the current `scaffolding_version` to the seed config; next session preflight sees no drift.
