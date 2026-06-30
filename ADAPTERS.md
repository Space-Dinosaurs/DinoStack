# Creating New Adapters

This guide is for adding support for a new AI coding tool. The methodology content is the same across all adapters - only the delivery format changes.

**Source of truth:** All methodology content lives in `content/` at the repo root. Adapters are generated outputs - never edit them directly. When building a new adapter, read from `content/` and transform to the tool's required format.

**Methodology assembly:** The core methodology body is assembled from numbered section files in `content/sections/` by `scripts/build-methodology.sh`. Each adapter's `build.sh` calls this script and redirects its output to the adapter's always-loaded rules file (e.g., `.claude/skills/agentic-engineering/METHODOLOGY.md`, `.codex/AGENTS.md`, `.gemini/GEMINI.md`). Do not assemble methodology content by hand.

**Skill body dedup:** `content/SKILL.md` is the canonical body text for the on-demand agentic-engineering skill. The `.claude` adapter assembles its `SKILL.md` from a frontmatter sidecar plus `content/SKILL.md`. Other adapters that maintain a separate skill file should derive from `content/SKILL.md` when their body content converges.

## Concept mapping

Each tool has its own mechanisms for the same core concepts:

| Concept | Claude Code | Cursor | Codex CLI | Gemini CLI | Kimi Code CLI | OpenCode | Pi coding agent | Pi (oh-my-pi) | Hermes Agent | OpenClaw | VS Code Copilot |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Auto-loaded rules | `~/.claude/rules/*.md` | `.cursor/rules/*.mdc` (`alwaysApply: true`) | `~/.codex/AGENTS.md` | `~/.gemini/GEMINI.md` | `.kimi/AGENTS.md` (`${KIMI_AGENTS_MD}`) | `AGENTS.md` + `instructions` in opencode.json | `AGENTS.md` context files + `.pi/skills/<name>/SKILL.md` discovery | `.omp/skills/<name>/SKILL.md` (Pi also auto-discovers `.claude/`, `.cursor/`, etc.) | Skills with matching `description` frontmatter (loaded on demand from `~/.hermes/skills/<category>/<name>/`) | `~/.openclaw/AGENTS.md` (global) | `.github/copilot-instructions.md` |
| Conditional rules | Skills (`SKILL.md`) | `.cursor/rules/*.mdc` (`globs`) | Skills (`~/.agents/skills/<name>/SKILL.md`) | Not available (all rules go in GEMINI.md) | Skills (`.kimi/skills/<name>/SKILL.md`) | Skills (`.opencode/skills/<name>/SKILL.md`) | Skills (`.pi/skills/<name>/SKILL.md` or `~/.pi/agent/skills/<name>/SKILL.md`) | Skills (`.omp/skills/<name>/SKILL.md`) | Skills (`~/.hermes/skills/<category>/<name>/SKILL.md`) | Skills (`~/.openclaw/skills/<name>/SKILL.md`) | `.github/instructions/*.instructions.md` (`applyTo`) |
| Agent definitions | `~/.claude/agents/*.md` | Custom modes / subagent configs | `~/.codex/agents/*.toml` (TOML w/ frontmatter) | `~/.gemini/agents/*.md` (markdown w/ frontmatter; `kind: local`) | Built-in subagent types (`coder`, `explore`, `plan`) | `~/.config/opencode/agents/*.md` (markdown w/ frontmatter) | Agent role docs available inside skill via `agents/`; optional Pi subagent extensions may consume `.pi/agents/*.md` | Built-in subagent types (`explore`, `plan`, `designer`, `reviewer`, `task`, `quick_task`) | `delegate_task` with role-specific context from `agents/*.md` | Skills with `disable-model-invocation: true` (read-on-demand reference specs; no Task-spawn) | `.github/agents/*.md` |
| Slash commands | `~/.claude/commands/*.md` | `.cursor/commands/*.md` | `~/.codex/commands/*.md` (hardlinks, no transform) | `~/.gemini/commands/*.toml` (TOML generated from content/commands/*.md) | `/skill:<name>` (no custom slash commands) | `~/.config/opencode/commands/*.md` (markdown w/ frontmatter) | `.pi/prompts/*.md` prompt templates generated from `content/commands/*.md` | Native TypeScript commands (no custom markdown commands) | Commands in skill `commands/` directory (read on demand, no slash command registration) | Skills with `user-invocable: true` (each command in its own skill dir at `~/.openclaw/skills/<name>/`) | `.github/prompts/*.prompt.md` |
| Lifecycle hooks | `settings.json` hooks | `.cursor/hooks.json` | `~/.codex/hooks.json` | `~/.gemini/settings.json` | `[[hooks]]` in `~/.kimi/config.toml` | Not available | Extension events available but not required for this adapter | Not available | Not available | Not available (lifecycle/command events only; no PreToolUse-deny equivalent) | `.github/hooks/*.{sh,js}` (PreToolUse `risk-reminder-copilot.sh`, SessionStart `session-start-copilot.sh`, Stop `stop-context-copilot.js`) |
| Risk reminder | UserPromptSubmit hook | beforeSubmitPrompt hook | UserPromptSubmit hook | BeforeAgent hook | `PreToolUse` hook | Embedded in skill content | Embedded in skill content; future extension can inject `before_agent_start` reminders | Embedded in skill content | Embedded in skill content | Embedded in skill content | PreToolUse hook |
| Session context save | Stop hook | stop hook | Stop hook | SessionEnd hook | `Stop` hook | Not available | Future extension can use `session_shutdown`; not implemented in this adapter | Not available | Not available | Not available | Stop hook |
| Version-update notice | SessionStart hook (`systemMessage`) | Not available | Not available | Not available | SessionStart hook (stderr) | Not available | Not available | Not available | Not available | Not available | Not available |

## Checklist for a new adapter

1. **Create the directory:** `.<toolname>/` matching the tool's config directory convention
2. **Convert rules:** Translate the 3 rules files into the tool's native rule format
   - Source: `content/rules/`
   - Decide which rules should always load vs. load conditionally
3. **Copy reference docs:** The 21 reference docs are plain markdown - copy or symlink them
   - Source: `content/references/`
4. **Convert commands:** Translate the 20 commands into the tool's command format
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
- Pi coding agent uses `.pi/` - adapter lives in `.pi/`
- Pi (oh-my-pi) uses `.omp/` - adapter lives in `.omp/`
- Continue.dev uses `.continue/` - adapter would live in `.continue/`
- Windsurf uses `.windsurf/` - adapter would live in `.windsurf/`
- Hermes Agent uses `.hermes/` - adapter lives in `.hermes/`
- OpenClaw uses `.openclaw/` - adapter lives in `.openclaw/`
- VS Code Copilot uses `.github/` for workspace artifacts - adapter source lives in `.copilot/`, generated output in `.github/copilot-instructions.md`, `.github/{agents,prompts,instructions,hooks}/`

## Existing adapters as reference

- **Claude Code** (`.claude/`): Uses a skill with YAML frontmatter for on-demand loading. Skill body text is assembled from `content/SKILL.md` (via `.claude/build.sh`) with a frontmatter sidecar. Agents live in `content/agents/`. `.claude/agents/` is a directory symlink into `content/agents/`, and `~/.claude/agents/<name>.md` are user-global symlinks into `.claude/agents/`. Commands are build artifacts in `.claude/commands/`, rebuilt from `content/commands/` by `.claude/build.sh` (prepending the `/agentic-engineering` prerequisite blockquote). Methodology body is assembled from `content/sections/` via `scripts/build-methodology.sh` into `METHODOLOGY.md`. Hooks are JSON entries in `settings.json`. Rules and references need no copy step - they are symlinked from `.claude/skills/agentic-engineering/` directly into `content/`.
- **Cursor** (`.cursor/`): Uses .mdc files with YAML frontmatter (`alwaysApply`, `globs`). Commands are markdown. Hooks use `hooks.json` with lifecycle event names. Build script at `.cursor/build.sh` combines `content/rules/` with frontmatter sidecars from `.cursor/rules/frontmatter/*.yaml` to produce `.mdc` files. Methodology is assembled via `scripts/build-methodology.sh`.
- **Codex CLI** (`.codex/`): Uses AGENTS.md (always-loaded global rules assembled from `content/sections/` via `scripts/build-methodology.sh`) and a SKILL.md for on-demand loading. Agents are TOML files generated from `content/agents/*.md`. Commands are hardlinks from `content/commands/` (no transform). Hooks use `~/.codex/hooks.json`. Install symlinks to `~/.codex/` and `~/.agents/skills/`.
- **Gemini CLI** (`.gemini/`): Uses GEMINI.md (always-loaded, assembled from `content/sections/` via `scripts/build-methodology.sh` plus code-standards and conventions). Agents are markdown files with YAML frontmatter (`kind: local`; `model` field stripped so agents inherit the session model). Commands are TOML files generated from `content/commands/*.md`. Hooks use `BeforeAgent` (risk reminder) and `SessionEnd` (context save) in `~/.gemini/settings.json`. Install symlinks GEMINI.md, agents/, commands/, and references/ to `~/.gemini/`.
- **Kimi Code CLI** (`.kimi/`): Uses SKILL.md with YAML frontmatter for on-demand loading via `/skill:agentic-engineering`. AGENTS.md is assembled from `content/sections/` via `scripts/build-methodology.sh` and loaded automatically via `${KIMI_AGENTS_MD}`. Agents map to Kimi's three built-in subagent types (`coder`, `explore`, `plan`) with detailed role prompts. Commands are invoked via `/skill:agentic-engineering <command>` or natural language. Hooks use `[[hooks]]` in `~/.kimi/config.toml`. Install symlinks skill to `~/.kimi/skills/`.
- **OpenCode** (`.opencode/`): Uses SKILL.md with YAML frontmatter for on-demand loading, matching opencode's native skill discovery. Methodology body assembled from `content/sections/` via `scripts/build-methodology.sh` into `METHODOLOGY.md`. Agents are markdown files with `description`, `mode`, and `permission` frontmatter (converted from Claude's `name`/`tools` format). Commands use `description`/`agent` frontmatter. Rules are loaded via `instructions` in opencode.json rather than symlinked. No hook system available; risk reminder is embedded in skill content. Install symlinks to `~/.config/opencode/`.
- **Pi coding agent** (`.pi/`): Uses Agent Skills standard discovery from `.pi/skills/` and `~/.pi/agent/skills/`. `SKILL.md` is assembled from `.pi/skills/agentic-engineering/SKILL.frontmatter.yaml` plus `content/SKILL.md`; `METHODOLOGY.md` is assembled from `content/sections/` via `scripts/build-methodology.sh`. Prompt templates in `.pi/prompts/` are generated from `content/commands/*.md` and provide slash-command equivalents such as `/brief` and `/wrap`. Rules, references, commands, and agents are symlinked from `content/` into the skill directory. Extension hooks are available in Pi but not required for this first native adapter. Generated project-local Pi files (`.pi/gsd/`, `.pi/taskplane.json`, `.pi/agents/supervisor.md`) are gitignored so adapter-owned files can be committed safely.
- **Pi (oh-my-pi)** (`.omp/`): Uses SKILL.md with YAML frontmatter for on-demand loading. Pi has built-in subagent types (`explore`, `plan`, `designer`, `reviewer`, `task`, `quick_task`) so no custom markdown agent definitions are created. Pi commands are native TypeScript, so no markdown command files are generated. Rules, references, commands, and agents are symlinked from `content/` into the skill directory. No hook system available; risk reminder is embedded in skill content. Install copies SKILL.md and symlinks content dirs to `~/.omp/agent/skills/`.
- **Hermes Agent** (`.hermes/`): Uses SKILL.md with YAML frontmatter for on-demand loading via Hermes's skill discovery (`~/.hermes/skills/<category>/<name>/`). The skill's `description` frontmatter triggers automatically on software development tasks. Methodology body is assembled from `content/sections/` via `scripts/build-methodology.sh` into `METHODOLOGY.md`. Agent role definitions in `agents/` are used as context when spawning `delegate_task` subagents. Commands are stored as markdown files in the skill's `commands/` directory and read on demand. No hook system available; risk reminder is embedded in skill content. Install symlinks the skill to `~/.hermes/skills/autonomous-ai-agents/agentic-engineering/`.
- **OpenClaw** (`.openclaw/`): Uses the MULTI-FILE skill pattern: one skill dir per entity (1 entry + 20 commands + 17 agents = 38 dirs). OpenClaw keys skill identity by the `name:` frontmatter field; dir name equals frontmatter `name` on every skill. Command skills use `user-invocable: true`. Agent skills use `user-invocable: false` and `disable-model-invocation: true` (read-on-demand reference specs; OpenClaw has no Task-spawn). Agent skill dirs and frontmatter names are prefixed `agent-` (e.g. `agent-skeptic`) to avoid collisions with same-named command skills. Methodology body is assembled from `content/sections/` via `scripts/build-methodology.sh` into `METHODOLOGY.md` inside the entry skill dir. Rules, references, and templates are relative symlinks into `content/`. No hook system available (lifecycle/command events only; no PreToolUse-deny equivalent); risk reminder is embedded in skill content. Activation config at `~/.openclaw/agentic-engineering.json` (`mode`, `profile`, `set_at`). Install creates per-skill-dir symlinks under `~/.openclaw/skills/<name>/`.
- **VS Code Copilot** (`.copilot/`): Source lives in `.copilot/`; generated output lands in `.github/`. Methodology body is assembled from `content/sections/` via `scripts/build-methodology.sh` and written to `.github/copilot-instructions.md`. Agent definitions are generated as `.github/agents/*.md` (e.g. `architect.md`). Slash-command equivalents are generated as `.github/prompts/*.prompt.md`. Conditional rules are generated as `.github/instructions/*.instructions.md` with `applyTo` glob frontmatter. Lifecycle hooks are shell and JS scripts in `.github/hooks/` (`risk-reminder-copilot.sh` for PreToolUse, `session-start-copilot.sh` for SessionStart, `stop-context-copilot.js` for Stop). References are hardlinked into `.copilot/references/`.
