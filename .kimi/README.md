# Agentic Engineering - Kimi Code CLI Adapter

Adapter for [Kimi Code CLI](https://github.com/MoonshotAI/kimi-cli).

## Concept mapping

| Concept | Claude Code | Kimi Code CLI |
|---|---|---|
| Auto-loaded rules | `~/.claude/rules/*.md` + CLAUDE.md | `.kimi/AGENTS.md` (loaded via `${KIMI_AGENTS_MD}`) |
| Conditional rules | Skill (`SKILL.md`) | Skill (`.kimi/skills/<name>/SKILL.md`) |
| Agent definitions | `~/.claude/agents/*.md` | Built-in subagent types (`coder`, `explore`, `plan`) with detailed prompts |
| Slash commands | `~/.claude/commands/*.md` | Skills loaded via `/skill:<name>` (no custom slash commands) |
| Lifecycle hooks | `settings.json` hooks | `[[hooks]]` in `~/.kimi/config.toml` |
| Risk reminder | `UserPromptSubmit` hook | `PreToolUse` hook (configurable) |
| Session context save | `Stop` hook | `Stop` hook (configurable) |

## What's adapted

- **AGENTS.md**: Auto-generated from `content/rules/`, loaded automatically by Kimi Code CLI via `${KIMI_AGENTS_MD}`.
- **Skill**: `agentic-engineering` SKILL.md with Kimi-compatible guidance. Includes subagent mapping (coder/explore/plan to agentic-engineering roles) and command index.
- **References**: Symlinked from `content/references/` into the skill directory.
- **Rules**: Symlinked from `content/rules/` into the skill directory for easy access.
- **Commands**: Symlinked from `content/commands/` into the skill directory. Invoked via `/skill:agentic-engineering <command-name>` or by asking the agent to run a specific command.
- **Hooks**: Sample hook configuration provided in README (user must add to `~/.kimi/config.toml` manually).

## Install

```bash
bash .kimi/install.sh
```

This will:
1. Build the adapter (generates AGENTS.md and symlinks from `content/`)
2. Configure activation mode (opt-out or opt-in)
3. Symlink the skill to `~/.kimi/skills/agentic-engineering/` for global availability

## Uninstall

```bash
bash .kimi/uninstall.sh
```

## Project-level vs global

**Project-level** (no install required):
When this repo is your working directory, Kimi automatically discovers `.kimi/AGENTS.md` and `.kimi/skills/agentic-engineering/`.

**Global** (optional):
Running `install.sh` symlinks the skill to `~/.kimi/skills/` so the methodology is available in all projects.

## Hooks

Kimi Code CLI supports lifecycle hooks in `~/.kimi/config.toml`. Add these to enable risk reminders and session context saving:

```toml
[[hooks]]
event = "PreToolUse"
matcher = "Shell|WriteFile|StrReplaceFile"
command = "echo 'Risk check: classify task risk before executing destructive operations. See rules/agent-methodology.md for risk table.'"
timeout = 5

[[hooks]]
event = "Stop"
command = "bash /path/to/agentic-engineering/hooks/stop-context.sh"
timeout = 10
```

Note: The shared `hooks/stop-context.js` is designed for Claude Code. Kimi users can create a custom stop hook or use the script below as a starting point.

## Rebuild after content changes

```bash
bash .kimi/build.sh
```

This regenerates AGENTS.md and verifies symlinks. Run this after editing files in `content/`.

## Limitations

- **No custom slash commands**: Kimi Code CLI does not support user-defined slash commands. Commands are invoked via `/skill:agentic-engineering <command>` or natural language requests.
- **Agent definitions are reference material**: Kimi's `Agent` tool uses built-in subagent types (`coder`, `explore`, `plan`). The named agent roles from `content/agents/` are mapped to these types with detailed prompts rather than distinct subagent configurations.
- **Hook scripts are manual**: Kimi requires hooks to be configured in `config.toml`. The installer does not modify `~/.kimi/config.toml` automatically.
