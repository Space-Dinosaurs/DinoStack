# /auto-harness operator runbook

`evals/auto/` is the P3 autonomous self-improvement loop. It drives a single
component's prompt toward higher eval scores by iterating editor-agent
proposals, applying each validated diff, running the component eval, and
keeping or reverting based on a scalar threshold. This is NOT a slash
command and NOT a daemon - it is a standalone Python CLI you run on demand.

Read `docs/planning/p2-self-improving-harness.md` ("Proposed approach" and
"Overfitting Rule") and `evals/OVERFITTING-RULE.md` before using this tool.

## One-time v2 migration + baseline (run before first loop)

Before running the loop for the first time after upgrading to v2, complete
these three steps in order. Step 1 must run before steps 2 and 3 - the loop's
baseline read and the ledger's header-width guard both require the migrated
schema.

```sh
# 1. Migrate stale-schema TSVs to the new 10-column (component) and
#    17-column (ledger) schemas. Idempotent - safe to run multiple times.
python -m evals.auto.migrate_tsv

# 2. Establish the v2 baseline (n_runs=9 is set in skeptic.yaml; no --n needed).
#    Run from the repo root on a clean tree on a NON-main branch.
python -m evals.runner.cli run skeptic

# 3. Then start the loop.
python -m evals.auto.cli run skeptic --max-iterations 5 --cost-budget-usd 20
```

Note: `migrate_tsv` is delivered by a separate setup step. If the module is
not yet present, check that your branch includes the `evals/auto/migrate_tsv.py`
file before running step 1.

## Quickstart

```sh
# From the repo root, with a clean tree, on a working branch (NOT main):
python3 -m evals.auto.cli run skeptic --max-iterations 5 --time-budget-sec 1800
```

For a smoke test that spawns the editor once, prints the proposed diff,
and exits without applying or committing:

```sh
python3 -m evals.auto.cli run skeptic --dry-run
```

## Preflight requirements

The CLI aborts before spawning any agent if any of these is false:

- The git tree is clean (no staged or unstaged changes)
- The current branch is not `main` / `master`
- The lock file `evals/.auto-harness.lock` does not exist
- The component has an entry in `evals/auto/components.yaml` that is
  populated (not just a `TODO` stub)
- The component's fixtures directory exists and has >= 1 fixture
- The component's TSV at `evals/results/<component>.tsv` has enough rows
  to compute a stable baseline (one full baseline cycle is the minimum)
- The `claude` CLI is on PATH

## What the loop does per iteration

1. Spawn an editor-agent via `claude -p` with only Read, Grep, Glob. The
   agent receives `evals/auto/program.md` parameterized with the
   component's editable and locked file lists, the current baseline
   scalar, and the max LOC budget.
