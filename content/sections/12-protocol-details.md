## Protocol Details (read on trigger)

Dispatch index (navigation, not rules). Shorthand: `REF` = `~/DinoStack/.claude/skills/agentic-engineering/references/`; `CR` = `content/references/`; `CS` = `content/sections/`.

| Trigger | Read | Sections |
|---|---|---|
| Activation preflight resolves to active (Step 4) | `CR/activation-detail.md` | §Step 5: First-Activation Notice, §Step 6: Scaffolding-Sync Check |
| Authoring Brief/Plan after planner returns 2+ Elevated-or-above units | `CS/03-planning-artifacts.md`; `CR/planning-artifacts.md` | Trigger table, ordering, gate semantics; templates, promotion mechanics, product-intent layer, `qa_default_skip` |
| Worker autonomy, stop-frequency, investigator-before-architect, delegation-enforcement | `CR/delegation-detail.md` | Worker Autonomy Contract, Stop-Frequency as Planning Signal, Investigator-Before-Architect Rules, Learnings Pipeline, Worker Preamble and Execution Contract Template, Digest-Return Discipline, Background-Spawn Enforcement Detail, Ticket-Offer Gate Mechanics, Proactive Autonomy Enforcement, Anti-Patterns (worked examples), Hard-Stop Branch - Executing vs Choosing, AskUserQuestion Precondition Detail, Evidence Verification, Orchestration Enforcement Hooks and Fan-out Detail |
| Config toggles, graph-derived risk signal, tier declaration | `CR/risk-config-and-tiers.md` | Config Toggle Catalog (behavioral), Graph-derived risk signal, Tier Declaration Detail |
| Elevated risk declared | `/skeptic`; `REF/skeptic-protocol.md`; `/implement-ticket` Phase 6 | Sections 2-5 (loop steps, state, re-route, escalation); findings_log schema, re-raise/auto-close rules |
| Reviewing Skeptic output | `REF/skeptic-protocol.md` | Sections 6, 11 (Critical/Major/Minor, sign-off format, validation) |
| Declaring Elevated + Cleanup | `REF/skeptic-protocol.md` | Section 12 (`/simplify` workflow, second Skeptic narrow-scope review) |
| Writing the brief for a Skeptic | `/skeptic`; `REF/skeptic-protocol.md` | Section 8 (domain-specific templates) |
| Decomposing work into multiple agents | `REF/subagent-protocol.md` | Sections 2, 5, 7 (parallel-by-default, worktree isolation, check-in) |
| Breaking work into multiple Workers | `REF/subagent-protocol.md`; `REF/skeptic-protocol.md` | Section 6 (decomposition rules); Section 9 (review scope) |
| Agent selection and composition | `REF/agent-team.md` | Flows (feature, bug, security), decision rules, spawn prompts |
| Worker fixes a Critical/Major Skeptic finding | `REF/regression-test-obligation.md` | Valid regression test, Worker obligation, Skeptic verification rule |
| Worker fixes a qa-engineer FAIL | `REF/qa-regression-obligation.md` | Regression-test obligation, `.agentic/qa-regressions.md` exception path, Skeptic verification rule |
| Change alters a count/list/path/convention/behavior in an intent-layer doc | `REF/doc-sync-obligation.md` | Trigger predicate, exemptions, Worker obligation, tiered Skeptic verification |
| Before every Agent spawn | `CS/06-capability-preflight.md`; `CR/capability-preflight.md` | Preflight timing, advisory/blocking, no-op rule; YAML schema, `required_when` grammar, `auto_install` rules, 7-step, output format, cache schema |
| Skeptic sign-off granted on a UI-visible change | `CS/05-qa-gate.md`; `CR/qa-gate.md` | Concurrent/sequential flow, qa_skip enums, preflight, INCONCLUSIVE; fan-out commands, architect-plan scenarios, dev-server boot |
| V1 telemetry event-type field shapes needed | `CR/events-log.md`; `CS/09-events-log.md` | `spawn_start`, `spawn_complete`, `meta_review_complete`, `session_total`, `tool_failure_workaround` schemas; writer scope, base schema (`conductor_direct` deprecated) |
| Cleanup command blocks, session-start prune script needed | `CR/worktree-lifecycle.md`; `CS/11-worktree-lifecycle.md` | Bash command blocks; isolation mandate, two-class summary, prune rule |
| `/implement-ticket` loop state must be resumed | `CR/cross-session-loop-resume.md` | §Cross-session loop resume (disk-write discipline, resumable phases, Brief/Plan path recording, batch-state coexistence) |
| Managing multi-unit plan orchestration state | `CR/task-state-file.md` | §Task-state file (schema, orphan detection, merge algorithm, `author_model`) |
| Implementing or modifying code in a specific language | `CR/code-standards-detail.md` | §Per-Language Strict Defaults (TS/JS/Python/Go/Rust/Next.js), §Browser Verification (`agent-browser`) |
| Intent layer, context economy, external comment rules | `CR/conventions-detail.md` | §The Intent Layer, §Context Economy, §External Comment Discipline |
| Writing a learning entry at a mandatory trigger | `CR/capture-classification.md`; `CR/conductor-operating-rules.md` | Guardrail-first precedence, MUST/SHOULD/SKIP table, declaration format; §learnings-agent (triggers, `Capture:` block ownership) |

Kept as prose (normative rules stated directly, not dispatch):

**Phase breadcrumb** - at every natural orchestration boundary (after agent spawn, agent return, escalation, task completion):
Emit `[phase: label]` inline in your status update to the user. Full vocabulary in `~/DinoStack/.claude/skills/agentic-engineering/references/subagent-protocol.md` Rule 6.

**Outcome rubric** - when authoring or reviewing a Brief for Elevated work:
Read `content/references/planning-artifacts.md` for the line schema (`{id, line, verification_type: deterministic | judgment}`), field guidance (distinct from Verification gate commands - the operator's semantic definition of done), and verification-gate `Rubric lines resolved` subsection. The rubric is co-authored via `product-discovery` step 5b (staged to `docs/overview/_proposed/outcome-rubric.md`) and confirmed before Brief authoring; `/brief` Section 3 copies the staged draft or elicits rubric lines inline. The independent Skeptic grades judgment lines adversarially (step 3.5 in `content/agents/skeptic.md`); absence on Elevated is a Critical finding.

**Trigger catalog and open-goal loops** - when setting up an action-triggered workflow or declaring a measured goal condition rather than a fixed unit list:
Read `content/references/trigger-catalog.md` for the three trigger types (manual / scheduled / action-triggered), the open-goal loop contract (trigger / action / measured condition / hard-stop), and the yolo-guard: a trigger fires the conductor (never a worker-spawn bypass), and risk classification plus a fresh Skeptic apply on every iteration regardless of how the loop was started.
