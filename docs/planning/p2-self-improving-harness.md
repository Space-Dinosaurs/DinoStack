# P2 Self-Improving Harness - Design Plan

## Problem statement

agentic-engineering is a harness: a bundle of named agents (`content/agents/*.md`), commands (`content/commands/*.md`), and rules (`content/rules/*.md`) that shape how a coding agent does software work. Today, every change to that harness is hand-authored. There is no way to measure whether a given edit made the Skeptic sharper, the conductor's routing smarter, or `/init-project` more accurate - we rely on human review and anecdotal feel. This blocks two things:

1. **Regression detection.** When we edit `content/rules/agent-methodology.md` or rewrite an agent prompt, we have no way to confirm we did not silently degrade a behavior that was working. The Skeptic Protocol catches bad *implementation* commits; it does not catch bad *prompt* commits.
2. **Auto-improvement.** The "Karpathy loop" pattern (autoresearch, autoagent) demonstrates that a coding agent pointed at its own harness, given a scalar metric and a fixed time budget, can iterate past what humans produce by hand. This repo has the edit surface (`content/`) and the review machinery (`/wrap`, Skeptic Protocol) already. The gap is evaluation.

Without per-component evals, neither is possible. Whole-system evals alone are illegible: a single score cannot tell you which part of the pipeline moved. Component evals first, system-level second.

## Scope

**In scope:**
- Per-component eval harness for named agents, core commands, and the conductor's routing decisions
- Fixture repository strategy (seeded defects, fixture codebases, labeled ground truth)
- Scoring functions per component with rationale, including asymmetric-cost handling
- Nondeterminism handling (N-runs aggregation, TSV schema including run variance)
- Shared infrastructure: TSV ledger format, sandboxed runner (Docker for any component that executes code), fixture snapshots
- Sequencing: which components get evals first, and why
- Overfitting Rule (prose directive) applied from day one to human-driven edits informed by scores
- Background reference: the Karpathy loop / autoagent pattern and how it maps onto this repo

**Explicitly out of scope:**
- The auto-improvement loop itself (a `/auto-harness` command or `program.md` equivalent). That is a P3 follow-on once component evals exist. This document stops at evals.
- Whole-system end-to-end evals. A small regression suite is noted as a follow-on; it is not a primary optimization target and is not specified here.
- Cross-component interaction tests (skeptic-worker co-regression).
- Persistent auto-improvement infrastructure (cron, scheduled runs, CI integration).
- Any edits to `content/` driven by eval results. Evals measure; humans decide what to change, under the Overfitting Rule.

## Background: how autoresearch and autoagent actually work

The mechanics (verified from the two MIT-licensed repos as of 2026-04-18):

- **The orchestrator is the existing coding agent** (Claude Code, Codex). There is no custom harness binary. Each project ships a `program.md` - a plain-English LOOP FOREVER procedure - and points the coding agent at it.
- **Edit surface is narrow and explicit.** autoresearch edits exactly one file (`train.py`); `prepare.py` (data + `evaluate_bpb`) is locked. autoagent edits everything above a `FIXED ADAPTER BOUNDARY` comment in `agent.py` (~80 lines); the Docker/Harbor integration below is locked.
- **Keep/revert is git + scalar comparison.** Run on a dedicated branch. Commit per attempt. If the metric improves, advance; else `git reset`. Tiebreaker: "less code wins."
- **Metric is a grep from a log file.** autoresearch greps `val_bpb` from stdout. autoagent reads per-task `reward.txt` written by Docker-sandboxed test runs, aggregated to `passed / avg_score`.
- **Trace feedback is a TSV plus structured per-run trajectories.** autoresearch: 5-col TSV. autoagent: 7-col TSV plus ATIF v1.6 JSON (reasoning, tool calls, observations, tokens, cost) per task.
- **"Model empathy" is a hardcoded default and a prose directive.** MODEL = gpt-5 in autoagent's default, with a `program.md` rule not to change it. No automated matching.
- **Anti-gaming is a prompted rule, not a detector.** program.md contains an Overfitting Rule: "If this exact task disappeared, would this still be a worthwhile harness improvement?" The verifier layer is declared off-limits in prose.

