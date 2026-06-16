# DinoStack - OpenCode Adapter

DinoStack adapter for [OpenCode](https://opencode.ai).

## Concept mapping

| Concept | Claude Code | OpenCode |
|---|---|---|
| Auto-loaded rules | `~/.claude/rules/*.md` + CLAUDE.md | `AGENTS.md` + `instructions` in opencode.json |
| Conditional rules | Skill (`SKILL.md`) | Skill (`.opencode/skills/<name>/SKILL.md`) |
| Agent definitions | `~/.claude/agents/*.md` | `~/.config/opencode/agents/*.md` |
| Slash commands | `~/.claude/commands/*.md` | `~/.config/opencode/commands/*.md` |
| Lifecycle hooks | `settings.json` hooks | Not available (risk reminder embedded in skill) |
| Risk reminder | UserPromptSubmit hook | Embedded in skill content, read on every load |
| Session context save | Stop hook (`stop-context.js`) | Not available |

## What's adapted

- **Skill**: `agentic-engineering` SKILL.md with opencode-compatible frontmatter. Risk classification reminder embedded directly in the skill body (since opencode lacks a UserPromptSubmit hook equivalent).
- **Agents**: 13 agent definitions converted to opencode markdown agent format with proper `description`, `mode: subagent`, and `permission` frontmatter. Engineers get `edit: allow, bash: allow`; read-only agents (skeptic, architect, etc.) get `edit: deny` with restricted bash.
- **Commands**: 9 commands converted to opencode command format with `description` and `agent: build` frontmatter. Prerequisite blockquotes stripped (opencode loads the skill via its own mechanism).
- **Rules**: Loaded via `instructions` in opencode.json rather than symlinked into a skill directory (opencode's native mechanism for auto-loading rules).
- **References**: Symlinked from `content/references/` into the skill directory, same as the Claude adapter.

## Install

```bash
git clone https://github.com/Space-Dinosaurs/DinoStack.git ~/agentic-engineering
bash ~/agentic-engineering/.opencode/install.sh
```

This installs:
- `agentic-engineering` skill into `~/.config/opencode/skills/`
- 13 named agent definitions into `~/.config/opencode/agents/`
- 9 workflow commands into `~/.config/opencode/commands/`
- Rule instructions wired into `~/.config/opencode/opencode.json`

It also configures the activation mode (opt-out or opt-in) and installs the pre-commit hook.

## Post-install verification

```bash
ls ~/.config/opencode/skills/agentic-engineering/SKILL.md
```

Should show the skill file. Then open OpenCode and ask: "What risk tiers does DinoStack define?" - it should reference Trivial/Low/Elevated/Elevated+Cleanup.

## Uninstall

```bash
bash .opencode/uninstall.sh
```

## Limitations

- **No lifecycle hooks**: OpenCode doesn't have a hook system. The risk classification reminder and session context save that Claude Code implements via `UserPromptSubmit` and `Stop` hooks are instead embedded in the skill content and AGENTS.md respectively. The session context save (`stop-context.js`) has no opencode equivalent.
- **No `~/.claude/agentic-engineering.json` activation config**: The activation mode config is stored at `~/.config/opencode/agentic-engineering.json` instead.
- **Agent tool restrictions differ**: Claude Code restricts tools via `tools:` frontmatter. OpenCode uses the `permission:` system. The adapter maps Write/Edit agents to `edit: allow` and read-only agents to `edit: deny` with restricted bash patterns.

## Rebuild after content changes

```bash
bash .opencode/build.sh
```

This regenerates agents and commands from `content/`. The skill SKILL.md and symlinks are not regenerated (they're either static or point directly to content/).