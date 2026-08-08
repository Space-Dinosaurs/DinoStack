#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-command-file-budget.sh.
#          Proves the gate actually fails on growth of content/commands/
#          ds-implement-ticket.md, not merely that it exits 0 today: builds
#          a scratch fixture repo containing a COPY of the real target file
#          plus enough appended padding to clear the gate's live headroom
#          (headroom + 1024 B, computed from the real THRESHOLD_BYTES and
#          the real file's current size - NOT a fixed 1024 B pad, which
#          would stay under budget and silently pass once THRESHOLD_BYTES
#          headroom exceeds it) and asserts the gate reports over budget
#          against it, then asserts the gate still passes against the real
#          file at its current size. Also asserts the two halves of the
#          R1-Critical fix directly, so either regressing silently: the
#          gate emits a `::error::` workflow-command annotation on
#          overage, and the real .github/workflows/command-file-budget.yml
#          does not contain `continue-on-error`. Exercises bash/zsh parity
#          and the missing-file path too.
#
# Public API: ./bin/tests/test_check_command_file_budget.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc, python3, grep, cut (THRESHOLD_BYTES is
#                parsed out of the gate script with grep|cut so this test
#                never hardcodes a copy that can drift from the real
#                value). zsh is required for the bash/zsh parity assertion
#                when running in CI (the assertion FAILs if zsh is absent
#                under CI=true); locally, without zsh on PATH it is
#                skipped (not failed) so contributors without zsh installed
#                can still run the rest of the suite. Fixtures also carry a
#                copy of scripts/lib/budget-gate.sh, since the gate now
#                sources it.
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script or target file missing -> immediate FAIL. Any
#                scenario's observed exit code or message does not match
#                the expected shape -> FAIL naming the scenario and what
#                was observed.
#
# Test hygiene: never mutates any tracked file in the working tree. All
#               fixture repos live under a mktemp -d directory that is
#               removed on exit via trap. Does not touch network. Runs
#               correctly from any cwd.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-command-file-budget.sh"
REAL_TARGET_FILE="$REPO_DIR/content/commands/ds-implement-ticket.md"

if [[ ! -f "$GATE_SCRIPT" ]]; then
  echo "FAIL: $GATE_SCRIPT not found" >&2
  exit 1
fi

if [[ ! -f "$REAL_TARGET_FILE" ]]; then
  echo "FAIL: $REAL_TARGET_FILE not found" >&2
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

# THRESHOLD_BYTES is fixed inside the real gate script and ratchets over
# time - we don't hardcode a copy that can drift from the real value;
# read it out of the script instead.
THRESHOLD_BYTES="$(grep -E '^THRESHOLD_BYTES=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$THRESHOLD_BYTES" ]]; then
  _fail "could not read THRESHOLD_BYTES out of $GATE_SCRIPT"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

GATE_LIB="$REPO_DIR/scripts/lib/budget-gate.sh"
if [[ ! -f "$GATE_LIB" ]]; then
  echo "FAIL: $GATE_LIB not found" >&2
  exit 1
fi

# --- Build a scratch fixture repo the gate script can run against without
#     touching the real working tree. It needs: scripts/ (copies of the
#     real gate script and the shared lib it sources) and
#     content/commands/ds-implement-ticket.md (a copy of the real target
#     file, optionally padded).
#
# $1 = fixture dir; $2 = extra bytes to append to the copied real file
#      (0 = exact copy, unmodified).
build_fixture() {
  local dir="$1" pad_bytes="$2"
  mkdir -p "$dir/scripts/lib" "$dir/content/commands"

  cp "$GATE_SCRIPT" "$dir/scripts/check-command-file-budget.sh"
  cp "$GATE_LIB" "$dir/scripts/lib/budget-gate.sh"
  cp "$REAL_TARGET_FILE" "$dir/content/commands/ds-implement-ticket.md"

  if [[ "$pad_bytes" -gt 0 ]]; then
    python3 -c "
import sys
n = int(sys.argv[1])
sys.stdout.write('x' * n)
" "$pad_bytes" >> "$dir/content/commands/ds-implement-ticket.md"
  fi
}

# --- Scenario 1: bash/zsh parity, current real-file size ---
PARITY_DIR="$TMP_ROOT/parity"
build_fixture "$PARITY_DIR" 0

bash_out="$(cd "$PARITY_DIR" && bash scripts/check-command-file-budget.sh 2>&1)"
bash_rc=$?

if [[ $bash_rc -eq 0 ]]; then
  _pass "bash invocation exits 0 on the real file at current size"
else
  _fail "bash invocation exited $bash_rc on the real file at current size (expected 0): $bash_out"
fi