The pattern we inherit: narrow edit surface, scalar metric, git-based keep/revert, TSV ledger plus structured traces, prompted anti-gaming guardrail. The rest is infrastructure choice.

## Proposed approach: component-first evals

Evaluate each named agent, each core command, and the conductor's routing decisions in isolation before attempting any system-level optimization. Each component gets:

1. **A fixture set** - seeded inputs with labeled ground truth, sampled to cover both known-failure categories (from `.claude/findings.md` and prior incidents) and easy cases
2. **A scoring function** - deterministic given a run transcript, produces a scalar (primary) plus a diagnostic breakdown (secondary), with asymmetric costs where appropriate
3. **A runner** - invokes the component in isolation against each fixture, captures the trace, writes the score, handles nondeterminism via N-run aggregation
4. **A TSV ledger** - one row per commit-under-eval, with columns including variance fields

### Sequencing-alternative note

Two viable orderings exist: (a) build shared infra first, then component evals (chosen below), or (b) build one component eval end-to-end with a throwaway runner, then generalize the infra from what emerged ("build one to throw away"). Option (b) is well-founded for eval harnesses and surfaces schema questions faster. We choose (a) anyway because the TSV schema, runner contract, and sandboxing design are answerable up front from autoagent's working example, and because Phase 2 (Skeptic) needs the runner to produce comparable traces across fixtures from day one. If Phase 1 exits with a TSV schema that Phase 2 immediately needs to change, treat that as a signal we got the ordering wrong and revisit.

### Component eval designs

#### Conductor / orchestration-planner (highest leverage)

The conductor is the primary decision-making surface in this repo: when to fan out vs. go sequential, when to tight-fix vs. re-enter the full loop, when a cap is reached, when to escalate. A prompt edit to `content/rules/agent-methodology.md` or `content/agents/orchestration-planner.md` can silently regress routing quality and no Worker / Skeptic eval would catch it.

- **Fixture set:** seeded task descriptions + observed state (e.g. "Skeptic returned 2 Major findings, Engineer previously attempted fix X, QA reports test failure Y") with ground-truth labels for the correct next routing decision (tight-fix, full-loop re-enter, escalate, proceed to next phase). 20-30 fixtures covering the canonical decision points in `agent-methodology.md` and the persistence-loop contract in `p0-persistence-loop.md`.
- **Primary scalar:** weighted accuracy with asymmetric cost - incorrectly-bypassing-Skeptic counts heavily against; incorrectly-escalating-early counts moderately; minor routing suboptimalities count lightly.
- **Diagnostic fields:** per-decision-class accuracy, cap-enforcement correctness, escalation-trigger precision/recall.
- **Why first (or tied-first):** highest leverage per edit. This eval should land alongside or immediately after Skeptic.

#### Skeptic

- **Fixture set:** seeded Worker outputs (diffs, change summaries) with human-labeled defects at Critical / Major / Minor. **Sampling strategy:** fixtures must include (a) defect patterns sampled from `.claude/findings.md` actual past Skeptic failures (missed findings, not just caught ones), (b) synthetic defects covering the canonical categories in `skeptic-protocol.md`, and (c) clean outputs as negative controls. Target distribution: 40% findings.md-derived, 40% synthetic-canonical, 20% clean.
- **Primary scalar:** asymmetric weighted score. Per severity: `score = TP_weight * TP - FN_weight * FN - FP_weight * FP`, with Critical weights dominating (FN_Critical >> FP_Critical, both >> Major weights). Initial weights to be calibrated against a human-reviewer baseline on a held-out set.
- **Diagnostic fields:** precision and recall per severity separately, false-positive rate on clean outputs, severity-classification confusion matrix.
- **Known limitation (documented, not resolved):** seeded defects select for patterns humans already recognize. This eval measures "getting better at the known failure surface" and will not surface entirely novel failure modes. Mitigation is continual refresh: every time a real Skeptic-missed defect is found in practice, it enters the fixture set. The eval's validity is directly proportional to how aggressively findings.md is mined.

#### `/init-project` (most reusable fixtures)

