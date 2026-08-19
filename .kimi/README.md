# DinoStack - Kimi Code CLI Adapter

Adapter for [Kimi Code CLI](https://github.com/MoonshotAI/kimi-cli).

## Quick start

Kimi Code CLI does **not** support custom slash commands like `/ds-init-project`.
Instead, use one of these methods:

- **Direct command load (preferred):** `/skill:ds-wrap`, `/skill:ds-skeptic`, `/skill:ds-implement-ticket`, etc.
  Each DinoStack command is available as its own skill.
- **Full skill load:** `/skill:dinostack ds-init-project` (loads the complete methodology)
- **Natural language:** "run ds-init-project" or "initialize DinoStack in this repo"

The skill auto-triggers when you mention software development tasks, but explicitly
loading it guarantees the methodology is active.

## Concept mapping

| Concept | Claude Code | Kimi Code CLI |
|---|---|---|
| Auto-loaded rules | `~/.claude/rules/*.md` + CLAUDE.md | `.kimi/AGENTS.md` (loaded via `${KIMI_AGENTS_MD}`) - a lean activation stub (DS-185), not the methodology body |
| Conditional rules | Skill (`SKILL.md`) | Skill (`.kimi/skills/<name>/SKILL.md`) |
| Agent definitions | `~/.claude/agents/*.md` | Built-in subagent types (`coder`, `explore`, `plan`) with detailed prompts |
| Slash commands | `~/.claude/commands/*.md` | Skills loaded via `/skill:<name>` (no custom slash commands) |
| Lifecycle hooks | `settings.json` hooks | `[[hooks]]` in `~/.kimi/config.toml` |
| Risk reminder | `UserPromptSubmit` hook | `PreToolUse` hook (configurable) |
| Session context save | `Stop` hook | `Stop` hook (configurable) |

## What's adapted

- **AGENTS.md**: A lean, always-resident activation stub (DS-185) loaded automatically by Kimi
  Code CLI via `${KIMI_AGENTS_MD}` on every session - not the full methodology body. It points at
  the `dinostack` skill and the activation config.
- **Skill**: `dinostack` SKILL.md embeds the full methodology body (assembled from
  `content/sections/` plus the two rules files, DS-185 - mirroring the DS-143 change that moved
  the equivalent always-loaded body out of Claude Code's `~/.claude/CLAUDE.md`) and loads on
  trigger, not at session start. Includes subagent mapping (coder/explore/plan to DinoStack
  roles) and command index.
- **References**: Symlinked from `content/references/` into the skill directory.
- **Sections**: Symlinked from `content/sections/` into the skill directory for easy access.
- **Commands**: Symlinked from `content/commands/` into the skill directory. Invoked via `/skill:dinostack <command-name>` or by asking the agent to run a specific command.
- **Hooks**: Sample hook configuration provided in README (user must add to `~/.kimi/config.toml` manually).

## Install

```bash
git clone https://github.com/Space-Dinosaurs/DinoStack.git ~/DinoStack
bash ~/DinoStack/.kimi/install.sh
```

This will:
1. Build the adapter (generates the AGENTS.md stub, the skill's `SKILL.md`, and symlinks from
   `content/`)
2. Configure activation mode (opt-out or opt-in)
3. Symlink the skill to `~/.kimi/skills/dinostack/` for global availability

## Uninstall

```bash
bash .kimi/uninstall.sh
```

## Project-level vs global

**Project-level** (no install required):
When this repo is your working directory, Kimi automatically discovers `.kimi/AGENTS.md` (the
activation stub, always loaded) and `.kimi/skills/dinostack/` (the full methodology body,
trigger-loaded).

**Global** (optional):
Running `install.sh` symlinks the skill to `~/.kimi/skills/` so the methodology is available in all projects.

## Hooks

Kimi Code CLI supports lifecycle hooks in `~/.kimi/config.toml`. Add these to enable risk reminders and session context saving:

```toml
[[hooks]]
event = "PreToolUse"
matcher = "Shell|WriteFile|StrReplaceFile"
command = "echo 'Risk check: classify task risk before executing destructive operations. See METHODOLOGY.md §Risk Classification for the risk table.'"
timeout = 5

[[hooks]]
event = "Stop"
command = "bash /path/to/DinoStack/hooks/stop-context.sh"
timeout = 10
```

Note: The shared `hooks/stop-context.js` is designed for Claude Code. Kimi users can create a custom stop hook or use the script below as a starting point.

## Rebuild after content changes

```bash
bash .kimi/build.sh
```

This regenerates the AGENTS.md stub, the skill's `SKILL.md` (embedded methodology body), and
verifies symlinks. Run this after editing files in `content/`.

## Limitations

- **No custom slash commands**: Kimi Code CLI does not support user-defined slash commands. Commands are available as individual skills (`/skill:<command-name>`) or via the main skill (`/skill:dinostack <command>`), or through natural language requests.
- **Agent definitions are reference material**: Kimi's `Agent` tool uses built-in subagent types (`coder`, `explore`, `plan`). The named agent roles from `content/agents/` are mapped to these types with detailed prompts rather than distinct subagent configurations.
- **Hook scripts are manual**: Kimi requires hooks to be configured in `config.toml`. The installer does not modify `~/.kimi/config.toml` automatically.
- **Global install copies SKILL.md**: The installer copies `SKILL.md` to `~/.kimi/skills/` and uses absolute symlinks for `content/`. This makes the global skill survive git branch switches, but means you must re-run `install.sh` after updating `SKILL.md` itself.
- **No `conductor_overreach` advisory**: Kimi Code CLI has no Stop hook mechanism, so the warn-only conductor-overreach detector (`hooks/conductor-overreach-nudge.js`) has no equivalent here.
