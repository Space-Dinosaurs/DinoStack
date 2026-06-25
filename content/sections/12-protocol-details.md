## Protocol Details (read on trigger)

**Planning artifacts (Brief and Plan tiers)** - when authoring a Brief or Plan after orchestration-planner returns 2+ Elevated-or-above units:
Read `content/sections/03-planning-artifacts.md` for the trigger table, ordering, and gate semantics; read `content/references/planning-artifacts.md` §Brief template, §Plan-tier directory, §Promotion mechanics for templates and promotion mechanics.

**Phase breadcrumb** - at every natural orchestration boundary (after agent spawn, agent return, escalation, task completion):
Emit `[phase: label]` inline in your status update to the user. Full vocabulary in `~/DinoStack/.claude/skills/agentic-engineering/references/subagent-protocol.md` Rule 6.

**Skeptic loop orchestration** - when Elevated risk is declared:
Run `/skeptic` for the full orchestration template, or read `~/DinoStack/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Sections 2-5) for loop steps, state management, re-route limits, and escalation. For findings accumulation rules across loop iterations (findings_log schema, re-raise detection, auto-close rule), see `/implement-ticket` Phase 6.

**Findings classification and sign-off** - when reviewing Skeptic output:
Read `~/DinoStack/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Sections 6, 11) for Critical/Major/Minor definitions, required sign-off format, and validation rules.

**Elevated + Cleanup path** - when declaring Elevated + Cleanup:
Read `~/DinoStack/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Section 12) for the /simplify integration workflow and second Skeptic narrow-scope review.

**Adversarial briefs** - when writing the brief for a Skeptic:
Run `/skeptic` (includes brief selection table) or read `~/DinoStack/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Section 8) for domain-specific templates.

**Parallel spawning and worktrees** - when decomposing work into multiple agents:
Read `~/DinoStack/.claude/skills/agentic-engineering/references/subagent-protocol.md` (Sections 2, 5, 7) for parallel-by-default, worktree isolation rules, and check-in behavior.

**Task decomposition and review scope** - when breaking work into multiple Workers:
Read `~/DinoStack/.claude/skills/agentic-engineering/references/subagent-protocol.md` (Section 6) for decomposition rules and `~/DinoStack/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Section 9) for review scope guidance.

**Agent team composition** - which agent to use and how they compose:
Read `~/DinoStack/.claude/skills/agentic-engineering/references/agent-team.md` for flows (feature, bug, security), decision rules, and spawn prompts.

**Regression test obligation** - when a Worker fixes a Critical or Major Skeptic finding:
Read `~/DinoStack/.claude/skills/agentic-engineering/references/regression-test-obligation.md` for what counts as a valid regression test, the Worker obligation to add one, and the Skeptic verification rule.

**QA regression-test obligation** - when a Worker fixes a qa-engineer FAIL:
Read `~/DinoStack/.claude/skills/agentic-engineering/references/qa-regression-obligation.md` for the engineer's regression-test obligation, the documented-exception path via `.agentic/qa-regressions.md`, and the Skeptic verification rule. Symmetric to the Skeptic-side `regression-test-obligation.md`.

**Doc-sync obligation** - when a change alters a count, list, path, convention, or behavior an intent-layer doc asserts:
Read `~/DinoStack/.claude/skills/agentic-engineering/references/doc-sync-obligation.md` for the trigger predicate, exemptions, the Worker obligation to update affected docs in the same change, and the tiered Skeptic verification rule.

**Capability preflight** - before every Agent spawn:
Read `content/references/capability-preflight.md` for the YAML schema, `required_when` predicate grammar, advisory-vs-blocking mode, `auto_install` safety constraints, 7-step procedure, and cache schema.

**QA gate** - when Skeptic sign-off is granted on a UI-visible change:
Read `content/sections/05-qa-gate.md` for the concurrent-vs-sequential flow, when-QA-skipped enums, conductor preflight, and INCONCLUSIVE classification; read `content/references/qa-gate.md` §Multi-PR / multi-ticket parallel-by-worktree, §Architect-plan-driven scenarios, and §qa-engineer dev-server boot pattern for operational details.

**Events log schema** - full V1 telemetry event-type field shapes and operational notes:
Read `content/references/events-log.md` §V1 telemetry event types for the full `data` field definitions, append discipline, atomicity, retention, consumer notes, and per-developer session log schema.

**Worktree lifecycle commands** - cleanup command blocks for isolation and feature worktrees, session-start prune script:
Read `content/references/worktree-lifecycle.md` §Isolation worktree cleanup commands, §Feature worktree cleanup commands, and §Session-start prune script for the full bash command blocks.

**Capture classification** - when deciding whether to write a learning entry at a mandatory trigger:
Read `content/references/capture-classification.md` for the guardrail-first precedence chain, the two-gate MUST/SHOULD/SKIP table, and the per-trigger declaration format. Mandatory triggers and the `Capture:` block format are owned by `content/references/conductor-operating-rules.md §learnings-agent`.

**Outcome rubric** - when authoring or reviewing a Brief for Elevated work:
Read `content/references/planning-artifacts.md` for the line schema (`{id, line, verification_type: deterministic | judgment}`), field guidance (distinct from Verification gate commands - the operator's semantic definition of done), and verification-gate `Rubric lines resolved` subsection. The rubric is co-authored via `product-discovery` step 5b (staged to `docs/overview/_proposed/outcome-rubric.md`) and confirmed before Brief authoring; `/brief` Section 3 copies the staged draft or elicits rubric lines inline. The independent Skeptic grades judgment lines adversarially (step 3.5 in `content/agents/skeptic.md`); absence on Elevated is a Critical finding.

**Activation detail (Steps 5-6)** - first-activation notice and scaffolding-sync check, triggered every active session:
Read `content/references/activation-detail.md` §Step 5: First-activation notice and §Step 6: Scaffolding-sync check.

**Cross-session loop resume** - loop-state.json schema and resume protocol:
Read `content/references/cross-session-loop-resume.md` §Cross-session loop resume body for the full phase-transition protocol.

**Task-state file** - tasks.jsonl schema and conductor protocol for multi-unit plans:
Read `content/references/task-state-file.md` §Task-state file body for schema, orphan detection, and field-level merge algorithm.

**Code standards detail** - per-language quality gates and browser verification:
Read `content/references/code-standards-detail.md` §Per-language strict defaults and §Browser Verification when implementing or modifying code.

**Conventions detail** - intent layer, project config toggles, context economy, external comment discipline:
Read `content/references/conventions-detail.md` §The Intent Layer, §Project Config conventions, §Context Economy, and §External Comment Discipline.

**Delegation detail** - open questions, worker autonomy, investigator-before-architect, and execution contract:
Read `content/references/delegation-detail.md` §Open Questions and Deferred defaults, §Worker autonomy contract, §Investigator-before-Architect, and §Worker preamble and execution contract.

**Risk config and tiers** - project config toggles and tier declaration:
Read `content/references/risk-config-and-tiers.md` §Config toggle catalog (behavioral) and §Tier declaration.

**Trigger catalog and open-goal loops** - when setting up an action-triggered workflow or declaring a measured goal condition rather than a fixed unit list:
Read `content/references/trigger-catalog.md` for the three trigger types (manual / scheduled / action-triggered), the open-goal loop contract (trigger / action / measured condition / hard-stop), and the yolo-guard: a trigger fires the conductor (never a worker-spawn bypass), and risk classification plus a fresh Skeptic apply on every iteration regardless of how the loop was started.