- **Fixture set:** 8-12 fixture repos spanning Node, Python, Go, mixed-stack, greenfield, with known correct scaffolds (signal set, expected files, forbidden files, expected AGENTS.md section topics).
- **Primary scalar:** structural match score - fraction of expected files created AND no unexpected files created, with asymmetric cost (missing a scaffold file > creating an extra one, since over-scaffolds are reversible by deletion but missing sections are silent gaps).
- **Diagnostic fields:** signal-detection accuracy, over-scaffold rate, under-scaffold rate, AGENTS.md content-quality rubric.
- **Why early:** fixture repos are reusable for Worker / Investigator / Debugger evals. Amortizes fixture-authoring cost.

#### `/wrap`

- **Fixture set:** seeded session transcripts with a known set of surprise moments, feedback-worthy corrections, and already-captured items (to test dedup).
- **Primary scalar:** memory-capture F1, with asymmetric weighting toward recall (missing a surprise moment is worse than duplicating a near-miss).
- **Diagnostic fields:** duplication rate, MEMORY.md line budget adherence, feedback-vs-project classification accuracy.

#### Worker (engineer)

- **Fixture set:** small implementation tasks against fixture repos with hidden test suites. Tasks span bug-fix, feature-add, refactor.
- **Primary scalar:** weighted task score per task, aggregated by mean. Per-task score: `1.0 if tests_pass AND diff_size_within_budget, 0.6 if tests_pass AND diff_size_over_budget, 0.0 if tests_fail`. Partial credit avoids a purely binary signal and distinguishes "correct but bloated" from "broken".
- **Diagnostic fields:** tests-pass-only rate, diff-size distribution, scope-creep rate (files touched outside task scope), tokens-per-task.
- **Sandboxing:** Docker-mandatory (see Shared infrastructure below). Worktree alone is insufficient.

#### Other named agents (investigator, debugger, architect, qa-engineer, etc.)

Each gets a fixture set matched to its job, authored incrementally after the first four evals prove the pattern. Debugger: fixture repos with planted bugs + failing tests, score = correct root cause. Investigator: questions with known-correct answers about a fixture codebase. Architect: design prompts with rubric-scored responses.

## Shared infrastructure

One-time build, reused across components:

### Isolation model

Isolation requirements vary by component. We commit to these explicit tiers:

- **Tier 1 - read-only prompt components** (Skeptic, conductor eval, Architect): git worktree is sufficient. These components do not execute code, do not shell out, and do not modify files. Network is still mocked or denied at the runner level.
- **Tier 2 - commands that write to the fixture** (/init-project, /wrap): git worktree plus a redirected `HOME` env var (`HOME=$PWD/.fake-home`) so writes to `~/.claude/` land in the worktree, not the real user home. MEMORY.md path overrides required.
- **Tier 3 - code-executing components** (Worker, Debugger, QA-engineer): **Docker mandatory**. Ephemeral container per run, no network egress by default (`--network=none` unless the fixture explicitly requires it), filesystem scoped to mounted fixture volume, token/cost cap enforced at the runner level, no inherited credentials, no recursive subagent spawning into the parent's tool grants.

The runner inspects the component's declared tier and refuses to execute if the isolation requested does not match the component's declaration. This prevents a future Tier-1 component from silently becoming Tier-3 without isolation changes.

### Nondeterminism handling

Every eval run of a component-on-fixture is repeated **N=3 times by default** (configurable per component). The TSV ledger records:

- `primary_score_median` - median of N runs (primary scalar)
- `primary_score_stdev` - standard deviation across N runs
- `n_runs` - N actually executed (may be less than requested if budget exceeded)
- `run_seeds` - seed / model-params used per run, for reproducibility

Cache key: `(component_content_hash, fixture_hash, runner_version, N)`. Increasing N invalidates the cache; decreasing does not. A single run is never the primary signal; a component version is compared to another version only when both have N>=3 runs.

### Other shared infrastructure

- **Fixture repo storage:** `evals/fixtures/` tracked in git, one subdirectory per fixture. Large fixtures via git-lfs or external storage if needed.
- **Runner:** a thin orchestration script that invokes the component via the existing agent-spawn mechanism, inside the component's declared isolation tier, captures the trace, runs N times, aggregates, writes the TSV row.
- **Trace format:** per-run JSON capturing agent input, tool calls, tool results, final output. A normalized subset of what `/wrap` already collects from subagents, augmented where `/wrap` captures only summaries and the eval needs step-level detail.
- **TSV ledger:** `evals/results/<component>.tsv`, append-only. Columns: `commit, component_content_hash, fixture_hash, primary_score_median, primary_score_stdev, n_runs, status, diagnostic_json, description`.

