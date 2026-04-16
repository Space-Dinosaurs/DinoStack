# Creating New Adapters

This guide is for adding support for a new AI coding tool. The methodology content is the same across all adapters - only the delivery format changes.

**Source of truth:** All methodology content lives in `content/` at the repo root. Adapters are generated outputs - never edit them directly. When building a new adapter, read from `content/` and transform to the tool's required format.

## Concept mapping

Each tool has its own mechanisms for the same core concepts:

| Concept | Claude Code | Cursor | Your tool |
|---|---|---|---|
| Auto-loaded rules | `~/.claude/rules/*.md` | `.cursor/rules/*.mdc` (`alwaysApply: true`) | ? |
| Conditional rules | Skills (`SKILL.md`) | `.cursor/rules/*.mdc` (`globs`) | ? |
| Agent definitions | `~/.claude/agents/*.md` | Custom modes / subagent configs | ? |
| Slash commands | `~/.claude/commands/*.md` | `.cursor/commands/*.md` | ? |
| Lifecycle hooks | `settings.json` hooks | `.cursor/hooks.json` | ? |
| Risk reminder | UserPromptSubmit hook | beforeSubmitPrompt hook | ? |
| Session context save | Stop hook | stop hook | ? |

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
- Continue.dev uses `.continue/` - adapter would live in `.continue/`
- Windsurf uses `.windsurf/` - adapter would live in `.windsurf/`

## Existing adapters as reference

- **Claude Code** (`.claude/`): Uses a skill with YAML frontmatter for on-demand loading. Agents live in `content/agents/`. `.claude/agents/` is a directory symlink into `content/agents/`, and `~/.claude/agents/<name>.md` are user-global symlinks into `.claude/agents/`. Commands are build artifacts in `.claude/commands/`, rebuilt from `content/commands/` by `.claude/build.sh` (prepending the `/agentic-engineering` prerequisite blockquote). Hooks are JSON entries in `settings.json`. Rules and references need no copy step - they are symlinked from `.claude/skills/agentic-engineering/` directly into `content/`.
- **Cursor** (`.cursor/`): Uses .mdc files with YAML frontmatter (`alwaysApply`, `globs`). Commands are markdown. Hooks use `hooks.json` with lifecycle event names. Build script at `.cursor/build.sh` combines `content/rules/` with frontmatter sidecars from `.cursor/rules/frontmatter/*.yaml` to produce `.mdc` files. References and commands are **copies** (via `cp` + `sed` transforms), not hardlinks — edits must go in `content/`. Agent instruction files land at `.cursor/agents/`, generated from `content/agents/`. Native hooks live at `.cursor/hooks/` (not the shared `hooks/` directory). The build applies path transforms via `sed` to normalize `references/<file>` and `rules/<file>` relative paths to Cursor-specific locations; the session context path is rewritten from `~/.claude/projects/[hash]/context.md` to `~/.cursor/projects/[hash]/context.md`, and memory paths are adjusted accordingly.
