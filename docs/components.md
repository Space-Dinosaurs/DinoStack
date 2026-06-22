# What's included

**Rules** (3 files) - the core methodology:
- Agent methodology - delegation, risk classification, task decomposition, worktree lifecycle
- Code standards - tool discipline, quality gates, package management, browser verification
- Conventions - writing style, project structure, session context, git workflow

**Reference docs** (7 files) - detailed protocol specs loaded on trigger:
- Skeptic protocol - adversarial review loop, findings classification, sign-off format
- Subagent protocol - parallel spawning, worktree isolation, task decomposition
- Agent team - roles, composed flows, decision rules, spawn requirements
- Design goals - system design principles and intent
- Multi-developer coordination - parallel sessions, branch and worktree hygiene
- Regression test obligation - when a fix requires a regression test and what counts
- Doc-sync obligation - when a reality-asserting change must update intent-layer docs in the same PR

**Agents** (17) - named specialist roles:
adr-drift-detector, adr-generator, architect, debugger, dependency-auditor, engineer, investigator, learning-extractor, learnings-agent, orchestration-planner, perf-analyst, product-discovery, qa-engineer, release-orchestrator, security-auditor, skeptic, wrap-ticket

**Commands** (19) - workflow shortcuts:
agentic-cost (token / wall-time rollups from `.agentic/events.jsonl`; opt-in pricing via `~/.agentic/pricing.yml`), agentic-disable, agentic-help (static, zero-token command reference listing every slash command), agentic-identity, agentic-status, brief, cleanup-worktrees, implement-ticket, init-project, memory-update, migrate-project, prune-harness, pull-and-install, representation-audit, skeptic, test-suite-comprehension, ticket-status-sync, update-agentic-engineering, wrap

**Hooks / Plugins** - lifecycle event handlers for risk reminders and session context saving. Claude Code uses native hooks; OpenCode uses a plugin that writes session context when the session becomes idle.

**Project config / overview layer** - the committed `.agentic/config.json` holds four operator-tunable methodology toggles: `debugger_on_failure` (bool, default `false`; interposes a Debugger diagnosis step before each Phase 7 engineer fix pass), `qa_default_skip` (reserved; no-op, does not alter QA-gate behavior), `model_profile` (`default` | `budget`; `budget` routes eligible spawns to Tier 1), and `auto_merge_on_ci_green` (bool, default `false`; when `true`, `/implement-ticket` Phase 12 squash-merges the PR after CI passes and the PR is ready with no requested changes). The operator-owned `docs/overview/{vision,requirements}.md` files capture durable product intent above the task level; Architect and Investigator read them when present and must not contradict them. Both are optional and graceful - if absent, defaults apply and nothing breaks.

## Repo structure

```
DinoStack/
  .claude/              Claude Code adapter (skill, agents, commands, install/uninstall)
  .codex/               Codex CLI adapter (AGENTS.md, skill, commands, install/uninstall)
  .cursor/              Cursor adapter (rules, commands, hooks, install/uninstall)
  .gemini/              Gemini CLI adapter (GEMINI.md, agents, commands, install/uninstall)
  .kimi/                Kimi Code CLI adapter (AGENTS.md, skill, commands, install/uninstall)
  .opencode/            OpenCode adapter (skill, agents, commands, install/uninstall)
  .pi/                  Pi coding agent adapter (skill, prompts, install/uninstall)
  .omp/                 Pi (oh-my-pi) adapter (skill, install/uninstall)
  .hermes/               Hermes Agent adapter (skill, METHODOLOGY.md, install/uninstall)
  .openclaw/            OpenClaw adapter (skill tree, METHODOLOGY.md, install/uninstall)
  hooks/                Shared hook scripts
  docs/                 Documentation and reference HTML
  ADAPTERS.md           Guide for creating new tool adapters
  CONTRIBUTING.md       How to contribute via pull requests
  README.md             This file
```