if command -v zsh >/dev/null 2>&1; then
  zsh_out="$(cd "$PARITY_DIR" && zsh scripts/check-command-file-budget.sh 2>&1)"
  zsh_rc=$?

  if [[ $zsh_rc -eq 0 ]]; then
    _pass "zsh invocation exits 0 on the real file at current size"
  else
    _fail "zsh invocation exited $zsh_rc on the real file at current size (expected 0): $zsh_out"
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

# --- Scenario 2: gate passes at current real-file size (proves it is not
#     already red today) ---
current_bytes="$(wc -c < "$REAL_TARGET_FILE" | tr -d '[:space:]')"
if [[ "$current_bytes" -le "$THRESHOLD_BYTES" ]]; then
  _pass "current real-file size ($current_bytes B) is within THRESHOLD_BYTES ($THRESHOLD_BYTES B) - sanity check for the growth scenario below"
else
  _fail "current real-file size ($current_bytes B) already exceeds THRESHOLD_BYTES ($THRESHOLD_BYTES B) - THRESHOLD_BYTES needs raising in the same PR as the growth that caused this, or the file needs trimming"
fi

# --- Scenario 3: growth past the live headroom on a COPY of the real
#     file is caught. The pad is derived from the real THRESHOLD_BYTES and
#     current_bytes (headroom + 1024 B), not a fixed constant - a fixed
#     1024 B pad only proves anything while it exceeds the live headroom;
#     if THRESHOLD_BYTES is ever raised by more than 1 KB in the same PR
#     that shrinks headroom below the pad, a fixed pad would stay under
#     budget, this scenario would FAIL, and the failure message below
#     would be lying about what it caught. ---
headroom=$(( THRESHOLD_BYTES - current_bytes ))
pad_bytes=$(( headroom + 1024 ))

GROWTH_DIR="$TMP_ROOT/growth"
build_fixture "$GROWTH_DIR" "$pad_bytes"

growth_out="$(cd "$GROWTH_DIR" && bash scripts/check-command-file-budget.sh 2>&1)"
growth_rc=$?

if [[ $growth_rc -ne 0 ]]; then
  _pass "gate fails against a copy of the real file with $pad_bytes B appended (headroom $headroom B + 1024 B)"
else
  _fail "gate exited 0 against a copy of the real file with $pad_bytes B appended (expected non-zero) - this is the exact regression this test exists to catch: $growth_out"
fi

if echo "$growth_out" | grep -q "OVER BUDGET"; then
  _pass "growth fixture prints OVER BUDGET"
else
  _fail "growth fixture did not print OVER BUDGET: $growth_out"
fi

if echo "$growth_out" | grep -q "::error::"; then
  _pass "growth fixture emits a ::error:: workflow-command annotation on overage"
else
  _fail "growth fixture did not emit a ::error:: annotation on overage - this is the exact R1-Critical regression (silent overage, no annotation) this test exists to catch: $growth_out"
fi

# --- Scenario 3b: the workflow does not swallow the gate's failure behind
#     continue-on-error. This is the other half of the R1-Critical fix
#     (a previously-shipped `continue-on-error: true` made overage look
#     green with only a warning) - it has to be asserted against the real
#     workflow file, not a fixture, since continue-on-error is a workflow
#     property, not a gate-script property. ---
WORKFLOW_FILE="$REPO_DIR/.github/workflows/command-file-budget.yml"
if [[ ! -f "$WORKFLOW_FILE" ]]; then
  _fail "$WORKFLOW_FILE not found"
# Match the YAML key form only (with trailing colon) - the workflow's own
# comment legitimately discusses `continue-on-error` in prose to explain
# why it is NOT used, and a bare substring grep would false-positive on
# that explanation.
elif grep -qE '^\s*continue-on-error\s*:' "$WORKFLOW_FILE"; then
  _fail "$WORKFLOW_FILE contains a continue-on-error: key - this reintroduces the R1-Critical defect (overage silently reported green)"
else
  _pass "$WORKFLOW_FILE does not contain a continue-on-error: key"
fi

# --- Scenario 4: missing target file fails distinctly ---
MISSING_DIR="$TMP_ROOT/missing"
mkdir -p "$MISSING_DIR/scripts/lib" "$MISSING_DIR/content/commands"
cp "$GATE_SCRIPT" "$MISSING_DIR/scripts/check-command-file-budget.sh"
cp "$GATE_LIB" "$MISSING_DIR/scripts/lib/budget-gate.sh"

missing_out="$(cd "$MISSING_DIR" && bash scripts/check-command-file-budget.sh 2>&1)"
missing_rc=$?

if [[ $missing_rc -ne 0 ]]; then
  _pass "missing-target-file fixture exits non-zero"
else
  _fail "missing-target-file fixture exited 0 (expected non-zero): $missing_out"
fi

if echo "$missing_out" | grep -q "missing file"; then
  _pass "missing-target-file fixture prints the missing-file message"
else
  _fail "missing-target-file fixture did not print the expected message: $missing_out"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
