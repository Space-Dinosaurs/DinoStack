# DinoStack - Hermes Adapter

## What this provides

- **SKILL.md** - A Hermes skill containing the full DinoStack methodology (rules, references, agents, commands)
- **Global config** - `~/.hermes/agentic-engineering.json` stores the activation mode (`opt-out` or `opt-in`)
- **Auto-loading** - The skill loads automatically when Hermes detects software-development context, or manually via `skill_view(name="agentic-engineering")`

## Prerequisites

- Hermes Agent installed and configured
- The agentic-engineering repo cloned to `~/agentic-engineering/` (expected by references)

## Installation

Clone the repo (if you haven't):

```bash
git clone https://github.com/Space-Dinosaurs/DinoStack.git ~/agentic-engineering
```

Run the installer:

```bash
~/agentic-engineering/.hermes/install.sh
```

This:
1. Runs `.hermes/build.sh` to generate `SKILL.md` from `content/`
2. Symlinks `~/.hermes/skills/agentic-engineering/SKILL.md` to the generated skill
3. Writes the activation mode to `~/.hermes/agentic-engineering.json`

### Non-interactive install

```bash
bash ~/agentic-engineering/.hermes/install.sh --mode=opt-out
bash ~/agentic-engineering/.hermes/install.sh --mode=opt-in
```

## Post-install verification

1. **Skill is installed:**
   ```bash
   ls -la ~/.hermes/skills/agentic-engineering/SKILL.md
   ```
   Should show a symlink pointing to `~/agentic-engineering/.hermes/SKILL.md`.

2. **Skill loads correctly:**
   In a Hermes session, run:
   ```
   skill_view(name="agentic-engineering")
   ```
   Then ask: "What risk tiers does the DinoStack protocol define?"
   The answer should reference Trivial/Low/Elevated/Elevated+Cleanup.

3. **Activation mode set:**
   ```bash
   cat ~/.hermes/agentic-engineering.json
   ```
   Should show `{"mode": "opt-out"|"opt-in", "set_at": "..."}`.

## Uninstall

```bash
~/agentic-engineering/.hermes/uninstall.sh
```

Removes the skill symlink and optionally the config file.

## Updating

Pull and re-run the installer - it is idempotent:

```bash
cd ~/agentic-engineering
git pull
bash .hermes/install.sh
```

For a clean refresh:

```bash
bash .hermes/uninstall.sh
git pull
bash .hermes/install.sh
```

## How it works

### Skill loading

Hermes auto-discovers skills from `~/.hermes/skills/`. The `agentic-engineering` skill contains the full methodology as a single document. Hermes loads it based on tag matching (`software-development`, `coding-standards`, etc.) or when explicitly requested.

### Activation preflight

The skill includes an activation preflight section. At the start of each session where the skill is loaded, the agent checks:

1. `~/.hermes/agentic-engineering.json` for the global mode
2. The project's root `AGENTS.md` for per-project opt-in/opt-out markers

If inactive for the current project, the skill no-ops gracefully.

### Commands

Hermes does not have "slash commands" like Claude Code. Instead, the commands from `content/commands/` are included as documented workflow patterns. Invoke them by asking the agent to run the workflow (e.g., "Run the skeptic workflow" or "Initialize this project with DinoStack").

### Hooks

Hermes has a hooks system at `~/.hermes/hooks/`. Future versions of this adapter may add:
- Risk reminder hook (fires before prompt submission)
- Context save hook (fires on session end)

For now, use the `/wrap` workflow pattern before ending a session to capture context.

## Build

Regenerate `SKILL.md` from updated source files:

```bash
bash ~/agentic-engineering/.hermes/build.sh
```

Run after `git pull` to pick up upstream changes. The build script concatenates all rules, references, agents, and commands into a single skill file.

## Coexistence with other adapters

This adapter is designed to run alongside Claude Code, Cursor, Codex, and Gemini adapters:

- **Config paths are disjoint:** Hermes uses `~/.hermes/`, others use `~/.claude/`, `~/.cursor/`, `~/.codex/`, `~/.gemini/`
- **Context files are disjoint:** Each tool manages its own session context
- **The repo can be shared:** All adapters read from the same `content/` source of truth
