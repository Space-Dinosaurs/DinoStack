---
description: "/ds-change-delta"
agent: build
---
# /ds-change-delta

Render a before/after telemetry delta bracketing a methodology-change
"cut point" - a git commit SHA or an ISO8601 date. Answers "did this
specific commit help or hurt" by re-deriving sessions, subagent spawns
per session, hook denies per session, tokens per session, wall time per
session, and (for a git-checkout `--repo` with a resolvable `gh` remote)
commits per merged PR, for two equal-length windows either side of the
cut point, from the same live telemetry stores `ds-cost`, `ds-evaluate`,
`ds-hook-fire-report`, and `ds-branch-prune` already read.

Implementation: `bin/ds-change-delta` (Python 3 stdlib).

## Usage

```
ds-change-delta --cut <SHA|ISO8601> [--cut-repo PATH] [--window-days N] [--pr-lookahead-days N] --repo PATH [--repo PATH ...] [--json]
```

- `--cut` (required): a git SHA (resolved to its **committer** date on
  `--cut-repo`, deliberate for a squash-merge repo) or an ISO8601
  date/datetime. A 7-40 hex-char argument is tried as a SHA FIRST
  (real all-digit abbreviated SHAs exist and are also valid compact ISO
  dates, so SHA resolution is never skipped based on digit/letter
  composition); if that fails, it falls through to ISO date parsing.
  An argument that resolves neither way exits 1 with an error message.
- `--cut-repo` (optional, default: the first `--repo` that resolves to
  a real directory with `.agentic/` or `.git`).
- `--window-days N` (optional, default 14). Before window
  `[cut - N days, cut)`, after window `[cut, cut + N days)` - always
  genuinely equal-length, never truncated to "now".
- `--repo PATH` (repeatable, at least one required). Session, spawn,
  hook-deny, token, and wall-time metrics are computed over the MERGED
  row set across every `--repo` - not independently per repo and then
  combined. PR history is reported separately, per repo.
- `--pr-lookahead-days N` (optional, default 7): merged PRs up to N days
  past a window's end still count for that window's tickets.
- `--json` for the full machine-readable report; default is a fixed-width
  table.

## Spawn telemetry: `agent_model` and `per_ticket` (DS-246)

Both read only hook spawn rows with `data.telemetry_v: 2` from each
`--repo`'s `.agentic/events.jsonl`; older rows never contribute. Their
status comes from the same precedence as every other metric, over the v2
rows' own extent (intersected across repos, reported as `v2_coverage`):
a window the v2 rows do not fully bracket is `INSUFFICIENT_COVERAGE`, and
a store with no v2 rows is `ABSENT`, both with `null` values.

- `agent_model`: per agent x model, the runs ending in the window with
  their tokens, wall time and dollars. Dollars use built-in rates from
  the DS-246 ticket, overridden by `~/.agentic/pricing.yml`. An exact
  model id goes to `dollars_exact`; an id priced by family (for example
  `claude-opus-5` at the Opus 5.5 rate) goes to `dollars_family_estimated`
  and is named in `family_priced_models`. A run with no tokens is counted
  in `tokens_null_runs`, never priced as zero.
