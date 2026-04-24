# Creating New Adapters

This guide is for adding support for a new AI coding tool. The methodology content is the same across all adapters - only the delivery format changes.

**Source of truth:** All methodology content lives in `content/` at the repo root. Adapters are generated outputs - never edit them directly. When building a new adapter, read from `content/` and transform to the tool's required format.

## Concept mapping

Each tool has its own mechanisms for the same core concepts:

| Concept | Claude Code | Cursor | OpenCode | Kimi Code CLI | Pi (oh-my-pi) |
|---|---|---|---|---|---|
| Auto-loaded rules | `~/.claude/rules/*.md` | `.cursor/rules/*.mdc` (`alwaysApply: true`) | `AGENTS.md` + `instructions` in opencode.json | `.kimi/AGENTS.md` (`${KIMI_AGENTS_MD}`) | `.omp/skills/<name>/SKILL.md` (Pi also auto-discovers `.claude/`, `.cursor/`, etc.) |
| Conditional rules | Skills (`SKILL.md`) | `.cursor/rules/*.mdc` (`globs`) | Skills (`.opencode/skills/<name>/SKILL.md`) | Skills (`.kimi/skills/<name>/SKILL.md`) | Skills (`.omp/skills/<name>/SKILL.md`) |
| Agent definitions | `~/.claude/agents/*.md` | Custom modes / subagent configs | `~/.config/opencode/agents/*.md` (markdown w/ frontmatter) | Built-in subagent types (`coder`, `explore`, `plan`) | Built-in subagent types (`explore`, `plan`, `designer`, `reviewer`, `task`, `quick_task`) |
| Slash commands | `~/.claude/commands/*.md` | `.cursor/commands/*.md` | `~/.config/opencode/commands/*.md` (markdown w/ frontmatter) | `/skill:<name>` (no custom slash commands) | Native TypeScript commands (no custom markdown commands) |
| Lifecycle hooks | `settings.json` hooks | `.cursor/hooks.json` | Not available | `[[hooks]]` in `~/.kimi/config.toml` | Not available |
| Risk reminder | UserPromptSubmit hook | beforeSubmitPrompt hook | Embedded in skill content | `PreToolUse` hook | Embedded in skill content |
| Session context save | Stop hook | stop hook | Not available | `Stop` hook | Not available |

## Checklist for a new adapter

1. **Create the directory:** `.<toolname>/` matching the tool's config directory convention
2. **Convert rules:** Translate the 3 rules files into the tool's native rule format
   - Source: `content/rules/`
   - Decide which rules should always load vs. load conditionally
3. **Copy reference docs:** The 4 reference docs are plain markdown - copy or symlink them
   - Source: `content/references/`
4. **Convert commands:** Translate the 7 commands into the tool's command format
   - Source: `content/commands/`
   - Remove the `/agentic-engineering` prerequisite line (it's Claude Code-specific)
5. **Map hooks:** Wire up the tool's lifecycle events
   - Risk reminder: fire before each prompt/submission
   - Context save: fire on session stop/completion
   - Hook scripts live in `hooks/` at the repo root (shared across adapters)
6. **Write `.<toolname>/README.md`:** Setup instructions for that tool
7. **Update root `README.md`:** Add the adapter to the table

## What NOT to change

The methodology content itself. Adapters translate format, not substance. If you find a rule that doesn't apply to your tool (e.g., worktree lifecycle for a tool without git integration), keep the rule but note the limitation in the adapter's README.

## Naming convention

Each adapter directory matches the tool's native config directory name:
- Claude Code uses `.claude/` - adapter lives in `.claude/`
- Cursor uses `.cursor/` - adapter lives in `.cursor/`
- OpenCode uses `.opencode/` - adapter lives in `.opencode/`
- Kimi Code CLI uses `.kimi/` - adapter lives in `.kimi/`
- Pi (oh-my-pi) uses `.omp/` - adapter lives in `.omp/`
- Continue.dev uses `.continue/` - adapter would live in `.continue/`
- Windsurf uses `.windsurf/` - adapter would live in `.windsurf/`

## Existing adapters as reference

- **Claude Code** (`.claude/`): Uses a skill with YAML frontmatter for on-demand loading. Agents live in `content/agents/`. `.claude/agents/` is a directory symlink into `content/agents/`, and `~/.claude/agents/<name>.md` are user-global symlinks into `.claude/agents/`. Commands are build artifacts in `.claude/commands/`, rebuilt from `content/commands/` by `.claude/build.sh` (prepending the `/agentic-engineering` prerequisite blockquote). Hooks are JSON entries in `settings.json`. Rules and references need no copy step - they are symlinked from `.claude/skills/agentic-engineering/` directly into `content/`.
- **Cursor** (`.cursor/`): Uses .mdc files with YAML frontmatter (`alwaysApply`, `globs`). Commands are markdown. Hooks use `hooks.json` with lifecycle event names. Build script at `.cursor/build.sh` combines `content/rules/` with frontmatter sidecars from `.cursor/rules/frontmatter/*.yaml` to produce `.mdc` files.
- **OpenCode** (`.opencode/`): Uses SKILL.md with YAML frontmatter for on-demand loading, matching opencode's native skill discovery. Agents are markdown files with `description`, `mode`, and `permission` frontmatter (converted from Claude's `name`/`tools` format). Commands use `description`/`agent` frontmatter. Rules are loaded via `instructions` in opencode.json rather than symlinked. No hook system available; risk reminder is embedded in skill content. Install symlinks to `~/.config/opencode/`.
- **Kimi Code CLI** (`.kimi/`): Uses SKILL.md with YAML frontmatter for on-demand loading via `/skill:agentic-engineering`. AGENTS.md is auto-generated from `content/rules/` and loaded automatically via `${KIMI_AGENTS_MD}`. Agents map to Kimi's three built-in subagent types (`coder`, `explore`, `plan`) with detailed role prompts. Commands are invoked via `/skill:agentic-engineering <command>` or natural language. Hooks use `[[hooks]]` in `~/.kimi/config.toml`. Install symlinks skill to `~/.kimi/skills/`.
- **Pi (oh-my-pi)** (`.omp/`): Uses SKILL.md with YAML frontmatter for on-demand loading. Pi has built-in subagent types (`explore`, `plan`, `designer`, `reviewer`, `task`, `quick_task`) so no custom markdown agent definitions are created. Pi commands are native TypeScript, so no markdown command files are generated. Rules, references, commands, and agents are symlinked from `content/` into the skill directory. No hook system available; risk reminder is embedded in skill content. Install copies SKILL.md and symlinks content dirs to `~/.omp/agent/skills/`.
