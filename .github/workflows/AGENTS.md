# .github/workflows

Canonical site for this repo's **CI trigger policy**. Workflow files carry a
short pointer here, never a copy of it.

## The premise, stated accurately

`main`'s ruleset (`14778332`) sets `strict_required_status_checks_policy: true`.
Under `strict` alone, a PR must be up to date with its base before it can merge,
so its squash reproduces its head tree byte-for-byte and the PR run **is** the
evaluation of what landed.

**But the same ruleset carries `bypass_actors: [{RepositoryRole admin,
bypass_mode: always}]`, and `gh pr merge --admin --squash` is this repo's normal
unattended-agent merge path** (root `AGENTS.md` documents it as such, because
GitHub disallows self-approval and no human reviewer is present). Admin bypass
defeats `strict`: a behind-base PR can merge without being brought up to date,
and the resulting squash synthesizes a tree that no run ever evaluated.

**This file is the ONLY site that carries the measurement.** The 15 consolidated
workflows' `on:` comments state the qualitative claim and point here, and
`verify-merged-tree.yml`'s header does the same, precisely so that re-measuring
(see the retirement condition) touches one file rather than seventeen. Do not
copy the figures below into a workflow comment.

Measured over the 25 most recent first-parent merges (comparing each squash
commit's tree object to its PR head commit's tree object) - **6 of the last 25
merged trees had never been evaluated by any run**:

| | count | meaning |
|---|---|---|
| merged tree **matches** PR head tree | 19 (76%) | PR run was the evaluation; a post-merge run is pure duplication |
| merged tree **differs** | 6 (24%) | #850, #854, #855, #856, #857, #860 - the post-merge run was the *only* evaluation |

`#850`'s merged tree differed from its head across 46 files.

## Trigger policy

- **PR-only by default.** A workflow triggers on `pull_request` (plus
  `workflow_dispatch` where useful) and nothing else.
- **`push: branches: [main]` only when the main tree is itself the subject.**
  `codeql.yml` (SARIF upload is default-branch-scoped), `gitleaks.yml`
  (full-history scan of `main`), and `scorecard.yml` (scores the default
  branch). Nothing else.
- **`verify-merged-tree.yml` is the single post-merge run**, on
  `push: branches: [main]` + `workflow_dispatch`. Its `needs-full-run` gate job
  (~10 s) compares the pushed commit's tree object against the tree of the
  merged PR's head commit and sets `run_full`. When the trees match, the whole
  suite skips - the PR already tested exactly this content. Both tree SHAs and
  the verdict are printed to the log so the operator can read why it ran or
  skipped.

  **The gate fails open, always toward running, on two distinct axes:**
  1. *Inside the script* - any inability to resolve the PR, fetch
     `refs/pull/N/head`, or read either tree yields `run_full=true`.
  2. *At the job boundary* - every suite job guards on
     `if: ${{ !cancelled() && (needs.needs-full-run.result != 'success' || needs.needs-full-run.outputs.run_full == 'true') }}`.
     The status-check function is load-bearing. A bare
     `if: needs.needs-full-run.outputs.run_full == 'true'` carries none, so
     GitHub applies the implicit `success()` and a **failed** gate job (step
     timeout on a slow `git fetch`/`gh api`, lost runner, checkout failure)
     would SKIP every suite job instead of running it - inverting the contract
     precisely when the gate is least trustworthy. `!cancelled()` rather than
     `always()`: the same run-on-gate-failure behavior, but an operator/API
     cancel of the gate does not go on to start all 10 suite jobs. The
     `${{ }}` wrapper is mandatory, not cosmetic - a bare leading `!` opens a
     YAML tag and `if: !cancelled() && ...` is a scanner error.

  The gate step also sets `shell: bash {0}`. GitHub's default is
  `bash -e {0}` (errexit ON), which silently made two `emit true` branches -
  parentless commit, unreadable merged SHA - dead code: the step aborted at the
  first failing `git rev-parse` with no verdict line and nothing written to
  `$GITHUB_OUTPUT`. The boundary guard still produced the right *outcome*, but
  the operator lost the diagnostic. Relatedly, every `git rev-parse` in the
  step uses `--verify`: without it git echoes the unresolvable argument back on
  stdout, so an emptiness test never fires and the wrong branch reports.

  A gate that cannot prove the tree was already tested must never assert that
  it was, and a gate that never finished has proven nothing.

