# evals - component eval harness (Phase 1)

This is the Phase 1 deliverable of the P2 self-improving-harness plan
(`docs/planning/p2-self-improving-harness.md`). It runs named-agent components
against labeled fixtures in isolation, aggregates scores across N runs, and
appends to a per-component TSV ledger.

Phase 1 ships one component end-to-end: **Skeptic** (Tier 1 isolation,
skeptic-lite scoring, 5 seeded fixtures).

## Prerequisites

- **Python 3.11+**
- **`claude` CLI on PATH**, authenticated and working. The runner probes
  `claude --version` at startup and fails with a clear error if absent. This is
  a hard prerequisite; there is no fallback. Install Claude Code from
  https://docs.claude.com/claude-code.
- **`git`** on PATH (used by the Tier 1 worktree isolator).
- `pip install -r evals/requirements.txt` (only `pyyaml>=6.0`).

The runner shells out to the CLI so the eval code path matches how a human
spawns the agent; it does **not** use the Anthropic SDK directly.

## Commands

From the repo root:

```
python -m evals.runner.cli list-components
python -m evals.runner.cli run skeptic                       # full N=3 over all fixtures
python -m evals.runner.cli run skeptic --fixture sk-001      # one fixture
python -m evals.runner.cli run skeptic --fixture sk-001 --n 1   # smoke
python -m evals.runner.cli show-results skeptic
```

Results land in:
- `evals/results/<component>.tsv` - committed, append-only ledger.
- `evals/results/<component>.runlog.jsonl` - gitignored per-run detail.
- `evals/.worktrees/` - gitignored Tier 1 worktrees; cleaned up after each run.

## TSV schema

```
commit  component_content_hash  fixture_hash  primary_score_median  primary_score_stdev  n_runs  status  diagnostic_json  description
```

- `component_content_hash` is the sha256 of the sorted content_glob files, each
  file preceded by its repo-root-relative path and a NUL separator. Renames
  and re-orderings change the hash even when the raw bytes happen to collide.
- `fixture_hash` is the sha256 of a canonical-JSON serialization of the
  fixture's **semantic fields only**: `id`, `inputs`, `expected_findings`,
  `expected_signoff_granted`. Description rewords, `protocol_sha` bumps, and
  free-form comments do **not** alter the hash - TSV rows remain comparable
  across those edits. Changing any semantic field does alter the hash.
- `primary_score_median` is the median of the N per-run primary scores.
- `primary_score_stdev` is the **sample stdev (N-1 divisor)** of the N
  per-run primaries. With n<2 the sample stdev is undefined; the runner
  records 0.0 explicitly.
- `n_runs` is N actually executed.
- `description` is the fixture's human-readable description at run time. If
  the runner's invocation path is the fallback raw-prompt path (see "Known
  substitution: invocation path" below), the description is prefixed
  `[raw-prompt]` so readers can distinguish measurement regimes.
- Cache key pattern `(commit, content_hash, fixture_hash, N)` is implicit
  in the row columns.

## Overfitting Rule

Any human edit to `content/` motivated wholly or partly by a TSV score must
satisfy the rule in [`OVERFITTING-RULE.md`](./OVERFITTING-RULE.md). Read it
before reacting to a score.

## Isolation tiers

| Tier | Use | Phase 1 status |
|---|---|---|
| 1 | Read-only prompt components (Skeptic, conductor, Architect) | Implemented (git worktree) |
| 2 | Commands that write (/init-project, /wrap) | Stubbed - raises NotImplementedError |
| 3 | Code-executing components (Worker, Debugger) | Stubbed - raises NotImplementedError |

**Tier 1 is read-only.** Allowed tools at the runner level are `Read`, `Grep`,
`Glob`, plus `Task` (for the two-level subagent spawn). No `Bash`, no `Write`,
no `Edit`, no network-bound tools. The CLI permission mode is `default` - there
is nothing for the component to accept. If a component needs shell or network
for its correctness, it does not belong at Tier 1; declare it Tier 2 or Tier 3
and wait for those isolators to land.

## Scoring (skeptic-lite)

The Phase 1 Skeptic scorer matches a raised finding against an expected
finding by case-insensitive substring. Known limitations, documented rather
than fixed in Phase 1:

- **Case-insensitive substring only.** No stemming, no morphology, no lemmatisation.
- **Keyword lists are AND-joined.** Every keyword in an expected entry's
  `keywords` list must appear in the raised description for it to match.
  Single-keyword entries are the most permissive.
- **No synonym expansion.** "manifest header" and "module header" do not match
  each other - fixture authors must pick keywords that the Skeptic is likely
  to use verbatim, or list alternates explicitly in multi-entry expected sets.
- **Category fallback.** If `category` is set on an expected entry, its lower-
  cased string is also tried as a substring - use this sparingly, since common
  words ("hash", "print") false-match easily.

Fixture authors should pick keywords that minimize false-match risk on
unrelated raised findings. The scoring module asserts single-run traces;
N-run aggregation is the runner aggregator's job.

## Known substitution: invocation path

The runner's preferred path is a two-level invocation: the outer `claude -p`
session uses the `Task` tool to spawn the named subagent declared in
`invoke.agent_name`, and the subagent's response is extracted from the
`tool_result` event for scoring. This measures the actual named agent - with
its frontmatter tools, description, and per-agent system-prompt wiring
applied by the spawn mechanism.

If `Task` is not permitted in `claude -p` or stream-json does not expose the
subagent's output, the runner falls back to the **raw-prompt path**: the
top-level Claude session is given a prompt that instructs it to follow
`content/agents/<name>.md`. The consequence is that the `agent_name`'s
frontmatter (tools list, model, description) is **not** applied by the spawn
mechanism - only by the prompt-level "follow this file" instruction. Scores
from this path measure a close-but-not-identical entity.

TSV rows from runs on the raw-prompt path have `[raw-prompt]` prefixed to the
`description` column so readers can distinguish them from two-level-spawn
rows. Do not compare a raw-prompt row's primary against a two-level-spawn
row's primary as if they measured the same thing.

## How to add a new component eval

10-line recipe:

1. Create `evals/components/<name>.yaml` with the manifest fields (see
   `evals/components/skeptic.yaml` as the template).
2. Create `evals/fixtures/<name>/<fixture-id>/` with `fixture.yaml`, and any
   companion files the fixture references in `inputs` (e.g. `diff.patch`,
   `worker_output.md`).
3. Each fixture records the `protocol_sha` of the file in `content_glob` at
   labeling time. The runner warns on drift between the fixture's
   `protocol_sha` and the current git SHA of the content files. Re-run
   fixture-label review whenever that `protocol_sha` warning fires.
4. Create `evals/scoring/<name>_lite.py` exposing
   `score(trace: dict, fixture: dict) -> {"primary": float, "diagnostic": dict, "status": str}`.
   Declare asymmetric costs explicitly (or justify symmetric).
5. If the component writes to disk or executes code, declare `tier: 2` or
   `tier: 3` in the manifest; Phase 1 only runs Tier 1. Tier 2/3 raise
   `NotImplementedError` until their isolators land.
6. Reference `evals/OVERFITTING-RULE.md` from the component's section in this
   README (or a per-component README if the component grows one).
7. Run `python -m evals.runner.cli run <name> --fixture <one> --n 1` as a
   smoke test.
8. Run the full eval: `python -m evals.runner.cli run <name>`.
9. Inspect `evals/results/<name>.tsv`; commit it.
10. Add the component to the phase-sequencing table in the planning doc if it
    is new.