- `per_ticket`: one row per ticket whose first v2 spawn (else its ledger
  `opened_ts`) falls in the window, keyed by the hooks' `task_id`. Each
  row reports Skeptic reviews, max iteration, Critical/Major/Minor totals,
  `re_raised` (`null` when no `findings_log` entry records it), QA runs and
  fail-backs (FAIL or PARTIAL), merged and follow-up PRs, re-entries more
  than 1h after the first merge, Critical+Major findings after it (`null`
  when the review count fell back to the ledger's `skeptic_rounds`),
  `ledger_skeptic_rounds` (shown beside a telemetry count so an undercount
  is visible), `unit_count` (from the ledger, default 1), rework loops
  (`max(skeptic_reviews - unit_count, 0) + qa_fail_backs +
  max(prs_merged - unit_count, 0)`, so a clean ticket with one review and
  one PR per unit reports 0), end-to-end wall (final merge minus first
  spawn) and dollars. A ticket whose ledger `opened_ts` predates the v2
  extent is listed in `excluded_pre_v2` instead; a ticket with no ledger
  row that began before the v2 extent cannot be detected, so it is
  anchored at its first v2 spawn with a short wall and fewer reviews.
- PR attribution: a PR number in a repo's `ticket-ledger.jsonl` counts
  for every ticket recording it. Any other PR counts for T only when its
  title starts with `T:`, `[T]`, `[T]:` or `type(T):`, or else when the
  last `/`-separated segment of its branch starts with T; a PR that only
  mentions T does not count, and one matching several tickets goes to
  `ambiguous_prs`. When `gh` is unavailable, only the PR-derived fields
  (and `loops`) are `null`.

## Coverage and status

Every metric's `--json` output names the file(s) or query it read and
the row/record count it consumed - the default table is a compact
summary and omits both; use `--json` to see the provenance. When a
store is absent, empty, or does not reach the
requested window on one side, that side reports a status word
(`ABSENT`, `NOT_YET_ELAPSED`, `INSUFFICIENT_COVERAGE`, `ZERO_SESSIONS`,
or `OK`) and a `null` delta rather than a misleading numeric zero - the
`value` field is also `null` on every non-`OK` status, including
`NOT_YET_ELAPSED`; a not-yet-elapsed after window never reports a
partial informational figure. Token
and wall-time metrics additionally carry a `data_quality` flag
(`"zero-filled"`, `"zero-filled-before"`, or `"zero-filled-after"`) that
forces `delta` to `null` even when both sides otherwise report `OK` -
this checkout's own session-log is majority zero-filled for
tokens/wall_seconds, and without this check a real instrumentation gap
would print as a large numeric methodology-change effect. The
`data_quality` check only runs when both sides report `OK`: if one side
is a genuine zero and the other side is any non-`OK` status, the zero
side's real value is shown as-is (never flagged `zero-filled`) and
`delta` stays `null` because a non-`OK` opposite side already forces it.

With multiple `--repo` arguments, a metric's before/after VALUE always
sums across every repo's rows, but coverage is judged per store as the
INTERSECTION of each contributing repo's own recorded extent, not the
union of the merged rows - a repo whose telemetry only starts after the
cut (e.g. newly onboarded) cannot be masked by a sibling repo that alone
brackets the whole window. When one repo's extent is the limiting one,
the `note` field names it. That `note` (including which repo limited
coverage) is reachable only via `--json` - the default table does not
surface it.

## Known limitation

Passing a repo root AND one of that repo's own `.claude/worktrees/*`
checkouts as separate `--repo` arguments double-counts fires rows: the
parent repo's stranded-copy glob already reads the child worktree's own
`.agentic/.enforcement-fires.jsonl`, and passing the child again as its
own `--repo` reads it a second time. Avoid passing a repo and its own
nested worktree checkouts together.

## What this tool does NOT measure

- **Skeptic-loop yield per round** - this repo's telemetry cannot support
  that measurement at all (see `MEMORY.md`'s KNW-20260818-002 through
  -006); it is out of scope here and is never synthesized from a proxy
  signal. `per_ticket` reports review counts and findings totals, not
  per-round yield.
- **Consumer-repo PR history beyond a resolvable `gh` remote** - a
  `--repo` with no `origin` remote `gh` can resolve reports
  `NOT_A_GIT_REPO` for that one signal while still contributing to the
  merged session/hook/token/wall metrics.

This tool reports correlational deltas across a cut point, never a
verdict on whether a methodology change was good or bad - read the
status fields before trusting any number, and treat a real delta as one
input to a human judgment, not the judgment itself.

## Read-only guarantee

The tool never writes to any telemetry file and never mutates git or gh
state. Every subprocess call is one of `git rev-parse --verify`,
`git show`, `git remote get-url`, `gh repo view`, or `gh api graphql`
(all read-only). See `bin/tests/test_ds_change_delta.py`'s R5 test for
the enforced argv allowlist and a fixture-repo HEAD/status
byte-identity assertion.

## Known limitation: PR-history window granularity

PR-history windows are built as GitHub search `merged:` datetime ranges
(second precision), with the end instant one second before the window's
own end - a PR merged exactly on the shared boundary between the before
and after windows lands in exactly one of them, never both. The residual
granularity is one second: a PR merged in the same second as a window
boundary cannot be resolved further, since `mergedAt` carries no
sub-second precision. Not a practical concern at any realistic
`--window-days`.

## Known limitation: GitHub search's 1,000-result ceiling

The GraphQL `search` connection this tool uses for PR history has a
documented hard cap of 1,000 total results per query, regardless of
pagination depth. A `--window-days` wide enough to push a repo's merged-PR
`issueCount` past that cap will never let the completeness check
reconcile, and the tool correctly reports `INCOMPLETE_WINDOW` rather than
silently truncating - a self-detecting condition, not a silent one. Not a
practical concern at the default 14-day window.

## Retirement condition (Pillar 8)

A one-shot diagnostic, matching `bin/ds-skill-load-rate`'s retirement
shape: it retires once an operator has run it across a representative
set of methodology-change PRs (e.g. the first 5-10 real uses), recorded
in a decision entry whether the reported deltas ever changed a
merge/rollback/rollout decision, and made an explicit call on whether
the tool is worth keeping - not an invocation-count trigger, since the
tool keeps no record of its own invocations (read-only guarantee above).
