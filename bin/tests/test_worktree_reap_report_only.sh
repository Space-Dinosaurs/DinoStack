#!/usr/bin/env bash
#
# Purpose: Mechanical pinning test for automation/dinostack-worktree-reap/
#          run.sh's never-removal-capable property (DS-189 round-2
#          integration fix, Minor 8): asserts every ds-cleanup-worktrees
#          invocation inside run.sh contains `--report` and that none of
#          them contains `--archive-unproven`. A run.sh that ever drops
#          `--report` or adds `--archive-unproven` would turn a report-only
#          scheduled job into a removal-capable one - this test exists to
#          catch that mechanically, not via prose review. Empty-discovery is
#          a hard failure (zero invocations found reddens the test, not a
#          vacuous pass).
#
# Public API: ./bin/tests/test_worktree_reap_report_only.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, grep. Reads
#                automation/dinostack-worktree-reap/run.sh directly (no
#                fixture - this is a pin on the real shipped script).
#
# Downstream consumers: bin-sh-tests CI job (auto-collected via the
#                        bin/tests/test_*.sh glob in
#                        .github/workflows/bin-tests.yml).
#
# Failure modes: fails loud (not silently 0/0) when the invocation grep
#                finds zero matches - a change to run.sh that renames or
#                restructures the ds-cleanup-worktrees call away from a
#                greppable single-line form must redden this test, not pass
#                it vacuously.
#
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_SH="$REPO_ROOT/automation/dinostack-worktree-reap/run.sh"

FAILURES=0
fail() {
  echo "FAIL: $1" >&2
  FAILURES=$((FAILURES + 1))
}
pass() {
  echo "PASS: $1"
}

if [[ ! -f "$RUN_SH" ]]; then
  fail "run.sh not found at $RUN_SH"
  exit 1
fi

# Every line in run.sh that actually EXECUTES ds-cleanup-worktrees (not a
# line that merely echoes or assigns the variable holding its resolved
# binary path, $DS_CLEANUP_BIN) - i.e. a line invoking it via $PYTHON_BIN.
mapfile -t invocations < <(grep -n '"\$PYTHON_BIN" "\$DS_CLEANUP_BIN"' "$RUN_SH")

if [[ "${#invocations[@]}" -eq 0 ]]; then
  fail "found zero \$DS_CLEANUP_BIN invocation lines in run.sh - empty discovery is a hard failure, not a vacuous pass"
else
  pass "found ${#invocations[@]} \$DS_CLEANUP_BIN invocation line(s) in run.sh"
fi

MISSING_REPORT=0
HAS_ARCHIVE=0
for line in "${invocations[@]}"; do
  content="${line#*:}"
  if [[ "$content" != *"--report"* ]]; then
    fail "invocation line missing --report: $line"
    MISSING_REPORT=$((MISSING_REPORT + 1))
  fi
  if [[ "$content" == *"--archive-unproven"* ]]; then
    fail "invocation line contains --archive-unproven (removal-capable): $line"
    HAS_ARCHIVE=$((HAS_ARCHIVE + 1))
  fi
done

if [[ "$MISSING_REPORT" -eq 0 && "${#invocations[@]}" -gt 0 ]]; then
  pass "every invocation line contains --report"
fi
if [[ "$HAS_ARCHIVE" -eq 0 && "${#invocations[@]}" -gt 0 ]]; then
  pass "no invocation line contains --archive-unproven"
fi

if [[ "$FAILURES" -gt 0 ]]; then
  echo "=== $FAILURES failure(s) ===" >&2
  exit 1
fi

echo "=== all checks passed ==="
exit 0
