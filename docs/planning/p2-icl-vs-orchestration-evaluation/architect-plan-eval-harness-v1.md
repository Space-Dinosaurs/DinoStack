## Operator-confirmed Open Questions

- **Q1 (AE-orchestrated execution mechanics)**: RESOLVED 2026-05-04 - operator confirmed (a) `single-shot` for v1.
- **Q2 (correctness scorer)**: RESOLVED 2026-05-04 - operator confirmed (b) `test-pass` with (a) AC-keyword fallback when test-extraction fails per ticket. This expands `eval-corpus-curate`'s scope (per-ticket test extraction is a deliverable of that unit).
- **Q3, Q4**: deferred per Brief.

---

Now writing the round-4 plan inline as text (this is an architect plan output, not a file write).

## Technical Plan: eval-harness-v1 (icl-vs-orchestration) - Round 4

### Approach

Build a standalone two-condition eval harness at `evals/icl-vs-orchestration/` that replays a corpus of historical tickets under two pluggable conditions (AE-orchestrated and ICL-baseline), scores results on the 6 Brief-Q4 dimensions via a pluggable scorer registry on a symmetric dim set with a defined floor, tracks running cost+token spend with per-cell sub-budget AND global ceiling, and emits a single JSON report shared by Stage 3 and Stage 6. Round-4 deltas: output-coherence formula is mathematically pinned to **binarized-per-type** counting (`score = 1 - distinct_fired_types / len(TAXONOMY)`, naturally bounded in [0, 1]); ICL `rationale_or_plan` extraction has a **v1 fallback rule** (entire `final_text` when no structured rationale section is identifiable) so the harness does not block on `icl-baseline-spec`; the COVERAGE.md is tightened to per-condition binding (`AE:scored / ICL:floored`); a one-line taxonomy-version pin constraint is documented under known limitations. Two prior CRITICAL design decisions remain escalated to Open Questions (Q1: AE execution mechanics; Q2: correctness scorer); no new Open Questions added (recommendation (a) on both Majors).

### Codebase context

