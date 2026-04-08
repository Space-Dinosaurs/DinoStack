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
