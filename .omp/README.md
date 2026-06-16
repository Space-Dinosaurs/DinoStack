# DinoStack - Pi (oh-my-pi) Adapter

DinoStack adapter for [Pi](https://github.com/oh-my-pi/pi-coding-agent) (oh-my-pi).

## Quick start

Pi does **not** support custom slash commands like `/init-project`.
Instead, use natural language to invoke the methodology:

- **Explicit skill load:** Ask the agent to use the DinoStack skill
- **Natural language:** "run init-project" or "initialize DinoStack in this repo"

The skill auto-triggers when you mention software development tasks, but explicitly
referencing the methodology guarantees it is active.

## Concept mapping

| Concept | Claude Code | Pi (oh-my-pi) |
|---|---|---|
| Auto-loaded rules | `~/.claude/rules/*.md` + CLAUDE.md | `.omp/` skill auto-discovered; Pi also picks up `.claude/` and `.cursor/` configs via universal discovery |
| Conditional rules | Skill (`SKILL.md`) | Skill (`.omp/skills/<name>/SKILL.md`) |
| Agent definitions | `~/.claude/agents/*.md` | Built-in subagent types (`explore`, `plan`, `designer`, `reviewer`, `task`, `quick_task`) |
| Slash commands | `~/.claude/commands/*.md` | Native TypeScript commands in `~/.omp/agent/commands/` (no custom markdown commands) |
| Lifecycle hooks | `settings.json` hooks | Not available (risk reminder embedded in skill) |
| Risk reminder | `UserPromptSubmit` hook | Embedded in skill content, read on every load |
| Session context save | `Stop` hook | Not available |

## What's adapted

- **Skill**: `agentic-engineering` SKILL.md with Pi-compatible guidance. Includes subagent mapping (task/explore/plan/designer/reviewer to DinoStack roles) and methodology overview.
- **References**: Symlinked from `content/references/` into the skill directory.
- **Rules**: Symlinked from `content/rules/` into the skill directory for easy access.
- **Commands**: Not adapted as markdown files. Pi commands are native TypeScript. Use natural language to invoke methodology commands ("run init-project", "do a wrap", "run skeptic review").
- **Agents**: Not adapted as markdown files. Pi uses built-in subagent types with detailed prompts from `content/agents/`.

## Install

```bash
git clone https://github.com/Space-Dinosaurs/DinoStack.git ~/agentic-engineering
bash ~/agentic-engineering/.omp/install.sh
```

This will:
1. Build the adapter (ensures symlinks from `content/`)
2. Configure activation mode (opt-out or opt-in)
3. Copy the skill to `~/.omp/agent/skills/agentic-engineering/` for global availability

## Uninstall

```bash
bash .omp/uninstall.sh
```

## Project-level vs global

**Project-level** (no install required):
When this repo is your working directory, Pi automatically discovers `.omp/skills/agentic-engineering/`.

**Global** (optional):
Running `install.sh` copies the skill to `~/.omp/agent/skills/` so the methodology is available in all projects.

## Rebuild after content changes

```bash
bash .omp/build.sh
```

This verifies symlinks from `content/`. Run this after editing files in `content/`.

## Limitations

- **No custom markdown commands**: Pi commands are implemented in TypeScript, not markdown. The skill provides natural language access to methodology commands instead.
- **Agent definitions are reference material**: Pi's built-in subagent types (`explore`, `plan`, `designer`, `reviewer`, `task`, `quick_task`) are used directly. The named agent roles from `content/agents/` are mapped to these types with detailed prompts.
- **No lifecycle hooks**: Pi does not have a hook system. The risk classification reminder and session context save are embedded in the skill content instead.
- **Global install copies SKILL.md**: The installer copies `SKILL.md` to `~/.omp/agent/skills/` and uses absolute symlinks for `content/`. This makes the global skill survive git branch switches, but means you must re-run `install.sh` after updating `SKILL.md` itself.
- **Universal config discovery**: Pi may already pick up `.claude/` configs via universal discovery. The `.omp/` adapter ensures native `.omp/` skill loading for Pi-specific behavior.
