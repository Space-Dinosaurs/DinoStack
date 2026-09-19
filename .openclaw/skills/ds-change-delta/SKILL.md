---
name: ds-change-delta
description: "Render a before/after telemetry delta bracketing a methodology-change"
user-invocable: true
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
ds-change-delta --cut <SHA|ISO8601> [--cut-repo PATH] [--window-days N] --repo PATH [--repo PATH ...] [--json]
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
- `--json` for the full machine-readable report; default is a fixed-width
  table.

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

## What this tool does NOT measure

- **Skeptic-loop yield per round** - this repo's telemetry cannot support
  that measurement at all (see `MEMORY.md`'s KNW-20260818-002 through
  -006); it is out of scope here and is never synthesized from a proxy
  signal.
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
state. Every subprocess call is one of `git show`, `gh repo view`, or
`gh api graphql` (all read-only). See
`bin/tests/test_ds_change_delta.py`'s R5 test for the enforced argv
allowlist and a fixture-repo HEAD/status byte-identity assertion.

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
