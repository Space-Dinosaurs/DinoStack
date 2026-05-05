# Brief: ICL vs Orchestration Evaluation and Protocol Slimming

**Status:** Draft, awaiting Skeptic review
**Priority:** P2 (strategic; not blocking current work)
**Tier:** Plan-tier (cross-cutting; spans architect, engineer, /implement-ticket, evals/, content/sections/)
**Author:** conductor (drafted from operator-driven analysis 2026-05-04)
**Trigger:** University of Melbourne paper "In-Context Prompting Obsoletes Agent Orchestration in Procedural Tasks" (April 30, 2026) - operator request to assess and respond.

---

## Problem

The protocol has grown in two opposing directions over the past month. Verification surfaces have hardened in ways the Melbourne paper validates: `qa_criteria` is mandatory on architect plans, `source-verified-acceptable` is forbidden, INCONCLUSIVE is a real terminal state, structured engineer returns replaced prose-scraping, per-consumer impact tables force whole-system reasoning at the architect stage. These are paper-aligned changes - they buy verification value with their token cost.

Routing surfaces have grown in parallel and the paper says they are likely net-negative for capable models. `/implement-ticket` is now 1,427 lines across 12+ phases. The engineer reads from 8+ document fragments stitched at spawn time (engineer.md + brief_path + plan_path + execution contract + qa_criteria + structured-return schema + regression-test rules + module manifest rules + HUD writes for fan-out). Each phase boundary and each fragment is a routing decision the paper measured at up to 18x failure rate against the same model running the whole flow holistically.

We do not know empirically which half wins on real software tickets. The protocol's core premise - that orchestration scaffolding improves outcomes vs the same model self-orchestrating with full context - is currently faith-based. The paper is a recipe to settle the question. We have not run it.

## Success criteria

- An internal head-to-head eval lives in `evals/` that compares an AE-orchestrated path against a full-context single-prompt baseline on a corpus of historical tickets, scored by Skeptic-equivalent rubric AND quality-gate pass rate AND token-cost-per-ticket. Reproducible by `bun evals/icl-vs-orchestration/run.ts` (or equivalent).
- `/implement-ticket` is restructured from 12+ named phases into 3 named stages (PLAN, EXECUTE, VERIFY) with no loss of verification gates. Line count drops by at least 40%. All current Critical/Major Skeptic-finding categories remain catchable; this is measured against the existing eval corpus, not asserted.
- A `loop-engineer` variant exists that receives the entire context (Brief + architect plan + per-consumer table + qa_criteria + verification gate + relevant files) in one prompt and runs the whole multi-step ticket end-to-end, returning at the verification boundary. Conductor intervenes only at PLAN/VERIFY transitions. The standard step-by-step engineer remains as fallback.
- Prompt assembly is canonical inside `content/` (one file, one assembled prompt per spawn) instead of being stitched at runtime by each adapter. Helios's `assemble-prompt.ts` pattern is the reference.
- Skeptic spawn briefs include the global picture (architect plan, qa_criteria, per-consumer table, related files), not just diff + brief snippet. Skeptic-on-architect-plan and Skeptic-on-engineer-output both updated.
- Eval corpus shows a clear winner per ticket class (Trivial / single-unit Elevated / multi-unit Brief / Plan-tier). The protocol routes based on measured wins, not on intuition.

## Non-goals

- Removing verification surfaces. `qa_criteria`, INCONCLUSIVE, structured returns, regression-test obligations, module manifests, per-consumer impact tables ALL stay. The Melbourne paper validates these; we are not cutting them.
- Removing the Skeptic loop. Verification value is the half of the protocol that earns its tokens.
- Removing risk classification or the Trivial/Low/Elevated taxonomy. The signals stay; what changes is what happens AFTER the classification.
- Touching adapter-specific code (Claude/Codex/Gemini/Kimi build scripts). All work targets `content/` and `evals/`; adapter regen is downstream.
- Reworking `/wrap` or `wrap-ticket`. They were just landed and serve a different purpose (learnings capture, not routing).
- Dropping or compressing telemetry surfaces under the banner of "stage simplification." `events.jsonl` writes, `loop-state.json` schema fields, fan-out HUD writes, `tasks.jsonl` schema, and `[phase: ...]` breadcrumbs are all preserved across the rename - only phase labels change. The restructure may rename the labels emitted but MUST NOT remove the emission sites or change the schemas.

