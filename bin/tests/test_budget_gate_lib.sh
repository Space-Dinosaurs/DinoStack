#!/usr/bin/env bash
# Purpose: Regression guard for scripts/lib/budget-gate.sh in isolation -
#          the shared repo-dir resolution, byte measurement, and
#          OK/OVER-BUDGET report shape now backing all three size-ratchet
#          gates (check-resident-budget.sh, check-skill-embed-budget.sh,
#          check-command-file-budget.sh). Exercises the exposed functions
#          directly (budget_repo_dir, budget_file_bytes, budget_eval,
#          budget_report, and, as of DS-182, budget_base_resolve/
#          budget_delta/budget_burn_line) rather than only indirectly
#          through a caller gate, so a break in the shared lib is caught
#          here even if a particular caller's own fixtures happen not to
#          exercise the broken path. The zero-extra-context budget_report
#          scenarios run under `set -euo pipefail`, matching every real
#          caller, and with no extra-context args, matching
#          check-command-file-budget.sh's call shape - this is what
#          reproduces the bash-3.2 empty-array "unbound variable"
#          regression (a bare `bash -c` without set -euo pipefail cannot).
#          Also covers the bytes == threshold boundary, which the
#          interior-only 100-vs-200 / 300-vs-200 cases do not exercise.
#
#          DS-182 scenarios (7+) build a REAL git-backed scratch fixture
#          (git init, a bare "origin" remote, one commit pushed to it)
#          rather than a mocked git, since budget_base_resolve/
#          budget_delta shell out to the real `git` binary and a mock
#          would only prove the mock's own shape - the git-backed fixture
#          proves the actual origin/main -> main fallback and the actual
#          `<ref>:<path>` object lookup work.
#
# Public API: ./bin/tests/test_budget_gate_lib.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc, git (DS-182 scenarios only - a git
#                binary is required in CI; there is no soft-skip for it,
#                since bin-tests.yml always provides one). zsh is required
#                for the bash/zsh parity assertion when running in CI (the
#                assertion FAILs if zsh is absent under CI=true); locally,
#                without zsh on PATH it is skipped (not failed) so
#                contributors without zsh installed can still run the rest
#                of the suite.
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
#               fixture files (including the DS-182 git-backed fixture
#               repos) live under a mktemp -d directory that is removed on
#               exit via trap. Does not touch network - the "origin"
#               remote used to exercise budget_base_resolve is a local
#               bare repo under the same mktemp -d, never a real network
#               fetch. Runs correctly from any cwd.

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

# --- Scenario 7: budget_eval returns 1 on overage WITHOUT calling `exit` -
#     the calling script must still be running after the call. Mutation
#     that would redden this: change budget_eval's `return 1`/`return 0`
#     back to `exit 1`/`exit 0` - the script would never reach the second
#     "still running" echo. ---
eval_no_exit_out="$(bash -c '
set -euo pipefail
source "'"$GATE_LIB"'"
if budget_eval "first" "m" 300 200 "trim" >/dev/null 2>&1; then
  echo "first-ok"
else
  echo "first-over"
fi
echo "still-running"
if budget_eval "second" "m" 100 200 "trim" >/dev/null 2>&1; then
  echo "second-ok"
else
  echo "second-over"
fi
echo "still-running-after-second"
')"

if [[ "$eval_no_exit_out" == $'first-over\nstill-running\nsecond-ok\nstill-running-after-second' ]]; then
  _pass "budget_eval returns (never exits) on both OK and OVER paths - two sequential calls both run"
else
  _fail "budget_eval did not behave as a non-exiting return - got: [$eval_no_exit_out]"
fi

# --- DS-182 git-backed fixture builder for scenarios 8-14. Builds a real
#     git repo (not a mock) with one commit on "main" pushed to a local
#     bare "origin" remote under the same mktemp -d, so
#     budget_base_resolve/budget_delta exercise the actual git plumbing
#     they shell out to. $1 = fixture dir; $2 = initial target file
#     content (written to target.txt at the base commit).
_build_git_fixture() {
  local dir="$1" base_content="$2"
  mkdir -p "$dir"
  git -C "$dir" init -q -b main
  printf '%s' "$base_content" > "$dir/target.txt"
  git -C "$dir" add -A
  git -C "$dir" -c user.email="test@example.com" -c user.name="test" commit -q -m base
  git -C "$dir" init -q --bare "$dir.origin.git"
  git -C "$dir" remote add origin "$dir.origin.git"
  git -C "$dir" push -q origin main
}

