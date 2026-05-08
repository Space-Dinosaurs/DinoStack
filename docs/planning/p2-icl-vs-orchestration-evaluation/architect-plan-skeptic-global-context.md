## Operator-confirmed Open Questions

- **Q-A (eval scenario descope)**: CLOSED via round-3 step 17 (sibling files scenarios-todo.md + cost-normalization-contract.md) and round-4 steps 17a/17b/18/19.
- **Q-B (multi-dim Step-0 enforcement on security-auditor / perf-analyst)**: RESOLVED 2026-05-04 - operator confirmed (B1) NO Step-0 enforcement; supplemental-context block, informational only.
- **Q-C (counter file form)**: RESOLVED 2026-05-04 - operator confirmed (C1) per-unit-slug file `.agentic/.spawn-block-counter-<unit_slug>`.

---

Got the round-3 plan. Note: file count - skeptic-protocol, subagent-protocol, agent-team, skeptic.md, security-auditor, perf-analyst, skeptic command, implement-ticket, wrap, init-project, brief, prune-harness, representation-audit, 02-delegation, 03-planning-artifacts, 05-qa-gate = 16 files (or 15 if I count differently). Skeptic finding says actual is 15, plan said 14. Let me count: 1) skeptic-protocol.md 2) skeptic.md (agent) 3) skeptic.md (command) 4) implement-ticket.md 5) 02-delegation.md 6) 03-planning-artifacts.md 7) 05-qa-gate.md 8) agent-team.md 9) subagent-protocol.md 10) wrap.md 11) init-project.md 12) brief.md 13) prune-harness.md 14) representation-audit.md 15) security-auditor.md 16) perf-analyst.md = 16 files. Skeptic says 15. Likely doesn't count agent files separately or counts something differently. I'll trust skeptic's number "15" in finding text. Recount: probably grouping security-auditor + perf-analyst as one row entry. Let me follow finding instruction "Fix to 15" exactly.

Now write the round-4 plan addressing:
- MAJOR: BOTH (a) Brief amendment spec + (b) conductor-handoff step
- MINOR #1: split Scenario 5 to a sibling file `cost-normalization-contract.md`
- MINOR #2: pick (i) - keep `n/a` marker as informational
- MINOR #3: 15 files

## Technical Plan: skeptic-global-context (round 4)

### Approach

Add a mandatory "Global-context input set" to every Skeptic spawn brief - both Skeptic-on-architect-plan and Skeptic-on-engineer-output (and the correctness-Skeptic in the multi-dim fan-out) - so reviewers receive the architect plan, `qa_criteria` block, per-consumer impact table, and related-files list on every spawn. The contract is enforced through a new Section 4.5 of `content/references/skeptic-protocol.md`, referenced verbatim by every Skeptic spawn site - exhaustively catalogued including the canonical multi-dimensional spawn-template DEFINITION at `content/references/subagent-protocol.md:265`. The "n/a" loophole is closed by an enumerated rationale set with Skeptic Step 0 BLOCKED enforcement. Descoped eval scenarios are concretely handed off to `eval-harness-v1` via TWO complementary mechanisms: (a) a Brief amendment row recording the inbound dependency durably, and (b) a conductor-handoff sub-step injecting the artifact paths into every `eval-harness-v1` spawn until that unit's engineer lands.

### Codebase context

The Skeptic protocol is centralized in `content/references/skeptic-protocol.md` (sections 0-14, sign-off in 11) and `content/agents/skeptic.md`. There is no shared template file the spawn sites import; every site constructs the spawn prompt as a runtime string. The `qa_criteria` block already exists on architect plans and Briefs for Elevated work (`content/agents/architect.md`, `content/sections/03-planning-artifacts.md`). The per-consumer impact table is mandatory on architect plans for shared-utility surfaces.

**Multi-dim spawn-template canonical definition (carried from round 3):** `content/references/subagent-protocol.md:265` defines the `multi-dimensional` skeptic_strategy. This is the DEFINITION site; `content/sections/02-delegation.md:145` is the INVOCATION site. Both are updated.

**Eval harness reality:** harness at `evals/auto/` is a Python component-loop. Eval is descoped from this unit; handoff via Brief amendment + conductor instruction + dedicated artifacts (see steps 17 and 18).

**Brief amendment precedent:** the just-landed Q-ROUTING/Q-NOISE Brief amendment on `feature/brief-amendment-q-routing-q-noise` is the template pattern - small targeted row addition / Constraint update, sub-bullet under the affected unit row, supersedes the prior wording.

