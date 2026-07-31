#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-resident-budget.sh. The
#          round-1 defect was a bare `${BASH_SOURCE[0]}` that is unset under
#          zsh, collapsing REPO_DIR to "//" and aborting the script for any
#          contributor who runs it via `zsh scripts/check-resident-budget.sh`
#          instead of bash. This test exercises the gate script directly
#          against a scratch copy of the repo's real input files (never the
#          working tree itself), asserting: bash/zsh parity, the over-budget
#          exit path, the build-failure floor's distinct message, and the
#          THRESHOLD boundary.
#
# Public API: ./bin/tests/test_check_resident_budget.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc. zsh is used opportunistically for the
#                bash/zsh parity assertion - skipped (not failed) when zsh
#                is not on PATH.
#
# Downstream consumers: developer running locally before commit; CI
#                        (bin-sh-tests.yml auto-discovers bin/tests/test_*.sh).
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

if [[ ! -f "$GATE_SCRIPT" ]]; then
  echo "FAIL: $GATE_SCRIPT not found" >&2
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
#     touching the real working tree. It only needs: scripts/, a stub
#     build-methodology.sh (so we control methodology_bytes deterministically
#     instead of depending on the real, ever-changing build output), and the
#     two content/rules files the gate sums.
build_fixture() {
  # $1 = fixture dir; $2 = bytes the stub build-methodology.sh should print;
  # $3 = conventions.md byte count; $4 = code-standards.md byte count.
  local dir="$1" build_bytes="$2" conv_bytes="$3" cs_bytes="$4"
  mkdir -p "$dir/scripts" "$dir/content/rules"

  cp "$GATE_SCRIPT" "$dir/scripts/check-resident-budget.sh"

  # Stub build-methodology.sh: prints exactly $build_bytes bytes of 'x' to
  # stdout, nothing else - deterministic and network-free.
  python3 -c "
import sys
n = int(sys.argv[1])
sys.stdout.write('x' * n)
" "$build_bytes" > "$dir/scripts/build-methodology.sh.out"
  cat > "$dir/scripts/build-methodology.sh" <<'EOF'
#!/usr/bin/env bash
cat "$(dirname "$0")/build-methodology.sh.out"
EOF
  chmod +x "$dir/scripts/build-methodology.sh"

  python3 -c "
import sys
n = int(sys.argv[1])
sys.stdout.write('c' * n)
" "$conv_bytes" > "$dir/content/rules/conventions.md"
  python3 -c "
import sys
n = int(sys.argv[1])
sys.stdout.write('s' * n)
" "$cs_bytes" > "$dir/content/rules/code-standards.md"
}

# THRESHOLD is fixed inside the real gate script (currently 124938) - we
# don't parse or override it, so fixtures are built to land on either side
# of the *real* threshold value. Read it out of the script so this test
# tracks the ratchet automatically instead of hardcoding a copy that can
# drift from the real value.
THRESHOLD="$(grep -E '^THRESHOLD=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$THRESHOLD" ]]; then
  _fail "could not read THRESHOLD out of $GATE_SCRIPT"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

MIN_PLAUSIBLE="$(grep -E '^MIN_PLAUSIBLE_METHODOLOGY_BYTES=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"

# --- Scenario 1: bash/zsh parity (the actual round-1 regression) ---
# Under budget but above the build-failure floor:
# MIN_PLAUSIBLE < build_bytes + conv_bytes + cs_bytes < THRESHOLD.
PARITY_DIR="$TMP_ROOT/parity"
parity_build=$(( MIN_PLAUSIBLE + 100 ))
build_fixture "$PARITY_DIR" "$parity_build" 10 10

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
    _fail "bash and zsh output diverged (this is the round-1 zsh regression) - bash: [$bash_out] zsh: [$zsh_out]"
  fi
else
  echo "SKIP: zsh not found on PATH - skipping zsh parity assertion (bash-only coverage below still applies)"
fi

# --- Scenario 2: over-budget path exits non-zero with correct arithmetic ---
OVER_DIR="$TMP_ROOT/over"
over_build=$(( THRESHOLD + 500 ))
build_fixture "$OVER_DIR" "$over_build" 0 0

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

expected_overage=500
if echo "$over_out" | grep -q "overage:   $expected_overage B"; then
  _pass "over-budget fixture reports correct overage ($expected_overage B)"
else
  _fail "over-budget fixture did not report overage=$expected_overage B: $over_out"
fi

# --- Scenario 3: build-failure floor fires distinctly, not as a budget fail ---
FLOOR_DIR="$TMP_ROOT/floor"
floor_build=$(( MIN_PLAUSIBLE - 1 ))
build_fixture "$FLOOR_DIR" "$floor_build" 0 0

floor_out="$(cd "$FLOOR_DIR" && bash scripts/check-resident-budget.sh 2>&1)"
floor_rc=$?

if [[ $floor_rc -ne 0 ]]; then
  _pass "build-floor fixture exits non-zero"
else
  _fail "build-floor fixture exited 0 (expected non-zero): $floor_out"
fi

if echo "$floor_out" | grep -q "BUILD FAILURE"; then
  _pass "build-floor fixture prints BUILD FAILURE"
else
  _fail "build-floor fixture did not print BUILD FAILURE: $floor_out"
fi

if echo "$floor_out" | grep -q "OVER BUDGET"; then
  _fail "build-floor fixture incorrectly also printed OVER BUDGET (should read as a build failure, not a budget failure): $floor_out"
else
  _pass "build-floor fixture does not read as a budget failure"
fi

# --- Scenario 4: boundary - total == THRESHOLD passes ---
BOUNDARY_DIR="$TMP_ROOT/boundary"
# Split THRESHOLD across the three inputs exactly.
boundary_build=$(( THRESHOLD - 20 ))
build_fixture "$BOUNDARY_DIR" "$boundary_build" 10 10

boundary_out="$(cd "$BOUNDARY_DIR" && bash scripts/check-resident-budget.sh 2>&1)"
boundary_rc=$?

if [[ $boundary_rc -eq 0 ]]; then
  _pass "boundary fixture (total == THRESHOLD) exits 0"
else
  _fail "boundary fixture (total == THRESHOLD) exited $boundary_rc (expected 0): $boundary_out"
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
