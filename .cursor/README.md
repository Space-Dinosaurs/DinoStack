# Agentic Engineering - Cursor Adapter

## What this provides

- **Rules** (3 .mdc files) - agent methodology, code standards, conventions
- **Reference docs** (5) - skeptic protocol, subagent protocol, agent team, design goals, findings-flywheel
- **Commands** (7) - skeptic, memory-update, wrap, init-project, implement, update-protocol, cleanup-worktrees
- **Agent definitions** (13) - named agent instruction files in `.cursor/agents/`
- **Hooks** - beforeSubmitPrompt risk reminder, stop context saver

## Setup

Clone the repo to `~/agentic-engineering/` (this path is expected by references):

```bash
git clone git@github.com:Solara6/agentic-engineering.git ~/agentic-engineering
```

### Project-level (team use)

Copy the `.cursor/` directory into your project repo:

```bash
cp -r ~/agentic-engineering/.cursor/ /path/to/your/project/.cursor/
```

Commit `.cursor/` so the whole team gets the methodology. Rules, commands, and hooks are picked up automatically by Cursor.

### Global (personal use)

Run the installer from the repo root:

```bash
~/agentic-engineering/.cursor/install.sh
```

This symlinks rules, reference docs, and commands into `~/.cursor/` and copies `hooks.json`. To remove:

```bash
~/agentic-engineering/.cursor/uninstall.sh
```

## How rules load

- **alwaysApply: true** - `agent-methodology.mdc` and `conventions.mdc` load every session
- **Glob-based** - `code-standards.mdc` loads when code files (*.ts, *.py, *.go, etc.) are in context
- **Commands** - available via `/` in Cursor's chat
- **Reference docs** - in `.cursor/rules/references/`, loaded when referenced by rules

## Agent Definitions

`.cursor/agents/` contains 13 agent instruction files, one per named agent in the methodology:

- `architect.md`, `engineer.md`, `investigator.md`, `debugger.md`, `skeptic.md`
- `orchestration-planner.md`, `security-auditor.md`, `qa-engineer.md`
- `perf-analyst.md`, `release-orchestrator.md`, `dependency-auditor.md`
- `adr-drift-detector.md`, `adr-generator.md`

These are generated from `content/agents/` by `.cursor/build.sh`. Each file maps to a Cursor `subagent_type` of the same name. Before spawning a named agent, read the file and include its instructions in the Task prompt. See `orchestration-cursor.mdc` for the full subagent_type mapping and Task API usage.

## Hooks

- `.cursor/hooks/stop-context-cursor.js` — writes session context to `~/.cursor/projects/[hash]/context.md` at session end (Cursor-specific path, distinct from the Claude Code path)
- `.cursor/hooks/risk-reminder.sh` — risk classification reminder, fires before each prompt submission

Hooks are registered in `.cursor/hooks.json`. The stop hook is Cursor-native and writes to the correct Cursor project path.

## Project config convention

Per-project configuration files (`.claude/qa.md`, `.claude/findings.md`) live under `.claude/` even when using Cursor. This keeps them in a single, tool-agnostic location that works across Claude Code, Cursor, and Codex without duplication.