- **The non-PR direct push.** `changelog-publish.yml` runs daily at 00:00 UTC,
  regenerates `CHANGELOG.md` + `docs/changelog.html`, and pushes straight to
  `main` with a PAT (`CHANGELOG_PUSH_TOKEN`) - and a PAT *does* trigger
  workflows. Its commit subject (`chore(changelog): regenerate from merged
  PRs`) has no `(#N)` and no PR, so it hits the gate's no-PR path. Left alone
  that fires the entire suite - `merged-codex-skill-sync` alone is budgeted 45
  minutes - every single day on a two-file bot commit, and makes the retirement
  condition below unsatisfiable by construction.

  The gate therefore has a **second `run_full=false` path**: when no PR
  resolves, it diffs `<sha>^ <sha>` and skips only if the changed set is
  non-empty and a subset of `UNTESTED_SAFE_PATHS` - exactly `CHANGELOG.md` and
  `docs/changelog.html`. Verified by `grep -rn 'CHANGELOG\.md\|changelog\.html'
  .github/workflows/ scripts/ bin/ hooks/`: no check reads the *content* of
  either file. The only hits are `changelog-publish.yml`'s own `git add`,
  `generate-changelog.js` (the producer), `update-needsrebuild.test.js` (paths
  as literal test data), and `test_gate_provenance.sh` (asserts `CHANGELOG.md`
  is DERIVED via D2, which reads the *workflow's* `git add` line, never the
  file). The slide tooling is scoped to `docs/slides/*` and never sees
  `docs/changelog.html`. Any other non-PR push stays `run_full=true`.
  Keep this allowlist tiny. Catch: the daily 45-minute bot run. Retires when
  `changelog-publish.yml` opens a PR instead of pushing to `main`.
- **No `paths:` filters.** A path filter turns a required check into one that
  never reports on a PR not touching its paths, which blocks the merge rather
  than passing it. Scope by need (the gate), not by path.

## What is in the full suite

Every check the 15 consolidated workflows ran, because on a behind-base merged
tree **any** of them can flip - including the ones whose verdict looks like a
pure function of a single file. `check-skill-embed-budget`'s CEILING is measured
over a `SKILL.md` generated from all of `content/**`: two PRs each adding
content, the second merged behind, yield a merged embed larger than either PR
run measured. Root `AGENTS.md` names this exact mode (KNW-20260818-001). The
same applies to `check-command-file-budget` and to `hooks-js-tests`' sha256
prose goldens.

Jobs: `merged-adapter-sync` (incl. the DS-57 codex-hooks and DS-104
symlinks-relative guards, which audit a landed SHA), `merged-methodology-drift`,
`merged-agent-fragment-sync`, `merged-slides-sync` (incl. the advisory overflow
check), `merged-codex-skill-sync`, `merged-budget-gates` (all 7),
`merged-content-guards`, `merged-wrap-lock-tests`, `merged-hooks-js-tests`,
`merged-hooks-sh-tests`.

The three hook-test jobs are kept separate rather than folded into one, mirroring
`hooks-tests.yml`: `bin/tests/test_discovery_zero_match_guard_spec.py` keys
`LIVE_GUARD_SITES` on `(file, job)`, so two discovery loops sharing a job collapse
to a single pin and either loop's zero-match guard can then be deleted with the
spec still green. One loop per job means one pin per loop.

`merged-slides-sync` runs the overflow checks *after* `build-slides.sh`, so it
measures regenerated HTML where `slides-sync.yml` measures the committed HTML.
Equivalent in practice: the drift step reddens first whenever the two differ.

**Known gap - `bin-tests.yml`.** Its three jobs (`python-bin-tests`,
`hooks-python-tests`, `bin-sh-tests`) are *not* in the suite. That file is owned
by a separate change and **still carries its own `push: branches: [main]`
trigger**, so its post-merge coverage is currently intact and nothing is lost.
When that trigger is dropped, those three jobs must be added here in the same
change - otherwise three required contexts lose behind-base coverage.

## Pillar 8 record

- **Named catch (a):** the 6 behind-base merges above. Without a post-merge run
  those merged trees are evaluated by nothing at all.
