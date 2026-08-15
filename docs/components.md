# What's included

**Rules** (3 files) - the core methodology:
- Module manifest - required manifest header for non-trivial source files (exports, 50+ LOC, or side-effecting)
- Code standards - tool discipline, quality gates, package management, browser verification
- Conventions - writing style, project structure, session context, git workflow

**Reference docs** (39 .md docs plus 3 example .yml files; `content/references/` is the authoritative list) - detailed protocol specs loaded on trigger:
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
- Wrap context format - canonical schema for the /ds-wrap session-context block
- Digest-return pattern - conductor stays context-lean; workers return a structured digest, not the transcript
- Activation detail - first-activation notice and scaffolding-sync check (Steps 5-6)
- Code standards detail - per-language strict defaults and browser verification patterns
- Conventions detail - intent layer, context economy, external comment discipline
- Cross-harness teams - dispatching workers to non-Claude harnesses, self-containment guard
- Cross-session loop resume - disk-write discipline, resumable phases, batch-state coexistence
- Model discovery - model routing and role-model assignment
- Role models - default model assignments by agent role
- Task state file - multi-unit plan orchestration state schema and protocol
- Handoff evaluation - the Phase 12a gate that runs after a ticket completes in batch, open-goal, or single-ticket-capped mode
- Tracker writeback - the reusable Tracker Writeback Helper invocation pattern shared by every tracker state-transition call site
- Learnings capture instruction - what counts as a learning and the canonical learnings_candidate digest-field definition
- Subagent return contract - the attention test that classifies every subagent return field as MECHANICAL or ADVISORY

**Agents** (18) - named specialist roles:
adr-drift-detector, adr-generator, architect, debugger, dependency-auditor, engineer, goal-condition-evaluator, investigator, learning-extractor, learnings-agent, orchestration-planner, perf-analyst, product-discovery, qa-engineer, release-orchestrator, security-auditor, skeptic, wrap-ticket

**Commands** (27) - workflow shortcuts:
ds-brief, ds-cleanup-worktrees, ds-config (interactive view/change of dinostack settings), ds-configure-team, ds-cost (token / wall-time rollups from `.agentic/events.jsonl`; opt-in pricing via `~/.agentic/pricing.yml`), ds-disable, ds-evaluate (evaluate methodology effectiveness against the North Star pillars from live telemetry), ds-failure-audit (conductor-invoked audit: spawns an agent to mine session telemetry and categorize failure modes per model/harness with quantified frequency), ds-feedback-triage (triage captured session friction from `~/.agentic/feedback.jsonl` into tracker tickets), ds-help (static, zero-token command reference listing every slash command), ds-identity, ds-implement-ticket, ds-init-project, ds-memory-update, ds-migrate-project, ds-prune-harness, ds-representation-audit, ds-skeptic, ds-skill-candidates, ds-status, ds-test-suite-comprehension, ds-ticket-status-sync, ds-ticket-triage (batch planner: dependency analysis, lane distribution, paste-ready kickoff prompts; plan-only, no tracker writes), ds-update (pull and reinstall dinostack from upstream, or fresh-install if not yet set up), ds-update-agentic-engineering (pushes methodology edits up to upstream - opposite direction from `ds-update`), ds-wrap, ds-wrap-deferred

**Hooks / Plugins** - lifecycle event handlers for risk reminders and session context saving. Claude Code uses native hooks; OpenCode uses a plugin that writes session context when the session becomes idle.

**Codex native skills** - Codex installs exactly four native Codex skills: `dinostack`, `brief`, `wrap`, and `implement-ticket`. Invoke the workflow skills with `$brief`, `$wrap`, and `$implement-ticket`; the corresponding canonical sources are `content/commands/ds-brief.md`, `content/commands/ds-wrap.md`, and `content/commands/ds-implement-ticket.md`. `.codex/build.sh` runs `scripts/codex-skills.py` to transform those reviewed sources, generate `SKILL.md` and `RESOURCE-MAP.json` files, validate relative symlink/resource-map closure, and synchronize the exact allowlist. The read-only check rejects generated drift.

