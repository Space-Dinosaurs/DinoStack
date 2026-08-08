#!/usr/bin/env bash
# Purpose: Regression guard for scripts/lib/budget-gate.sh in isolation -
#          the shared repo-dir resolution, byte measurement, and
#          OK/OVER-BUDGET report shape now backing all three size-ratchet
#          gates (check-resident-budget.sh, check-skill-embed-budget.sh,
#          check-command-file-budget.sh). Exercises the three exposed
#          functions directly (budget_repo_dir, budget_file_bytes,
#          budget_report) rather than only indirectly through a caller
#          gate, so a break in the shared lib is caught here even if a
#          particular caller's own fixtures happen not to exercise the
#          broken path.
#
# Public API: ./bin/tests/test_budget_gate_lib.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc. zsh is required for the bash/zsh parity
#                assertion when running in CI (the assertion FAILs if zsh
#                is absent under CI=true); locally, without zsh on PATH it
#                is skipped (not failed) so contributors without zsh
#                installed can still run the rest of the suite.
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: lib file missing -> immediate FAIL. Any scenario's
#                observed exit code or message does not match the expected
#                shape -> FAIL naming the scenario and what was observed.
#
# Test hygiene: never mutates any tracked file in the working tree. All
#               fixture files live under a mktemp -d directory that is
#               removed on exit via trap. Does not touch network. Runs
#               correctly from any cwd.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_LIB="$REPO_DIR/scripts/lib/budget-gate.sh"

if [[ ! -f "$GATE_LIB" ]]; then
  echo "FAIL: $GATE_LIB not found" >&2
  exit 1
fi

PASS=0
FAIL=0

_fail() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

_pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  rm -rf "$TMP_ROOT"
}
trap _cleanup EXIT

# --- Scenario 1: budget_repo_dir returns the parent of the given dir ---
repo_dir_out="$(bash -c '
source "'"$GATE_LIB"'"
budget_repo_dir "/some/repo/scripts"
')"
if [[ "$repo_dir_out" == "/some/repo" ]]; then
  _pass "budget_repo_dir(/some/repo/scripts) == /some/repo"
else
  _fail "budget_repo_dir(/some/repo/scripts) returned [$repo_dir_out], expected [/some/repo]"
fi

# --- Scenario 2: budget_file_bytes measures a known-size fixture file ---
FIXTURE_FILE="$TMP_ROOT/fixture.txt"
python3 -c "
import sys
sys.stdout.write('x' * 500)
" > "$FIXTURE_FILE"

bytes_out="$(bash -c '
source "'"$GATE_LIB"'"
budget_file_bytes "'"$FIXTURE_FILE"'"
')"
if [[ "$bytes_out" == "500" ]]; then
  _pass "budget_file_bytes reports 500 B for a 500 B fixture"
else
  _fail "budget_file_bytes reported [$bytes_out], expected [500]"
fi

# --- Scenario 3: budget_report OK path (bytes <= threshold) ---
report_ok_out="$(bash -c '
source "'"$GATE_LIB"'"
budget_report "widget check" "widget.txt" 100 200 "trim the widget" 2>&1
')"
report_ok_rc=$?

if [[ $report_ok_rc -eq 0 ]]; then
  _pass "budget_report exits 0 when bytes (100) <= threshold (200)"
else
  _fail "budget_report exited $report_ok_rc when bytes <= threshold (expected 0): $report_ok_out"
fi

if echo "$report_ok_out" | grep -q "widget check: OK"; then
  _pass "budget_report OK path prints the header/status line"
else
  _fail "budget_report OK path did not print the header/status line: $report_ok_out"
fi

if echo "$report_ok_out" | grep -q "headroom:  100 B"; then
  _pass "budget_report OK path reports correct headroom (100 B)"
else
  _fail "budget_report OK path did not report correct headroom: $report_ok_out"
fi

# --- Scenario 4: budget_report OVER BUDGET path (bytes > threshold) ---
report_over_out="$(bash -c '
source "'"$GATE_LIB"'"
budget_report "widget check" "widget.txt" 300 200 "trim the widget" 2>&1
')"
report_over_rc=$?

if [[ $report_over_rc -ne 0 ]]; then
  _pass "budget_report exits non-zero when bytes (300) > threshold (200)"
else
  _fail "budget_report exited 0 when bytes > threshold (expected non-zero): $report_over_out"
fi

if echo "$report_over_out" | grep -q "widget check: OVER BUDGET"; then
  _pass "budget_report OVER path prints the header/status line"
else
  _fail "budget_report OVER path did not print the header/status line: $report_over_out"
fi

if echo "$report_over_out" | grep -q "overage:   100 B"; then
  _pass "budget_report OVER path reports correct overage (100 B)"
else
  _fail "budget_report OVER path did not report correct overage: $report_over_out"
fi

if echo "$report_over_out" | grep -q "trim the widget"; then
  _pass "budget_report OVER path prints the remediation text"
else
  _fail "budget_report OVER path did not print the remediation text: $report_over_out"
fi

# --- Scenario 5: budget_report with an extra context line, OK path ---
report_extra_out="$(bash -c '
source "'"$GATE_LIB"'"
budget_report "widget check" "widget.txt" 100 200 "trim the widget" "extra context: 42 B" 2>&1
')"
if echo "$report_extra_out" | grep -q "extra context: 42 B"; then
  _pass "budget_report prints an optional extra context line"
else
  _fail "budget_report did not print the optional extra context line: $report_extra_out"
fi

# --- Scenario 6: bash/zsh parity on budget_file_bytes ---
if command -v zsh >/dev/null 2>&1; then
  zsh_bytes_out="$(zsh -c '
source "'"$GATE_LIB"'"
budget_file_bytes "'"$FIXTURE_FILE"'"
')"
  if [[ "$zsh_bytes_out" == "500" ]]; then
    _pass "zsh: budget_file_bytes reports 500 B for a 500 B fixture"
  else
    _fail "zsh: budget_file_bytes reported [$zsh_bytes_out], expected [500]"
  fi
elif [[ -n "${CI:-}" ]]; then
  _fail "zsh absent on PATH in CI - parity assertion cannot be skipped here"
else
  echo "SKIP: zsh not found on PATH - skipping zsh parity assertion (bash-only coverage above still applies)"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