### Overfitting Rule (applies from day one)

A plain-English directive, stored at `evals/OVERFITTING-RULE.md` and referenced by every component-eval README:

> Any human edit to `content/` motivated wholly or partly by a TSV score must satisfy: "If this exact fixture disappeared, would this edit still be a worthwhile change to the harness?" If the answer is no, revert. Scores inform; they do not justify. Every such edit must note in the commit message which fixture(s) motivated it, so reviewers can apply this test.

This lands in P2 - not deferred to P3 - because P2 is exactly when humans first read scores and are tempted to nudge prompts. The rule is the mitigation for Risk "Overfitting to fixtures" below.

## Sequencing

1. **Phase 1 - Shared infra.** Runner contract, isolation tiers, TSV schema (including nondeterminism columns), fixture storage, trace normalizer, Overfitting Rule checked in. Deliverable: can invoke one named agent against one fixture at its declared isolation tier and get a row in a TSV with N=3 runs aggregated. **Exit criterion:** one real component eval (chosen: Skeptic-lite with 5 seeded fixtures) runs end-to-end through the infra.
2. **Phase 2 - Skeptic eval.** 30+ fixtures per the sampling strategy (findings.md-derived, synthetic-canonical, clean controls). Asymmetric scoring function calibrated. Deliverable: a populated TSV with >=10 rows across >=3 content/agents/skeptic.md variants, producing a deterministic ordering.
3. **Phase 3 - Conductor eval.** 20-30 routing fixtures per the decision points in agent-methodology.md.
4. **Phase 4 - `/init-project` eval.** 8-12 fixture repos + structural-match scoring.
5. **Phase 5 - `/wrap` eval.** Seeded transcripts + memory-capture scoring.
6. **Phase 6 - Worker eval.** Fixture tasks + Docker sandboxing.
7. **Phase 7+ - remaining named agents.** Long tail.

Phases 2-5 can parallelize once Phase 1 lands. Phase 6 gates on Docker sandboxing being production-ready.

## Mapping to autoresearch / autoagent

| autoagent concept | agentic-engineering equivalent |
|---|---|
| `program.md` LOOP FOREVER | Out of scope here. A `/auto-harness` command is the P3 follow-on once evals exist. |
| Edit surface above FIXED ADAPTER BOUNDARY (~80 lines of agent.py) | `content/agents/*.md` and `content/commands/*.md`; `content/rules/*.md` is borderline and treated as locked for any future auto-loop because it contains verifier-adjacent contracts (skeptic-protocol.md, agent-methodology.md). |
| Locked verifier layer (Harbor, tests/, reward.txt contract) | `evals/fixtures/`, `evals/scoring/*.py`, the runner, and `content/rules/skeptic-protocol.md` (because Skeptic fixture labels are written against it). |
| `run.log` grep for `val_bpb` | Component-specific scoring function output written to TSV. |
| ATIF v1.6 trajectory JSON | Normalized trace format capturing agent I/O and tool calls. `/wrap` output is a summary-level precursor; richer step-level capture needed for scoring. |
| 7-col TSV ledger | Per-component TSV with nondeterminism columns added (median, stdev, n_runs). |
| Overfitting Rule (program.md prose) | `evals/OVERFITTING-RULE.md`, applied from P2 to human edits. |

We are building the verifier layer. Auto-improvement is what that layer enables later.

## Open questions (non-blocking for Phase 1)

- **Who authors fixtures?** See revised estimate below.
- **Ground truth drift when protocol changes.** If skeptic-protocol.md changes what counts as Critical vs Major, existing fixture labels may become stale. Proposed mitigation: each fixture file records the protocol commit SHA it was labeled against; the runner warns if the current SHA differs and fixture labels have not been reviewed.
- **Trace capture fidelity.** Does `/wrap`'s summary-level capture suffice for Skeptic fixture scoring (probably yes - Skeptic input is already diff-level), or do we need full tool-call trajectories for Worker / Debugger? Decide in Phase 6 prep.
- **Cost budget per eval run.** Worker eval at N=3 runs per fixture * 10 fixtures * model cost is non-trivial. Target: under $5 per full Worker-eval pass. If it exceeds, reduce N or fixture count before reducing isolation.

