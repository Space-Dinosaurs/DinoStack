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
#          DS-182 added a second axis (per-PR DELTA_LIMIT_BYTES, git-based,
#          on top of the original absolute-size THRESHOLD_BYTES check).
#          build_fixture() above has always built a pure-filesystem-copy
#          fixture with NO `git init` at all - verified by its absence in
#          that function - so every existing scenario above already
#          exercises the delta axis's SKIPPED-degrade path (git absent from
#          the fixture) without a single line changed; the new scenarios
#          below add an explicit assertion for that instead of leaving it
#          implicit, plus a second, git-backed fixture builder
#          (build_git_fixture) for the scenarios that need a real base
#          commit to diff against: delta under the limit passing, delta
#          over the limit failing (naming the delta axis distinctly from
#          THRESHOLD_BYTES), a path absent at the base ref degrading to
#          SKIPPED rather than being treated as a full-size delta, and
#          `lines[-1]` of stdout staying the `headroom:` line exactly as
#          bin/ds-evaluate's `_collect_budget_gates` depends on (it takes
#          `lines[-1]` of stdout as the gate's one-line summary).
#
# Public API: ./bin/tests/test_check_command_file_budget.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc, python3, grep, cut (THRESHOLD_BYTES and
#                DELTA_LIMIT_BYTES are parsed out of the gate script with
#                grep|cut so this test never hardcodes a copy that can
#                drift from the real values). git is required for the
#                DS-182 git-backed scenarios - no soft-skip, since
#                bin-tests.yml always provides one. zsh is required for the
#                bash/zsh parity assertion when running in CI (the
#                assertion FAILs if zsh is absent under CI=true); locally,
#                without zsh on PATH it is skipped (not failed) so
#                contributors without zsh installed can still run the rest
#                of the suite. Fixtures also carry a copy of
#                scripts/lib/budget-gate.sh, since the gate now sources it.
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
#               fixture repos (including the DS-182 git-backed ones) live
#               under a mktemp -d directory that is removed on exit via
#               trap. Does not touch network - the "origin" remote used by
#               build_git_fixture is a local bare repo under the same
#               mktemp -d. Runs correctly from any cwd.

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

# DELTA_LIMIT_BYTES (DS-182), same re-derive-not-hardcode rationale as
# THRESHOLD_BYTES above.
DELTA_LIMIT_BYTES="$(grep -E '^DELTA_LIMIT_BYTES=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$DELTA_LIMIT_BYTES" ]]; then
  _fail "could not read DELTA_LIMIT_BYTES out of $GATE_SCRIPT"
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

# --- Scenario 1b (DS-182): build_fixture() above never runs `git init` -
#     the delta axis therefore degrades to SKIPPED against this same
#     non-git PARITY_DIR fixture, and $bash_out from Scenario 1 already
#     captured that run's output - assert the SKIPPED line explicitly
#     rather than leaving it implicit in the parity check above. Mutation
#     that would redden this: change the gate's `base_ref="$(budget_base_
#     resolve)" || base_ref=""` fallback to something that crashes or
#     omits the line instead of degrading. ---
if echo "$bash_out" | grep -q "delta: SKIPPED (base unresolvable)"; then
  _pass "delta axis degrades to SKIPPED (not a crash, not a false pass/fail) against a non-git fixture"
else
  _fail "delta axis did not degrade to SKIPPED against a non-git fixture: $bash_out"
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

# --- Scenario 5 (DS-182): git-backed delta axis fixture. A real git repo
#     (not a mock) with one commit on "main" pushed to a local bare
#     "origin" remote under the same mktemp -d, so budget_base_resolve/
#     budget_delta exercise the actual git plumbing they shell out to.
#     $1 = fixture dir; $2 = base-commit target-file content.
build_git_fixture() {
  local dir="$1" base_content="$2"
  mkdir -p "$dir/scripts/lib" "$dir/content/commands"
  cp "$GATE_SCRIPT" "$dir/scripts/check-command-file-budget.sh"
  cp "$GATE_LIB" "$dir/scripts/lib/budget-gate.sh"
  printf '%s' "$base_content" > "$dir/content/commands/ds-implement-ticket.md"

  git -C "$dir" init -q -b main
  git -C "$dir" add -A
  git -C "$dir" -c user.email="test@example.com" -c user.name="test" commit -q -m base
  git -C "$dir" init -q --bare "$dir.origin.git"
  git -C "$dir" remote add origin "$dir.origin.git"
  git -C "$dir" push -q origin main
}