# --- Scenario 8: budget_base_resolve in a non-git directory prints
#     nothing and returns 1. ---
NONGIT_DIR="$TMP_ROOT/nongit"
mkdir -p "$NONGIT_DIR"
nongit_resolve_out="$(bash -c '
set -uo pipefail
source "'"$GATE_LIB"'"
budget_base_resolve "'"$NONGIT_DIR"'"
' 2>&1)"
nongit_resolve_rc=$?

if [[ $nongit_resolve_rc -eq 1 ]]; then
  _pass "budget_base_resolve returns 1 in a non-git directory"
else
  _fail "budget_base_resolve returned $nongit_resolve_rc in a non-git directory (expected 1): $nongit_resolve_out"
fi

if [[ -z "$nongit_resolve_out" ]]; then
  _pass "budget_base_resolve prints nothing in a non-git directory"
else
  _fail "budget_base_resolve printed [$nongit_resolve_out] in a non-git directory (expected nothing)"
fi

# --- Scenario 9: budget_base_resolve resolves "origin/main" when an
#     origin remote carries it. Mutation that would redden this: swap the
#     origin/<b> and <b> resolution order in budget_base_resolve. ---
if command -v git >/dev/null 2>&1; then
  ORIGIN_FIXTURE_DIR="$TMP_ROOT/origin_fixture"
  _build_git_fixture "$ORIGIN_FIXTURE_DIR" "hello"

  origin_resolve_out="$(bash -c '
set -uo pipefail
source "'"$GATE_LIB"'"
budget_base_resolve "'"$ORIGIN_FIXTURE_DIR"'"
')"

  if [[ "$origin_resolve_out" == "origin/main" ]]; then
    _pass "budget_base_resolve resolves origin/main when the origin remote carries it"
  else
    _fail "budget_base_resolve resolved [$origin_resolve_out], expected [origin/main]"
  fi

  # --- Scenario 10: with the origin remote removed, budget_base_resolve
  #     falls back to the bare local "main" branch. ---
  git -C "$ORIGIN_FIXTURE_DIR" remote remove origin
  noorigin_resolve_out="$(bash -c '
set -uo pipefail
source "'"$GATE_LIB"'"
budget_base_resolve "'"$ORIGIN_FIXTURE_DIR"'"
')"

  if [[ "$noorigin_resolve_out" == "main" ]]; then
    _pass "budget_base_resolve falls back to bare main with no origin remote"
  else
    _fail "budget_base_resolve resolved [$noorigin_resolve_out] with no origin remote, expected [main]"
  fi

  # --- Scenario 11: budget_delta reports the correct signed delta for a
  #     path that grew between the base commit and the working tree.
  #     Mutation that would redden this: swap the subtraction order
  #     (base_bytes - current_bytes) in budget_delta. ---
  DELTA_GROW_DIR="$TMP_ROOT/delta_grow"
  _build_git_fixture "$DELTA_GROW_DIR" "$(python3 -c "print('a' * 100, end='')")"
  python3 -c "
with open('$DELTA_GROW_DIR/target.txt', 'a') as f:
    f.write('b' * 30)
"
  delta_grow_out="$(bash -c '
set -euo pipefail
source "'"$GATE_LIB"'"
budget_delta "'"$DELTA_GROW_DIR"'" "'"$DELTA_GROW_DIR"'/target.txt" "origin/main"
')"

  if [[ "$delta_grow_out" == "30" ]]; then
    _pass "budget_delta reports +30 for a file grown 100 -> 130 B since base"
  else
    _fail "budget_delta reported [$delta_grow_out], expected [30]"
  fi

  # --- Scenario 12: budget_delta reports a negative signed delta for a
  #     path that shrank between the base commit and the working tree. ---
  DELTA_SHRINK_DIR="$TMP_ROOT/delta_shrink"
  _build_git_fixture "$DELTA_SHRINK_DIR" "$(python3 -c "print('a' * 100, end='')")"
  python3 -c "