**Project config / overview layer** - the committed `.agentic/config.json` holds twenty-three methodology toggles (one, `qa_default_skip`, is reserved/inert): `debugger_on_failure` (bool, default `false`; interposes a Debugger diagnosis step before each Phase 7 engineer fix pass), `qa_default_skip` (reserved; no-op, does not alter QA-gate behavior), `model_profile` (`default` | `budget`; `budget` routes eligible spawns to Tier 1), `auto_merge_on_ci_green` (bool, default `false`; when `true`, `/ds-implement-ticket` Phase 12 squash-merges the PR after CI passes and the PR is ready with no requested changes), `capability_preflight_mode` (`advisory` | `blocking`, default `blocking`; controls whether a missing required dependency warns-and-proceeds or halts the spawn), `perceptual_diff_enabled` (bool, default `false`; opt-in Playwright screenshot diff against committed baselines), `theme_aware` (bool, default `false`; opt-in per-theme QA tuples in light and dark), `storybook_enabled` (bool, default `false`; opt-in `story_id` targeting of the Storybook iframe), `motion_aware` (bool, default `false`; opt-in CDP reduced-motion QA checks), `storybook_version` (`6` | `7`, default `7`; selects the Storybook URL format), `commit_telemetry` (bool, default `true`; commits the per-developer session log as a separate commit on the PR branch), `knowledge_commit_on_pr` (bool, default `true`; when `true`, `/ds-implement-ticket` Phase 11e commits any changed `MEMORY.md`, `decisions.md`, and `.agentic/learnings.md` onto the ticket's PR branch, checkout-free via a temporary index plus `commit-tree`), `deferred_wrap_daemon` (bool, default `false`; opt-in out-of-session daemon that runs deferred `/ds-wrap` jobs), `abdication_guard_enabled` (bool; absent → guard inert; `/ds-init-project` template sets `true`; Stop hook blocks conductor turns that end by asking permission for a non-destructive next step, announcing a surface-and-proceed default and then not acting on it, or presenting a prose co-equal ballot in an `## Operator decisions` block; requires an explicit `true` to run), `skill_candidate_detection` (bool, default `true`; master toggle for the skill-candidate detector; when `true`, the Stop hook surfaces recurring friction patterns as skill candidates), `skill_candidate_nudge` (bool, default `false`; Layer-2 opt-in in-session nudge when a domain crosses the candidate threshold), `ticket_driven` (`off` | `offer` | `require`; controls whether the conductor creates a tracker ticket before spawning the first implementer on net-new work; absent-key resolution: effective `offer` when `TRACKER != none`, `off` when `TRACKER == none`), `rework_detection` (bool, default `true`; disables the Phase 9 ledger write, Phase 1 detection, the notice, the triage badge, and the escalation with a single flag), `pending_merge_sweep` (bool, default `true`; controls the session-start pending-merge sweep that pushes the dev-complete transition (`TRACKER_STATE_DEV_COMPLETE`, which defaults to the resolved `TRACKER_STATE_DONE` value) to the tracker once a ticket's PR merges; set `false` to disable), `tracker_state_diagnostic` (bool, default `true`; controls whether the tracker writeback subagent emits a live diagnostic naming currently-available states when a configured `TRACKER_STATE_*` name cannot be used; set `false` to disable), `turn_shape_guard_enabled` (bool, default `true`; Stop hook checks the conductor's final turn against the fixed-shape/warranted-turn rule - as of DS-156 NOT uniformly advisory, since the execution-turn structural check (`_execution_prose_flag`) is blocking and can block the stop while the operator-decisions per-item shape check (`_decision_item_sprawl_flag`) stays advisory-only and only logs; as of DS-171, three prior checks (the answer relevance check, the zero-warrant status-only check, and the whole-message turn-volume check) are retired from this hook and live instead in the `dinostack` Claude Code output style, which additionally carries two rules with no prior hook-mechanized form: self-narrating candor, and editorial addenda (the ban on any conductor-selected item that carries none of the four turn warrants, in any position in the turn and whether or not it is bundled - a labelled package of such observations is the canonical form, not the boundary); absent key resolves to on), `worktree_read_guard_exemptions` (list of strings, default `[]`; path prefixes relative to the primary checkout root exempted from the worktree-isolation `Read` guard), and `worktree_write_guard_exemptions` (list of strings, default `[]`; SEPARATE key from `worktree_read_guard_exemptions`; path prefixes relative to the primary checkout root exempted from the worktree-isolation `Write`/`Edit`/`MultiEdit` guard). The operator-owned intent-layer files (`docs/overview/vision.md`) capture durable product intent above the task level; Architect, Investigator, and Engineer read them when present and must not contradict them. The files are optional and graceful - if absent, defaults apply and nothing breaks.

## Repo structure

```
DinoStack/
  .claude/              Claude Code adapter (skill, agents, commands, install/uninstall)
  .codex/               Codex CLI adapter (AGENTS.md, four native skills, commands, install/uninstall)
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