## Constraints

- **Routing for content/** edits.** Methodology source-of-truth lives in content/**; edits to content/**, .codex/skill/**, build.sh scripts, and hooks/** route through `/update-agentic-engineering` (pre-commit hooks regenerate adapter outputs). Edits under `evals/**` and `docs/**` route via normal feature-branch + PR into `develop`.
- Eval corpus must use real historical tickets from a real codebase. Helios is the obvious source: it has a sufficient ticket history, an `.agentic/` state trail, and the inference layer (Z.AI GLM family) spans frontier and weaker models so the model-capability axis is testable.
- **Eval cost ceiling (hard).** Combined v1 eval run is capped at **$300 USD total LLM spend** OR **30M total tokens across all matrix cells**, whichever is reached first. The harness MUST emit a running cost tally and abort the run cleanly if either ceiling is hit; partial results are reported with the abort reason. Per-cell budget is derived: 2 corpora x 2 model tiers x 2 protocol conditions = 8 cells, ~$37/cell or ~3.75M tokens/cell. Within each cell, the per-ticket cap is 50 tickets but a smoke-test sub-corpus runs FIRST: 5 tickets per cell at the lowest-cost model tier, gating the full run. If the smoke pass shows one condition dominating by >2x in pass rate AND >2x in cost, the dominated condition is dropped from that cell before the full run; results are reported as "smoke-decided." This brings worst-case smoke spend to ~$15 and bounds the decision-to-commit window.
- Backwards compatibility for Briefs/Plans already in `docs/planning/` of consumer projects (Helios, agentic-factory). Phase rename must not orphan existing `loop-state.json` files mid-flight.
- Open Questions hard gate, re-route limits, INCONCLUSIVE classification, and the worktree isolation contract are all non-negotiable; the restructure preserves them.
- **Pre-work eval baseline (Stage 0).** Before any architect spawn on the units below, capture and commit current `evals/auto/` and `evals/components/` scores as `evals/baselines/2026-05-pre-icl-restructure.json`. This is the regression floor for verification criterion 2. Without this commit, "no regression" is unverifiable - so the baseline capture itself becomes the first work item, ahead of Stage 1.
- **Content/ freeze window.** Between Stage 0 baseline capture and Stage 6 comparison, no unrelated commits land in `content/`. If unrelated work must land, Stage 0 is re-run at the post-merge SHA and the new baseline replaces the prior one. Stage 3 (current-protocol baseline run) and Stage 6 (restructured-protocol comparison run) MUST share the same eval-harness SHA AND the same corpus selection; both SHAs are recorded in the eval report.

## Verification

**Two-gate sign-off.** This document is the BRIEF assembly entrypoint of a Plan-tier task. Brief sign-off (Skeptic on this file) authorizes ONLY architect spawns on the Stage-0/Stage-1 units (`evals-baseline-capture`, `eval-harness-v1`, `skeptic-global-context`). Engineer spawns on any unit are gated by the SECOND Skeptic pass on the assembled Plan directory (`risk-register.md`, `rollback.md`, `verification-gate.md` authored after Brief sign-off). The criteria below split into the two gates accordingly.

**Brief-tier verification (gates architect spawns on Stage-0/Stage-1 units):**

B1. The eval harness skeleton at `evals/icl-vs-orchestration/` runs end-to-end on a 1-ticket-per-cell smoke input and emits a JSON report with per-ticket-class win rates, quality-gate pass rates, and token-cost ratios. Verified by `bun evals/icl-vs-orchestration/run.ts --smoke` returning exit 0.

B2. **Stage 0 baseline committed.** `evals/baselines/2026-05-pre-icl-restructure.json` exists in the repo with current `evals/auto/` and `evals/components/` scores captured at a recorded git SHA. This is the regression floor for the engineer-tier criteria below.

B3. `loop-engineer` agent spec exists in `content/agents/loop-engineer.md` defining the full-context contract, structured return schema, and a single passing scenario in `evals/auto/`. Wiring into `/implement-ticket` is NOT in the Brief-tier scope - it lives under the Plan-tier gate (P3 below).

B4. Skeptic-on-architect-plan and Skeptic-on-engineer-output spawn templates in `content/agents/skeptic.md` (or equivalent) reference the global-picture inputs (architect plan + qa_criteria + per-consumer table + related files) explicitly. Verified by reading the spec.

B5. Prompt assembly canonicalization: a single `content/scripts/assemble-prompt.ts` (or `.md`-described convention) produces the engineer prompt; at minimum the Claude adapter `build.sh` consumes it. Remaining adapters (Codex, Gemini, Kimi) migrate under the Plan-tier gate.

B6. Migration note drafted at `docs/overview/icl-restructure-migration.md` describing the phase-rename compatibility window (default 30 days; finalized at Plan-tier gate).

**Plan-tier verification (gates engineer spawns; reviewed by second Skeptic pass on assembled Plan):**

P1. `/implement-ticket` line count is below 850 (40% reduction target from 1,427) AND `evals/baselines/2026-05-pre-icl-restructure.json` scores are matched or exceeded by the post-restructure run, where "matched" means no fixture shows a Wilcoxon signed-rank statistically significant decrease at alpha=0.05 against the recorded n>=3 baseline medians, and "exceeded" means at least one fixture shows a statistically significant increase by the same test. Stage 6 captures n>=3 runs per fixture (matches existing evals/auto/ convention).

P2. Stage 6 eval comparison report at `evals/icl-vs-orchestration/results-v1.json` exists, contains both Stage 3 baseline and Stage 6 restructured-protocol results, and declares a per-ticket-class winner (or "no significant difference" with a documented confidence interval). Both runs share the same harness SHA and corpus selection (recorded in the report).

P3. **Routing decision is a disjunction, not a circular gate.** EITHER (a) the eval shows loop-engineer wins on at least one ticket class AND `/implement-ticket` EXECUTE stage routes that class to loop-engineer by default, with the routing rule landed in `content/sections/` and exercised by an eval scenario; OR (b) the eval shows loop-engineer LOSES across all ticket classes AND that result is documented in `evals/icl-vs-orchestration/results-v1.json` AND `loop-engineer` is retained as a non-default variant with the routing decision deferred (or the unit is explicitly closed as "measured loss, no production routing"). Either branch satisfies P3; circular wiring is not required.

P4. Phase-rename compatibility shim is in place: `loop-state.json` resume hook accepts both old (`6`, `6b`, `7`, etc.) and new (`PLAN`, `EXECUTE`, `VERIFY`) phase identifiers for the documented window. Verified by an eval scenario at `evals/auto/scenarios/loop-state-resume-compat/` (deliverable owned by the `implement-ticket-restructure` unit; the architect plan for that unit MUST include scenario authoring as a step) that resumes a pre-restructure `loop-state.json` against the new code path.

P5. Telemetry preservation: `events.jsonl` event types, `loop-state.json` field set, fan-out HUD schema, and `tasks.jsonl` schema match the pre-restructure schemas at the field level. Phase-label values may change; field names and emission sites do not. Verified by snapshot test or manual diff against the Stage 0 baseline schema.

P6. Adapter migration of the canonical prompt builder is complete across all four supported adapters: Claude (covered in B5 Brief-tier), Codex, Gemini, and Kimi each consume `content/scripts/assemble-prompt.ts` (or its declared convention) from their respective `build.sh`. Verified by reading each adapter's build script and confirming the runtime-stitching code paths are removed. The Cursor adapter is exempt per its different output structure (per `content/sections/` and `agentic-engineering/AGENTS.md`).

**Cannot specify** is not permitted on any line above. If a line becomes unverifiable during implementation, that is a planning gap and the operator escalates - do not silently move it to a future doc.

## Plan-tier units

Promotion to Plan tier (vs Brief tier) is justified by:
- 6+ Elevated-or-above units (counted below)
- Cross-track surface (touches `content/`, `evals/`, `content/scripts/`, multiple adapter outputs)
- Architecture decision constraining future choices (`loop-engineer` variant changes the engineer contract)

This Brief is the assembly entrypoint. The companion files in this Plan directory (to be authored on Skeptic sign-off) are:
- `architect-plan.md` - design output for each unit, produced by spawning architect on the units below
- `orchestration.jsonl` - planner output across the units
- `risk-register.md` - operational risks (in-flight session breakage, eval cost overrun, false-confidence on a too-small corpus)
- `rollback.md` - how to revert each unit independently if a downstream consumer breaks
- `verification-gate.md` - the gate template populated against the success criteria above

### Unit list (preliminary; architect+planner re-decompose before any engineer spawn)

| Slug | Description | Surface | Risk | Depends on |
|---|---|---|---|---|
| `evals-baseline-capture` | Capture and commit current `evals/auto/` + `evals/components/` scores to `evals/baselines/2026-05-pre-icl-restructure.json` at a recorded SHA. Stage 0 precondition for P1. | evals/baselines/ | Elevated | none (Stage 0) |
| `eval-harness-v1` | Build the head-to-head eval in `evals/icl-vs-orchestration/`: corpus loader, two-condition runner, scorer, JSON report, cost-tally + abort-on-ceiling. (see inbound-dependencies note below this row) | evals/ | Elevated | none (kickoff) |

> **Inbound dependencies (added by `skeptic-global-context` round-4):** `eval-harness-v1`'s architect plan MUST consume the following artifacts as input and either implement the contracts they describe OR explicitly defer with rationale:
> - `agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/scenarios-todo.md` - Skeptic Step-0 enforcement eval scenarios.
> - `agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/cost-normalization-contract.md` - report-format contract for the Stage 3 vs Stage 6 cost-comparison normalization confounder.

| Slug | Description | Surface | Risk | Depends on |
|---|---|---|---|---|
| `eval-corpus-curate` | Select 30-50 historical tickets per corpus (Helios, agentic-engineering self-tickets) with known-good outcomes AND a metadata-sufficiency filter (architect plan + qa_criteria + scenarios present). Document rejection rate. Tag by ticket class. | evals/ | Elevated | eval-harness-v1 |
| `icl-baseline-spec` | Author the concrete spec for the "ICL baseline" prompt: file-selection rule, context-budget cap, prompt-assembly order. Ambiguity here is the moving-target risk; this spec is the freeze. | evals/icl-vs-orchestration/ | Elevated | eval-harness-v1 |
| `loop-engineer-spec` | Author `content/agents/loop-engineer.md` with the full-context contract and structured return schema | content/agents/ | Elevated | architect plan signed off |
| `prompt-assembly-canonical` | Move stitched-at-runtime engineer prompt assembly into a single canonical builder under `content/scripts/` | content/scripts/, build scripts | Elevated | loop-engineer-spec |
| `implement-ticket-restructure` | Collapse 12+ phases to 3 stages (PLAN, EXECUTE, VERIFY); preserve all gates AND telemetry surfaces; emit migration note and compatibility shim | content/commands/, docs/overview/ | Elevated | loop-engineer-spec, prompt-assembly-canonical, Stage 3 baseline run completed |
| `skeptic-global-context` | Update Skeptic spawn templates to receive architect plan + qa_criteria + per-consumer table on every spawn | content/agents/, content/references/ | Elevated | none (parallel) |
| `planner-into-architect` | Move orchestration-planner output into the architect plan as a section; deprecate separate spawn | content/agents/ | Elevated | implement-ticket-restructure |
| `eval-routing-rules` | Bake measured eval winners into the protocol: per-ticket-class default routing (loop-engineer vs phased), OR record measured loss with no production routing per P3 disjunction | content/sections/, content/agents/ | Elevated | Stage 6 complete (transitively: eval-harness-v1, eval-corpus-curate, icl-baseline-spec, loop-engineer-spec, prompt-assembly-canonical, implement-ticket-restructure, planner-into-architect) |

10 Elevated units. Multi-track. Plan-tier confirmed.

### Sequencing

- **Stage 0 (precondition):** `evals-baseline-capture`. No work proceeds until the baseline file exists at a recorded SHA.
- **Stage 1 (parallel):** `eval-harness-v1`, `skeptic-global-context`. Independent.
- **Stage 2 (sequential after Stage 1):** `eval-corpus-curate`, `icl-baseline-spec`. Both depend on harness; can run in parallel with each other.
- **Stage 3 (sequential after Stage 2):** First v1 eval run AGAINST CURRENT PROTOCOL. Smoke pass first (5 tickets/cell, lowest-cost model tier). If smoke shows dominant signal per the cost-ceiling rule, drop dominated cells before full run. Records harness SHA, content/ SHA, and corpus selection in the report.
- **Stage 4 (parallel after Stage 3):** `loop-engineer-spec`, `prompt-assembly-canonical`.
- **Stage 5 (sequential after Stage 4):** `implement-ticket-restructure`, `planner-into-architect`.
- **Stage 6 (sequential after Stage 5):** Re-run the v1 eval against the restructured protocol with the SAME harness SHA, SAME corpus selection, and SAME ICL-baseline spec as Stage 3. Compare to Stage 3 baseline.
- **Stage 7:** `eval-routing-rules`. Bake the measured winners in (or record the measured loss per P3 branch b).

The order is deliberate: **measure first, change second, re-measure third.** Restructuring `/implement-ticket` before the baseline eval exists is the most expensive way to discover the change had no effect (or a negative one). The eval is the protocol's accountability mechanism for itself.

## Open questions

### Resolved (operator decisions; closed before Brief sign-off per Skeptic round 1)

**Q1 (RESOLVED 2026-05-04). Eval corpus source: BOTH Helios AND agentic-engineering self-tickets.** Helios provides application-level signal (real software work, frontier and weak models in routine use). The agentic-engineering self-tickets corpus provides protocol-level signal (does the restructure improve work the protocol itself does on itself?). Two corpus axes; reflected in the cost-cap derivation (8 matrix cells, $300/30M-token ceiling).

**Q2 (RESOLVED 2026-05-04). Model axis: BOTH frontier and weak.** Frontier = Claude Sonnet 4.5 (or current top-tier at run time, declared in report). Weak = GLM-4.7 (Helios-routine; cheap; representative of where scaffolding may genuinely earn its keep). 2-tier axis; reflected in the cost-cap derivation.

**Q4 (RESOLVED 2026-05-04). Scoring rubric.** Reuse the `evals/auto/` scorer interface (`{dim: {score: float}}`). Required dimensions: `correctness`, `scope-discipline`, `quality-gate-pass`, `regression-test-presence`, `verification-realism` (does INCONCLUSIVE fire when it should?), `prompt-coherence` (single coherent prompt vs stitched). The earlier "finding-category coverage" notion in success criterion 2 is dropped - it was unsupported by the existing scorer and would have been a separate evals project. The 6 dimensions above are sufficient and concrete.

**Q-ROUTING (RESOLVED 2026-05-04). Scope of `/update-agentic-engineering` routing constraint.** The original Constraints line "All changes routed through `/update-agentic-engineering`" was over-broad. `/update-agentic-engineering`'s documented scope is `content/**`, `.codex/skill/**`, the three `build.sh` scripts, and `hooks/**`/`.codex/hooks/**`; `evals/**` and `docs/**` are NOT in that scope. Resolution: scope the routing constraint explicitly to content/** (and the other in-scope methodology paths) only; `evals/**` and `docs/**` work routes via normal feature-branch + PR into `develop`. Supersedes the original blanket Constraints routing line.

**Q-NOISE (RESOLVED 2026-05-04). Verification P1 noise model.** The original P1 wording specified "no per-component score regression beyond a 5% noise band." Empirical data from `evals/results/skeptic.tsv` shows mean per-fixture stdev 0.186 / max 0.346 / median 0.173 on a [0,1] scale across n=15 fixtures with stdev>0; a 5% absolute band would mark essentially every fixture as regressed on a same-SHA re-run. Resolution: replace point-comparison-with-fixed-band with Wilcoxon signed-rank against recorded n>=3 medians per fixture, alpha=0.05. "Matched" becomes "no fixture's distribution shows a statistically significant decrease at alpha=0.05"; "exceeded" becomes "at least one fixture shows a statistically significant increase outside that test." Stage 6 captures n>=3 runs per fixture (matches existing `evals/auto/` convention). Supersedes the original P1 "5% noise band" wording.

### Deferred to architect spawns (do not block Brief sign-off)

Q3. **What counts as "the AE-orchestrated path" in the eval.** Recommended default: pin the AE-orchestrated condition to the git SHA at Stage 3 baseline run, and require Stage 6 to use the SAME harness SHA but the new content/ SHA. The "ICL baseline" prompt spec is the `icl-baseline-spec` unit (Stage 2) - that unit's architect plan is where this is concretely answered.

Q5. **Migration backward-compatibility window.** Recommended default: 30-day window where the `loop-state.json` resume hook accepts both old (`6`, `6b`, `7`, ...) and new (`PLAN`, `EXECUTE`, `VERIFY`) phase identifiers. Finalized at the architect spawn for `implement-ticket-restructure`; operator may shorten to 14 days or extend to 60 if consumer-project signal warrants.

Q3 and Q5 are design-taste calls answered inside their respective architect plans, not Brief-shaping decisions. The hard-gate carve-out applies only to these two. Q1, Q2, and Q4 are resolved above and are no longer Open Questions.

## Linked artifacts

- Trigger source: video https://youtu.be/bECA_S805As, paper "In-Context Prompting Obsoletes Agent Orchestration in Procedural Tasks", University of Melbourne, April 30, 2026.
- Research synthesis: `/Users/tyson/Documents/Research/agentic-frameworks/in-context-prompting-vs-orchestration.md` (operator's local research workspace).
- Operator analysis chain: conversation 2026-05-04 (this Brief is the synthesis target).
- Adjacent planning: `docs/planning/p2-self-improving-harness.md` (eval infrastructure conventions); `docs/planning/p2-planning-tiers.md` (Brief/Plan-tier semantics this doc uses); `docs/planning/implement-ticket-default-qa-and-wrap.md` (recent Phase 11b precedent).
- Methodology cross-refs: `content/sections/02-delegation.md`, `content/sections/03-planning-artifacts.md`, `content/sections/05-qa-gate.md`, `content/agents/architect.md`, `content/agents/engineer.md`, `content/commands/implement-ticket.md`.

---

## Next actions (for the operator)

1. Skeptic-on-Brief review of this revised document (round 2). Adversarial brief: "Document synthesis, architecture, and planning". Round 1 produced 5 Major findings; this revision addresses each. Round 2 is a re-review against the same brief.
2. On Brief Skeptic sign-off: spawn architect (`architect:default`, Tier 2) on the Stage-0/Stage-1 units in parallel: `evals-baseline-capture`, `eval-harness-v1`, `skeptic-global-context`. All three are foundational and independent. (Stage 0 must complete before any Plan-tier engineer spawn but does not block its own architect spawn.)
3. On each architect plan sign-off: orchestration-planner per unit, then engineer per unit. Conventional flow.
4. Author Plan-tier coverage docs (`risk-register.md`, `rollback.md`, `verification-gate.md`) as the Stage-1 architect plans return. Second Skeptic pass on the assembled Plan directory before any engineer spawn. P1-P5 above are the gate.
5. Q3 and Q5 resolve inside their respective architect plans (`icl-baseline-spec`, `implement-ticket-restructure`); they do not block Brief sign-off.