- **Retirement condition (b):** when the admin bypass is removed from ruleset
  `14778332`, or every merge is reliably preceded by `gh pr update-branch
  --rebase`, the gate stops finding differing trees. The condition is therefore
  stated over *merge-triggered* runs only: **60 consecutive days in which no
  `push`-triggered run whose commit resolves to a PR reports `run_full=true`.**
  Runs that skip via the `UNTESTED_SAFE_PATHS` path are `run_full=false` and do
  not reset the counter; a `workflow_dispatch` run is excluded because it always
  forces `run_full=true` by design. (Phrasing this as "60 days of *every* run
  reporting false" would be unsatisfiable while any PR-less push exists at all -
  the earlier draft had that bug.) After that window, the full-suite jobs retire
  and only the gate job remains as the standing measurement. The gate itself
  retires when the bypass is gone.
- **The cheap path that makes `run_full=false` the norm:** local `gh` is 2.100
  and `gh pr update-branch --rebase` works, so the conductor can bring a BEHIND
  PR up to date before an `--admin` merge. Prefer that over relying on this
  workflow to catch the difference afterwards.

## What the 0/600 measurement did and did not show

Across 2026-08-26 -> 2026-09-03: 31 merges, 600+ push-to-`main` workflow runs
(~19 per merge), 579 success, 20 cancelled, 1 failure - and that failure was the
advisory `check-slide-overflow`. **Required-check catches on the post-merge run
in that window: zero.**

That is genuine evidence that **~19 duplicate runs per merge** is the wrong
shape - it is not evidence that the post-merge run is unnecessary. A zero-catch
window across 31 merges cannot distinguish "this run is redundant" from "this
run is load-bearing on 24% of merges and those merges happened to be clean".
The tree comparison above is what settles it, and it settles it the other way.
The cost this policy removes is the ~19x duplication and the 20 cancel events;
the coverage it keeps is the 24%.

## Reinstatement condition

A workflow's own `push: branches: [main]` trigger comes back if
`verify-merged-tree.yml` proves inadequate - i.e. it skips (or cannot run) a
tree that later turns out to have been broken. "Belt and braces", "it is cheap",
and "for safety" are not reinstatement conditions.

## Triage: a red `verify-merged-tree` run

It has no PR, so there is nothing to push a fix to. Fixing main-tree drift means
opening a normal PR that regenerates the artifact and commits it. Read the gate
job's log first: it prints the merged tree SHA, the PR head tree SHA, and why it
decided to run.

Note that consolidation trades run count for failure granularity: sibling checks
share a job and run as sequential steps with no `continue-on-error`, so a
`Fail on slide drift` failure hides the overflow checks after it and a
`check-resident-budget.sh` failure hides the other six budget gates - you get one
finding per triage cycle rather than all of them at once. Accepted deliberately
for a post-merge run (nobody is waiting on it), and the reason the hook-test
loops are *not* consolidated (see `merged-hooks-js-tests`).

## Related conventions

- The 16-path adapter pathspec and the 18-entry existence loop are duplicated
  verbatim between `adapter-sync.yml` and `verify-merged-tree.yml`. This is
  **not** extracted into a composite action: `scripts/gate-provenance.sh`'s D1
  rule only scans `.github/workflows/*.yml`, so moving the assertion out of a
  workflow file would stop `.claude`/`.codex`/... classifying as DERIVED and
  break `bin/tests/test_gate_provenance.sh`. Instead the duplication is
  **mechanically guarded**: `merged-adapter-sync`'s first step fails the build
  if the two pathspec lines are not byte-identical. Root `AGENTS.md`'s rule
  ("copy it verbatim from `Fail on adapter drift` in `adapter-sync.yml`") now
  has two in-repo consumers.
- `verify-merged-tree.yml`'s "Verify public build is clean" step is scoped
  `-- .codex`, unlike `codex-skill-sync.yml`'s bare `git diff --exit-code`.
  `gate-provenance.sh`'s D4 rule takes the FIRST bare, no-pathspec assertion
  across the sorted workflow files as its input, and both that script and
  `test_gate_provenance.sh` treat `codex-skill-sync.yml` as the repo's only
  one. A second bare assertion would make D4's input depend on filename order.
- `verify-merged-tree.yml` is named to sort **after** `slides-sync.yml`.
  D1 cites the first workflow whose pathspec covers the queried target, so an
  earlier-sorting name would re-point `gate-provenance.sh docs/slides/<deck>.md`
  at the post-merge suite instead of the canonical PR gate.
- `bin-tests.yml`'s header holds the repo's TIMEOUT POLICY (job-level timeouts
  are a backstop; network and execution steps carry their own).
  `verify-merged-tree.yml` follows it.