**Manifest reality:** `content/commands/implement-ticket.md` and `content/sections/05-qa-gate.md` have NO manifest headers. Round 4 commits to populating new manifests on both files.

### Data model

No persistent schema changes. State-file additions (carried from round 3):

- `.agentic/loop-state.json` gains optional `architect_plan_path` and `brief_path` writes at planning-artifact-emit time so resume reconstructs the Global-context input set without re-discovery.
- `findings_log` schema unchanged.
- New tracker file: `.agentic/.spawn-block-counter-<unit_slug>` (per-spawn-target counter for Skeptic Step-0 BLOCKED returns; default form per Q-C default).

### API / interface design

**The Global-Context Input Set (canonical block, new Section 4.5 in `skeptic-protocol.md`):**

Every Skeptic spawn prompt MUST include this block in this order, after the adversarial brief and before the artifact-under-review:

```
## Global-context inputs

1. Architect plan: <absolute path to plan.md, OR "n/a - <enumerated reason>">
2. Brief / Plan tier artifact: <absolute path, OR "n/a - <enumerated reason>">
3. qa_criteria block (verbatim YAML, OR "n/a - <enumerated reason>")
4. Per-consumer impact table (verbatim, OR "n/a - <enumerated reason>")
5. Related files (list of absolute paths the diff touches OR is logically coupled to)
6. Diff under review: <git diff command OR file paths>
```

