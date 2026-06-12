# Brief: skeptic-eval-signal - make the auto-harness produce real signal

Status: approved-plan, pre-implementation
Tier: Brief (5 Elevated units, single-track `evals/`)
Date: 2026-06-10

## Problem

The auto-harness (`evals/auto/`) is the autoresearch-style self-improvement loop: an
editor agent proposes a prompt edit to a component, the loop runs the component eval,
and keeps or reverts based on whether the metric improved. Today it never keeps
anything, and a five-round design investigation found why - the failure is not in the
loop's mechanics but in the eval substrate and the keep statistic:

1. **Wrong keep statistic.** The gate (`loop.py:654-656`) compares the change in a
   ~15-fixture corpus mean against a *single-fixture* noise threshold
   (`max(pooled_stdev, 0.02)`, ~0.14). The bar is several times too high; no real edit
   clears it.
2. **Eval noise from two sources.** (a) `skeptic.tsv` mixes v1- and v2-scorer rows,
   inflating apparent variance; (b) the skeptic *agent* emits a variable number of
   spurious findings per run, and the runner invokes it with no temperature/seed control,
   so per-fixture medians at `n_runs=3` are unstable. The scorer itself (`skeptic_lite`)
   is deterministic - it is not the noise source.
3. **No stable fixture identity.** Pairing before/after scores by `fixture_hash` is
   unreliable (4 of ~19 fixtures drift their hash when content is edited).

## Success criteria

A correct, statistically-grounded keep gate that fires honestly on real signal, on a
clean low-noise eval substrate. Concretely:

- **SC1** Keep/revert is decided by a paired **sign-flip permutation test** over
  per-fixture deltas, gated on one-sided significance (alpha=0.05) AND a minimum mean
  effect (epsilon=0.02) AND a minimum-evidence guard (>=5 nonzero pairs). Zeros retained.
- **SC2** Fixtures are paired by a **stable `fixture_id`** (the fixture dir id,
  `sk-001`..`sk-015`), carried as a TSV column - not by `fixture_hash` or position.
- **SC3** The runner executes fixtures in **parallel** (bounded) and writes results in a
  single **post-join batch sorted by `fixture_id`**, eliminating the concurrent-append
  race, so a higher `n_runs` is affordable. `n_runs` raised 3 -> 9.
- **SC4** A **run-delimiter** (`expected_commit` filter + exact-count + unique-id
  assertions) prevents the trailing-window read from mixing rows across runs.
- **SC5** A one-time, idempotent **migration** brings all existing result TSVs to the new
  schema (component TSVs 9->10 cols; ledger 14->17 cols) without corrupting on-disk files;
  a header-width guard converts any schema mismatch into a hard error, never silent
  corruption.
- **SC6** The campaign runs end-to-end and the ledger shows the gate fired **honestly** -
  either >=1 kept edit with `signed_rank_p<=0.05`, `effect_mean_delta>=0.02`,
  `nonzero_pairs>=5`, or a clean all-revert run where every iteration's ledger row carries
  real (non-empty) p-values and effect sizes. The effect floor is the **mean** of paired
  deltas; the ledger column `effect_mean_delta` is named to reflect that (the prior plan
  draft's `effect_median_delta` was a misnomer - it always held the mean).

## Non-goals

- Rewriting `skeptic_lite` (it is deterministic; not the noise source).
- Expanding the fixture corpus (most of the 15 fixtures move; the movable set is workable now).
- Tuning alpha/epsilon/n_runs against a labeled sensitivity target (follow-up; constants
  live in one place).
- Generalizing the gate to non-skeptic components in this effort (the `stats.py` API is
  component-agnostic, so no rework is needed later).
- Changing the editor-agent prompt strategy.

## Constraints

- **stdlib-only** (Python 3.11+, + pyyaml). No scipy/numpy. The permutation test is
  hand-rolled (`itertools`, `math`, `fractions`).
- Single track (`evals/`); no cross-track changes; no new runtime dependency.
- The statistical core design is **frozen and Skeptic-approved** - constants
  `MIN_NONZERO_PAIRS=5`, `ALPHA=0.05`, `EPSILON=0.02`, `EXACT_MAX=22`; W=sum of positive
  deltas; p=P(W>=W_obs); exact conditional permutation null for k<=22 else normal approx.
- `expected_commit` is an optional kwarg defaulting to `None`; the `None` path preserves
  current `aggregate_latest` behavior bit-for-bit (existing tests are a back-compat gate).
- Migration is an **operator-run setup step**, never wired into any `cmd_run`.
- Every module-manifest touched by a contract change is updated in the same unit (stale
  manifest = Major).

## Verification

- **Per-unit:** each unit ships its own tests and passes lint/typecheck/pytest with zero
  errors. Specific gates: `stats.py` permutation math pinned against hand-computed values
  (incl. a tied-magnitude case); `aggregate_latest(expected_commit=None)` proven
  bit-for-bit unchanged by the existing `test_runner_shim.py`; `migrate_tsv` idempotency +
  no-overwrite proven on tmp_path fixtures; the loop integration test monkeypatches
  `aggregate_latest`+`run_component` and asserts keep/revert + all 3 ledger columns at all
  6 row-dict sites.
- **Integration (unit L Skeptic):** the `pair_deltas` join is keyed on `fixture_id` and
  composes correctly across B (emits the column), C (deterministic sorted order), and A
  (key name match).
- **End-to-end:** the 3-command setup phase (`migrate_tsv` -> `runner.cli run skeptic
  --n 9` baseline -> `auto.cli run skeptic --max-iterations 5`) runs; the operator reviews
  the before/after `show-results` diff and the `auto-harness.tsv` ledger. This is SC6 and
  is operator-run, not a qa-engineer scenario.

## QA criteria

```yaml
qa_skip: pure-backend-library
qa_skip_rationale: "Pure stdlib Python eval-harness library + YAML config; no runtime UI/HTTP/service surface. Verified by pytest. The campaign is the operator-run end-to-end check (SC6), not a browser/api QA scenario."
scenarios: []
```

## Units (from orchestration-planner; merge order A‖B -> M‖C -> L)

| slug | files | depends_on | risk |
|---|---|---|---|
| `stats-core` (A) | `evals/auto/stats.py` (+test) | - | Elevated |
| `fixture-id-schema` (B) | `evals/runner/tsv_writer.py`, `evals/runner/aggregator.py` (+test) | - | Elevated |
| `migrate-tsv` (M) | `evals/auto/migrate_tsv.py`, `evals/auto/loop.py` (ledger guard) | B | Elevated |
| `runner-parallelization` (C) | `evals/runner/cli.py`, `evals/auto/runner_shim.py` (+test) | B | Elevated |
| `loop-keep-gate` (L) | `evals/auto/loop.py`, `evals/auto/cli.py`, `evals/components/skeptic.yaml`, `evals/auto/program.md`, `evals/auto/README.md` (+test) | A,B,C | Elevated |

Per-unit acceptance criteria are in the orchestration-planner JSONL (carried into each
engineer's execution contract). Per-unit Skeptic for A, B, M, C; integration Skeptic for L
(primary focus: the `fixture_id`-keyed `pair_deltas` join).

## Open questions

None. Design frozen and Skeptic-approved across the statistical core and the substrate
integration.
