# Agentic Engineering - Claude Code Adapter

## What this provides

- **Skill** (`/engineering`) - loads the full engineering methodology on demand
- **Agents** (10) - architect, debugger, engineer, investigator, orchestration-planner, security-auditor, skeptic, adr-drift-detector, adr-generator, qa-engineer
- **Commands** (5) - skeptic, memory-update, wrap, init-project, implement
- **Hooks** - UserPromptSubmit risk-classification reminder, Stop context saver

## Installation

Clone the repo to `~/agentic-engineering/` (this path is expected by the skill):

```bash
git clone git@github.com:Solara6/agentic-engineering.git ~/agentic-engineering
```

Then open Claude Code and ask your agent:

```
Run ~/agentic-engineering/.claude/install.sh
```

Or run manually from the repo root:

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

## Permissions

The install script offers to configure `bypassPermissions` mode in `~/.claude/settings.json`. This is the recommended setup for agentic-engineering — agents need uninterrupted access to Bash, Edit, and Write to work effectively. Constant permission prompts break agent flow and cause subagents to stall.

**What it configures:**

- `defaultMode: "bypassPermissions"` — agents can use tools without prompting
- **Allow list** — `Bash(*)`, `Write`, `Edit`, and write access to `~/.claude/` directories
- **Deny list** — blocks destructive commands as a safety net:
  - `git push --force`, `rm -rf`, `git reset --hard`, `git clean -f`
  - `sudo rm`, `dd if=`, `shutdown`, `reboot`
- **Additional directories** — `~/.claude/projects` for cross-session context

The deny list is merged with any existing deny rules — it won't overwrite rules you've already added. You can edit `~/.claude/settings.json` directly to customize.

## Uninstallation

```bash
.claude/uninstall.sh
```

Removes all symlinks and hook entries added by install. Permissions configuration (`bypassPermissions` mode, allow/deny rules) is intentionally preserved — edit `~/.claude/settings.json` manually to revert.

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
