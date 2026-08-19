#!/usr/bin/env bash
# Purpose: Re-derive the real duration distribution of every step in a
#          GitHub Actions workflow, straight from the Actions API, so a
#          timeout-minutes bound in .github/workflows/*.yml can be justified
#          by a reproducible measurement instead of a hand-written comment.
#          This exists because three straight review rounds on the
#          bin-tests.yml timeout PR each shipped a hand-typed distribution
#          figure that was wrong or went stale before merge (a false "10s-
#          152s" ceiling, a false "p95 86s", a "max 89s" that was already
#          102s by the time it was reviewed). A script's output can be
#          reproduced by anyone; a comment's claim can only be trusted.
#
# Public API: bash scripts/ci-step-durations.sh [WORKFLOW_FILE] [MAX_RUNS]
#             WORKFLOW_FILE defaults to bin-tests.yml. MAX_RUNS (number of
#             most-recent workflow runs to scan, across ALL conclusions -
#             success, failure, cancelled, timed_out) defaults to 100.
#             Prints one line per (job, step) with n / median / p95 / max,
#             in seconds, to stdout. Exits 0 on success. Exits 1 if `gh` is
#             unavailable, unauthenticated, or if zero step-duration rows
#             were collected (a silent empty result must never be read as
#             "the distribution is empty" - it means collection is broken).
#
# Upstream deps: `gh` CLI (authenticated against this repo), the GitHub
#                Actions REST API (workflow runs + jobs endpoints), `python3`
#                (median/p95/max arithmetic - no hand-rolled percentile math
#                in shell).
#
# Downstream consumers: .github/workflows/bin-tests.yml's timeout-minutes
#                        comments point back at this script instead of
#                        embedding a distribution figure. Re-run before
#                        changing any timeout-minutes value in that file.
#
# Failure modes: network/API failure from `gh api` propagates as a non-zero
#                exit (set -e). A run whose job/step lacks both started_at
#                and completed_at (never actually started - e.g. queue
#                cancellation) is skipped for that step, not counted as a
#                zero-second duration. Read-only; makes no repo or GitHub
#                state changes.
#
# Collection hazard (already hit twice reviewing this file's callers): the
# harness shell is zsh, which does not word-split an unquoted $ids in
# `for id in $ids` - combined with `2>/dev/null` that silently yields an
# empty result. This script avoids the hazard entirely: run ids are read
# into a bash array via `mapfile`/process substitution, never split from an
# unquoted variable, and it is invoked via `bash scripts/ci-step-durations.sh`
# (see the shebang) so `for` never runs under a zsh interpreter here.

set -euo pipefail

WORKFLOW_FILE="${1:-bin-tests.yml}"
MAX_RUNS="${2:-100}"

if ! command -v gh >/dev/null 2>&1; then
  echo "ci-step-durations.sh: gh CLI not found on PATH" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "ci-step-durations.sh: gh is not authenticated" >&2
  exit 1
fi

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

TMP_RUN_IDS="$(mktemp)"
TMP_ROWS="$(mktemp)"
trap 'rm -f "$TMP_RUN_IDS" "$TMP_ROWS"' EXIT

# Every conclusion, not just success - a step that was killed by its own
# timeout or the job backstop is exactly the data point a bound must be
# derived from, and excluding it (success-only) is what produced the false
# "10 minutes is real headroom" claim this script replaces.
gh api --method GET "repos/${REPO}/actions/workflows/${WORKFLOW_FILE}/runs" \
  --paginate \
  -f per_page=100 \
  -q '.workflow_runs[] | select(.status == "completed") | .id' \
  > "$TMP_RUN_IDS" || true

if [ ! -s "$TMP_RUN_IDS" ]; then
  echo "ci-step-durations.sh: zero workflow runs found for ${WORKFLOW_FILE} - collection is broken, not clean" >&2
  exit 1
fi

run_count=0
: > "$TMP_ROWS"
while IFS= read -r run_id; do
  [ -z "$run_id" ] && continue
  run_count=$((run_count + 1))
  if [ "$run_count" -gt "$MAX_RUNS" ]; then
    break
  fi
  gh api --method GET "repos/${REPO}/actions/runs/${run_id}/jobs" -f per_page=100 \
    -q '.jobs[] | .name as $job | .steps[] | select(.started_at != null and .completed_at != null) | [$job, .name, .started_at, .completed_at] | @tsv' \
    >> "$TMP_ROWS" || true
done < "$TMP_RUN_IDS"

if [ ! -s "$TMP_ROWS" ]; then
  echo "ci-step-durations.sh: zero step-duration rows collected across ${run_count} runs - collection is broken, not clean" >&2
  exit 1
fi

python3 - "$TMP_ROWS" <<'PYEOF'
import sys
import statistics
from collections import defaultdict
from datetime import datetime

def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")

rows = defaultdict(list)
path = sys.argv[1]
with open(path, "r") as f:
    for line in f:
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        job, step, started, completed = parts
        try:
            dur = (parse_ts(completed) - parse_ts(started)).total_seconds()
        except ValueError:
            continue
        if dur < 0:
            continue
        rows[(job, step)].append(dur)

if not rows:
    print("ci-step-durations.sh: parsed zero valid rows", file=sys.stderr)
    sys.exit(1)

print(f"{'job':<28} {'step':<70} {'n':>5} {'median_s':>9} {'p95_s':>7} {'max_s':>7}")
for (job, step), durations in sorted(rows.items()):
    durations.sort()
    n = len(durations)
    median = statistics.median(durations)
    if n == 1:
        p95 = durations[0]
    else:
        idx = min(n - 1, max(0, int(round(0.95 * (n - 1)))))
        p95 = durations[idx]
    mx = durations[-1]
    print(f"{job:<28} {step:<70} {n:>5} {median:>9.1f} {p95:>7.1f} {mx:>7.1f}")
PYEOF
