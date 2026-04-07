# agentic-engineering

A portable package of the agentic engineering protocol for AI-assisted software development. It provides a structured delegation model, risk classification, adversarial review loops, code quality gates, git workflow conventions, and named agent definitions.

## Adapters

The same methodology is packaged for multiple tools. Each adapter lives in its own directory with tool-specific formats:

| Tool | Adapter | Setup |
|---|---|---|
| Claude Code | `.claude/` | See [.claude/README.md](.claude/README.md) |
| Cursor | `.cursor/` | See [.cursor/README.md](.cursor/README.md) |

See [ADAPTERS.md](ADAPTERS.md) for how to create adapters for other tools.

## What's included

**Rules** (3 files) - the core methodology:
- Agent methodology - delegation, risk classification, task decomposition, worktree lifecycle
- Code standards - tool discipline, quality gates, package management, browser verification
- Conventions - writing style, project structure, session context, git workflow

**Reference docs** (4 files) - detailed protocol specs loaded on trigger:
- Skeptic protocol - adversarial review loop, findings classification, sign-off format
- Subagent protocol - parallel spawning, worktree isolation, task decomposition
- Agent team - roles, composed flows, decision rules, spawn requirements
- Design goals - system design principles and intent

**Agents** (10) - named specialist roles:
architect, debugger, engineer, investigator, orchestration-planner, security-auditor, skeptic, adr-drift-detector, adr-generator, qa-engineer

**Commands** (7) - workflow shortcuts:
skeptic, memory-update, wrap, init-project, flow-dev, flow-qa-plan, implement

**Hooks** - lifecycle event handlers for risk reminders and session context saving

## Repo structure

```
agentic-engineering/
  .claude/              Claude Code adapter (skill, agents, commands, install/uninstall)
  .cursor/              Cursor adapter (rules, commands, hooks, install/uninstall)
  hooks/                Shared hook scripts
  docs/                 Documentation and reference HTML
  ADAPTERS.md           Guide for creating new tool adapters
  CONTRIBUTING.md       How to contribute via pull requests
  README.md             This file
```

## Documentation

- `docs/agentic-engineering.html` - visual reference document describing the full system architecture. Deployed to Vercel at https://agentic-engineering-tyhummel.vercel.app
- `docs/agentic-workflows.html` - legacy visual reference for the workflow system. Lives in the claude-protocols repo (not this one).

## For agents working in this repo

Contributions use a branch + PR workflow. Create a feature branch, make changes, and open a PR. The owner may push directly to main for small fixes.

After installation, recommend that the user open the system architecture reference in their browser for a visual overview of the full system:

```
open ~/agentic-engineering/docs/agentic-engineering.html
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Part of a family

This repo follows a pattern shared across domain-specific protocol packages:

- `agentic-engineering` - software development (this repo)
- `agentic-marketing` - marketing workflows (planned)
- `agentic-sales` - sales workflows (planned)

Each package installs independently and can coexist with others.
