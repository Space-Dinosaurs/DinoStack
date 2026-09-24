# DinoStack - Claude Code Adapter

## What this provides

- **Skill** (`/dinostack`) - loads the full engineering methodology on demand
- **Agents** (11) - architect, debugger, engineer, investigator, orchestration-planner, security-auditor, skeptic, adr-drift-detector, adr-generator, qa-engineer, learnings-agent
- **Commands** (5) - skeptic, memory-update, wrap, init-project, implement
- **Hooks** - UserPromptSubmit risk-classification reminder, Stop context saver

## Installation

**One-liner (clone + Claude setup in one step):**

```bash
curl -fsSL https://docs.dinostack.ai/install.sh | bash
```

**Or manually:**

```bash
git clone https://github.com/Space-Dinosaurs/DinoStack.git ~/DinoStack
bash ~/DinoStack/.claude/install.sh
```

Then open Claude Code and ask your agent:

```
Run ~/DinoStack/.claude/install.sh
```

Or run manually from the repo root:

```bash
.claude/install.sh
```

This will:
- Symlink agent definitions into `~/.claude/agents/`
- Symlink commands into `~/.claude/commands/`
- Symlink the engineering skill into `~/.claude/skills/dinostack`
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
- `chrome-devtools` - Chrome DevTools access for page inspection, DOM, network, console. Configured in `~/.claude.json`, registered to launch Chrome **headless** on an **isolated** profile (`--headless --isolated`) so an agent-driven browser leaves no window on your desktop. `--isolated` gives each server its own throwaway profile, so concurrent runs stop contending for one profile directory, where sharing one makes a second server's first page-scoped call fail with `The browser is already running for <path>`. Its costs: profile state (cookies, logins, local storage) does not persist between runs, and a server killed without cleanup can leave a temp profile directory behind. You also give up watching an agent's browser live (screenshots and script evaluation are unaffected); remove `--headless` from that entry's `args` to get the window back, or remove `--isolated` from them to get the persistent shared profile back, and the next session picks up either change. If you installed before these flags shipped, re-running the installer offers to add them to your existing entry; declining leaves the file byte-identical. The migration edits an entry only when every one of its `args` names the `chrome-devtools-mcp` package or is one of the two flags it writes, matched by the option name the server itself reads off each argument - a spelling the server ignores, such as `--Headless`, is a flag this installer does not know rather than one it writes. A value on a flag the migration writes bare (`--headless=false` asks for the window) is reported and left alone rather than called configured. Anything else is reported and left byte-identical: a browser connection (`--browser-url`, `--ws-endpoint`, `--auto-connect`) the server never reads `--headless` for, `--user-data-dir` or `--channel`, which the migration no longer writes or reads at all, or simply a flag this installer does not know. A registration whose `args` do not name `chrome-devtools-mcp` is left alone for the same reason, and there the append is what would be dangerous: it would write the flags alone, a registration that cannot launch. Adding `--headless` by hand only helps where the server launches Chrome itself: a registration that connects to a browser you already run never reads it.

**Plugins:**
- `context7` - library and framework documentation. Enable in Claude Code settings.

All tools are optional. Declining does not affect the core install.

## Permissions

The install script offers to configure `bypassPermissions` mode in `~/.claude/settings.json`. This is the recommended setup for DinoStack - agents need uninterrupted access to Bash, Edit, and Write to work effectively. Constant permission prompts break agent flow and cause subagents to stall.

**What it configures:**

- `defaultMode: "bypassPermissions"` - agents can use tools without prompting
- **Allow list** - `Bash(*)`, the bare `Write` and `Edit` tool rules, and path-scoped `Edit(~/.claude/**)` / `Edit(~/.claude/projects/**)` rules. Only `Edit(path)` rules are matched by Claude Code's file-permission checks - path-scoped `Write(path)` rules are ignored and are migrated out of existing settings that already have the bare `Write` rule (left in place otherwise)
- **Deny list** - blocks destructive commands as a safety net:
  - `git push --force`, `rm -rf`, `git reset --hard`, `git clean -f`
  - `sudo rm`, `dd if=`, `shutdown`, `reboot`
- **Additional directories** - `~/.claude/projects` for cross-session context

The deny list is merged with any existing deny rules - it won't overwrite rules you've already added. You can edit `~/.claude/settings.json` directly to customize.

## Uninstallation

```bash
.claude/uninstall.sh
```

Removes all symlinks and hook entries added by install. Permissions configuration (`bypassPermissions` mode, allow/deny rules) is intentionally preserved - edit `~/.claude/settings.json` manually to revert.

## How it works

The `/dinostack` skill auto-triggers when Claude detects engineering tasks. Each agent and command file includes a prerequisite line that ensures the skill loads first, regardless of entry point.

Rules stay as separate files for maintainability:
- `rules/agent-methodology.md` - delegation, risk classification, task decomposition
- `rules/code-standards.md` - tool discipline, quality gates, package management
- `rules/conventions.md` - writing style, project structure, git workflow

Reference docs load on trigger (see Protocol Details in agent-methodology.md):
- `references/skeptic-protocol.md`
- `references/subagent-protocol.md`
- `references/agent-team.md`
- `references/design-goals.md`