**Enumerated `n/a` rationale set (closes round-1 MAJOR #1).** A bare `n/a` is invalid. Only the following strings are valid `n/a` values:

- `n/a - Trivial direct edit`
- `n/a - permission-blocked carve-out`
- `n/a - Brief tier (per-consumer lives in architect plan path above)` (per-consumer table only, on Skeptic-on-Brief)
- `n/a - non-shared-utility surface (importer count below 5 threshold)` (per-consumer table only)
- `n/a - architect plan deferred to Plan-tier second pass` (Brief field only)
- `n/a - Skeptic-on-Brief (Brief is the artifact under review)` (Brief field only)
- `n/a - assembled Plan review (per-unit plans listed inline)` (architect plan field only, on Plan-tier second-pass)

Skeptic Step 0 BLOCKS on any string outside this enum. **Round-4 change (resolves MINOR #2 via option (i)):** the round-3 enum value `n/a - multi-dim supplemental reviewer` is REMOVED. Supplemental reviewers (`security-auditor`, `perf-analyst`) are NOT Step-0-enforced (steps 11 and 16); they receive the Global-context block as supplemental context with no `n/a` rationale required because there is no Step-0 gate to satisfy. The marker is unused; the enum stays tight to the Step-0 enforcement set.

**Skeptic Step 0 BLOCKED return semantics (carried from round 3):**

1. `last_phase_action` accepts new value `skeptic_blocked_input`. Resume re-spawns the Skeptic with corrected inputs; iteration counter does NOT advance.
2. Step-0 BLOCKED is conductor-fault, not engineer-fault. Does NOT count toward 3-fix-pass re-route cap. Consumes a separate counter capped at 3.
3. Iteration counter: maintained, neither reset nor advanced.
4. The CONDUCTOR fixes the spawn brief, NOT the Engineer.
5. **Counter file form:** default `.agentic/.spawn-block-counter-<unit_slug>` (single units use slug `single`).
6. **Counter file delete site:** `content/commands/implement-ticket.md` Phase 7 entry, immediately after Phase 6 loop terminates with sign-off. Cleanup glob: `rm -f .agentic/.spawn-block-counter-*`.

**Plan-tier second-pass overflow fallback (carried from round 3):** threshold 60K tokens; conductor switches to per-unit second-pass mode + lightweight integration Skeptic on findings only. Documented in `content/sections/03-planning-artifacts.md`.

**Skeptic agent file changes (`content/agents/skeptic.md`):** "Reading your spawn prompt" gains 4th item (Global-context input set, with instruction to Read the architect plan in full); new Step 0 (BLOCKED on incomplete inputs); Step 1 update; new Step 2.5 (verify Worker output complies with architect plan API/interface and `qa_criteria`); new Step 5.5 (per-consumer impact check).

**Supplemental-reviewer spawn-prompt shape (resolves MINOR #2).** For `security-auditor` and `perf-analyst` in the multi-dim fan-out, the spawn prompt has the shape:

```
<existing domain-specific brief - unchanged>

## Supplemental context (informational, NOT Step-0 enforced)

- Architect plan: <absolute path>
- Brief / Plan tier artifact: <absolute path or omitted>
- qa_criteria block: <verbatim YAML or omitted>
- Per-consumer impact table: <verbatim or omitted>
- Related files: <list>
- Diff under review: <as today>
```

Heading is `## Supplemental context` (not `## Global-context inputs`); fields may be omitted entirely (no `n/a` enum needed); Step 0 does NOT apply. This makes the contract for these two agents lexically distinct from the correctness-Skeptic Step-0 block.

### Implementation steps

1. **`content/references/skeptic-protocol.md`.** Add Section 4.5 "Global-context input set" between Section 4 and Section 5. Contents: canonical block format, enumerated `n/a` rationale set (round-3 enum minus the removed `multi-dim supplemental reviewer` value), Step-0 BLOCKED semantics, cross-reference paragraph in Section 7. **Update existing manifest.**

2. **`content/agents/skeptic.md`.** Add Steps 0, 1-update, 2.5, 5.5. Update "Reading your spawn prompt" to enumerate 7 items. **Update existing manifest.**

3. **`content/commands/skeptic.md`.** Replace Step 2 and Step 4 prompt templates with the 6-field Global-context input set.

4. **`content/commands/implement-ticket.md` Phase 6 Step 1 (line 879 region).** Replace "Spawn `skeptic` with adversarial brief" with "Spawn `skeptic` with the Global-context input set per `skeptic-protocol.md` Section 4.5". Add new sub-step 1a (BLOCKED-handling; counter file `.agentic/.spawn-block-counter-<unit_slug>`). Update resume table (line 185 region) to add `skeptic_blocked_input` row. **Add Phase 7 entry cleanup line:** `rm -f .agentic/.spawn-block-counter-*` immediately after Phase 6 loop terminates with sign-off, matching the existing `loop-state.json` `status: complete` transition pattern. **Add new manifest header.**

5. **`content/commands/implement-ticket.md` Phase 5 fan-out (lines 756, 758).** Per-unit and integration Skeptic spawns gain the Global-context input set.

6. **`content/commands/implement-ticket.md` Phase 6 calibration step (line 937).** Meta-Skeptic spawn brief gains the Global-context input set, matching original Skeptic.

7. **`content/sections/02-delegation.md`.** Edits:
   - Line 149 architect-plan Skeptic invocation: add Section 4.5 reference.
   - Line 145 region multi-dim INVOCATION: correctness-Skeptic gets Global-context per Section 4.5; supplemental reviewers get the supplemental block (no Step-0).
   - Line 133 permission-blocked fallback: add Global-context with `n/a - permission-blocked carve-out`.
   - Cross-session loop resume section: add `skeptic_blocked_input` enum.
   - **Update existing manifest.**

8. **`content/sections/03-planning-artifacts.md`.** Edits:
   - Line 185 Skeptic-on-Brief: add Global-context reference.
   - Line 190 Plan-tier second-pass: per-unit-fallback rule on overflow.
   - **Update existing manifest.**

9. **`content/sections/05-qa-gate.md`.** Line 17: "Skeptic receives the Global-context input set per `skeptic-protocol.md` Section 4.5". **Add new manifest header.**

10. **`content/references/agent-team.md` lines 186-192.** Update canonical Skeptic-on-architect-plan AND Skeptic-on-engineer-output spawn-input templates to enumerate the 6-field Global-context input set.

11. **`content/references/subagent-protocol.md:265`.** Update line 265 to instruct: "...the **correctness-Skeptic** receives the Global-context input set per `skeptic-protocol.md` Section 4.5 (Step-0 BLOCKED enforcement applies). The `security-auditor` and `perf-analyst` receive the Supplemental-context block defined in Section 4.5 (no Step-0 enforcement; informational only)."

12. **`content/commands/wrap.md` Skeptic spawn sites (lines 274, 290, 296, 427, 443).** Each gains the 6-field block. Architect plan / Brief paths typically `n/a - Trivial direct edit` or `n/a - permission-blocked carve-out`.

13. **`content/commands/init-project.md` Skeptic spawn sites (lines 225, 251, 354).** Each gains the 6-field block; architect-plan field is `n/a - Trivial direct edit`.

14. **`content/commands/brief.md` line 196 (Skeptic-on-architect-plan, operator-confirmed Brief variant).** Update invocation to construct the 6-field Global-context input set; architect plan field is the companion architect plan path; Brief field carries the operator-confirmed Brief path.

15. **`content/commands/prune-harness.md:116` and `content/commands/representation-audit.md:179`.** Per-candidate Skeptic invocations gain the 6-field block; architect-plan field `n/a - Trivial direct edit`; related-files is the single target file.

16. **Multi-dimensional reviewer agent files (`content/agents/security-auditor.md`, `content/agents/perf-analyst.md`).** Add a "Reading your spawn prompt" item enumerating Supplemental-context (no Step-0 BLOCKED enforcement; consistent with Q-B default and step 11 line-265 update). Spawn-prompt shape per the "Supplemental-reviewer spawn-prompt shape" subsection above. Manifest update only if file already carries a manifest.

17. **NEW - Eval handoff artifacts (resolves round-3 MAJOR; resolves MINOR #1 by splitting contracts).** Author TWO sibling files in `agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/` as deliverables of THIS unit, before its engineer spawns:

    **17a. `scenarios-todo.md` - Step-0 enforcement scenarios (single contract: Skeptic Step-0 verification).**
    - **Title:** "Descoped eval scenarios - Skeptic Step-0 enforcement; inbound dependency for `eval-harness-v1`."
    - **Scenario 1 - Skeptic Step-0 BLOCKED on incomplete prompt-structure.** Spawn a Skeptic with deliberately incomplete Global-context (e.g., omit `qa_criteria`); assert return is exactly `BLOCKED - Global-context input set incomplete: <missing fields>`. Assert no review content follows. Assert iteration counter unchanged in `loop-state.json`.
    - **Scenario 2 - Skeptic Step-0 BLOCKED on non-enum `n/a`.** Spawn with `architect_plan: n/a - I forgot`. Assert BLOCKED. Validates the enum gate.
    - **Scenario 3 - Conductor counter-and-escalate.** After 3 consecutive BLOCKED returns on same spawn target, assert conductor escalates (does not silently retry). Validates step 4 counter cap.
    - **Scenario 4 - Plan-tier overflow fallback fires above 60K tokens.** Construct synthetic Plan with combined Global-context > 60K tokens; assert conductor switches to per-unit + integration mode.
    - **Multi-dim correctness-Skeptic coverage:** scenarios 1-3 must also cover the multi-dim fan-out (correctness-Skeptic Step-0 enforcement; security-auditor and perf-analyst no Step-0; verify the Supplemental-context block fields shape).
    - **Cross-reference:** this artifact is one of two inbound dependency records for `eval-harness-v1`; companion is `cost-normalization-contract.md`.

    **17b. `cost-normalization-contract.md` - Report-format contract (single contract: token-cost normalization on `eval-harness-v1`'s output report).**
    - **Title:** "Descoped report-format contract - token-cost confounder normalization; inbound dependency for `eval-harness-v1`."
    - **Contract:** `eval-harness-v1`'s Stage 3 vs Stage 6 cost-comparison report MUST normalize the 3-5x post-restructure Skeptic input cost OR explicitly flag it as an interpretation confounder. The cost-ratio comparison is biased against the restructure even when the restructure is a protocol improvement, because pre-restructure Skeptics do not pay this input cost and post-restructure Skeptics do.
    - **Concrete report shape:** `evals/icl-vs-orchestration/results-v1.json` carries a `skeptic_input_cost_normalization: {applied: bool, method: string, baseline_tokens: int, post_restructure_tokens: int}` block.
    - **Acceptance:** if `applied: false`, the report's "limitations" section flags this confounder verbatim.
    - **Cross-reference:** this artifact is the second inbound dependency record for `eval-harness-v1`; companion is `scenarios-todo.md`.

    Splitting the two contracts (Step-0 enforcement vs report-format) makes each artifact single-purpose and lets `eval-harness-v1`'s architect consume them independently (the Step-0 enforcement scenarios may land before the cost-normalization report shape, or vice versa).

18. **NEW - Brief amendment SPEC (resolves MAJOR option (a)).** [ALREADY APPLIED 2026-05-04 via Brief amendment #2 commit 669d4ec on feature/brief-amendment-2-inbound-deps; the amendment is now part of brief.md lines 102-105. This step is preserved as historical record.] Author the diff for a small targeted Brief amendment to `agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/brief.md`. The conductor will spawn an engineer for this based on this spec; do NOT apply in this plan.

    **Diff target:** the unit-list table at lines 97-108. Locate the `eval-harness-v1` row (line 100).

    **Amendment shape (sub-bullet under the row, mirroring the just-landed Q-ROUTING/Q-NOISE pattern of supersession via documented sub-bullet):** add an "Inbound dependencies" sub-bullet directly below the table row, formatted identically to the Q-ROUTING/Q-NOISE Brief amendment (small, targeted, durable):

    ```
    | `eval-harness-v1` | Build the head-to-head eval ... | evals/ | Elevated | none (kickoff) |

    > **Inbound dependencies (added by `skeptic-global-context` round-4):** `eval-harness-v1`'s architect plan MUST consume the following artifacts as input and either implement the contracts they describe OR explicitly defer with rationale:
    > - `agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/scenarios-todo.md` - Skeptic Step-0 enforcement eval scenarios.
    > - `agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/cost-normalization-contract.md` - report-format contract for the Stage 3 vs Stage 6 cost-comparison normalization confounder.
    ```

    **Engineer instructions (for the conductor's downstream spawn):** the amendment is a single contiguous block-quote inserted immediately after the `eval-harness-v1` row, before the next table row. No other Brief content is modified. Brief Skeptic re-route is NOT required for this amendment - it follows the same operator-confirmed-style pattern as Q-ROUTING/Q-NOISE.

19. **NEW - Conductor-handoff instruction (resolves MAJOR option (b); discrete sub-step ride-along to step 17).** Add a CONDUCTOR-PROTOCOL instruction (this is an instruction to the main session, not to the engineer for this unit). The instruction is recorded as a discrete sub-step under step 17 in this plan AND surfaced verbatim in the final return summary so the conductor honors it across spawn boundaries:

    **Conductor protocol instruction (verbatim):**

    > Until the engineer for `eval-harness-v1` lands its diff (i.e., the unit's branch merges), every spawn brief for `eval-harness-v1`'s architect or engineer MUST inject the following two paths as `brief_path`-adjacent inputs in the Worker execution contract:
    >
    > - `agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/scenarios-todo.md`
    > - `agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/cost-normalization-contract.md`
    >
    > The injection takes the form of an additional `inbound_dependencies` field in the execution contract, listing both absolute paths. The Worker reads them before starting and treats their contents as binding inputs (per the Worker autonomy contract: deviation that ignores a binding input is a Skeptic finding, not a design-taste call).
    >
    > Once the `eval-harness-v1` engineer's diff lands, the Brief amendment row from step 18 becomes the durable record and this conductor-handoff instruction is retired. Until then, both mechanisms are live (belt-and-braces).

    **Rationale for both mechanisms.** Step 18 (Brief amendment) is the durable, auditable record that survives session exit and any architect re-spawn. Step 19 (conductor-handoff) is the immediate-action mechanism while `eval-harness-v1`'s plan is still being reworked AND covers the window between this round-4 plan landing and the Brief amendment engineer landing. Either alone has a gap; together they close the inbound-dependency hole that round-3 left as prose-only.

### Per-consumer impact table

This plan modifies `content/references/skeptic-protocol.md` and `content/references/subagent-protocol.md`, both shared-protocol files referenced across `content/`. Importer count well exceeds 5. Independent grep:

```
grep -rn -iE "(spawn(ing)?|Spawn the) *(a |an |the |fresh |independent |concurrent |parallel )?[Ss]keptic" content/
```

| `consumer_file:line` | `passes_relevant_arg?` | `uses_compensating_pattern?` | `current_behavior` | `new_behavior` |
|---|---|---|---|---|
| `content/agents/skeptic.md:15-19` | yes | no | 3 inputs | 7 inputs incl. Global-context block + Step 0 BLOCKED rule (step 2) |
| `content/commands/skeptic.md:39-50` Step 2 | yes | no | 4-field template | 6-field template per Section 4.5 (step 3) |
| `content/commands/implement-ticket.md:879` Phase 6 Step 1 | yes | no | brief + diff + iteration findings | + Global-context input set; new sub-step 1a BLOCKED-handler; Phase 7 counter cleanup (step 4) |
| `content/commands/implement-ticket.md:756` Phase 5 per-unit | yes | no | per-unit diff + brief | + per-unit Global-context input set (step 5) |
| `content/commands/implement-ticket.md:758` Phase 5 integration | yes | no | combined diff + brief | + combined Global-context spanning all unit plans (step 5) |
| `content/commands/implement-ticket.md:937` Phase 6 meta-Skeptic | yes | no | original diff + findings + sign-off + brief | + Global-context input set matching original (step 6) |
| `content/commands/implement-ticket.md:185` resume table | n/a - state | no | enum lacks `skeptic_blocked_input` | + new resume row (step 4) |
| `content/sections/02-delegation.md:149` architect-plan invocation | yes - prose | no | "spawn a Skeptic using ... brief" | + Global-context Section 4.5 reference (step 7) |
| `content/sections/02-delegation.md:145` multi-dim reviewers INVOCATION | yes - prose | no | conductor reads `skeptic_strategy` | correctness-Skeptic gets Global-context per Section 4.5; supplemental reviewers get Supplemental-context block (step 7) |
| `content/sections/02-delegation.md:133` permission-blocked fallback | yes - prose | no | "spawn a Skeptic on the applied diff" | + Global-context with `n/a - permission-blocked carve-out` (step 7) |
| `content/sections/02-delegation.md` cross-session loop resume | n/a - schema | no | enum lacks `skeptic_blocked_input` | + new enum value (step 7) |
| `content/sections/03-planning-artifacts.md:185` Skeptic-on-Brief | yes | no | Brief + adversarial brief; QA-criteria validation | + Global-context input set + companion architect-plan path (step 8) |
| `content/sections/03-planning-artifacts.md:190` Plan-tier second-pass | yes | no | assembled-Plan review brief | + Global-context input set + per-unit-fallback rule on overflow (step 8) |
| `content/sections/05-qa-gate.md:17` concurrent QA + Skeptic | yes | no | both receive diff + qa_criteria | Skeptic + Global-context; qa-engineer unchanged (step 9) |
| `content/references/agent-team.md:186-192` canonical Skeptic-on-architect AND Skeptic-on-engineer templates | yes - canonical | no | 3-field architect-review; 2-field engineer-review | both replaced with 6-field Global-context input set (step 10) |
| `content/references/subagent-protocol.md:265` multi-dim spawn-template DEFINITION | yes - canonical | no | "fans out a correctness-Skeptic, a security-auditor, and a perf-analyst" with no Global-context instruction | correctness-Skeptic gets Global-context per Section 4.5 with Step-0 enforcement; security-auditor / perf-analyst get Supplemental-context block, no Step-0 (step 11) |
| `content/commands/wrap.md:274` draft-Worker review | yes | no | draft + adversarial brief + scope-constraint | + Global-context block, `n/a - Trivial direct edit` (step 12) |
| `content/commands/wrap.md:290` re-route after Critical/Major | yes | no | revised draft + findings + brief | + Global-context block (step 12) |
| `content/commands/wrap.md:296` mandatory on-disk Skeptic | yes | no | on-disk files + adversarial brief | + Global-context block (step 12) |
| `content/commands/wrap.md:427` compression Worker Skeptic | yes | no | original + compressed draft + brief | + Global-context block (step 12) |
| `content/commands/wrap.md:443` compression re-route Skeptic | yes | no | revised compressed + findings | + Global-context block (step 12) |
| `content/commands/init-project.md:225` CLAUDE.md split Skeptic | yes | no | three artifacts + adversarial brief | + Global-context block, `n/a - Trivial direct edit` (step 13) |
| `content/commands/init-project.md:251` edit-iteration re-spawn | yes | no | revised three-way + nudge | + Global-context block (step 13) |
| `content/commands/init-project.md:354` AGENTS.md curation Skeptic | yes | no | AGENTS.md + adversarial brief | + Global-context block (step 13) |
| `content/commands/brief.md:196` Skeptic-on-architect-plan, operator-confirmed Brief variant | yes | no | Brief + operator-confirmed completeness-only brief | + Global-context block + companion architect-plan path (step 14) |
| `content/commands/prune-harness.md:116` per-candidate deletion | yes | no | single-file diff + brief | + Global-context block, single-file related-files (step 15) |
| `content/commands/representation-audit.md:179` per-candidate rewrite | yes | no | single-file rewrite diff + meaning-preservation brief | + Global-context block (step 15) |
| `content/agents/security-auditor.md` multi-dim supplemental | yes - supplemental | no | domain brief + scope | + Supplemental-context block (no Step-0 enforcement; round-4 lexically distinct from correctness-Skeptic block) (step 16) |
| `content/agents/perf-analyst.md` multi-dim supplemental | yes - supplemental | no | target + repro + budget | + Supplemental-context block (no Step-0 enforcement) (step 16) |

Total: 28 spawn-site rows across **15 distinct files** (round-3 erroneously stated 14; resolves MINOR #3). Files: `content/agents/skeptic.md`, `content/commands/skeptic.md`, `content/commands/implement-ticket.md`, `content/sections/02-delegation.md`, `content/sections/03-planning-artifacts.md`, `content/sections/05-qa-gate.md`, `content/references/agent-team.md`, `content/references/subagent-protocol.md`, `content/commands/wrap.md`, `content/commands/init-project.md`, `content/commands/brief.md`, `content/commands/prune-harness.md`, `content/commands/representation-audit.md`, `content/agents/security-auditor.md`, `content/agents/perf-analyst.md`. Spot-check: `grep -rn -iE "(spawn(ing)?|Spawn the) *(a |an |the |fresh |independent |concurrent |parallel )?[Ss]keptic" content/ | wc -l` returns ≥ 28.

**Manifest updates required:**
- `content/references/skeptic-protocol.md` (existing manifest, contract changes - update)
- `content/agents/skeptic.md` (existing manifest, contract changes - update)
- `content/sections/02-delegation.md` (existing manifest, contract changes - update)
- `content/sections/03-planning-artifacts.md` (existing manifest, contract changes - update)
- `content/commands/implement-ticket.md` (NO existing manifest - **add new** with all 6 fields)
- `content/sections/05-qa-gate.md` (NO existing manifest - **add new** with all 6 fields)
- `content/references/subagent-protocol.md` (verify before edit; if existing manifest, update; else no add - text-localized line-265 change)

### QA criteria

```yaml
qa_criteria:
  qa_skip: docs-only
  qa_skip_rationale: "Pure documentation/spec edits to content/ plus three new planning artifacts under docs/planning/. No runtime code in the diff. Eval-scenario verification handed off to eval-harness-v1 via scenarios-todo.md + cost-normalization-contract.md (step 17), Brief amendment spec (step 18), and conductor-handoff instruction (step 19). B4 verified by reading the spec."
  scenarios: []
  manual_smoke: "none"
```

Rationale: with the eval scenario descoped (steps 17/18/19 hand it to `eval-harness-v1` via concrete artifacts + Brief amendment + conductor instruction), the diff is exclusively `.md` edits under `content/` plus manifest updates plus the new planning artifacts. No runtime code added. B4 is a spec-read verification - exactly what `docs-only` covers. `eval-harness-v1` carries the executable verification per its own architect plan, with the two `scenarios-todo.md` + `cost-normalization-contract.md` files as binding inputs (recorded durably in the Brief amendment AND injected at spawn time by the conductor handoff).

### Trade-offs and constraints

**Alternatives considered:**
- *Inline all global-context content verbatim into every spawn prompt.* Rejected: per-spawn cost 5-10x; architect plans alone are 400-1200 lines.
- *Pass only paths; let the Skeptic Read each file lazily.* Rejected as sole strategy: Skeptic that does not Read the architect plan loses verification-surface check. Hybrid wins.
- *Make Global-context optional - "include where useful".* Rejected: optional context is the same as no context for failure-mode purposes.
- *Keep eval scenario in this unit by extending the Python harness inline.* Rejected: harness extension is `eval-harness-v1`'s scope.
- *MAJOR handoff: Brief amendment alone vs conductor-handoff alone vs both.* Picked BOTH per round-3 Skeptic recommendation. Brief amendment is the durable record; conductor-handoff is the immediate-action mechanism while `eval-harness-v1`'s plan is being reworked. Either alone has a gap; together they close it.
- *MINOR #1 Scenario 5 placement: subsection in `scenarios-todo.md` vs sibling file `cost-normalization-contract.md`.* Picked sibling file. Each artifact carries one contract, single-purpose; `eval-harness-v1`'s architect can consume them independently and on different timelines.
- *MINOR #2 supplemental-reviewer enum: keep `n/a - multi-dim supplemental reviewer` as informational vs remove.* Picked remove (option (i) was the round-3 plan but stale; option (ii) is round-4 outcome): supplemental reviewers receive a lexically distinct `## Supplemental context` block - no `n/a` rationale required because there is no Step-0 gate to satisfy. Enum stays tight to the Step-0 enforcement set.
- *Round-2 MINOR per-unit-slug counter form vs single-file with internal map.* Picked per-unit-slug files - matches existing `.agentic/` per-task scoping pattern. Q-C remains an Open Question for operator override.

**Token-cost trade-off per Skeptic spawn:** ~3000-10000 additional input tokens. At 2-4 spawns per Elevated unit, 3-5x input cost. Justification per Brief: verification-surface preservation.

**Stage 3 vs Stage 6 token-cost confounder (resolves round-2 MINOR token-cost; round-4 split into dedicated artifact):** the 3-5x post-restructure Skeptic input cost is now a CONCRETE CONTRACT against `eval-harness-v1` via `cost-normalization-contract.md` (step 17b). The cost-comparison report MUST normalize for this OR explicitly flag it in `evals/icl-vs-orchestration/results-v1.json` `skeptic_input_cost_normalization` block.

**Plan-tier second-pass overflow:** mitigated by per-unit fallback rule in Section 4.5. Threshold 60K tokens.

**Known limitations:**
- Fan-out per-unit/integration paths construct briefs slightly differently; `eval-harness-v1` scenarios must cover both branches.
- Meta-Skeptic now sees same context as original; detects rubber-stamping/skill drift, not context-completeness drift.
- The `n/a` enum is finite; additions are Section 4.5 amendments, not backdoors.
- Belt-and-braces handoff (Brief amendment + conductor instruction) introduces a small redundancy: the conductor instruction is retired once the Brief amendment lands and `eval-harness-v1`'s engineer consumes it. The retirement step is not automated; it relies on the conductor noticing the durable record is now in place. Accepted as low-cost.
- The Supplemental-context heading vs Global-context heading distinction must hold across all spawn-template documentation; if a future variant introduces a third class of reviewer, Section 4.5 will need a third heading or an explicit collapse rule.

### Open questions

Q-A from round 2 is CLOSED (resolved by steps 17/18/19 - dedicated `scenarios-todo.md` + `cost-normalization-contract.md` artifacts authored as deliverables, Brief amendment spec'd, conductor-handoff instruction issued).

Remaining operator-blocking:

> [SUPERSEDED 2026-05-04 - see "Operator-confirmed Open Questions" header at top of file. Q-A is CLOSED via steps 17/18/19; Q-B is RESOLVED to (B1) no Step-0 enforcement; Q-C is RESOLVED to (C1) per-unit-slug counter file. The text below is preserved verbatim from the round-4 architect plan as historical record; do not act on these sections as if these questions are open.]

**Q-B. Should the multi-dimensional reviewers (`security-auditor`, `perf-analyst`) ALSO Step-0 BLOCK on missing Global-context inputs?** Current plan: no (steps 11, 16 - Supplemental-context block, no enforcement). Operator decides:
- (B1) No Step-0 enforcement (current plan default; informational supplemental block).
- (B2) Step-0 enforcement extended to `security-auditor` and `perf-analyst`.

Default recommendation: B1.

**Q-C. `.agentic/.spawn-block-counter-<unit_slug>` per-unit scoping under fan-out.** Current plan default: per-spawn-target file (one counter file per `unit_slug`). Operator may override:
- (C1) Per-spawn-target file: `.agentic/.spawn-block-counter-<unit_slug>` (current default).
- (C2) Single file `.agentic/.spawn-block-counter` with internal JSON `{unit_slug: count}` map.

Default recommendation: C1.

(Q-B and Q-C touch contract surfaces; operator should ratify before engineer spawn.)

---

**Files of relevance (absolute paths):**
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/references/skeptic-protocol.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/references/subagent-protocol.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/references/agent-team.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/agents/skeptic.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/agents/security-auditor.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/agents/perf-analyst.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/commands/skeptic.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/commands/implement-ticket.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/commands/wrap.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/commands/init-project.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/commands/brief.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/commands/prune-harness.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/commands/representation-audit.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/sections/02-delegation.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/sections/03-planning-artifacts.md`
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/sections/05-qa-gate.md`
- New artifact (step 17a): `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/scenarios-todo.md`
- New artifact (step 17b): `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/cost-normalization-contract.md`
- Brief amendment target (step 18): `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/brief.md`