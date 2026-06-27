## Protocol Details (read on trigger)

**Activation detail (Steps 5-6)** - when Step 4 of the activation preflight resolves to active:
Read `content/references/activation-detail.md` §Step 5: First-Activation Notice and §Step 6: Scaffolding-Sync Check for the sentinel write contract, TTY/QUIET gate, and `agentic-migrate` flow.

**Planning artifacts (Brief and Plan tiers)** - when authoring a Brief or Plan after orchestration-planner returns 2+ Elevated-or-above units:
See `content/sections/03-planning-artifacts.md` for the trigger table, ordering, and gate semantics. Templates (Brief, Plan-tier directory, verification-gate), promotion mechanics, product-intent layer, and the canonical `qa_default_skip` definition live in `content/references/planning-artifacts.md`.

**Delegation detail** - when consulting the full Worker autonomy contract, stop-frequency planning signal, or investigator-before-architect rules:
Read `content/references/delegation-detail.md` §Worker Autonomy Contract, §Stop-Frequency as Planning Signal, §Investigator-Before-Architect Rules, §Learnings Pipeline, §Worker Preamble and Execution Contract Template, and §Digest-Return Discipline.

**Risk config and tiers** - when consulting config toggles, the graph-derived risk signal, or tier declaration detail:
Read `content/references/risk-config-and-tiers.md` §Config Toggle Catalog (behavioral), §Graph-derived risk signal, and §Tier Declaration Detail.

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
See `content/sections/06-capability-preflight.md` for when preflight runs, advisory vs blocking mode, and the absent-block no-op rule. Full YAML schema, `required_when` predicate grammar, `auto_install` safety constraints, 7-step preflight procedure, output message format, and cache schema live in `content/references/capability-preflight.md`.

**QA gate** - when Skeptic sign-off is granted on a UI-visible change:
See `content/sections/05-qa-gate.md` for the concurrent-vs-sequential flow, when-QA-skipped enums, conductor preflight, and INCONCLUSIVE classification. Parallel-by-worktree fan-out commands, architect-plan-driven scenarios deep prose, and the dev-server boot pattern live in `content/references/qa-gate.md`.

**Events log schema** - full V1 telemetry event-type field shapes and operational notes:
Read `content/references/events-log.md` for the `spawn_start`, `spawn_complete`, `conductor_direct`, `meta_review_complete`, `session_total`, and `tool_failure_workaround` event schemas with full `data` field definitions, append discipline, atomicity, retention, and consumer notes. Writer scope and base schema remain in `content/sections/09-events-log.md`.

**Worktree lifecycle commands** - cleanup command blocks for isolation and feature worktrees, session-start prune script:
Read `content/references/worktree-lifecycle.md` for the full bash command blocks. Isolation mandate, two-class summary, and session-start prune rule remain in `content/sections/11-worktree-lifecycle.md`.

**Cross-session loop resume** - when `/implement-ticket` loop state must be resumed:
Read `content/references/cross-session-loop-resume.md` §Cross-session loop resume for disk-write discipline, resumable phases, Brief/Plan path recording, and batch-state coexistence.

**Task-state file** - when managing multi-unit plan orchestration state:
Read `content/references/task-state-file.md` §Task-state file for schema, file-absent/present behavior, orphan detection, field-level merge algorithm, and `author_model` field semantics.

**Code standards detail** - when implementing or modifying code in a specific language:
Read `content/references/code-standards-detail.md` §Per-Language Strict Defaults for TypeScript/JS/Python/Go/Rust/Next.js linter and typecheck configs, and §Browser Verification for `agent-browser` usage patterns.

**Conventions detail** - when consulting the intent layer, context economy, or external comment rules:
Read `content/references/conventions-detail.md` §The Intent Layer for artifact list and Project Config toggle catalog, §Context Economy for context-window discipline, and §External Comment Discipline for PR/review comment rules.

**Capture classification** - when deciding whether to write a learning entry at a mandatory trigger:
Read `content/references/capture-classification.md` for the guardrail-first precedence chain, the two-gate MUST/SHOULD/SKIP table, and the per-trigger declaration format. Mandatory triggers and the `Capture:` block format are owned by `content/references/conductor-operating-rules.md §learnings-agent`.

**Outcome rubric** - when authoring or reviewing a Brief for Elevated work:
Read `content/references/planning-artifacts.md` for the line schema (`{id, line, verification_type: deterministic | judgment}`), field guidance (distinct from Verification gate commands - the operator's semantic definition of done), and verification-gate `Rubric lines resolved` subsection. The rubric is co-authored via `product-discovery` step 5b (staged to `docs/overview/_proposed/outcome-rubric.md`) and confirmed before Brief authoring; `/brief` Section 3 copies the staged draft or elicits rubric lines inline. The independent Skeptic grades judgment lines adversarially (step 3.5 in `content/agents/skeptic.md`); absence on Elevated is a Critical finding.

**Trigger catalog and open-goal loops** - when setting up an action-triggered workflow or declaring a measured goal condition rather than a fixed unit list:
Read `content/references/trigger-catalog.md` for the three trigger types (manual / scheduled / action-triggered), the open-goal loop contract (trigger / action / measured condition / hard-stop), and the yolo-guard: a trigger fires the conductor (never a worker-spawn bypass), and risk classification plus a fresh Skeptic apply on every iteration regardless of how the loop was started.
