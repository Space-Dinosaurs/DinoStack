#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-resident-budget.sh, rewritten
#          for DS-143's post-manifest-body measurement (the old version
#          measured a built METHODOLOGY.md plus two rules files that are no
#          longer part of the resident set; this version's fixtures build a
#          scratch claude-managed-content.md with a manifest comment
#          followed by a body of controlled size). Exercises: bash/zsh
#          parity, the over-budget exit path, the body-below-floor path
#          (gutted content, manifest left behind), the missing-terminator
#          path (file no longer shaped as manifest+body at all), and the
#          THRESHOLD boundary.
#
# Public API: ./bin/tests/test_check_resident_budget.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc, python3, grep, cut (build_fixture() calls
#                python3 to write deterministic fixture files; THRESHOLD and
#                MIN_PLAUSIBLE_BODY_BYTES are parsed out of the gate script
#                with grep|cut). zsh is required for the bash/zsh parity
#                assertion when running in CI (the assertion FAILs if zsh is
#                absent under CI=true); locally, without zsh on PATH it is
#                skipped (not failed) so contributors without zsh installed
#                can still run the rest of the suite.
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script missing -> immediate FAIL. Any scenario's
#                observed exit code or message does not match the expected
#                shape -> FAIL naming the scenario and what was observed.
#
# Test hygiene: never mutates any tracked file in the working tree. All
#               fixture repos and stub scripts live under a mktemp -d
#               directory that is removed on exit via trap. Does not touch
#               network. Runs correctly from any cwd.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-resident-budget.sh"
GATE_LIB="$REPO_DIR/scripts/lib/budget-gate.sh"

if [[ ! -f "$GATE_SCRIPT" ]]; then
  echo "FAIL: $GATE_SCRIPT not found" >&2
  exit 1
fi

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

# --- Build a scratch fixture repo the gate script can run against without
#     touching the real working tree. It needs: scripts/ (copies of the
#     real gate script and the shared lib it sources) and
#     content/templates/claude-managed-content.md shaped as a manifest
#     HTML comment followed by a body of controlled size, so we control
#     body_bytes deterministically.
#
# $1 = fixture dir; $2 = body byte count (the literal string NONE means "no
#      closing --> at all", exercising the missing-terminator path); $3 =
#      optional manifest comment prefix length in bytes (defaults to a
#      short fixed manifest).
build_fixture() {
  local dir="$1" body_bytes="$2" manifest_bytes="${3:-50}"
  mkdir -p "$dir/scripts/lib" "$dir/content/templates"

  cp "$GATE_SCRIPT" "$dir/scripts/check-resident-budget.sh"
  cp "$GATE_LIB" "$dir/scripts/lib/budget-gate.sh"

  if [[ "$body_bytes" == "NONE" ]]; then
    # No closing "-->" anywhere in the file - exercises the
    # missing-terminator failure path.
    python3 -c "
import sys
n = int(sys.argv[1])
sys.stdout.write('m' * n)
" "$manifest_bytes" > "$dir/content/templates/claude-managed-content.md"
    return
  fi

  python3 -c "
import sys
manifest_n = int(sys.argv[1])
body_n = int(sys.argv[2])
sys.stdout.write('<!-- ' + ('m' * manifest_n) + ' -->')
sys.stdout.write('x' * body_n)
" "$manifest_bytes" "$body_bytes" > "$dir/content/templates/claude-managed-content.md"
}

# THRESHOLD and MIN_PLAUSIBLE_BODY_BYTES are fixed inside the real gate
# script and ratchet over time - we don't hardcode a copy that can drift
# from the real value; read them out of the script instead.
THRESHOLD="$(grep -E '^THRESHOLD=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$THRESHOLD" ]]; then
  _fail "could not read THRESHOLD out of $GATE_SCRIPT"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

MIN_PLAUSIBLE="$(grep -E '^MIN_PLAUSIBLE_BODY_BYTES=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$MIN_PLAUSIBLE" ]]; then
  _fail "could not read MIN_PLAUSIBLE_BODY_BYTES out of $GATE_SCRIPT"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

# --- Scenario 1: bash/zsh parity ---
# Under budget but above the body-below-floor floor:
# MIN_PLAUSIBLE < body_bytes < THRESHOLD.
PARITY_DIR="$TMP_ROOT/parity"
parity_body=$(( MIN_PLAUSIBLE + 50 ))
build_fixture "$PARITY_DIR" "$parity_body"

bash_out="$(cd "$PARITY_DIR" && bash scripts/check-resident-budget.sh 2>&1)"
bash_rc=$?

if [[ $bash_rc -eq 0 ]]; then
  _pass "bash invocation exits 0 on an under-budget fixture"
else
  _fail "bash invocation exited $bash_rc on an under-budget fixture (expected 0): $bash_out"
