## Protocol Details (read on trigger)

**Phase breadcrumb** - at every natural orchestration boundary (after agent spawn, agent return, escalation, task completion):
Emit `[phase: label]` inline in your status update to the user. Full vocabulary in `~/agentic-engineering/.claude/skills/agentic-engineering/references/subagent-protocol.md` Rule 6.

**Skeptic loop orchestration** - when Elevated risk is declared:
Run `/skeptic` for the full orchestration template, or read `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Sections 2-5) for loop steps, state management, re-route limits, and escalation. For findings accumulation rules across loop iterations (findings_log schema, re-raise detection, auto-close rule), see `/implement-ticket` Phase 6.

**Findings classification and sign-off** - when reviewing Skeptic output:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Sections 6, 11) for Critical/Major/Minor definitions, required sign-off format, and validation rules.

**Elevated + Cleanup path** - when declaring Elevated + Cleanup:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Section 12) for the /simplify integration workflow and second Skeptic narrow-scope review.

**Adversarial briefs** - when writing the brief for a Skeptic:
Run `/skeptic` (includes brief selection table) or read `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Section 8) for domain-specific templates.

**Parallel spawning and worktrees** - when decomposing work into multiple agents:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/subagent-protocol.md` (Sections 2, 5, 7) for parallel-by-default, worktree isolation rules, and check-in behavior.

**Task decomposition and review scope** - when breaking work into multiple Workers:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/subagent-protocol.md` (Section 6) for decomposition rules and `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Section 9) for review scope guidance.

**Agent team composition** - which agent to use and how they compose:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/agent-team.md` for flows (feature, bug, security), decision rules, and spawn prompts.

**Regression test obligation** - when a Worker fixes a Critical or Major Skeptic finding:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/regression-test-obligation.md` for what counts as a valid regression test, the Worker obligation to add one, and the Skeptic verification rule.

**QA gate** - when Skeptic sign-off is granted on a UI-visible change:
Check qa.md for trigger patterns (resolver: `.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback). If the diff matches, spawn `qa-engineer`. The qa-engineer reads the resolved qa.md for dev server config, trigger patterns, and accumulated knowledge. See the QA Gate section above for the full flow.
