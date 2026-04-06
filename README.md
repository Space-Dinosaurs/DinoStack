# agentic-engineering

A portable, installable package of the agentic engineering protocol for Claude Code. It provides a structured delegation model, risk classification, adversarial review loops, code quality gates, git workflow conventions, and a full set of named agent definitions.

## What it installs

Running `./install.sh` places the following into your `~/.claude/` directory:

**Agent definitions** (`~/.claude/agents/`):
- `architect` - pre-implementation design and planning
- `debugger` - root cause analysis
- `engineer` - scoped implementation (Worker agent)
- `investigator` - codebase exploration and blast radius mapping
- `orchestration-planner` - decomposes multi-unit plans into parallel/sequential execution order
- `security-auditor` - security-focused review
- `skeptic` - adversarial review (finds Critical, Major, and Minor findings)
- `adr-drift-detector` - checks whether code has drifted from ADR decisions
- `adr-generator` - writes Architecture Decision Records
- `qa-engineer` - test planning and QA review

**Commands** (`~/.claude/commands/`):
- `skeptic` - orchestration template for the adversarial review loop
- `memory-update` - structured update to MEMORY.md
- `wrap` - on-demand session summarization
- `init-project` - scaffolds a new project with CLAUDE.md, settings, and pre-commit hooks
- `flow-dev` - development workflow shortcut
- `flow-qa-plan` - QA planning workflow shortcut
- `implement` - single-command implementation kickoff

**Engineering skill** (`~/.claude/skills/engineering/`): loaded on demand, not at session start. Contains the full protocol reference - delegation rules, risk classification tables, and Skeptic loop orchestration details.

**Hook entries** in `~/.claude/settings.json`:
- `UserPromptSubmit` - risk reminder that fires before each turn
- `Stop` - context saver that writes session state to `context.md` after every agent turn

## Installation

```bash
git clone <repo-url> ~/agentic-engineering
cd ~/agentic-engineering
./install.sh
```

The install script is additive and idempotent - it will not overwrite existing files that were not created by it.

## Uninstallation

```bash
cd ~/agentic-engineering
./uninstall.sh
```

The uninstall script removes only the files this package installed. It does not touch any settings or agents from other sources.

## Repo structure

```
agentic-engineering/
  install.sh          - installation script
  uninstall.sh        - uninstallation script
  agents/             - agent definition files
  commands/           - slash command files
  skills/engineering/ - on-demand skill content
  hooks/              - hook scripts wired into settings.json
  README.md
```

## Part of a family

This repo follows a common pattern shared across domain-specific protocol packages:

- `agentic-engineering` - software development protocol (this repo)
- `agentic-marketing` - marketing and content workflow protocol
- others as they are developed

Each package installs independently and can coexist with the others. They share the same install/uninstall convention and the same `~/.claude/` layout.
