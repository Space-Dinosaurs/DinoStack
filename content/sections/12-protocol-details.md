## Protocol Details (read on trigger)

**Planning artifacts (Brief and Plan tiers)** - when authoring a Brief or Plan after orchestration-planner returns 2+ Elevated-or-above units:
See METHODOLOGY.md §Planning Artifacts for the trigger table, ordering, and gate semantics. Templates (Brief, Plan-tier directory, verification-gate), promotion mechanics, product-intent layer, and the canonical `qa_default_skip` definition live in `content/references/planning-artifacts.md`.

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
See METHODOLOGY.md §Capability Preflight for when preflight runs, advisory vs blocking mode, and the absent-block no-op rule. Full YAML schema, `required_when` predicate grammar, `auto_install` safety constraints, 7-step preflight procedure, output message format, and cache schema live in `content/references/capability-preflight.md`.

**QA gate** - when Skeptic sign-off is granted on a UI-visible change:
See METHODOLOGY.md §QA Gate for the concurrent-vs-sequential flow, when-QA-skipped enums, conductor preflight, and INCONCLUSIVE classification. Parallel-by-worktree fan-out commands, architect-plan-driven scenarios deep prose, and the dev-server boot pattern live in `content/references/qa-gate.md`.

**Events log schema** - full V1 telemetry event-type field shapes and operational notes:
Read `content/references/events-log.md` for the `spawn_start`, `spawn_complete`, `conductor_direct`, `meta_review_complete`, `session_total`, and `tool_failure_workaround` event schemas with full `data` field definitions, append discipline, atomicity, retention, and consumer notes. Writer scope and base schema remain in METHODOLOGY.md §Events log.

**Worktree lifecycle commands** - cleanup command blocks for isolation and feature worktrees, session-start prune script:
Read `content/references/worktree-lifecycle.md` for the full bash command blocks. Isolation mandate, two-class summary, and session-start prune rule remain in METHODOLOGY.md §Worktree Lifecycle.

**Capture classification** - when deciding whether to write a learning entry at a mandatory trigger:
Read `content/references/capture-classification.md` for the guardrail-first precedence chain, the two-gate MUST/SHOULD/SKIP table, and the per-trigger declaration format. Mandatory triggers and the `Capture:` block format are owned by `content/references/conductor-operating-rules.md §learnings-agent`.

**Outcome rubric** - when authoring or reviewing a Brief for Elevated work:
Read `content/references/planning-artifacts.md` for the line schema (`{id, line, verification_type: deterministic | judgment}`), field guidance (distinct from Verification gate commands - the operator's semantic definition of done), and verification-gate `Rubric lines resolved` subsection. The rubric is co-authored via `product-discovery` step 5b (staged to `docs/overview/_proposed/outcome-rubric.md`) and confirmed before Brief authoring; `/brief` Section 3 copies the staged draft or elicits rubric lines inline. The independent Skeptic grades judgment lines adversarially (step 3.5 in `content/agents/skeptic.md`); absence on Elevated is a Critical finding.
