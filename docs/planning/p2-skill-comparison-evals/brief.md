# Brief: Skill-Comparison Evals (AE methodology + 6 named agents vs baseline)

## Problem

We have no measured evidence for two claims the AE methodology makes implicitly:
(a) the methodology, applied end-to-end, produces better engineering outcomes than a vanilla Claude session; and
(b) each of the 6 core named agents (engineer, architect, investigator, debugger, skeptic, qa-engineer) contributes positively to those outcomes when used in isolation. Without measurement, content/ edits are flying blind: we cannot tell whether a prompt change is a net win, and we cannot defend the methodology's existence to a skeptical reader. The existing `evals/components/` harness measures per-agent prompt correctness on synthetic fixtures, but it does not answer "does using this agent yield a better solution to a real software-engineering task than not using it?" That is a different eval class - outcome-driven, not behavior-driven.

## Success criteria

- A reproducible TSV ledger reports, per task and per condition, a binary held-out-test pass/fail plus diff-hygiene diagnostics, for one methodology-level pair (`baseline` vs `baseline+ae-rules-injected`) and six per-agent pairs (`baseline` vs `baseline+<agent>-direct`).
- A canary verification proves that the per-agent invocation path actually spawns the named agent via two-level Task with frontmatter intact (matches production), before any task-corpus runs are seeded for non-baseline cells.
- Aggregated medians and stdev (n>=3 per cell; n=5 on the methodology pair) are produced by a single `aggregate_benchmark`-style rollup that handles the 8-condition matrix in one pass, with per-condition delta-vs-baseline rather than only-pairwise.
- The Overfitting Rule applies: every content/ edit motivated by a score must cite the fixture and pass the counterfactual.
- All work runs in a worktree branched from `main`; PR documents the eval design and posts representative TSV rows.

## Non-goals

