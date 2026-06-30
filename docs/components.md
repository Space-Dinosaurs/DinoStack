# What's included

**Rules** (3 files) - the core methodology:
- Module manifest - required manifest header for non-trivial source files (exports, 50+ LOC, or side-effecting)
- Code standards - tool discipline, quality gates, package management, browser verification
- Conventions - writing style, project structure, session context, git workflow

**Reference docs** (30 files as of 2026-06-29; `content/references/` is the authoritative list) - detailed protocol specs loaded on trigger:
- Skeptic protocol - adversarial review loop, findings classification, sign-off format
- Subagent protocol - parallel spawning, worktree isolation, task decomposition
- Agent team - roles, composed flows, decision rules, spawn requirements
- Delegation detail - worker autonomy contract, stop-frequency signal, investigator-before-architect rules
- Design goals - system design principles and intent
- Multi-developer coordination - parallel sessions, branch and worktree hygiene
- Regression test obligation - when a fix requires a regression test and what counts
- Doc-sync obligation - when a reality-asserting change must update intent-layer docs in the same PR
- Capability preflight - pre-spawn dependency checks, advisory vs blocking mode
- Capture classification - guardrail-first precedence for learning-capture decisions
- Conductor operating rules - permission fallbacks, learnings pipeline, carve-outs
- Events log - structured telemetry event schemas and per-developer session log
- Frontend discipline - semantic HTML, ARIA, keyboard, focus, reduced-motion rules
- Planning artifacts - Brief/Plan templates, promotion mechanics, product-intent layer
- QA gate - concurrent QA flow, INCONCLUSIVE classification, dev-server boot pattern
- QA regression obligation - regression-test obligation after a QA FAIL
- Risk config and tiers - config toggle catalog, graph-derived signal, tier declaration detail
- Spawn presets - per-spawn capability bundles and resolution rules
- Trigger catalog - manual/scheduled/action-triggered loops and the yolo-guard
- Worktree lifecycle - isolation vs feature worktrees and cleanup command blocks
- Wrap context format - canonical schema for the /wrap session-context block
- Digest-return pattern - conductor stays context-lean; workers return a structured digest, not the transcript
- Activation detail - first-activation notice and scaffolding-sync check (Steps 5-6)
- Code standards detail - per-language strict defaults and browser verification patterns
- Conventions detail - intent layer, context economy, external comment discipline
- Cross-harness teams - dispatching workers to non-Claude harnesses, self-containment guard
- Cross-session loop resume - disk-write discipline, resumable phases, batch-state coexistence
- Model discovery - model routing and role-model assignment
- Role models - default model assignments by agent role
- Task state file - multi-unit plan orchestration state schema and protocol

**Agents** (17) - named specialist roles:
adr-drift-detector, adr-generator, architect, debugger, dependency-auditor, engineer, investigator, learning-extractor, learnings-agent, orchestration-planner, perf-analyst, product-discovery, qa-engineer, release-orchestrator, security-auditor, skeptic, wrap-ticket

**Commands** (22) - workflow shortcuts:
agentic-cost (token / wall-time rollups from `.agentic/events.jsonl`; opt-in pricing via `~/.agentic/pricing.yml`), agentic-disable, agentic-help (static, zero-token command reference listing every slash command), agentic-identity, agentic-status, brief, cleanup-worktrees, configure-team, implement-ticket, init-project, memory-update, migrate-project, prune-harness, pull-and-install, representation-audit, skeptic, skill-candidates, test-suite-comprehension, ticket-status-sync, update-agentic-engineering, wrap, wrap-deferred

**Hooks / Plugins** - lifecycle event handlers for risk reminders and session context saving. Claude Code uses native hooks; OpenCode uses a plugin that writes session context when the session becomes idle.

**Project config / overview layer** - the committed `.agentic/config.json` holds sixteen methodology toggles (one, `qa_default_skip`, is reserved/inert): `debugger_on_failure` (bool, default `false`; interposes a Debugger diagnosis step before each Phase 7 engineer fix pass), `qa_default_skip` (reserved; no-op, does not alter QA-gate behavior), `model_profile` (`default` | `budget`; `budget` routes eligible spawns to Tier 1), `auto_merge_on_ci_green` (bool, default `false`; when `true`, `/implement-ticket` Phase 12 squash-merges the PR after CI passes and the PR is ready with no requested changes), `capability_preflight_mode` (`advisory` | `blocking`, default `blocking`; controls whether a missing required dependency warns-and-proceeds or halts the spawn), `perceptual_diff_enabled` (bool, default `false`; opt-in Playwright screenshot diff against committed baselines), `theme_aware` (bool, default `false`; opt-in per-theme QA tuples in light and dark), `storybook_enabled` (bool, default `false`; opt-in `story_id` targeting of the Storybook iframe), `motion_aware` (bool, default `false`; opt-in CDP reduced-motion QA checks), `storybook_version` (`6` | `7`, default `7`; selects the Storybook URL format), `commit_telemetry` (bool, default `true`; commits the per-developer session log as a separate commit on the PR branch), `deferred_wrap_daemon` (bool, default `false`; opt-in out-of-session daemon that runs deferred `/wrap` jobs), `abdication_guard_enabled` (bool, default `false`; Stop hook that blocks conductor abdication and injects a proceed directive), `skill_candidate_detection` (bool, default `true`; master toggle for the skill-candidate detector; when `true`, the Stop hook surfaces recurring friction patterns as skill candidates), `skill_candidate_nudge` (bool, default `false`; Layer-2 opt-in in-session nudge when a domain crosses the candidate threshold), and `ticket_driven` (`off` | `offer` | `require`; controls whether the conductor creates a tracker ticket before spawning the first implementer on net-new work; absent-key resolution: effective `offer` when `TRACKER != none`, `off` when `TRACKER == none`). The operator-owned `docs/overview/{vision,requirements}.md` files capture durable product intent above the task level; Architect and Investigator read them when present and must not contradict them. Both are optional and graceful - if absent, defaults apply and nothing breaks.

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