2. Extract the first fenced ```diff block from the response.
3. Parse the "Overfitting Rule verdict:" line. Scan both the rationale
   and the diff for fixture IDs (`sk-NNN`, `ip-NNN`, `wr-NNN`,
   `co-NNN`); any hit fails the check.
4. Validate the diff's file paths against the component's editable
   allowlist and locked deny-list; check LOC <= `max_edit_loc`.
5. Apply the diff via `git apply --index`, commit it on the working
   branch, and run `python -m evals.runner.cli run <component>`.
6. Aggregate the freshly-written TSV rows (mean-of-fixture-medians)
   into a scalar. Pair the per-fixture results against the baseline
   by `fixture_id`. Keep the commit only if a one-sided sign-flip
   permutation test (alpha=0.05) is significant AND the mean
   per-fixture delta is >= 0.02 AND there are >= 5 nonzero pairs.
   Otherwise `git reset --hard` back to the previous base.
7. Append a row to `evals/results/auto-harness.tsv` describing the
   decision, the delta, and cumulative cost.

The loop stops on any of: max iterations reached, wall-clock budget
exhausted, cost budget exhausted, three consecutive reject-or-revert
iterations (plateau), or editor-agent auth failure.

## Reading the ledger TSV

`evals/results/auto-harness.tsv` (17 columns):

| column | meaning |
|---|---|
| `timestamp_utc` | Iteration start |
| `component` | Component name |
| `branch` | Working branch |
| `iteration` | 1-indexed |
| `base_commit` | SHA the iteration started from |
| `proposed_commit` | SHA of the proposal commit (empty on pre-apply reject) |
| `baseline_metric` | Scalar before this iteration |
| `new_metric` | Scalar after apply+run (empty on reject/halt) |
| `delta` | new - baseline (empty on reject/halt) |
| `pooled_stdev` | Post-eval pooled stdev across fixtures (observability only) |
| `decision` | `keep` / `revert` / `reject` / `dry_run_skip_apply` / `halt` |
| `reason` | Decision rationale or reject/halt reason |
| `overfitting_verdict` | `pass` / `fail` from the editor's verdict line |
| `cost_usd_cumulative` | Total loop cost including this iteration |
| `signed_rank_p` | p-value from the one-sided sign-flip permutation test (empty on pre-runner rows) |
| `effect_mean_delta` | Mean per-fixture delta across paired fixtures (empty on pre-runner rows) |
| `nonzero_pairs` | Number of nonzero paired deltas used in the test (empty on pre-runner rows) |

## Killing a runaway loop

The loop is a foreground Python process. `Ctrl-C` stops it at the next
subprocess boundary. If the process is orphaned (e.g. terminal closed),
find the PID with `ps aux | grep 'evals.auto.cli'` and `kill` it, then
remove the lock file:

```sh
rm evals/.auto-harness.lock
```

Do NOT remove the lock while a loop is still running - you risk
concurrent git writes on the same branch.

## Merging a successful branch

There is no auto-merge. When the loop finishes with one or more
`keep` rows:

1. Inspect the branch: `git log auto-harness/<component>-<ts>`
2. Read the diffs; verify each kept edit passes the Overfitting Rule
   independently of score ("would this still be worth it if the exact
   fixture that moved disappeared?").
3. Run the component eval once more on `main` and on the branch as a
   sanity replication (the TSV rows on the branch were written during
   the loop; an external replication catches runner nondeterminism).
4. Open a PR manually: `gh pr create`. Default title form:
   `harness(<component>): auto-harness iteration N keep - <one-line
   rationale>`.

## Known failure modes

- **`auth_fatal`**: Claude CLI returned 401 / `invalid_api_key`. The
  loop halts immediately with no further iterations. Refresh your
  credentials and re-run.
- **`plateau_3_consecutive`**: three iterations in a row produced a
  reject or revert. Either the component is at a local maximum or the
  `max_edit_loc` budget is too tight for meaningful improvements.
  Consider expanding the fixture corpus or raising `max_edit_loc`,
  but only after verifying the current prompt is genuinely good.
- **`cost_budget_exhausted` / `time_budget_exhausted`**: normal early
  exits. The branch is left as-is; decide manually whether any
  kept commits are worth preserving.
- **`empty_or_noop_diff`**: the editor proposed no change. This is
  acceptable behavior once per session; three in a row triggers plateau
  exit.

## Scope guardrails

The loop CANNOT edit:

- `content/rules/agent-methodology.md` (locked - the verifier layer)
- `content/rules/skeptic-protocol.md` (locked - the verifier layer)
- Anything under `evals/` (locked - scorers, fixtures, runner, this loop)

These are enforced both by `evals/auto/apply.py` (pre-apply path
validation) and by the editor-agent's allowed-tools list (Read,
Grep, Glob only; no write tools).

The editable surface per component is the explicit allowlist in
`evals/auto/components.yaml`. To add a component, populate its entry
(replace `TODO`) with `editable`, `locked`, `max_edit_loc`, and
`keep_delta_rule` fields.