if command -v git >/dev/null 2>&1; then
  # --- Scenario 5a: delta under DELTA_LIMIT_BYTES passes, and lines[-1]
  #     of stdout (the last non-blank line, matching bin/ds-evaluate's
  #     `_collect_budget_gates`) is still the `headroom:` line - not the
  #     inserted delta context line. ---
  UNDER_LIMIT_DIR="$TMP_ROOT/delta_under_limit"
  build_git_fixture "$UNDER_LIMIT_DIR" "$(python3 -c "print('a' * 200, end='')")"
  python3 -c "
with open('$UNDER_LIMIT_DIR/content/commands/ds-implement-ticket.md', 'a') as f:
    f.write('b' * 500)
"
  under_limit_out="$(cd "$UNDER_LIMIT_DIR" && bash scripts/check-command-file-budget.sh 2>&1)"
  under_limit_rc=$?

  if [[ $under_limit_rc -eq 0 ]]; then
    _pass "delta under DELTA_LIMIT_BYTES ($DELTA_LIMIT_BYTES B) passes"
  else
    _fail "delta under DELTA_LIMIT_BYTES exited $under_limit_rc (expected 0): $under_limit_out"
  fi

  if echo "$under_limit_out" | grep -q "delta (vs origin/main): +500 B"; then
    _pass "delta-under-limit fixture reports the correct +500 B delta"
  else
    _fail "delta-under-limit fixture did not report +500 B: $under_limit_out"
  fi

  under_limit_expected_headroom=$(( THRESHOLD_BYTES - 700 ))
  under_limit_last_line="$(echo "$under_limit_out" | grep -v '^[[:space:]]*$' | tail -1)"
  if [[ "$under_limit_last_line" == "  headroom:  $under_limit_expected_headroom B" ]]; then
    _pass "delta-under-limit fixture's lines[-1] is still the headroom: line ($under_limit_expected_headroom B), not the delta line"
  else
    _fail "delta-under-limit fixture's lines[-1] is [$under_limit_last_line], expected [  headroom:  $under_limit_expected_headroom B]"
  fi

  # --- Scenario 5b: delta over DELTA_LIMIT_BYTES fails, naming the delta
  #     axis distinctly from THRESHOLD_BYTES, without ever exceeding
  #     THRESHOLD_BYTES itself (proves the two axes are independent, not
  #     just the same overage detected twice). ---
  over_limit_pad=$(( DELTA_LIMIT_BYTES + 1000 ))
  OVER_LIMIT_DIR="$TMP_ROOT/delta_over_limit"
  build_git_fixture "$OVER_LIMIT_DIR" "$(python3 -c "print('a' * 200, end='')")"
  python3 -c "
n = $over_limit_pad
with open('$OVER_LIMIT_DIR/content/commands/ds-implement-ticket.md', 'a') as f:
    f.write('b' * n)