with open('$DELTA_SHRINK_DIR/target.txt', 'w') as f:
    f.write('a' * 40)
"
  delta_shrink_out="$(bash -c '
set -euo pipefail
source "'"$GATE_LIB"'"
budget_delta "'"$DELTA_SHRINK_DIR"'" "'"$DELTA_SHRINK_DIR"'/target.txt" "origin/main"
')"

  if [[ "$delta_shrink_out" == "-60" ]]; then
    _pass "budget_delta reports -60 for a file shrunk 100 -> 40 B since base"
  else
    _fail "budget_delta reported [$delta_shrink_out], expected [-60]"
  fi

  # --- Scenario 13: budget_delta prints NOTHING and returns 2 for a path
  #     absent at the base ref - a newly-created file, never a delta equal
  #     to its own full size. Mutation that would redden this: fall back
  #     to `echo "$current_bytes"` instead of `return 2` when the
  #     `cat-file -e` existence check fails. ---
  ABSENT_AT_BASE_DIR="$TMP_ROOT/absent_at_base"
  _build_git_fixture "$ABSENT_AT_BASE_DIR" "base-only"
  printf 'brand new file' > "$ABSENT_AT_BASE_DIR/new-file.txt"

  absent_delta_out="$(bash -c '
set -uo pipefail
source "'"$GATE_LIB"'"
budget_delta "'"$ABSENT_AT_BASE_DIR"'" "'"$ABSENT_AT_BASE_DIR"'/new-file.txt" "origin/main"
' 2>&1)"
  absent_delta_rc=$?

  if [[ $absent_delta_rc -eq 2 ]]; then
    _pass "budget_delta returns 2 for a path absent at the base ref"
  else
    _fail "budget_delta returned $absent_delta_rc for a path absent at the base ref (expected 2): $absent_delta_out"
  fi

  if [[ -z "$absent_delta_out" ]]; then
    _pass "budget_delta prints nothing for a path absent at the base ref (not a delta equal to its own size)"
  else
    _fail "budget_delta printed [$absent_delta_out] for a path absent at the base ref (expected nothing)"
  fi

  # --- Scenario 14: budget_burn_line renders exactly one line and ALWAYS
  #     returns 0 - both when a base resolves (a "B/day" burn-rate line)
  #     and when it does not (a distinct "burn: SKIPPED (...)" line,
  #     never a blank output, still rc=0). $DELTA_GROW_DIR's base commit
  #     was made moments ago by _build_git_fixture, so the whole-day span
  #     floors to 1 - burn_per_day == delta_bytes exactly (+30 B), making
  #     the expected output deterministic rather than time-dependent.
  #     Mutation that would redden this: swap the headroom/burn_per_day
  #     division order, or drop the "floor at 1 day" clamp. ---
  burn_resolvable_out="$(bash -c '
set -euo pipefail
source "'"$GATE_LIB"'"
budget_burn_line "'"$DELTA_GROW_DIR"'" "'"$DELTA_GROW_DIR"'/target.txt" 999999 130
')"
  burn_resolvable_rc=$?

  if [[ $burn_resolvable_rc -eq 0 ]]; then
    _pass "budget_burn_line returns 0 when the base resolves"
  else
    _fail "budget_burn_line returned $burn_resolvable_rc when the base resolves (expected 0)"
  fi

  # headroom = 999999 - 130 = 999869; burn_per_day = 30 (delta / 1-day
  # floor); days_to_limit = 999869 / 30 = 33328 (integer division).
  expected_burn_line="burn: 30 B/day over 1 d - 33328 d to limit"
  if [[ "$burn_resolvable_out" == "$expected_burn_line" ]]; then
    _pass "budget_burn_line reports the correct B/day burn rate and days-to-limit"
  else
    _fail "budget_burn_line reported [$burn_resolvable_out], expected [$expected_burn_line]"
  fi

  burn_line_count="$(printf '%s\n' "$burn_resolvable_out" | wc -l | tr -d '[:space:]')"
  if [[ "$burn_line_count" == "1" ]]; then
    _pass "budget_burn_line prints exactly one line when the base resolves"
  else
    _fail "budget_burn_line printed $burn_line_count lines when the base resolves (expected 1): $burn_resolvable_out"
  fi

  burn_unresolvable_out="$(bash -c '
