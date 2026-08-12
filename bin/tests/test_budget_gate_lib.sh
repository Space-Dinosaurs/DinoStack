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
#          broken path. The zero-extra-context budget_report scenarios run
#          under `set -euo pipefail`, matching every real caller, and with
#          no extra-context args, matching check-command-file-budget.sh's
#          call shape - this is what reproduces the bash-3.2 empty-array
#          "unbound variable" regression (a bare `bash -c` without
#          set -euo pipefail cannot). Also covers the bytes == threshold
#          boundary, which the interior-only 100-vs-200 / 300-vs-200 cases
#          do not exercise.
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

# --- Scenario 3: budget_report OK path (bytes <= threshold). Invoked with
#     zero extra-context args, matching check-command-file-budget.sh's real
#     call shape, and under `set -euo pipefail` like every real caller -
#     this is the exact condition that let the bash-3.2 empty-array
#     "unbound variable" regression through undetected: without
#     set -euo pipefail this scenario cannot reproduce it. ---
report_ok_out="$(bash -c '
set -euo pipefail
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

# --- Scenario 4: budget_report OVER BUDGET path (bytes > threshold). Zero
#     extra-context args and set -euo pipefail, same rationale as
#     Scenario 3. ---
report_over_out="$(bash -c '
set -euo pipefail
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
set -euo pipefail
source "'"$GATE_LIB"'"
budget_report "widget check" "widget.txt" 100 200 "trim the widget" "extra context: 42 B" 2>&1
')"
if echo "$report_extra_out" | grep -q "extra context: 42 B"; then
  _pass "budget_report prints an optional extra context line"
else
  _fail "budget_report did not print the optional extra context line: $report_extra_out"
fi

# --- Scenario 5b: bytes == threshold boundary (OK path, headroom 0 B).
#     The gate uses `-le`, not `-lt` - only the equality case can catch a
#     `-le` -> `-lt` mutation; the 100-vs-200 and 300-vs-200 cases above
#     both skip past the boundary entirely. ---
report_boundary_out="$(bash -c '
set -euo pipefail
source "'"$GATE_LIB"'"
budget_report "widget check" "widget.txt" 200 200 "trim the widget" 2>&1
')"
report_boundary_rc=$?

if [[ $report_boundary_rc -eq 0 ]]; then
  _pass "budget_report exits 0 when bytes (200) == threshold (200)"
else
  _fail "budget_report exited $report_boundary_rc when bytes == threshold (expected 0): $report_boundary_out"
fi

if echo "$report_boundary_out" | grep -q "headroom:  0 B"; then
  _pass "budget_report boundary case reports 0 B headroom"
else
  _fail "budget_report boundary case did not report 0 B headroom: $report_boundary_out"
fi

# --- Scenario 5c: zero-extra-context budget_report call under the literal
#     /bin/bash binary, not whatever `bash` resolves to on PATH. This is
#     the specific historical regression: macOS ships bash 3.2 as
#     /bin/bash (bash >=4.4 tolerates expanding an empty array under
#     set -u; 3.2 does not), and the gate scripts are invoked as
#     `bash scripts/...` - which, run on a contributor's Mac without a
#     newer bash on PATH, resolves to that /bin/bash. This scenario always
#     runs (never skips) so the assertion is present on any runner where
#     /bin/bash exists, whatever its version - on a 3.2 /bin/bash it fails
#     red on the historical bug; on a >=4.4 /bin/bash (e.g. Ubuntu CI) it
#     still asserts the zero-extras call path works under set -u, per the
#     "must not silently skip" rule this repo applies to guarded
#     assertions (bin/tests/test_check_resident_budget.sh is the pattern). ---
if [[ -x /bin/bash ]]; then
  bin_bash_out="$(/bin/bash -c '
set -euo pipefail
source "'"$GATE_LIB"'"
budget_report "widget check" "widget.txt" 100 200 "trim the widget" 2>&1
')"
  bin_bash_rc=$?

  if [[ $bin_bash_rc -eq 0 ]]; then
    _pass "/bin/bash: budget_report exits 0 for a zero-extra-context call under set -euo pipefail"
  else
    _fail "/bin/bash: budget_report exited $bin_bash_rc for a zero-extra-context call under set -euo pipefail (expected 0) - this is the bash-3.2 empty-array regression: $bin_bash_out"
  fi

  if echo "$bin_bash_out" | grep -q "widget check: OK"; then
    _pass "/bin/bash: budget_report prints the header/status line"
  else
    _fail "/bin/bash: budget_report did not print the header/status line: $bin_bash_out"
  fi
elif [[ -n "${CI:-}" ]]; then
  _fail "/bin/bash absent in CI - the bash-3.2 zero-extra-context assertion cannot be skipped here"
else
  echo "SKIP: /bin/bash not found - skipping the explicit /bin/bash zero-extra-context assertion"
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
