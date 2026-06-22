# DinoStack - OpenClaw Adapter

DinoStack adapter for [OpenClaw](https://openclaw.ai) AI coding harness.

## What it provides

- **Entry skill** (`agentic-engineering`): on-demand skill with YAML frontmatter. Load it by invoking `agentic-engineering` in your session. Contains the full methodology, rules, and reference doc pointers.
- **Command skills** (19): one skill dir per workflow command (`implement-ticket`, `brief`, `skeptic`, `wrap`, etc.). Each has `user-invocable: true` for direct invocation.
- **Agent skills** (17): named specialist agents as reference-only skills (`disable-model-invocation: true`). Each is prefixed `agent-` (e.g. `agent-skeptic`, `agent-engineer`) to avoid name collisions with the same-named command skills. OpenClaw has no Task-spawn equivalent; these are read-on-demand specs.
- **Activation config** (`~/.openclaw/agentic-engineering.json`): `mode`, `profile`, `set_at` fields. Shared shape with other adapters (`~/.claude/agentic-engineering.json`).
- **Global AGENTS.md** (`~/.openclaw/AGENTS.md`): the Skill Loading signal injected via a managed HTML-comment-delimited block.

## Prerequisites

- OpenClaw AI coding harness installed
- Python 3 on PATH (for build and install scripts)
- Git repo cloned locally

## Install

```bash
git clone git@github.com:Space-Dinosaurs/DinoStack.git ~/DinoStack
cd ~/DinoStack
bash .openclaw/install.sh
```

Optional flags (shared with all adapters):

```bash
bash .openclaw/install.sh --mode=opt-in        # activate only in opted-in projects
bash .openclaw/install.sh --mode=opt-out       # activate everywhere (default)
bash .openclaw/install.sh --profile=strict     # strict risk profile
bash .openclaw/install.sh --identity=<handle>  # set developer identity non-interactively
bash .openclaw/install.sh --no-identity        # skip identity prompt
```

This installs:
- All 36 skill dirs symlinked from `~/.openclaw/skills/<name>/` into `.openclaw/skills/<name>/`
- Skill Loading signal in `~/.openclaw/AGENTS.md`
- Activation config at `~/.openclaw/agentic-engineering.json`
- `agentic-*` binaries symlinked to `~/.local/bin/`

## Uninstall

```bash
bash .openclaw/uninstall.sh
```

Removes all per-skill symlinks owned by this repo, the managed AGENTS.md block, and optionally the activation config.

## Update

```bash
cd ~/DinoStack
git pull
bash .openclaw/install.sh
```

Or use the interactive updater:

```bash
./update.sh
```

## How it works

OpenClaw discovers skills at `~/.openclaw/skills/<name>/SKILL.md`. Each skill has YAML frontmatter:

```yaml
---
name: <unique-name>
description: <trigger description>
user-invocable: true   # slash command / user-invocable
# or:
user-invocable: false
disable-model-invocation: true  # reference-only (agent specs)
---
```

OpenClaw keys skill identity by the `name:` frontmatter field. The adapter makes directory name equal to frontmatter `name` on every skill.

**Command skills** use `user-invocable: true`. Invoke by name (e.g. `implement-ticket`, `brief`).

**Agent skills** use `user-invocable: false` and `disable-model-invocation: true`. They are reference specs loaded on demand - OpenClaw has no Task-spawn equivalent to Claude Code's subagent system, so these provide role definitions when prompting the main model to adopt a specialist role.

**The `agent-` prefix** on agent skill names (both dir and `name:` frontmatter) avoids collisions where a command and an agent share a name (e.g. `skeptic` is both a command and an agent spec; OpenClaw would merge them without the prefix).

## Rebuild after content changes

```bash
bash .openclaw/build.sh
```

Regenerates all 36 skill dirs from `content/`. Idempotent - safe to run repeatedly.