set -euo pipefail
source "'"$GATE_LIB"'"
budget_burn_line "'"$NONGIT_DIR"'" "'"$NONGIT_DIR"'/nope.txt" 999999 130
')"
  burn_unresolvable_rc=$?

  if [[ $burn_unresolvable_rc -eq 0 ]]; then
    _pass "budget_burn_line returns 0 even when the base is unresolvable"
  else
    _fail "budget_burn_line returned $burn_unresolvable_rc when the base is unresolvable (expected 0)"
  fi

  if [[ "$burn_unresolvable_out" == "burn: SKIPPED (base unresolvable)" ]]; then
    _pass "budget_burn_line renders a distinct SKIPPED line (never blank) when the base is unresolvable"
  else
    _fail "budget_burn_line printed [$burn_unresolvable_out] when the base is unresolvable, expected [burn: SKIPPED (base unresolvable)]"
  fi

  # --- Scenario 15: budget_burn_line renders a distinct SKIPPED line
  #     (never blank) when the path is absent at the resolved base ref -
  #     mirrors budget_delta's own absent-at-base contract. ---
  burn_absent_out="$(bash -c '
set -euo pipefail
source "'"$GATE_LIB"'"
budget_burn_line "'"$ABSENT_AT_BASE_DIR"'" "'"$ABSENT_AT_BASE_DIR"'/new-file.txt" 999999 130
')"
  burn_absent_rc=$?

  if [[ $burn_absent_rc -eq 0 ]]; then
    _pass "budget_burn_line returns 0 when the path is absent at base"
  else
    _fail "budget_burn_line returned $burn_absent_rc when the path is absent at base (expected 0)"
  fi

  if [[ "$burn_absent_out" == "burn: SKIPPED (absent at base origin/main)" ]]; then
    _pass "budget_burn_line renders a distinct SKIPPED line when the path is absent at base"
  else
    _fail "budget_burn_line printed [$burn_absent_out] when the path is absent at base, expected [burn: SKIPPED (absent at base origin/main)]"
  fi

  # --- Scenario 16 (DS-182 round-3 Minor): budget_burn_line omits the
  #     "- N d to limit" clause when <current_bytes> is already at or over
  #     <limit> (headroom <= 0), rather than letting bash's
  #     truncate-toward-zero integer division render a small negative
  #     headroom as a misleading "0 d to limit" (reads as "at the limit
  #     right now", not "already past it"). Reuses $DELTA_GROW_DIR
  #     (burn_per_day=30, deterministic per scenario 14's own comment).
  #     limit=125 against current_bytes=130 -> headroom=-5; pre-fix,
  #     -5/30 truncates toward zero to 0, printing the misleading
  #     "0 d to limit". Mutation that would redden this: revert
  #     `[ "$headroom" -gt 0 ]` back out of the clause guard. ---
  burn_over_ceiling_out="$(bash -c '
set -euo pipefail
source "'"$GATE_LIB"'"
budget_burn_line "'"$DELTA_GROW_DIR"'" "'"$DELTA_GROW_DIR"'/target.txt" 125 130
')"
  if [[ "$burn_over_ceiling_out" == "burn: 30 B/day over 1 d" ]]; then
    _pass "budget_burn_line omits '- N d to limit' when already over the limit (headroom -5, would pre-fix truncate to '0 d to limit')"
  else
    _fail "budget_burn_line printed [$burn_over_ceiling_out] for a headroom of -5, expected the clause omitted: [burn: 30 B/day over 1 d]"
  fi
elif [[ -n "${CI:-}" ]]; then
  _fail "git absent on PATH in CI - the DS-182 git-backed scenarios cannot be skipped here"
else
  echo "SKIP: git not found on PATH - skipping the DS-182 git-backed scenarios (non-git scenario 8 above still applies)"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