"
  over_limit_current_bytes="$(wc -c < "$OVER_LIMIT_DIR/content/commands/ds-implement-ticket.md" | tr -d '[:space:]')"

  if [[ "$over_limit_current_bytes" -le "$THRESHOLD_BYTES" ]]; then
    _pass "delta-over-limit fixture ($over_limit_current_bytes B) stays under THRESHOLD_BYTES ($THRESHOLD_BYTES B) - proves the delta axis fails independently of the absolute-size axis"
  else
    _fail "delta-over-limit fixture ($over_limit_current_bytes B) already exceeds THRESHOLD_BYTES ($THRESHOLD_BYTES B) - widen DELTA_LIMIT_BYTES headroom in this test's pad sizing so the two axes stay independent"
  fi

  set +e
  over_limit_out="$(cd "$OVER_LIMIT_DIR" && bash scripts/check-command-file-budget.sh 2>&1)"
  over_limit_rc=$?
  set +e

  if [[ $over_limit_rc -ne 0 ]]; then
    _pass "delta over DELTA_LIMIT_BYTES fails"
  else
    _fail "delta over DELTA_LIMIT_BYTES exited 0 (expected non-zero): $over_limit_out"
  fi

  if echo "$over_limit_out" | grep -q "OVER DELTA LIMIT"; then
    _pass "delta-over-limit fixture names the delta axis (OVER DELTA LIMIT), distinct from THRESHOLD_BYTES"
  else
    _fail "delta-over-limit fixture did not name the delta axis: $over_limit_out"
  fi

  if echo "$over_limit_out" | grep -q "::error::.*grew by $over_limit_pad B"; then
    _pass "delta-over-limit fixture emits a ::error:: annotation naming the delta overage"
  else
    _fail "delta-over-limit fixture did not emit a ::error:: annotation naming the delta overage: $over_limit_out"
  fi

  # --- Scenario 5c: a newly-created file (absent at the base ref)
  #     degrades to SKIPPED rather than being treated as a delta equal to
  #     its own full size - which would fail every file-creating PR. ---
  ABSENT_AT_BASE_DIR="$TMP_ROOT/delta_absent_at_base"
  mkdir -p "$ABSENT_AT_BASE_DIR/scripts/lib"
  cp "$GATE_SCRIPT" "$ABSENT_AT_BASE_DIR/scripts/check-command-file-budget.sh"
  cp "$GATE_LIB" "$ABSENT_AT_BASE_DIR/scripts/lib/budget-gate.sh"
  git -C "$ABSENT_AT_BASE_DIR" init -q -b main
  git -C "$ABSENT_AT_BASE_DIR" add -A
  git -C "$ABSENT_AT_BASE_DIR" -c user.email="test@example.com" -c user.name="test" commit -q -m base-no-target
  git -C "$ABSENT_AT_BASE_DIR" init -q --bare "$ABSENT_AT_BASE_DIR.origin.git"
  git -C "$ABSENT_AT_BASE_DIR" remote add origin "$ABSENT_AT_BASE_DIR.origin.git"
  git -C "$ABSENT_AT_BASE_DIR" push -q origin main
  mkdir -p "$ABSENT_AT_BASE_DIR/content/commands"
  printf 'brand new command file' > "$ABSENT_AT_BASE_DIR/content/commands/ds-implement-ticket.md"

  absent_at_base_out="$(cd "$ABSENT_AT_BASE_DIR" && bash scripts/check-command-file-budget.sh 2>&1)"
  absent_at_base_rc=$?

  if [[ $absent_at_base_rc -eq 0 ]]; then
    _pass "delta axis on a file absent at base ref does not fail the gate"
  else
    _fail "delta axis on a file absent at base ref exited $absent_at_base_rc (expected 0): $absent_at_base_out"
  fi

  if echo "$absent_at_base_out" | grep -q "delta (vs origin/main): SKIPPED (absent at base)"; then
    _pass "delta axis on a file absent at base ref renders SKIPPED, not a full-size delta"
  else
    _fail "delta axis on a file absent at base ref did not render SKIPPED: $absent_at_base_out"
  fi
elif [[ -n "${CI:-}" ]]; then
  _fail "git absent on PATH in CI - the DS-182 git-backed delta-axis scenarios cannot be skipped here"
else
  echo "SKIP: git not found on PATH - skipping the DS-182 git-backed delta-axis scenarios (non-git SKIPPED-degrade coverage above still applies)"
fi

# --- Scenario 6 (DS-182): the workflow's checkout step carries
#     fetch-depth: 0, or the delta axis's origin/main resolution would be
#     unreachable on a default shallow checkout in real CI - a fixture
#     cannot exercise this (checkout depth is a workflow property, not a
#     gate-script property), so it is asserted against the real workflow
#     file directly. ---
if [[ ! -f "$WORKFLOW_FILE" ]]; then
  _fail "$WORKFLOW_FILE not found (already checked above, re-checking for scenario 6)"
elif grep -q 'fetch-depth: 0' "$WORKFLOW_FILE"; then
  _pass "$WORKFLOW_FILE's checkout step carries fetch-depth: 0"
else
  _fail "$WORKFLOW_FILE's checkout step is missing fetch-depth: 0 - the delta axis's origin/main resolution would be unreachable on a default shallow checkout"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
