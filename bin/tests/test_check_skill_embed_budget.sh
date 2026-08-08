#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-skill-embed-budget.sh. Exercises
#          bash/zsh parity, the floor-fail path (embed regression to a
#          pointer-only skill), the ceiling-fail path (payload above the
#          verified-safe injection range), and the pass path (in range).
#
# Public API: ./bin/tests/test_check_skill_embed_budget.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc, python3, grep, cut (build_fixture() calls
#                python3 to write a deterministic-size stub SKILL.md; FLOOR
#                and CEILING are parsed out of the gate script with
#                grep|cut). zsh is required for the bash/zsh parity
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
#               fixture repos and stub files live under a mktemp -d
#               directory that is removed on exit via trap. Does not touch
#               network. Runs correctly from any cwd.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-skill-embed-budget.sh"
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
#     .claude/skills/agentic-engineering/SKILL.md of a controlled size.
# $1 = fixture dir; $2 = SKILL.md byte count.
build_fixture() {
  local dir="$1" skill_bytes="$2"
  mkdir -p "$dir/scripts/lib" "$dir/.claude/skills/agentic-engineering"

  cp "$GATE_SCRIPT" "$dir/scripts/check-skill-embed-budget.sh"
  cp "$GATE_LIB" "$dir/scripts/lib/budget-gate.sh"

  python3 -c "
import sys
n = int(sys.argv[1])
sys.stdout.write('x' * n)
" "$skill_bytes" > "$dir/.claude/skills/agentic-engineering/SKILL.md"
}

# FLOOR and CEILING are fixed inside the real gate script and ratchet over
# time - we don't hardcode a copy that can drift from the real value; read
# them out of the script instead.
FLOOR="$(grep -E '^FLOOR=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$FLOOR" ]]; then
  _fail "could not read FLOOR out of $GATE_SCRIPT"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

CEILING="$(grep -E '^CEILING=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$CEILING" ]]; then
  _fail "could not read CEILING out of $GATE_SCRIPT"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

# --- Scenario 1: bash/zsh parity on a passing (in-range) fixture ---
midpoint=$(( (FLOOR + CEILING) / 2 ))
PARITY_DIR="$TMP_ROOT/parity"
build_fixture "$PARITY_DIR" "$midpoint"

bash_out="$(cd "$PARITY_DIR" && bash scripts/check-skill-embed-budget.sh 2>&1)"
bash_rc=$?

if [[ $bash_rc -eq 0 ]]; then
  _pass "bash invocation exits 0 on an in-range fixture"
else
  _fail "bash invocation exited $bash_rc on an in-range fixture (expected 0): $bash_out"
fi

if command -v zsh >/dev/null 2>&1; then
  zsh_out="$(cd "$PARITY_DIR" && zsh scripts/check-skill-embed-budget.sh 2>&1)"
  zsh_rc=$?

  if [[ $zsh_rc -eq 0 ]]; then
    _pass "zsh invocation exits 0 on an in-range fixture"
  else
    _fail "zsh invocation exited $zsh_rc on an in-range fixture (expected 0): $zsh_out"
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

# --- Scenario 2: below FLOOR fails as an embed regression ---
FLOOR_DIR="$TMP_ROOT/floor"
floor_fail_size=$(( FLOOR - 1 ))
build_fixture "$FLOOR_DIR" "$floor_fail_size"

floor_out="$(cd "$FLOOR_DIR" && bash scripts/check-skill-embed-budget.sh 2>&1)"
floor_rc=$?

if [[ $floor_rc -ne 0 ]]; then
  _pass "below-floor fixture exits non-zero"
else
  _fail "below-floor fixture exited 0 (expected non-zero): $floor_out"
fi

if echo "$floor_out" | grep -q "BELOW FLOOR"; then
  _pass "below-floor fixture prints BELOW FLOOR"
else
  _fail "below-floor fixture did not print BELOW FLOOR: $floor_out"
fi

# --- Scenario 3: above CEILING fails with the safety-boundary framing ---
CEILING_DIR="$TMP_ROOT/ceiling"
ceiling_fail_size=$(( CEILING + 1 ))
build_fixture "$CEILING_DIR" "$ceiling_fail_size"

ceiling_out="$(cd "$CEILING_DIR" && bash scripts/check-skill-embed-budget.sh 2>&1)"
ceiling_rc=$?

if [[ $ceiling_rc -ne 0 ]]; then
  _pass "above-ceiling fixture exits non-zero"
else
  _fail "above-ceiling fixture exited 0 (expected non-zero): $ceiling_out"
fi

if echo "$ceiling_out" | grep -q "ABOVE CEILING"; then
  _pass "above-ceiling fixture prints ABOVE CEILING"
else
  _fail "above-ceiling fixture did not print ABOVE CEILING: $ceiling_out"
fi

expected_overage=1
if echo "$ceiling_out" | grep -q "($expected_overage B over)"; then
  _pass "above-ceiling fixture reports correct overage ($expected_overage B)"
else
  _fail "above-ceiling fixture did not report overage=$expected_overage B: $ceiling_out"
fi

# --- Scenario 4: exact FLOOR and exact CEILING both pass (inclusive bounds) ---
AT_FLOOR_DIR="$TMP_ROOT/at_floor"
build_fixture "$AT_FLOOR_DIR" "$FLOOR"

at_floor_out="$(cd "$AT_FLOOR_DIR" && bash scripts/check-skill-embed-budget.sh 2>&1)"
at_floor_rc=$?

if [[ $at_floor_rc -eq 0 ]]; then
  _pass "fixture at exactly FLOOR exits 0"
else
  _fail "fixture at exactly FLOOR exited $at_floor_rc (expected 0): $at_floor_out"
fi

AT_CEILING_DIR="$TMP_ROOT/at_ceiling"
build_fixture "$AT_CEILING_DIR" "$CEILING"

at_ceiling_out="$(cd "$AT_CEILING_DIR" && bash scripts/check-skill-embed-budget.sh 2>&1)"
at_ceiling_rc=$?

if [[ $at_ceiling_rc -eq 0 ]]; then
  _pass "fixture at exactly CEILING exits 0"
else
  _fail "fixture at exactly CEILING exited $at_ceiling_rc (expected 0): $at_ceiling_out"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
