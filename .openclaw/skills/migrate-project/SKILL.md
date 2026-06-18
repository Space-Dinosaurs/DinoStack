---
name: migrate-project
description: "Conductor-facing command to inspect and apply project scaffolding migrations from the canonical manifest (content/project-scaffolding.yml)."
user-invocable: true
---
# /migrate-project

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

<!--
Purpose: Conductor-facing command to inspect and apply project scaffolding migrations
         from the canonical manifest (content/project-scaffolding.yml).
Public API: /migrate-project, /migrate-project --apply, /migrate-project --apply --include-destructive,
            /migrate-project --reset <version>
Upstream: content/project-scaffolding.yml (via bin/agentic-migrate); project .agentic/config.json
Downstream: called by operator; shells out to bin/agentic-migrate
Failure modes: silently swallowed by agentic-migrate; command surfaces exit-code summary to operator
-->

Inspect or apply project scaffolding migrations from the canonical manifest (`content/project-scaffolding.yml`). By default (no flags) runs a dry-run diff and shows what would change without applying anything.

## CLI

```
/migrate-project                                     # dry-run, show diff, no apply
/migrate-project --apply                             # apply additive rules
/migrate-project --apply --include-destructive       # apply additive + destructive (markers, file modifications, renames)
/migrate-project --reset <version>                   # roll back scaffolding_version stamp only
```

## Subcommands

### (no flags) - Dry-run diff

Shells out to:
```bash
agentic-migrate diff [--manifest <resolved-path>] [--project-root <cwd>]
```

Prints a human-readable summary of what `--apply` would do. Read-only - no changes written.

### --apply - Apply additive rules

Shells out to:
```bash
agentic-migrate apply [--manifest <resolved-path>] [--project-root <cwd>]
```

Applies additive scaffolding rules from the manifest:
- Appends missing `.gitignore` patterns (exact-line match after `rstrip()`; never duplicates).
- Seeds missing `.agentic/` files from `content/templates/` (never overwrites existing files).
- Updates `scaffolding_version` in `.agentic/config.json` when all rules are satisfied.
- Appends one-line audit entry to `.agentic/context.md` if anything was written.
- Acquires `~/.agentic/.scaffolding-apply.lock` before writing (EWOULDBLOCK = another session active, skip silently).

The `markers:` key in the manifest is IGNORED by this path. Operator-owned scaffolding (AGENTS.md markers, destructive file changes) requires `--include-destructive`.

### --apply --include-destructive - Full migration

Same as `--apply` plus applies the `markers:` section of the manifest. Currently a no-op because the v1 manifest has no markers. Future manifest versions may add markers for:
- Inserting lines into `AGENTS.md` (e.g. opt-in markers, tracker config)
- Renaming or modifying existing `.agentic/` files

Use this only when you understand and accept all the changes the manifest prescribes. Preview with the dry-run diff first.

### --reset \<version\> - Roll back stamp only

Sets `scaffolding_version` in `.agentic/config.json` to the specified integer without undoing any applied changes.

**Use case:** you want the next preflight to re-run the full diff and re-emit the audit line - for example, to verify the migration engine is idempotent after a manual edit to `.gitignore` or `.agentic/`. Does NOT undo applied changes; if you need to undo, do so manually.

```bash
agentic-migrate apply --project-root <cwd>  # after resetting stamp, re-apply to re-verify
```

## Manifest resolution

`agentic-migrate` resolves the manifest in this order (first found wins):
1. `AGENTIC_MANIFEST_PATH` env var
2. `~/.claude/skills/agentic-engineering/project-scaffolding.yml`
3. `<script_dir>/../content/project-scaffolding.yml` (dev path)

## Exit codes from agentic-migrate

| Code | Meaning |
|------|---------|
| 0 | Success / no-op |
| 1 | Drift detected (check subcommand only) |
| 2 | Manifest not found or parse error |
| 3 | Partial apply - some rules errored |

## Notes

- AGENTS.md is never modified by `--apply`. Only `--include-destructive` can touch AGENTS.md, and only when the manifest's `markers:` section contains instructions for it.
- This command is safe to run multiple times. All rules are idempotent.
- The `scaffolding_version` stamp in `.agentic/config.json` is the source of truth for "has this project been migrated to vN". The preflight Step 6 compares this stamp against the manifest version on every session start.