### Resolved in this revision (moved from Open Questions)

- **Nondeterminism aggregation.** Resolved: N=3 default, median as primary, stdev as diagnostic, cache key includes N. Phase 1 TSV schema is specified accordingly.

## Fixture authoring: realistic estimates

The prior estimate (15-30 min/fixture, ~10 hours for 30 Skeptic fixtures) was significantly understated. Revised:

- **Skeptic fixture:** 45-90 min each. Includes authoring a realistic 20-200 LOC Worker diff (30-60 min), seeding the defect, writing the ground-truth label with severity rationale, dry-running the current Skeptic to confirm the fixture is actually discriminating (i.e. it's a defect the current version can plausibly miss). 30 fixtures: 22-45 hours.
- **Conductor fixture:** 30-60 min each. Seeded state is more structured and less code-heavy. 25 fixtures: 12-25 hours.
- **/init-project fixture repo:** 3-6 hours each. Authoring a minimal-but-realistic fixture repo plus the expected-scaffold ground truth plus signal-detection labels. 10 repos: 30-60 hours.
- **/wrap seeded transcript:** 1-2 hours each. 15 transcripts: 15-30 hours.
- **Worker fixture task with hidden tests:** 2-4 hours each. Test-authoring dominates. 10 tasks: 20-40 hours.
- **Protocol-change versioning:** ~5% ongoing overhead on the fixture corpus per protocol-rule change that touches labels.

Total Phase 2-6 fixture authoring: ~100-200 person-hours, not 10. This is a multi-person-month investment at typical part-time pace. Phase-by-phase delivery is the only viable model; boiling the ocean on fixtures upfront will stall the whole effort. Start each phase with a *small* fixture set (5-10 items) to prove the runner + scoring loop, then grow.

## Docs and slides

No changes to `docs/` in scope for this plan. Evals are internal infrastructure, not part of the public protocol narrative. The hub page `docs/agentic-engineering.html` and the slide decks describe the delivered protocol; they do not need to describe the measurement layer used to maintain it. If the P3 auto-improvement loop later lands and changes what users experience, that effort will own its own docs/slides update.

## Success criteria for this plan

The plan is done when:
- Phase 1 infra exists and is documented with a 10-line example of "how to add a new component eval."
- At least two components (Skeptic and Conductor) have a fixture set, a scoring function, and a populated TSV.
- **Measurable ordering:** given two committed versions of `content/agents/skeptic.md` (or `content/rules/agent-methodology.md` for the conductor eval), the TSV produces a deterministic ordering - A > B, A < B, or statistical tie with `|median_A - median_B| < stdev` - that a reviewer can cite without re-running the eval, and that two independent reviewers agree on.
- The Overfitting Rule (`evals/OVERFITTING-RULE.md`) is checked in and referenced from every component-eval README at Phase 1 exit.
- Every scoring function declares asymmetric costs explicitly with rationale, or declares symmetric costs and justifies why asymmetry is not needed.

## Risks

- **Fixture authoring drags.** Biggest risk per the revised estimates above. Mitigation: each phase ships with a small fixture set first (5-10 items) and grows incrementally; the runner and scoring function land before fixture corpus completion.
- **Evals measure the wrong thing.** The Skeptic eval specifically can only catch defect patterns humans already recognize. Mitigation: findings.md-derived sampling (40% of Skeptic corpus), and continual refresh as real missed defects surface.
- **Sandboxing gaps.** Enumerated by tier above. Mitigation: tier declarations enforced by the runner; Tier-3 components do not run without Docker.
- **Overfitting to fixtures by humans reading scores.** Mitigation: Overfitting Rule checked in at P2 Phase 1 exit, referenced from every eval README, enforced in commit messages.
- **Protocol drift invalidating fixture labels.** Mitigation: each fixture records the protocol commit SHA it was labeled against; runner warns on SHA mismatch; fixture-label-review burden explicit in the change-rules workflow.
- **Phase 1 TSV schema turns out wrong.** Mitigation: exit criterion requires running at least one real component eval through the infra before declaring Phase 1 done, surfacing schema gaps early.
