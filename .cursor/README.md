# DinoStack - Cursor Adapter

## What this provides

- **Rules** (3 .mdc files) - agent methodology, code standards, conventions
- **Reference docs** (4) - skeptic protocol, subagent protocol, agent team, design goals
- **Commands** (6) - skeptic, memory-update, wrap, init-project, implement, update-agentic-engineering
- **Hooks** - beforeSubmitPrompt risk reminder, stop context saver

## Setup

First, clone the repo if you haven't already:

```bash
git clone https://github.com/Space-Dinosaurs/DinoStack.git ~/DinoStack
```

### Project-level (team use)

Copy the `.cursor/` directory into your project repo:

```bash
cp -r ~/DinoStack/.cursor/ /path/to/your/project/.cursor/
```

Commit `.cursor/` so the whole team gets the methodology. Rules, commands, and hooks are picked up automatically by Cursor.

### Global (personal use)

Run the installer from the repo root:

```bash
bash ~/DinoStack/.cursor/install.sh
```

This symlinks rules, reference docs, and commands into `~/.cursor/` and copies `hooks.json`. To remove:

```bash
bash ~/DinoStack/.cursor/uninstall.sh
```

## How rules load

- **alwaysApply: false** - `agent-methodology.mdc` and `conventions.mdc` load on-demand (not every session)
- **Glob-based** - `code-standards.mdc` loads when code files (*.ts, *.py, *.go, etc.) are in context
- **Commands** - available via `/` in Cursor's chat
- **Reference docs** - in `.cursor/references/`, loaded when referenced by rules

## Hooks

- **beforeSubmitPrompt** - fires a risk-classification reminder before every prompt
- **stop** - runs `hooks/stop-context.js` on session end

**Note:** The stop hook script was written for Claude Code and saves context to a Claude Code-specific path. It runs without error in Cursor but the saved context is not automatically surfaced in subsequent Cursor sessions. For session continuity in Cursor, manually maintain a `context.md` file at your project root.
