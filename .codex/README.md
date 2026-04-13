# Agentic Engineering - Codex Adapter

## What this provides

- **AGENTS.md** - Always-loaded rules: agent methodology, code standards, conventions (combined from 3 source files)
- **Reference docs** (4) - skeptic protocol, subagent protocol, agent team, design goals
- **Command templates** (6) - skeptic, implement, wrap, memory-update, init-project, update-protocol
- **Global skill** - `~/.agents/skills/agentic-engineering/` with SKILL.md and bundled references
- **Global AGENTS.md** - `~/.codex/AGENTS.md` symlinked to `.codex/AGENTS.md` for global session loading

## Installation

Clone the repo to `~/agentic-engineering/` (this path is expected by references):

```bash
git clone git@github.com:Solara6/agentic-engineering.git ~/agentic-engineering
```

Run the installer:

```bash
~/agentic-engineering/.codex/install.sh
```

This:
1. Runs `.codex/build.sh` to ensure all artifacts are current
2. Symlinks `.codex/skill/` to `~/.agents/skills/agentic-engineering/` (the correct Codex user-scope skill path per Codex docs)
3. Symlinks `.codex/AGENTS.md` to `~/.codex/AGENTS.md` (global instructions, loaded by Codex in every session)

If `~/.codex/AGENTS.md` already exists and is not a symlink, the installer backs it up to `~/.codex/AGENTS.md.backup-<timestamp>` before replacing it with the symlink, printing a loud warning. The uninstaller restores the most recent backup if one exists.

To remove:

```bash
~/agentic-engineering/.codex/uninstall.sh
```

## How it works

### Always-loaded rules (AGENTS.md)

Codex automatically reads `AGENTS.md` from the project root. The `.codex/AGENTS.md` in this repo contains the full agentic engineering methodology (all 3 rules files concatenated).

For projects outside this repo that want the methodology, either:
1. Add an `AGENTS.md` to your project root referencing or copying the rules, or
2. Copy `.codex/AGENTS.md` to your project root as `AGENTS.md`

### Global skill

The `~/.agents/skills/agentic-engineering/` skill (per Codex's user-scope skill path spec) triggers automatically for software development tasks. It provides:
- A methodology summary in `SKILL.md`
- Reference docs (skeptic protocol, subagent protocol, agent team, design goals) in `references/`

### Commands

Command templates live in `.codex/commands/`. These are plain markdown files - not native slash commands. To use them:

1. Open `.codex/commands/<command>.md`
2. Read it and paste the relevant prompt into your Codex session

Commands live in `.codex/commands/` as hardlinks from `content/commands/`. The `/agentic-engineering` prerequisite line that Claude Code prepends is not present here because it is never in the source - it is a Claude Code-specific addition made only by `.claude/build.sh`, not part of the `content/` files.

### Reference docs

Reference docs are available in two places:
- `~/.agents/skills/agentic-engineering/references/` (via global skill install)
- `.codex/references/` (local copies in this repo)

`.codex/references/` contains hardlinks to `content/references/`. `.codex/skill/references/` is a symlink to `.codex/references/` - a single source of truth so `build.sh` only manages one set of hardlinks.

## Build

The build script generates `AGENTS.md` and hardlinks reference/command files:

```bash
bash ~/agentic-engineering/.codex/build.sh
```

Run after `git pull` to regenerate artifacts from updated source files. The pre-commit hook in this repo runs `.claude/build.sh`, `.cursor/build.sh`, and `.codex/build.sh` automatically whenever `content/` files are staged.

## Coexistence with Claude Code

This adapter is designed to run alongside the Claude Code adapter without collision:

- **Config paths are disjoint:** Codex uses `~/.codex/`, Claude Code uses `~/.claude/`
- **Install writes to `~/.agents/skills/` and `~/.codex/AGENTS.md`** - no other paths modified outside the repo
- **Hook scripts:** The shared `hooks/stop-context.js` writes to `~/.claude/projects/` - a Claude Code-specific path. Codex has no lifecycle hook system, so this script is not invoked by the Codex adapter at all. Context saving in Codex sessions must be done manually via the `/wrap` command template.
- **AGENTS.md vs CLAUDE.md:** Codex reads `AGENTS.md` natively. Claude Code reads `CLAUDE.md` and supports importing `AGENTS.md` via a one-line `CLAUDE.md` containing `@AGENTS.md`. This repo treats `AGENTS.md` as the canonical source; Claude Code users should keep a thin `CLAUDE.md` that imports it. No collision risk.

## Updating

Pull and re-run the installer - it is idempotent:

```bash
cd ~/agentic-engineering
git pull
bash .codex/install.sh
```

For a clean refresh:

```bash
bash .codex/uninstall.sh
git pull
bash .codex/install.sh
```

## Known limitations vs Claude Code adapter

| Feature | Claude Code | Codex |
|---|---|---|
| Risk reminder | Fires automatically via `UserPromptSubmit` hook before every prompt | Not supported - no hook system. Must apply risk classification manually by following the protocol. |
| Session context save | Fires automatically via `Stop` hook on session end | Not supported - no hook system. Save context manually using the `/wrap` command template. |
| Slash commands | First-class slash commands (`/skeptic`, `/wrap`, etc.) | Not supported - paste command templates manually from `.codex/commands/`. |
| Named agents | `~/.claude/agents/*.md` loaded automatically | Not supported natively. Use agent preambles from `SKILL.md` when spawning subagents. |
| Background subagents | `run_in_background: true` in Agent tool | Depends on Codex version - verify in your Codex release. |
| Global AGENTS.md | `~/.claude/CLAUDE.md` loaded globally | `~/.codex/AGENTS.md` is confirmed - installed as a symlink to `.codex/AGENTS.md`. Backup behavior applies if a file already exists (see Installation). |
| Community skills | Managed via `/community-skills` command | Not available - `community-skills` is a Claude Code-only command that symlinks into `~/.claude/skills/`. It is intentionally absent from `.codex/commands/`. |

## Customizing for a project

To add the methodology to a project that doesn't have `.codex/AGENTS.md` checked in, create an `AGENTS.md` at your project root:

```bash
cp ~/agentic-engineering/.codex/AGENTS.md /path/to/your/project/AGENTS.md
```

Or reference the methodology from your project's `AGENTS.md`:

```markdown
# [Your Project]

[Project-specific context here]

---

[Paste relevant sections from ~/agentic-engineering/.codex/AGENTS.md]
```
