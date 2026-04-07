# Contributing

## Getting started

1. Fork and clone the repo
2. Install the Claude Code adapter: `.claude/install.sh`
3. Test changes locally by re-running `install.sh` and verifying behavior in a Claude Code session

## What to contribute

- Bug fixes in rules, references, or adapter scripts
- New agents or commands
- Rule improvements (make them clearer or more precise)
- New adapters for other tools (see [ADAPTERS.md](ADAPTERS.md))
- Documentation improvements

## PR guidelines

- One concern per PR — don't bundle unrelated changes
- Describe the *why* in the PR body, not just the *what*
- Test locally before opening: re-run `install.sh`, open a Claude Code session, verify the change works as expected

## Architecture guardrails

**Methodology vs. adapters.** Rules and references live in `.claude/skills/agentic-engineering/rules/` and `references/`. Adapters (`.claude/`, `.cursor/`) translate those into tool-specific formats. Content changes go in methodology files — never duplicate or diverge content in adapter files.

**Rules vs. references.** Rules are always-loaded on every task. References are loaded on trigger. Keep rules terse — every line costs context on every task (Design Goal 4). Verbose content belongs in a reference file, not a rules file.

**Idempotent install/uninstall.** Install scripts must be safe to run multiple times. Use sentinel markers (`<!-- BEGIN managed-by-agentic-engineering -->`) for managed sections so changes install gracefully and uninstall cleanly.

**Agent frontmatter.** Agent definitions specify `tools:` and `model:` in frontmatter. Only list built-in Claude Code tools — MCP tools are implicitly available. All agents currently use `model: claude-sonnet-4-6`; match this unless there's a specific reason to diverge.

**Symlink delivery.** Agents, commands, and skills are symlinked from the repo into `~/.claude/`. Changes in the repo take effect immediately after install — no copy step needed.

## Style

Match existing patterns before adding new ones. Rules are terse by design. Look at existing rule files before writing new content — if it reads longer than the files around it, trim it.
