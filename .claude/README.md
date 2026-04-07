# Agentic Engineering - Claude Code Adapter

## What this provides

- **Skill** (`/engineering`) - loads the full engineering methodology on demand
- **Agents** (10) - architect, debugger, engineer, investigator, orchestration-planner, security-auditor, skeptic, adr-drift-detector, adr-generator, qa-engineer
- **Commands** (7) - skeptic, memory-update, wrap, init-project, flow-dev, flow-qa-plan, implement
- **Hooks** - UserPromptSubmit risk-classification reminder, Stop context saver

## Installation

From the repo root:

```bash
.claude/install.sh
```

This will:
- Symlink agent definitions into `~/.claude/agents/`
- Symlink commands into `~/.claude/commands/`
- Symlink the engineering skill into `~/.claude/skills/agentic-engineering`
- Add hook entries to `~/.claude/settings.json` (preserves all existing entries)

The script is idempotent - safe to run multiple times.

## Recommended Tools

The install script will prompt to install these optional tools that enhance the engineering workflow.

**CLIs:**
- `gh` - GitHub CLI for PRs, issues, repo management. Install: `brew install gh`
- `agent-browser` - browser verification for UI changes. Install: `npm install -g agent-browser`
- `lc` (linearctl) - Linear issue tracking CLI. Install: `npm install -g linearctl`
- `rclone` - file sync for Google Drive access. Install: `brew install rclone`

**MCP Servers:**
- `chrome-devtools` - Chrome DevTools access for page inspection, DOM, network, console. Configured in `~/.claude.json`.

**Plugins:**
- `context7` - library and framework documentation. Enable in Claude Code settings.

All tools are optional. Declining does not affect the core install.

## Uninstallation

```bash
.claude/uninstall.sh
```

Removes all symlinks and hook entries added by install. Leaves everything else untouched.

## How it works

The `/agentic-engineering` skill auto-triggers when Claude detects engineering tasks. Each agent and command file includes a prerequisite line that ensures the skill loads first, regardless of entry point.

Rules stay as separate files for maintainability:
- `rules/agent-methodology.md` - delegation, risk classification, task decomposition
- `rules/code-standards.md` - tool discipline, quality gates, package management
- `rules/conventions.md` - writing style, project structure, git workflow

Reference docs load on trigger (see Protocol Details in agent-methodology.md):
- `references/skeptic-protocol.md`
- `references/subagent-protocol.md`
- `references/agent-team.md`
- `references/design-goals.md`