fi

if command -v zsh >/dev/null 2>&1; then
  zsh_out="$(cd "$PARITY_DIR" && zsh scripts/check-resident-budget.sh 2>&1)"
  zsh_rc=$?

  if [[ $zsh_rc -eq 0 ]]; then
    _pass "zsh invocation exits 0 on an under-budget fixture"
  else
    _fail "zsh invocation exited $zsh_rc on an under-budget fixture (expected 0): $zsh_out"
  fi

  if [[ "$bash_out" == "$zsh_out" ]]; then
    _pass "bash and zsh produce byte-identical output"
  else
    _fail "bash and zsh output diverged - bash: [$bash_out] zsh: [$zsh_out]"
  fi
elif [[ -n "${CI:-}" ]]; then
  _fail "zsh absent on PATH in CI - parity assertion cannot be skipped here"
else
  echo "SKIP: zsh not found on PATH - skipping zsh parity assertion (bash-only coverage below still applies)"
fi

# --- Scenario 2: over-budget path exits non-zero with correct arithmetic ---
OVER_DIR="$TMP_ROOT/over"
over_body=$(( THRESHOLD + 250 ))
build_fixture "$OVER_DIR" "$over_body"

over_out="$(cd "$OVER_DIR" && bash scripts/check-resident-budget.sh 2>&1)"
over_rc=$?

if [[ $over_rc -ne 0 ]]; then
  _pass "over-budget fixture exits non-zero"
else
  _fail "over-budget fixture exited 0 (expected non-zero): $over_out"
fi

if echo "$over_out" | grep -q "OVER BUDGET"; then
  _pass "over-budget fixture prints OVER BUDGET"
else
  _fail "over-budget fixture did not print OVER BUDGET: $over_out"
fi

expected_overage=250
if echo "$over_out" | grep -q "overage:   $expected_overage B"; then
  _pass "over-budget fixture reports correct overage ($expected_overage B)"
else
  _fail "over-budget fixture did not report overage=$expected_overage B: $over_out"
fi

# --- Scenario 3: body-below-floor fires distinctly, not as a budget fail ---
FLOOR_DIR="$TMP_ROOT/floor"
floor_body=$(( MIN_PLAUSIBLE - 1 ))
build_fixture "$FLOOR_DIR" "$floor_body"

floor_out="$(cd "$FLOOR_DIR" && bash scripts/check-resident-budget.sh 2>&1)"
floor_rc=$?

if [[ $floor_rc -ne 0 ]]; then
  _pass "body-below-floor fixture exits non-zero"
else
  _fail "body-below-floor fixture exited 0 (expected non-zero): $floor_out"
fi

if echo "$floor_out" | grep -q "BODY FAILURE"; then
  _pass "body-below-floor fixture prints BODY FAILURE"
else
  _fail "body-below-floor fixture did not print BODY FAILURE: $floor_out"
fi

if echo "$floor_out" | grep -q "OVER BUDGET"; then
  _fail "body-below-floor fixture incorrectly also printed OVER BUDGET (should read as a body failure, not a budget failure): $floor_out"
else
  _pass "body-below-floor fixture does not read as a budget failure"
fi

# --- Scenario 4: missing manifest terminator fails distinctly ---
NOTERM_DIR="$TMP_ROOT/noterm"
build_fixture "$NOTERM_DIR" "NONE"

noterm_out="$(cd "$NOTERM_DIR" && bash scripts/check-resident-budget.sh 2>&1)"
noterm_rc=$?

if [[ $noterm_rc -ne 0 ]]; then
  _pass "missing-terminator fixture exits non-zero"
else
  _fail "missing-terminator fixture exited 0 (expected non-zero): $noterm_out"
fi

if echo "$noterm_out" | grep -q "could not find manifest comment terminator"; then
  _pass "missing-terminator fixture prints the terminator-not-found message"
else
  _fail "missing-terminator fixture did not print the expected message: $noterm_out"
fi

# --- Scenario 5: boundary - body == THRESHOLD passes ---
BOUNDARY_DIR="$TMP_ROOT/boundary"
build_fixture "$BOUNDARY_DIR" "$THRESHOLD"

boundary_out="$(cd "$BOUNDARY_DIR" && bash scripts/check-resident-budget.sh 2>&1)"
boundary_rc=$?

if [[ $boundary_rc -eq 0 ]]; then
  _pass "boundary fixture (body == THRESHOLD) exits 0"
else
  _fail "boundary fixture (body == THRESHOLD) exited $boundary_rc (expected 0): $boundary_out"
fi

if echo "$boundary_out" | grep -q "headroom:  0 B"; then
  _pass "boundary fixture reports zero headroom"
else
  _fail "boundary fixture did not report zero headroom: $boundary_out"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
