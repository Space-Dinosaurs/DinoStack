# Contributing

## Getting started

1. Fork and clone the repo to `~/agentic-engineering/`:
   ```bash
   git clone git@github.com:Solara6/agentic-engineering.git ~/agentic-engineering
   ```
2. Install the adapter for your tool:
   - Claude Code: `.claude/install.sh` (runs the initial build and wires up the pre-commit hook)
   - Cursor: `.cursor/install.sh` (runs the initial build for the Cursor adapter)
3. Test changes locally by re-running the relevant `install.sh` and verifying behavior in a session

## What to contribute

- Bug fixes in rules, references, or adapter scripts
- New agents or commands
- Rule improvements (make them clearer or more precise)
- New adapters for other tools (see [ADAPTERS.md](ADAPTERS.md))
- Community skills for task-specific workflows (see below)
- Documentation improvements

## PR guidelines

- One concern per PR — don't bundle unrelated changes
- Describe the *why* in the PR body, not just the *what*
- Test locally before opening: re-run `install.sh`, open a Claude Code session, verify the change works as expected

## Before editing

**Pull before you change anything.** Run `git fetch origin && git pull --rebase origin main` at the start of every editing session — especially one that will spawn agents or touch multiple files. This repo is actively maintained. A refactor landing remotely while you work (file renames, symlink restructures, directory reshapes) turns clean edits into hand-merges. Cheap to prevent, expensive to untangle.

## Editing content

**Edit in `content/`, never in adapter files directly.** The `content/` directory is the single source of truth:
- `content/rules/` - the 3 rule files (agent-methodology, code-standards, conventions)
- `content/references/` - the 4 reference docs (skeptic-protocol, subagent-protocol, agent-team, design-goals)
- `content/commands/` - the 5 command files (implement, init-project, memory-update, skeptic, wrap)

Build scripts regenerate adapter files from `content/`:
- `.claude/build.sh` - copies rules/references to the skill directory, prepends prerequisite blockquote to commands
- `.cursor/build.sh` - combines frontmatter sidecars with rules to produce .mdc files, copies references and commands

The pre-commit hook runs both build scripts automatically when `content/` files are staged. If you bypass the hook, run the build scripts manually before committing.

**Frontmatter sidecars.** Cursor rules require YAML frontmatter. This metadata lives in `.cursor/rules/frontmatter/*.yaml` (one file per rule). The cursor build script combines the sidecar with the rule content to produce the `.mdc` file. Edit the sidecar to change frontmatter; edit `content/rules/` to change rule content.

## Architecture guardrails

**Methodology vs. adapters.** Rules and references live in `content/rules/` and `content/references/`. Adapters (`.claude/`, `.cursor/`) translate those into tool-specific formats. Content changes go in `content/` - never edit generated adapter files directly.

## Style

Match existing patterns before adding new ones. Rules are terse by design. Look at existing rule files before writing new content — if it reads longer than the files around it, trim it.

## Contributing a community skill

Community skills live in `community-skills/`. Each is a self-contained skill directory that works without agentic-engineering installed.

To add one:
1. Copy `community-skills/_template/` to `community-skills/your-skill-name/`
2. Fill in the SKILL.md (frontmatter + instructions) and README.md
3. Add your skill to the catalog table in `community-skills/README.md`
4. Open a PR

**Design principle:** community skills must work standalone. Do not add a prerequisite line that loads `/agentic-engineering`. If the core methodology is installed, the skill benefits from it automatically (risk classification, adversarial review, named agents). If not, the skill still functions on its own.

### Formatting standards

Every community skill must follow these conventions so discovery, listing, and install behavior stays consistent:

- **Directory name**: lowercase kebab-case. No spaces, uppercase letters, or underscores. The directory name must match the `name` field in the SKILL.md frontmatter.
- **SKILL.md frontmatter**: a YAML block at the top with `name` and `description` required. The `description` is one line, under 200 characters, phrased as "Use when ..." or a declarative statement of the triggering scenario. This string is what Claude Code matches against to auto-trigger the skill, so be specific about when the skill should fire.
- **SKILL.md body**: must include a `## When to use` section and a `## What it does` section. Additional sections are allowed.
- **README.md**: must include `## What this does`, `## Prerequisites`, `## Installation`, `## Usage`, and `## Author` sections. The Installation section should show `/community-skills install <skill-name>` as the primary method, with the manual `ln -s` command as a fallback.
- **Additional files**: scripts, reference docs, or assets may live in the skill directory. Keep the layout flat unless complexity demands subdirectories.
- **Standalone requirement**: the skill must function without agentic-engineering installed. Verify by temporarily removing the `~/.claude/skills/agentic-engineering` symlink (or testing on a machine without the core methodology) and triggering your skill in a fresh Claude Code session.
- **Catalog entry**: add a row to the table in `community-skills/README.md`: `| skill-name | description | @handle |`