- Not building a generic SWE-bench leaderboard. Task corpus is small and curated.
- Not measuring conductor-level orchestration as its own dimension (that is the existing `agentic-engineering` skill eval's job in aggregate; per-agent isolation evals deliberately bypass orchestration).
- Not solving cost tracking (skill-creator has none; we inherit that gap and document it).
- Not measuring bit-identical production `/agentic-engineering` activation. The `ae-rules-injected` condition measures rules-text-in-system-prompt only. See "Measurement equivalence" for the explicit production-layer table.

## Constraints

- Two-level Task spawn is the only invocation path that preserves agent frontmatter (LEARNINGS.md:6-12). Per-agent conditions MUST route via Task, not via top-level `claude -p "follow <agent>"`.
- Slash commands / skills are NOT discoverable under `isolator.tier_2` HOME redirect (LEARNINGS.md:97-109). This forecloses any "stub skill at ~/.claude/skills/..." approach for per-agent conditions. See "Measurement equivalence" below for how the AE-rules-injected condition is loaded without HOME-redirected skill discovery.
- Tier 3 (Docker isolator) is `NotImplementedError`. SWE-bench-style execution requires it. Either build Tier 3 or descope task corpus to Tier-2-runnable shape.
- AE-rules payload injected into the methodology condition's system prompt must not bleed into per-agent or baseline conditions; each condition is invoked in a fresh session.
- `content_glob` is load-bearing for cache invalidation (LEARNINGS.md:75-80). The AE-rules content blob and any per-agent named-agent files are content-globbed.
- Scorer FP-penalty cap ~50% max_credit (LEARNINGS.md:14-19).
- Pre-commit secret-scanner triggers on sha256 substrings; fixture-hash uses semantic subset only.
- Overfitting Rule binds: see `evals/OVERFITTING-RULE.md`.
- Worktree workflow per root AGENTS.md.
- **Task corpus is frozen and committed to git BEFORE any run.** Selector identity: chosen by the implementing engineer agent (unit 3 owner) from SWE-bench-lite. Selection criteria (documented in `tasks/corpus.yaml` header): difficulty distribution 60% single-file-with-failing-test / 30% multi-file / 10% design-y; license-permissive; no GPU; no network required at fix time; fits in 1 GB container RAM; held-out pytest runs in <120s. No post-hoc additions or substitutions once a baseline cell has been run against the list. Corpus changes after first run require a new eval generation (new TSV path).
- **Cost ceiling per full matrix run:** USD 250 wall-clock-spend ceiling, 75 M tokens aggregate. Estimate basis: 8 conditions x 12 tasks x n=3 (n=5 on methodology pair) ~= 312 runs; ~150k tokens/run average baseline runs; the `ae-rules-injected` condition adds ~143k tokens of system-prompt-resident rules text per run (see "Measurement equivalence" payload-size note), raising those ~36 runs to ~290k tokens each (~5.5 M extra tokens total, ~3% of budget). Round up to 75 M aggregate ceiling and $250 wall-clock-spend. Enforced via the existing `evals/icl_vs_orchestration/cost_gate.py` `BudgetExceeded` exit-3 pattern. Runner halts and emits a partial report on breach.
- **Wall-clock ceiling per full matrix run:** 12 hours. Same halt-and-partial-report behavior on breach.

## Verification

- **Canary must pass first; halt on failure.** Before any other stub/wrapper authoring or any task-corpus seeding for non-baseline cells, run scenario 1 (canary stream-json inspection on `skeptic` via direct two-level Task spawn). If the canary fails, halt all downstream work and surface the fallback decision to the operator. Subsequent units do not start until the canary returns green.
- For every (task, condition) cell, n>=3 runs land in the TSV with status, score, and held-out-test result. The methodology pair (`baseline` vs `ae-rules-injected`) uses n=5.
- `aggregate_benchmark`-style rollup produces a single table with 8 conditions and 7 deltas-vs-baseline, with stdev per cell.
- Sensitivity check (LEARNINGS.md:62-65): baseline-vs-baseline runs on the methodology pair establish the noise envelope (stdev of n=5 identical-condition replicates); the baseline-vs-ae-rules-injected delta must exceed that envelope on >=60% of in-scope tasks, OR a plausible prompt edit on at least one agent must move >=60% of in-scope tasks outside the envelope. If neither holds, the eval cannot discriminate and is not done.
- **Held-out test leakage check:** the Tier 3 isolator's unit tests prove that an in-container process started during the fix phase cannot read the held-out test path (mount layout enforces ro + separate path; an in-container `cat` attempt must fail with ENOENT or EACCES). This test lives in the unit 2 diff.
- Worktree clean, PR opened against `main`, all docs (Brief, README, AGENTS.md, per-spec inline) present.
- **Production-layer disclosure in published report.** The README and the published comparison report MUST include the condition name `ae-rules-injected` (not `ae-skill`) and the production-layer table from "Measurement equivalence" verbatim, so readers cannot mistake the measurement for bit-identical production activation.

## QA criteria

```yaml
qa_criteria:
  qa_skip: null
  scenarios:
    - id: 1
      description: Canary stream-json inspection - direct two-level Task spawn of `skeptic` produces a transcript whose inner Task tool_use has subagent_type "skeptic" and whose inner system prompt includes the agent's frontmatter-declared tool list (Read/Grep/Glob/Task).
      method: runtime-required
      evidence: stream-json transcript saved under evals/skill-comparison/canary/; assertion script (in unit 4 diff) parses the transcript and exits 0 on match, non-zero on mismatch.
    - id: 2
      description: Sensitivity-check discrimination - baseline-vs-baseline n=5 replicates on the methodology pair establish a stdev envelope, and the baseline-vs-ae-rules-injected delta exceeds that envelope on >=60% of in-scope tasks (or, equivalently, a plausible prompt edit on at least one per-agent condition moves >=60% of tasks outside the envelope).
      method: runtime-required
      evidence: aggregate.py output TSV with envelope column and delta column; rollup check script exits 0 when discrimination threshold met.
    - id: 3
      description: Held-out test leakage isolator test - an in-container process started during the fix phase cannot read the held-out test path. Attempted read returns ENOENT or EACCES.
      method: runtime-required
      evidence: pytest test in evals/runner/tests/test_isolator_tier3.py (in unit 2 diff) that boots the container, attempts the read, asserts failure, and asserts the fix-phase rw mount and the held-out-test ro mount are at distinct paths.
    - id: 4
      description: Published report uses the `ae-rules-injected` condition label (not `ae-skill`) and contains the production-layer table verbatim from the Brief's Measurement equivalence section.
      method: api
      evidence: README at evals/skill-comparison/README.md grep-asserts the literal token `ae-rules-injected` is present and the literal token `ae-skill` is absent (outside of historical/changelog context); production-layer table is included.
  manual_smoke: After the first full matrix run completes, operator spot-checks one row per condition in the TSV to confirm status/score/held-out fields are populated and non-degenerate.
```

## Measurement equivalence

Conditions must share invocation shape so that observed deltas reflect agent or methodology effects, not wrapper-mechanism artifacts. The methodology cell is named `ae-rules-injected` (not `ae-skill`) to make the measurement boundary explicit: we inject AE rules text into the system prompt; we do NOT replicate the full production `/agentic-engineering` activation pipeline.

- **Per-agent cells (6 conditions):** `invoker.run_session(mode="agent", agent_name=<name>)` directly. No skill wrapper. No stub. This is a bare two-level Task spawn of the named agent against the task. (Recommendation C2-A from Skeptic review; resolves LEARNINGS.md:97-109 skill-discoverability constraint by removing skill discovery from the per-agent path entirely.)
- **AE-rules-injected cell (1 condition):** AE methodology content is injected inline into the conductor's system prompt at invocation time. `ae_rules_payload.py` reads `content/SKILL.md` plus `content/sections/*.md` plus `content/rules/*.md` plus `content/references/*.md` plus `content/commands/*.md`, concatenates in that order, and passes as the system prompt of the outer session. Ordering rationale: SKILL.md first (skill manifest / entry point), then sections (methodology core), then rules (code standards + conventions + module manifests), then references (on-demand protocol text), then commands (slash-command bodies). This avoids HOME-redirected skill discovery and gives a deterministic, content-globbed payload. Bare two-level Task spawns are then orchestrated by that conductor as the methodology directs.
- **Baseline cell (1 condition):** bare conductor session, no AE content injected, no per-agent target. The conductor decides invocation shape on its own.

### Production layers: what is exercised vs not

The `ae-rules-injected` condition is NOT bit-identical to production `/agentic-engineering` activation. Explicit per-layer disclosure:

- **Exercised:** Rules-text injection into the outer conductor's system prompt (concatenated SKILL.md + sections + rules + references + commands).
- **Exercised:** Named-agent invocation via two-level Task spawn, frontmatter intact (per the canary).
- **NOT exercised:** Activation preflight (`~/.claude/agentic-engineering.json` mode/profile/preset resolution; AGENTS.md marker scan).
- **NOT exercised:** MEMORY.md auto-injection at session start.
- **NOT exercised:** First-activation sentinel file (`.agentic/.activated`) and one-time notice.
- **NOT exercised:** Stop hook writes to `.agentic/context.md` between turns.
- **NOT exercised:** Per-command preflight re-checks at top of each slash-command body.
- **NOT exercised:** `.agentic/` runtime state files (events.jsonl, tasks.jsonl, loop-state.json) and any behavior conditioned on their presence.

Payload size note: SKILL.md (~4 KB) + sections (~107 KB) + rules (~21 KB) + references (~126 KB) + commands (~313 KB) = ~571 KB raw, ~143k tokens at ~4 chars/token. This is a substantial system prompt; the cost ceiling above accounts for ~36 `ae-rules-injected` runs at ~290k tokens each (~150k task tokens + ~143k system-prompt tokens), adding ~5.5 M tokens to the matrix budget. Reported alongside the score; the cost difference is part of what is being measured, not a confounder.

Why not stub skills: per LEARNINGS.md:97-109 the stub install path under HOME-redirected isolation is not discovered. Building stubs would either require disabling HOME redirection (breaking isolation) or proving discoverability under redirect (a separate research unit not worth the cost given the cleaner direct-invocation path).

Why not load AE skill via the skill-discovery mechanism for the methodology cell: same reason - HOME redirection forecloses it. Inline system-prompt injection is the only mechanism that works under the existing isolator without weakening isolation.

## Linked artifacts

- architect-plan: ./architect-plan.md
- orchestration: ./orchestration.jsonl (stub; to be filled by orchestration-planner)
- risk register: ./risk-register.md
- rollback: ./rollback.md
- verification gate: ./verification-gate.md

## Open Questions

None. All architectural choices are decided in `./architect-plan.md`; planner-level decomposition refinements (parallel batching, exact unit boundaries) are normal planner work, not architect Open Questions.