What exists (carried forward from rounds 1-3; not re-read this round):
- `evals/runner/` (Python 3.11, stdlib + pyyaml). Component-eval pattern: per-component YAML manifest, dynamic-import scorer, shell-out to `claude -p` via `invoker.invoke_run()`, stream-json parsing via `normalizer.parse_stream_json`, git-worktree isolation via `isolator.py`. Tier 1/2/3 invocation profiles.
- `evals/scoring/<comp>_lite.py` per-scorer contract: `score(trace, fixture) -> {primary, status, diagnostic, scorer_version}`.
- `evals/auto/` is the karpathy auto-improvement harness; this unit does NOT route through it.
- `evals/LEARNINGS.md` and `evals/OVERFITTING-RULE.md` are mandatory engineer reads.
- `agentic-engineering/CLAUDE.md`: Python 3.11, stdlib + pyyaml, shell-out to Claude CLI.
- Brief amendment for Q-ROUTING/Q-NOISE landed: Wilcoxon for P1, content/**-only routing scope (informational only; this unit's contract surface unaffected).

What this unit reuses: `invoker.invoke_run`, `isolator` Tier-2 worktree pattern, `normalizer.parse_stream_json`, `loader.compute_component_content_hash` SHA idiom, scorer return-shape conventions.

What this unit adds: two-condition runner orchestration; multi-dimension symmetric scorer registry; cost-tally with global+per-cell budgets; smoke-mode + smoke-gate dominance check; corpus-loader format contract; ICL-baseline-spec consumer interface (with v1 fallback); AE-execution-mechanics contract surface; preflight gate for required binaries.

### Required input artifacts

The engineer reads these at implementation time:

- **`agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation/scenarios-todo.md`** (authored by `skeptic-global-context`'s engineer alongside this unit's rework). Provides Skeptic Step-0 enforcement scenarios that this harness must surface in its smoke fixtures, plus a **cost-confounder normalization contract** that this harness's `cost_gate.py` and `report.py` must implement. The engineer reads this file before scaffolding the smoke fixtures (step 16) and before finalizing the report schema (step 13). If the file is absent at engineer-spawn time, the engineer returns BLOCKED - this is a hard input dependency.
- `evals/LEARNINGS.md`, `evals/OVERFITTING-RULE.md`: mandatory pre-read.
- `agentic-engineering/docs/planning/p2-icl-vs-orchestration-evaluation.md`: governing Brief.

### Data model

No DB changes. On-disk artifacts only.

**Corpus directory (input; produced by `eval-corpus-curate`):** unchanged from round 3.

```
evals/icl-vs-orchestration/corpora/<corpus_name>/
  manifest.yaml
  tickets/<ticket_id>/
    ticket.yaml
    architect_plan.md
    brief.md                 # optional
    relevant_files/
    known_good/
      diff.patch
      commit_sha
      tests/
      acceptance_criteria.yaml
```

**Runtime state (gitignored under `.runtime/`):** unchanged from round 3.

```
.runtime/<run_id>/
  cost_tally.json
  ticket_results/<ticket_id>__<condition>.json
  abort.flag
  partial-report.json
```

**Final report:** `evals/icl-vs-orchestration/results/<run_id>/results-v1.json` (committed). Stage 3 and Stage 6 are separate run_ids written by the same harness SHA.

### API / interface design

Binding contracts. The engineer implements these signatures verbatim.

**1. Condition runner contract.** Unchanged from round 3.

```python
# conditions/base.py
class TicketInput(TypedDict):
    ticket_id: str
    ticket_yaml: dict
    ticket_dir: Path
    relevant_files_dir: Path
    architect_plan_path: Path
    brief_path: Path | None

class ConditionResult(TypedDict):
    ticket_id: str
    condition_id: str            # "ae-orchestrated" | "icl-baseline"
    status: str                  # "ok" | "timeout" | "error" | "aborted"
    final_text: str
    diff: str | None
    files_touched: list[str]
    tool_calls: list[dict]
    tokens: dict
    cost_usd: float
    wall_seconds: float
    raw_trace_path: Path
    invocation_meta: dict
    quality_gates: dict
    artifacts: dict              # ConditionArtifacts; see below

class Condition(Protocol):
    condition_id: str
    def prepare(self, ticket: TicketInput, workspace: Path) -> None: ...
    def run(self, ticket: TicketInput, workspace: Path,
            cost_gate: 'CostGate', timeout_seconds: int) -> ConditionResult: ...
```

**Artifact contract (round-3 carried forward; round-4 augments extraction rule for ICL).**

```python
class ConditionArtifacts(TypedDict, total=False):
    rationale_or_plan: str       # REQUIRED on every condition. AE -> architect plan text;
                                 # ICL -> structured rationale section if present, else entire final_text (v1 fallback).
    diff: str                    # REQUIRED on every condition (mirrors result.diff).
    commit_message: str          # OPTIONAL; AE only. Captured for trace inspection; NOT scored.
    architect_plan_path: Path    # OPTIONAL; AE only. Captured for trace inspection.
    rationale_extraction_method: str  # NEW round-4: "structured" | "fallback-full-text"; recorded for trace.
```

**ICL `rationale_or_plan` extraction rule (round-4, addresses Major #2).** Pin the v1 default explicitly:

> **v1 default:** the ICL adapter looks for a structured rationale section in `final_text` per the ICL spec's prompt-template contract (a delimited block such as `## Rationale\n...\n## Diff` or an analogous marker the spec defines). If a structured section is identifiable, use its body as `rationale_or_plan` and set `rationale_extraction_method = "structured"`. **If no structured section is identifiable**, use the entire `final_text` as `rationale_or_plan` and set `rationale_extraction_method = "fallback-full-text"`. This fallback is the v1 default and is a defensible "ICL produced its rationale somewhere in its output" reading. When `icl-baseline-spec` lands with a structured prompt-template contract, the rule is upgraded under the **P-prod-ICL** Plan-tier gate (existing) - the harness re-runs against the production spec and the report records `rationale_extraction_method` per-ticket so any v1->v2 drift is visible.

This rule removes the hidden coupling: the engineer can spawn before `icl-baseline-spec` lands; the harness produces v1 smoke fixtures using the fallback; the upgrade is gated downstream.

**2. AE-orchestrated condition spec.** Unchanged from round 3.

```yaml
spec_version: v1
content_sha: <40-hex>
implement_ticket_path: content/commands/implement-ticket.md
agent_paths: { architect: ..., engineer: ..., skeptic: ..., qa_engineer: ... }
execution_mode: <single-shot | sdk-multiturn | python-conductor-sim>   # Open Q1
invocation_mode: replay
max_turns: <int>               # required iff sdk-multiturn
phase_router_path: <path>      # required iff python-conductor-sim
```

**3. ICL-baseline condition spec.** Unchanged from round 3.

```python
class ICLSpec(TypedDict):
    spec_version: str
    file_selection_rule: str
    context_budget_tokens: int
    prompt_template_path: str
    model: str
    max_turns: int
    allowed_tools: list[str]

def load_spec(path: Path) -> ICLSpec: ...
def validate_spec(spec: ICLSpec) -> None: ...
def assemble_icl_prompt(spec: ICLSpec, ticket: TicketInput) -> str: ...
```

**4. Scorer registry.** Round-3 carried forward; round-4 changes output-coherence formula only.

```python
class DimensionScore(TypedDict):
    score: float
    diagnostic: dict
    scorer_version: str
    status: str                  # "scored" | "floored" | "not-applicable"

class TicketScore(TypedDict):
    ticket_id: str
    condition_id: str
    dimensions: dict[str, DimensionScore]
    primary: float               # weighted aggregate over identical dim set on both conditions
    primary_method: str          # "symmetric-fixed-dimset" (round-3 default; unchanged)
    status: str

DIMENSIONS = [
    "correctness",
    "scope-discipline",
    "quality-gate-pass",
    "regression-test-presence",
    "verification-realism",
    "output-coherence",
]
```

Aggregation rule: **identical dim set on both conditions, no cross-condition renormalization for the primary, defined floor (`status="floored"`, `score=0.0`) replaces N/A when one condition lacks the artifact.** `status="not-applicable"` is reserved for ticket-level absences that apply identically to both conditions (must be N/A on both or neither; invariant asserted per ticket; violation aborts the ticket with `status="invariant-violation"`).

**Per-dimension scorer details (round-4 changes only):**

- **`correctness.py`** (Open Q2 escalation; unchanged).
- **`scope-discipline.py`**: option (b) file-set inclusion check (unchanged).
- **`quality-gate-pass.py`**: reads `result.quality_gates`; symmetric N/A on tickets without runners (unchanged).
- **`regression-test-presence.py`**: greps `result.diff` for added test files; symmetric N/A (unchanged).
- **`verification-realism.py`**: `floored` (score=0.0) when no architect plan / no qa_criteria block; `floored` is the only fallback status; never `not-applicable` on this dim (unchanged from round 3).
- **`output-coherence.py` (round-4 changed per Major #1).** Round-3 left ambiguity between binarized-per-type and total-instance counting. Round-4 commits to **option (a) binarized-per-type:**

  ```
  TAXONOMY = [
      "file-mismatch",
      "symbol-mismatch",
      "op-mismatch",
      "scope-mismatch",
      "claimed-vs-actual-files-mismatch",
  ]
  # len(TAXONOMY) == 5

  count = number of distinct contradiction TYPES from TAXONOMY that fired
          at least once in the (rationale_or_plan, diff) pair.
          Range: [0, len(TAXONOMY)] == [0, 5].

  score = 1.0 - (count / len(TAXONOMY))
          Range: [0.0, 1.0] by construction; no clamp needed.
  ```

  **Definition (verbatim, binding):** "`count` is the number of distinct contradiction TYPES from `TAXONOMY` that fired at least once in the `(rationale_or_plan, diff)` pair; range `[0, len(TAXONOMY)]`; `score` is exactly `1.0 - count / len(TAXONOMY)`. Multiple instances of the same type contribute 1 to `count`, not N. The score is naturally bounded in `[0.0, 1.0]` and requires no clamp."

  Cleaner semantics than total-instance counting: no calibration constant to tune, naturally bounded, aligns with "did the proposing-rationale match the executed change" framing. Total-instance counts (unbounded) are still recorded in `diagnostic.contradictions: list[{type, plan_excerpt, diff_excerpt}]` for inspection, but they do NOT enter the score.

  `scorer_version = "fixed-common-pair-binarized-v1"`.

**5. Cost gate.** Unchanged from round 3.

```python
class CostGate:
    def __init__(self, run_dir: Path,
                 max_usd_global: float = 300.0,
                 max_tokens_global: int = 30_000_000,
                 max_usd_per_cell: float | None = None,
                 max_tokens_per_cell: int | None = None): ...
    def record(self, cell_id: str, ticket_id: str,
               tokens: dict, cost_usd: float) -> None: ...
    def check(self, cell_id: str) -> None: ...
    def remaining(self, cell_id: str | None = None) -> tuple[float, int]: ...

class BudgetExceeded(Exception):
    scope: str                   # "global" | "cell"
    cell_id: str | None
    totals: dict
```

The `cost-confounder normalization contract` from `scenarios-todo.md` is implemented inside `cost_gate.py` and surfaced in `report.py` per that file's instructions. Engineer reads `scenarios-todo.md` before finalizing those modules.

**6. CLI and resume.** Unchanged from round 3 (write-order: ticket_results -> tally; reconcile re-derives tally from ticket_results on resume).

```bash
python -m evals.icl_vs_orchestration.cli run \
    --corpus <name> --ae-spec <path> --icl-spec <path> \
    [--smoke] [--smoke-gate] [--max-tickets N] [--cells <whitelist>] \
    [--max-usd-per-cell <usd>] [--max-tokens-per-cell <tok>]

python -m evals.icl_vs_orchestration.cli resume <run_id>
```

**Preflight (round-3, carried forward).** `cli.py` and `run.ts` both check for `python3` and `bun` on PATH; exit 4 with documented one-line message on miss. Documented in `evals/icl-vs-orchestration/AGENTS.md` "Required binaries on PATH" section.

**7. Smoke fixtures and dimension coverage (round-4 changed per Minor #1).** Coverage matrix tightened to per-condition binding (`AE:<status> / ICL:<status>`) per fixture row, replacing the round-3 `floored-or-scored` shorthand:

| Fixture (class)        | correctness          | scope-disc           | qg-pass              | reg-test             | verif-real                | out-coh              |
|------------------------|----------------------|----------------------|----------------------|----------------------|---------------------------|----------------------|
| `s-trivial-typo`       | AE:scored / ICL:scored | AE:scored / ICL:scored | AE:scored / ICL:scored | N/A-both             | AE:scored / ICL:floored   | AE:scored / ICL:scored |
| `s-single-elev-bug`    | AE:scored / ICL:scored | AE:scored / ICL:scored | AE:scored / ICL:scored | AE:scored / ICL:scored | AE:scored / ICL:floored   | AE:scored / ICL:scored |
| `s-brief-tier-feature` | AE:scored / ICL:scored | AE:scored / ICL:scored | AE:scored / ICL:scored | AE:scored / ICL:scored | AE:scored / ICL:floored   | AE:scored / ICL:scored |
| `s-plan-tier-cross`    | AE:scored / ICL:scored | AE:scored / ICL:scored | AE:scored / ICL:scored | AE:scored / ICL:scored | AE:scored / ICL:floored   | AE:scored / ICL:scored |

Scenario 1's evidence asserts strict per-condition match against this binding (no "either-status-acceptable" cells). The smoke fixtures are constructed so the AE side genuinely produces a plan with qa_criteria (scored) and the ICL side genuinely does not (floored); deviation from the binding is a smoke-fixture defect or a scorer regression.

`COVERAGE.md` records the binding in the same per-condition format. Fixture-construction notes cite `scenarios-todo.md` for the Skeptic Step-0 enforcement scenarios that the smoke corpus must surface.

**8. Production-ICL-spec re-run validation (round-3, carried forward).** P-level Plan-tier criterion (P-prod-ICL): when `icl-baseline-spec` lands with a structured prompt-template contract, `bun evals/icl-vs-orchestration/run.ts --smoke --icl-spec specs/icl-baseline.yaml` returns exit 0; all 6 dimensions scored or floored per the coverage matrix; `rationale_extraction_method` flips from `fallback-full-text` to `structured` on the production spec; no crash on prompt-assembly seams. Gates the `icl-baseline-spec` unit's sign-off, not this unit's.

**9. JSON report schema.** Round-3 schema plus round-4 fields:
- `cells_dropped_by_per_cell_budget: list[str]`
- `correctness_method: "ac-keyword" | "test-pass" | "composite"` (Open Q2)
- `ae_execution_mode: "single-shot" | "sdk-multiturn" | "python-conductor-sim"` (Open Q1)
- `weights_renormalized_count: int`
- `floored_dim_count_per_condition: dict[str, dict[str, int]]`
- `output_coherence_method: "fixed-common-pair-binarized-v1"` (round-4: pinned binarized-per-type variant)
- `output_coherence_taxonomy_version: "v1"` (NEW round-4: surfaces the taxonomy version explicitly so cross-stage comparability is auditable)
- `rationale_extraction_method_count: dict[str, dict[str, int]]` (NEW round-4: per-condition count of `structured` vs `fallback-full-text` extractions; surfaces v1 fallback usage)
- Cost-confounder normalization fields per `scenarios-todo.md` contract (engineer implements per that file).

### Implementation steps

1. Directory scaffold: `__init__.py`, `AGENTS.md` (includes "Required binaries on PATH" section + "Required input artifacts" section pointing at `scenarios-todo.md`), `.gitignore`, `README.md`. AGENTS.md - new non-trivial module, manifest header **required** (six fields populated).
2. `schema.py` (validators for manifest/ticket/ae-spec/icl-spec). Stdlib + pyyaml. **Required, six fields populated.**
3. `corpus.py` (loader, corpus_sha). **Required, six fields populated.**
4. `cost_gate.py` (global + per-cell; cost-confounder normalization per `scenarios-todo.md`). **Required, six fields populated.**
5. `metering.py` (token/cost extraction reusing `evals/runner/normalizer.py`). **Required, six fields populated.**
6. `conditions/base.py` (Protocol + TypedDicts including `ConditionArtifacts` with `rationale_extraction_method`). **Required, six fields populated.**
7. `conditions/ae_orchestrated/` directory with `single_shot.py`, `sdk_multiturn.py`, `python_conductor_sim.py`. Only the operator-selected mode (Open Q1) implemented; others raise NotImplementedError. Each module **required, six fields populated.** Each adapter populates `ConditionArtifacts.rationale_or_plan` from architect plan text (`rationale_extraction_method = "structured"`), `diff` from the produced diff; commit message and architect-plan-path captured optionally for trace.
8. `conditions/icl_baseline.py` + `conditions/icl_spec.py`. ICL adapter implements the **v1 fallback extraction rule** (round-4 Major #2): try structured-section parse first, fall back to entire `final_text` on miss; record `rationale_extraction_method` accordingly. **Required, six fields populated.**
9. `scoring/correctness.py`, `scope_discipline.py`, `quality_gate_pass.py`, `regression_test_presence.py`, `verification_realism.py`, `output_coherence.py`. Each **required, six fields populated**. `correctness.py` implements only operator-selected option (Open Q2); others stub. `verification_realism.py` floors at 0.0 when no plan/qa_criteria. `output_coherence.py` implements the **binarized-per-type** scorer (round-4 Major #1): `score = 1 - distinct_fired_types / len(TAXONOMY)`; `scorer_version = "fixed-common-pair-binarized-v1"`; total-instance counts recorded in diagnostic but not in score.
10. `scoring/registry.py` + `scoring/weights.yaml`. **Required, six fields populated.** Weights sum-to-1.0 assertion at load. Symmetric-dimset invariant assertion per ticket.
11. `smoke_gate.py` (>2x dominance check). **Required, six fields populated.**
12. `runner.py` (orchestration loop; write-order: ticket_results -> tally; per-cell budget handling). **Required, six fields populated.**
13. `report.py` (assembles JSON; round-4 schema fields including `output_coherence_method`, `output_coherence_taxonomy_version`, `rationale_extraction_method_count`; cost-confounder normalization fields per `scenarios-todo.md`). **Required, six fields populated.**
14. `cli.py` (run + resume; preflight; reconcile algorithm). **Required, six fields populated.**
15. `run.ts` (bun wrapper). Includes preflight check (`Bun.which("python3")`); exits 4 on miss. Manifest header recommended (small wrapper, <50 LOC).
16. `corpora/smoke/` fixtures + `COVERAGE.md` (round-4 per-condition binding matrix; Skeptic Step-0 enforcement scenarios from `scenarios-todo.md` surfaced as required).
17. Stub `specs/ae-orchestrated.yaml` + `specs/icl-baseline.yaml`. Stubs minimal but VALID against schemas; ICL stub explicitly omits a structured rationale-section delimiter so the v1 fallback exercises in smoke.
18. `tests/` with: smoke end-to-end (asserts per-condition binding from COVERAGE.md); cost-gate unit tests (global breach, per-cell breach, atomic update crash recovery, write-order reconcile); scorer registry tests (incl. symmetric-dimset invariant violation); corpus loader tests; resume reconcile test; **output-coherence binarized-per-type test** (round-4): asserts `count` equals distinct-types-fired (e.g. 3 instances of `file-mismatch` -> count contributes 1, not 3); **output-coherence boundary test** (round-4, addresses Major #1): score is in `[0.0, 1.0]` for all paths including count=0 (score=1.0), count=len(TAXONOMY) (score=0.0), and count > len(TAXONOMY) is unreachable by construction (assert `count <= len(TAXONOMY)` in scorer); **AE-coherent + AE-mismatch + ICL-coherent + ICL-mismatch** four-fixture symmetry test (round-3 carried forward); **verification-realism floored test** (round-3 carried forward); **preflight test** (round-3 carried forward); **ICL fallback extraction test** (round-4): `final_text` lacking a structured rationale section yields `rationale_extraction_method = "fallback-full-text"` and `rationale_or_plan == final_text`; `final_text` with a structured section yields `rationale_extraction_method = "structured"` and `rationale_or_plan` equal to that section's body.
19. `abort.flag` write logic: only write when `cells_pending or tickets_in_flight`; else finalize normally with `budget_breached_at_finalization: true, aborted: false`.

**Per-consumer impact table.** This unit creates a new top-level directory; no existing importers. Round-4 verifies the round-3 mapping and adds the `scenarios-todo.md` input dependency:

| `consumer_unit:artifact` | `passes_relevant_arg?` | `uses_compensating_pattern?` | `current_behavior` | `new_behavior` |
|---|---|---|---|---|
| `eval-corpus-curate:corpora/<name>/{manifest.yaml,tickets/}` | yes (writes per `corpus.py` schema) | no | n/a | produces corpus matching schema |
| `icl-baseline-spec:specs/icl-baseline.yaml` + template | yes (writes per `ICLSpec`) | no | n/a | produces spec matching schema; v1 fallback bridges its absence |
| `skeptic-global-context:scenarios-todo.md` | reads (this unit's engineer reads at scaffold time) | no | n/a | provides Skeptic Step-0 enforcement scenarios + cost-confounder normalization contract |
| Stage 3 baseline run (CLI invocation) | yes (`--ae-spec` content_sha = pre-restructure HEAD) | no | n/a | writes Stage-3 report at `results/<run_id>/results-v1.json` |
| Stage 6 comparison run (CLI invocation) | yes (same harness SHA, same corpus, content_sha = post-restructure HEAD) | no | n/a | writes Stage-6 report |
| `eval-routing-rules:results-v1.json` | reads only | n/a | n/a | reads both Stage 3 and Stage 6 reports; owns `results-v1-comparison.json` |

### QA criteria

```yaml
qa_criteria:
  qa_skip: null
  qa_skip_rationale: null
  scenarios:
    - id: 1
      description: "`bun evals/icl-vs-orchestration/run.ts --smoke --corpus smoke --ae-spec specs/ae-orchestrated.yaml --icl-spec specs/icl-baseline.yaml` (and the equivalent python invocation) exits 0 and writes a JSON report at `results/<run_id>/results-v1.json` with all 4 ticket classes present and per-ticket per-condition `dimensions.<dim>.status` matching the per-condition binding in `corpora/smoke/COVERAGE.md` exactly (no either-status-acceptable cells; symmetric-dimset invariant holds)."
      method: runtime-required
      evidence: "Exit 0; report file exists; jq assertions on `summary.by_ticket_class` keys, per-ticket per-condition `dimensions.<dim>.status` strict-equal to coverage binding; symmetric-dimset invariant verified; `aborted: false`."
    - id: 2
      description: "Global cost gate aborts cleanly: `--smoke --max-usd 0.001` triggers `BudgetExceeded(scope='global')`, writes `abort.flag` (because in-flight work exists), finalizes partial report with `aborted: true`, exits 3."
      method: runtime-required
      evidence: "Exit 3; abort.flag present; partial report aborted=true; cost_tally totals exceed ceiling."
    - id: 3
      description: "Per-cell cost gate drops cell cleanly: `--smoke --max-usd-per-cell 0.0005` causes the breaching cell to drop, run continues with surviving cells, final report `cells_dropped_by_per_cell_budget` is non-empty, exit 0."
      method: runtime-required
      evidence: "Exit 0; report.cells_dropped_by_per_cell_budget contains the dropped cell_id; surviving cells have ticket entries."
    - id: 4
      description: "Scorer registry rejects malformed weights: weights summing != 1.0 causes registry import to raise AssertionError."
      method: api
      evidence: "pytest passes."
    - id: 5
      description: "Corpus loader rejects ticket missing required metadata."
      method: api
      evidence: "pytest passes."
    - id: 6
      description: "Resume reconcile: smoke run interrupted between ticket_results write and cost_tally update; resume re-derives tally from ticket_results/, continues from next pending ticket, produces complete report."
      method: runtime-required
      evidence: "Two-step run with simulated mid-write crash; final report ticket count matches corpus; reconciliation logged."
    - id: 7
      description: "abort.flag race resolved: a run that hits global budget AT FINALIZATION (no in-flight, no pending) writes report with `budget_breached_at_finalization: true, aborted: false` and does NOT write abort.flag."
      method: api
      evidence: "Unit test simulates the post-loop budget check; asserts no abort.flag, asserts report fields."
    - id: 8
      description: "Output-coherence fixed-common-pair binarized-per-type scorer (Major #1 round-4): an AE-shaped fixture where rationale_or_plan references file A but diff modifies file B yields output-coherence < 1.0; an ICL-shaped fixture with the analogous mismatch yields < 1.0; coherent counterparts on both shapes yield 1.0; multiple instances of the SAME contradiction type contribute 1 (not N) to count; scores are bounded by len(TAXONOMY) and comparable across conditions."
      method: api
      evidence: "pytest with four fixtures (AE-coherent, AE-mismatch, ICL-coherent, ICL-mismatch) plus a multi-instance-same-type fixture passes; AE-mismatch and ICL-mismatch fall in the same band; coherent counterparts both score 1.0; multi-instance-same-type fixture's count == distinct types fired, not total instances."
    - id: 9
      description: "Output-coherence boundary (Major #1 round-4): score is in [0.0, 1.0] for all paths. Fixtures: count=0 -> score=1.0; count=len(TAXONOMY)=5 -> score=0.0; scorer asserts count <= len(TAXONOMY) and never returns a value outside [0.0, 1.0]."
      method: api
      evidence: "pytest with three boundary fixtures passes; score values strictly in [0.0, 1.0]; no clamp invoked because not needed; assertion on count <= len(TAXONOMY) holds."
    - id: 10
      description: "Verification-realism symmetric floor (Major #2 round-3 carried forward): an ICL-shaped fixture that produces no architect plan / no qa_criteria yields `status='floored'`, `score=0.0`, dim REMAINS in aggregate; AE counterpart yields `status='scored'` with score > 0; primary aggregates computed over identical dim set on both conditions."
      method: api
      evidence: "pytest with paired fixtures passes; report.floored_dim_count_per_condition.icl-baseline.verification-realism > 0; primary aggregates over identical DIMENSIONS list on both conditions."
    - id: 11
      description: "ICL rationale extraction fallback (Major #2 round-4): ICL fixture with `final_text` lacking a structured rationale section yields `rationale_extraction_method='fallback-full-text'` and `rationale_or_plan == final_text`; ICL fixture with a structured section yields `rationale_extraction_method='structured'` and `rationale_or_plan` equal to that section's body."
      method: api
      evidence: "pytest with two ICL fixtures passes; report.rationale_extraction_method_count.icl-baseline records both methods present; v1 smoke run with stub icl-baseline spec exercises the fallback path (smoke report shows non-zero fallback count)."
    - id: 12
      description: "Preflight gates execution: with PATH lacking `bun`, python invocation exits 4 with one-line message naming `bun`; with PATH lacking `python3`, bun invocation exits 4 with one-line message naming `python3`."
      method: runtime-required
      evidence: "Two invocations under doctored PATH; each exits 4; stderr matches documented format."
  manual_smoke: "Operator inspects a successful smoke report by eye for one ticket per class: confirms diff captured; all 6 dimensions present with status in {scored, floored, not-applicable} matching the per-condition binding in COVERAGE.md exactly; symmetric-dimset invariant holds; cost_usd consistent with token totals at expected per-token rates; raw_trace_path resolves; correctness_method, ae_execution_mode, output_coherence_method='fixed-common-pair-binarized-v1', output_coherence_taxonomy_version='v1', rationale_extraction_method_count fields all populated and reflect the operator-resolved Open Questions and round-4 scorer choices."
```

### Trade-offs and constraints

**Alternatives considered (round-4 deltas only; rounds 1-3 alternatives carried forward):**

- **Major #1 round-4 alternatives:**
  - **(a) Binarized-per-type counting.** *Selected.* `count = distinct types fired ∈ [0, len(TAXONOMY)]`; `score = 1 - count / len(TAXONOMY)` ∈ [0.0, 1.0] by construction. No calibration constant; naturally bounded; multiple instances of one type don't double-count.
  - **(b) Total-instance counting with calibration constant + clamp.** Rejected: introduces a tunable constant (`max`) that drifts across runs and conditions; `score = max(0.0, 1 - count/max)` requires explicit clamp because count can exceed max; harder to explain and audit.
- **Major #2 round-4 alternatives:**
  - **(a) v1 fallback extraction rule (entire final_text when no structured section).** *Selected.* Defensible "ICL produced rationale somewhere in its output" reading; preserves Brief parallelism (no new dependency on `icl-baseline-spec`); upgrade path via existing P-prod-ICL gate. Recorded per-ticket as `rationale_extraction_method`.
  - **(b) Explicit dependency on `icl-baseline-spec`.** Rejected: breaks Brief sequencing (these were declared parallel); blocks engineer spawn on a downstream stub.
  - **(c) Open Question Q5.** Rejected: design-taste call answerable by reading the codebase + Brief; does not need operator arbitration. Surface-and-proceed via documented v1 default + upgrade gate.
- **Minor #1 (COVERAGE.md permissive):** Resolved by tightening to per-condition binding (`AE:scored / ICL:floored`) per fixture row. Scenario 1's evidence asserts strict equality, not "either-status-acceptable."
- **Minor #2 (taxonomy versioning vs SHA pin):** Resolved by adding the constraint statement under "Known limitations" below and surfacing `output_coherence_taxonomy_version` in the report schema.

**Known limitations (carried forward + round-4):**

- The harness measures what we wire. If operator picks `single-shot` for AE (Open Q1) and the protocol's value is multi-spawn orchestration, AE's value is under-reported. Surfaced in `ae_execution_mode`. (Carried forward.)
- Output-coherence on the fixed-common-pair set MAY under-detect contradictions in artifacts excluded from the pair (AE commit message contradicting both plan and diff). Trace inspection captures these; they don't enter the score. Acceptable for v1; flagged for v2. (Carried forward.)
- Symmetric-floor mechanic penalizes ICL on verification-realism by design. If ICL's design choice is "no architect plan" by intent, the floor measures that gap, not a misclassification. Surfaced in `floored_dim_count_per_condition`. (Carried forward.)
- Per-cell budget defaults derive from `global / num_cells`, assuming uniform cost. Hot cells WILL hit cell budget faster; smoke-gate dominance check partially mitigates. (Carried forward.)
- **Output-coherence taxonomy versioning vs Stage 3 / Stage 6 SHA pin (NEW round-4, addresses Minor #2).** Since harness SHA is identical across Stage 3 and Stage 6 per Brief P2, `output_coherence_method = "fixed-common-pair-binarized-v1"` and `output_coherence_taxonomy_version = "v1"` are pinned by construction; bumping the taxonomy to v2 (adding/removing/renaming contradiction types) invalidates cross-stage comparability and requires re-running Stage 3 at the new harness SHA. The taxonomy is a load-bearing constant; treat it as part of the harness contract.
- **ICL fallback extraction may produce noisier output-coherence scores in v1 than under the production ICL spec (NEW round-4).** When `rationale_extraction_method = "fallback-full-text"`, the entire `final_text` is the rationale half of the pair; this can include scratch reasoning that genuinely contradicts the diff in ways the production-spec structured rationale would have excluded. Surfaced via `rationale_extraction_method_count`; not a defect, but a measured artifact of the v1 default. The P-prod-ICL gate validates the upgrade path.

### Open questions

**Q1 (CRITICAL - operator decision required before any engineer spawn). AE-orchestrated execution mechanics.** Unchanged from rounds 2-3. Three options: (a) `single-shot`; (b) `sdk-multiturn`; (c) `python-conductor-sim`. Each has different cost, fidelity, and "what is being measured" implications. Recommendation (advisory): (a) for v1 with explicit caveat in report. Operator resolution required.

**Q2 (CRITICAL - operator decision required before any engineer spawn). Correctness scorer.** Unchanged from rounds 2-3. Three options: (a) AC-keyword; (b) test-pass; (c) composite. Recommendation (advisory): (b) with (a) as fallback when test-extraction fails. Choice changes `eval-corpus-curate`'s scope (test-file extraction is a deliverable iff (b) or (c)). Operator resolution required.

**Q3 (deferred to architect on `icl-baseline-spec` unit; carried forward from Brief).** What counts as the ICL-baseline prompt assembly. NOT blocking THIS unit's engineer spawn (the harness consumes the spec via the contract above; v1 fallback extraction bridges its absence per Major #2 (a)); blocks Stage 3 baseline run. P-prod-ICL gate validates when this unit lands.

**Q4 (deferred to architect on `implement-ticket-restructure`; carried forward from Brief).** Phase-rename compatibility window.

Q1 and Q2 are protocol-level blockers per METHODOLOGY.md Open Questions hard gate. Conductor must resolve both before spawning any engineer on this unit. Q3 and Q4 do not block this unit. No new Open Questions introduced in round 4 (recommendation (a) selected on both Major findings; no Q5 needed).

---

Round 4 plan complete. Major #1 resolved via binarized-per-type formula (option a) with explicit boundary semantics and dedicated boundary unit test; Major #2 resolved via v1 fallback extraction rule (option a) with `rationale_extraction_method` recorded per-ticket and P-prod-ICL upgrade path preserved; Minor #1 resolved by tightening COVERAGE.md to per-condition binding (`AE:<status> / ICL:<status>`); Minor #2 resolved via taxonomy-version pin under Known Limitations + `output_coherence_taxonomy_version` report field. `scenarios-todo.md` referenced as required input artifact in dedicated subsection and per-consumer impact table. Q1 and Q2 preserved as operator-blocking Open Questions; no new Open Questions added.