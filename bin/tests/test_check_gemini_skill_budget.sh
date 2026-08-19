#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-gemini-skill-budget.sh (DS-184
#          m4). Modeled directly on bin/tests/test_check_skill_embed_budget.sh
#          (the equivalent suite for the Claude adapter's SKILL.md gate) with
#          one addition specific to this gate's shape: the STUB_CEILING axis
#          on .gemini/GEMINI.md, which the Claude-adapter gate has no
#          equivalent of. Exercises bash/zsh parity, the SKILL floor-fail
#          path, the SKILL ceiling-fail path, the pass path (in range), the
#          exact-bound (inclusive) cases at SKILL_FLOOR and SKILL_CEILING,
#          the embed-completeness check (a dropped source-file heading, an
#          outright added source file, an outright deleted source file, and
#          the duplicate-heading guard), and the STUB_CEILING fail/pass path.
#
#          Per m4's explicit instruction, this suite is written so it FAILS
#          when the gate script itself is neutered, not only when a fixture
#          changes - every scenario below asserts on the gate's actual
#          stdout/stderr text and exit code against a constructed fixture,
#          never merely "the script ran". A `command -v zsh` guard exists
#          only for the parity assertion and hard-fails under CI=true rather
#          than silently skipping (the recorded trap: a shell gate whose
#          assertions are guarded by `command -v <tool>` must hard-fail
#          under CI or the job goes green having asserted nothing).
#
# Public API: ./bin/tests/test_check_gemini_skill_budget.sh
#             Exits 0 on all pass, 1 on any failure. This file's own PASS/
#             FAIL counters are summed into the final exit code so a real
#             miss cannot report 0 failed - bin/tests harnesses have no
#             `set -e` of their own; a gate with an uncounted echo would
#             silently pass.
#
# Upstream deps: bash, mktemp, wc, python3, grep, cut (build_fixture() below
#                calls python3 to write a deterministic-size stub SKILL.md;
#                SKILL_FLOOR, SKILL_CEILING, STUB_CEILING,
#                EXPECTED_SECTION_COUNT, and EXPECTED_RULES_COUNT are parsed
#                out of the real gate script with grep|cut, so this suite
#                never hardcodes a copy that can drift from the real
#                values). zsh is required for the bash/zsh parity assertion
#                when running in CI (the assertion FAILs if zsh is absent
#                under CI=true); locally, without zsh on PATH it is skipped
#                (not failed) so contributors without zsh installed can
#                still run the rest of the suite.
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script or shared lib missing -> immediate FAIL. Any
#                scenario's observed exit code or message does not match
#                the expected shape -> FAIL naming the scenario and what
#                was observed.
#
# Test hygiene: never mutates any tracked file in the working tree. All
#               fixture repos and stub files live under a mktemp -d
#               directory removed on exit via trap. Does not touch network.
#               Runs correctly from any cwd.
#
# Fixture design note: mirrors test_check_skill_embed_budget.sh's fixture
# design note - the gate script's embed-completeness check requires
# content/sections/[0-9][0-9]-*.md and content/rules/*.md (excluding
# module-manifest.md) to exist under the fixture's own REPO_DIR, with each
# file's own top-level "## " heading present verbatim in the fixture
# SKILL.md, plus a GEMINI.md stub file for the STUB_CEILING axis -
# otherwise every fixture below would fail with "embed incomplete" before
# ever reaching the axis this suite exists to exercise.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-gemini-skill-budget.sh"
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

# SKILL_FLOOR, SKILL_CEILING, STUB_CEILING, EXPECTED_SECTION_COUNT, and
# EXPECTED_RULES_COUNT are fixed inside the real gate script and ratchet
# over time - read them out of the script instead of hardcoding a copy
# that can drift from the real value.
SKILL_FLOOR="$(grep -E '^SKILL_FLOOR=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$SKILL_FLOOR" ]]; then
  _fail "could not read SKILL_FLOOR out of $GATE_SCRIPT"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

SKILL_CEILING="$(grep -E '^SKILL_CEILING=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$SKILL_CEILING" ]]; then
  _fail "could not read SKILL_CEILING out of $GATE_SCRIPT"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

STUB_CEILING="$(grep -E '^STUB_CEILING=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$STUB_CEILING" ]]; then
  _fail "could not read STUB_CEILING out of $GATE_SCRIPT"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

EXPECTED_SECTION_COUNT="$(grep -E '^EXPECTED_SECTION_COUNT=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$EXPECTED_SECTION_COUNT" ]]; then
  _fail "could not read EXPECTED_SECTION_COUNT out of $GATE_SCRIPT"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

EXPECTED_RULES_COUNT="$(grep -E '^EXPECTED_RULES_COUNT=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$EXPECTED_RULES_COUNT" ]]; then
  _fail "could not read EXPECTED_RULES_COUNT out of $GATE_SCRIPT"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

# --- Build a scratch fixture repo the gate script can run against without
#     touching the real working tree. It needs: scripts/ (copies of the
#     real gate script and the shared lib it sources), content/sections/
#     and content/rules/ (stub source files satisfying the embed-
#     completeness check), .gemini/skills/dinostack/SKILL.md embedding
#     every stub's heading padded to a controlled total size, and
#     .gemini/GEMINI.md as a small stub file (its own size controlled by
#     $3, default well under STUB_CEILING).
# $1 = fixture dir; $2 = SKILL.md byte count; $3 = GEMINI.md byte count
#      (defaults to 100, a trivially small stub).
build_fixture() {
  local dir="$1" skill_bytes="$2" stub_bytes="${3:-100}"
  mkdir -p "$dir/scripts/lib" "$dir/.gemini/skills/dinostack" \
    "$dir/content/sections" "$dir/content/rules"

  cp "$GATE_SCRIPT" "$dir/scripts/check-gemini-skill-budget.sh"
  cp "$GATE_LIB" "$dir/scripts/lib/budget-gate.sh"

  python3 -c "
import sys, os

fixture_dir = sys.argv[1]
skill_bytes = int(sys.argv[2])
stub_bytes = int(sys.argv[3])
section_count = int(sys.argv[4])
rules_count = int(sys.argv[5])

headings = []

for i in range(1, section_count + 1):
    heading = '## Section %d' % i
    headings.append(heading)
    path = os.path.join(fixture_dir, 'content', 'sections', '%02d-stub.md' % i)
    with open(path, 'w') as f:
        f.write(heading + '\n\nstub body.\n')

for i in range(1, rules_count + 1):
    heading = '## Rule %d' % i
    headings.append(heading)
    path = os.path.join(fixture_dir, 'content', 'rules', 'rule%d.md' % i)
    with open(path, 'w') as f:
        f.write(heading + '\n\nstub body.\n')

header_block = '\n'.join(headings) + '\n'
header_bytes = len(header_block.encode())
pad_len = skill_bytes - header_bytes
if pad_len < 0:
    sys.stderr.write(
        'build_fixture: requested skill_bytes=%d too small to hold %d '
        'heading(s) (%d B) - widen the fixture size\n'
        % (skill_bytes, len(headings), header_bytes)
    )
    sys.exit(1)

skill_path = os.path.join(fixture_dir, '.gemini', 'skills', 'dinostack', 'SKILL.md')
with open(skill_path, 'w') as f:
    f.write(header_block)
    f.write('x' * pad_len)

stub_path = os.path.join(fixture_dir, '.gemini', 'GEMINI.md')
with open(stub_path, 'w') as f:
    f.write('x' * stub_bytes)
" "$dir" "$skill_bytes" "$stub_bytes" "$EXPECTED_SECTION_COUNT" "$EXPECTED_RULES_COUNT"
}

# --- Scenario 1: bash/zsh parity on a passing (in-range) fixture ---
midpoint=$(( (SKILL_FLOOR + SKILL_CEILING) / 2 ))
PARITY_DIR="$TMP_ROOT/parity"
build_fixture "$PARITY_DIR" "$midpoint"

bash_out="$(cd "$PARITY_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
bash_rc=$?

if [[ $bash_rc -eq 0 ]]; then
  _pass "bash invocation exits 0 on an in-range fixture"
else
  _fail "bash invocation exited $bash_rc on an in-range fixture (expected 0): $bash_out"
fi

if command -v zsh >/dev/null 2>&1; then
  zsh_out="$(cd "$PARITY_DIR" && zsh scripts/check-gemini-skill-budget.sh 2>&1)"
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

if echo "$bash_out" | grep -q "burn: SKIPPED (base unresolvable)"; then
  _pass "burn line renders its SKIPPED variant (not a crash, not a blank line) against a non-git fixture"
else
  _fail "burn line did not render SKIPPED against a non-git fixture: $bash_out"
fi

parity_last_line="$(echo "$bash_out" | grep -v '^[[:space:]]*$' | tail -1)"
if [[ "$parity_last_line" == "  headroom to stub ceiling:"*"B" ]]; then
  _pass "non-git fixture's last output line is still the headroom to stub ceiling: line"
else
  _fail "non-git fixture's last output line is [$parity_last_line], expected a headroom to stub ceiling: line"
fi

# --- Scenario 2: below SKILL_FLOOR fails as an embed regression ---
FLOOR_DIR="$TMP_ROOT/floor"
floor_fail_size=$(( SKILL_FLOOR - 1 ))
build_fixture "$FLOOR_DIR" "$floor_fail_size"

floor_out="$(cd "$FLOOR_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
floor_rc=$?

if [[ $floor_rc -ne 0 ]]; then
  _pass "below-floor fixture exits non-zero"
else
  _fail "below-floor fixture exited 0 (expected non-zero): $floor_out"
fi

if echo "$floor_out" | grep -q "SKILL BELOW FLOOR"; then
  _pass "below-floor fixture prints SKILL BELOW FLOOR"
else
  _fail "below-floor fixture did not print SKILL BELOW FLOOR: $floor_out"
fi

# --- Scenario 3: above SKILL_CEILING fails with the safety-boundary framing ---
CEILING_DIR="$TMP_ROOT/ceiling"
ceiling_fail_size=$(( SKILL_CEILING + 1 ))
build_fixture "$CEILING_DIR" "$ceiling_fail_size"

ceiling_out="$(cd "$CEILING_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
ceiling_rc=$?

if [[ $ceiling_rc -ne 0 ]]; then
  _pass "above-ceiling fixture exits non-zero"
else
  _fail "above-ceiling fixture exited 0 (expected non-zero): $ceiling_out"
fi

if echo "$ceiling_out" | grep -q "SKILL ABOVE CEILING"; then
  _pass "above-ceiling fixture prints SKILL ABOVE CEILING"
else
  _fail "above-ceiling fixture did not print SKILL ABOVE CEILING: $ceiling_out"
fi

expected_overage=1
if echo "$ceiling_out" | grep -q "($expected_overage B over)"; then
  _pass "above-ceiling fixture reports correct overage ($expected_overage B)"
else
  _fail "above-ceiling fixture did not report overage=$expected_overage B: $ceiling_out"
fi

# --- Scenario 4: exact SKILL_FLOOR and exact SKILL_CEILING both pass
#     (inclusive bounds) ---
AT_FLOOR_DIR="$TMP_ROOT/at_floor"
build_fixture "$AT_FLOOR_DIR" "$SKILL_FLOOR"

at_floor_out="$(cd "$AT_FLOOR_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
at_floor_rc=$?

if [[ $at_floor_rc -eq 0 ]]; then
  _pass "fixture at exactly SKILL_FLOOR exits 0"
else
  _fail "fixture at exactly SKILL_FLOOR exited $at_floor_rc (expected 0): $at_floor_out"
fi

AT_CEILING_DIR="$TMP_ROOT/at_ceiling"
build_fixture "$AT_CEILING_DIR" "$SKILL_CEILING"

at_ceiling_out="$(cd "$AT_CEILING_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
at_ceiling_rc=$?

if [[ $at_ceiling_rc -eq 0 ]]; then
  _pass "fixture at exactly SKILL_CEILING exits 0"
else
  _fail "fixture at exactly SKILL_CEILING exited $at_ceiling_rc (expected 0): $at_ceiling_out"
fi

# --- Scenario 5: a source file dropped from the built SKILL.md (heading
#     missing) fails as "embed incomplete", distinct from and checked
#     before the SKILL_FLOOR/SKILL_CEILING bound check. ---
DROPPED_HEADING_DIR="$TMP_ROOT/dropped_heading"
midpoint2=$(( (SKILL_FLOOR + SKILL_CEILING) / 2 ))
build_fixture "$DROPPED_HEADING_DIR" "$midpoint2"
python3 -c "
path = '$DROPPED_HEADING_DIR/.gemini/skills/dinostack/SKILL.md'
with open(path) as f:
    lines = f.readlines()
lines = [l for l in lines if l.strip() != '## Section 1']
with open(path, 'w') as f:
    f.writelines(lines)
"

dropped_heading_out="$(cd "$DROPPED_HEADING_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
dropped_heading_rc=$?

if [[ $dropped_heading_rc -ne 0 ]]; then
  _pass "dropped-heading fixture exits non-zero"
else
  _fail "dropped-heading fixture exited 0 (expected non-zero): $dropped_heading_out"
fi

if echo "$dropped_heading_out" | grep -q "embed incomplete"; then
  _pass "dropped-heading fixture prints 'embed incomplete'"
else
  _fail "dropped-heading fixture did not print 'embed incomplete': $dropped_heading_out"
fi

if echo "$dropped_heading_out" | grep -q "missing section heading"; then
  _pass "dropped-heading fixture names the missing section heading"
else
  _fail "dropped-heading fixture did not name the missing section heading: $dropped_heading_out"
fi

# --- Scenario 6: an outright ADDED section source file (count above
#     EXPECTED_SECTION_COUNT) fails as "embed incomplete" with the
#     added-file direction message, not the deleted-file message. ---
EXTRA_FILE_DIR="$TMP_ROOT/extra_file"
build_fixture "$EXTRA_FILE_DIR" "$midpoint2"
extra_count=$(( EXPECTED_SECTION_COUNT + 1 ))
printf '## Section %d\n\nstub body.\n' "$extra_count" \
  > "$EXTRA_FILE_DIR/content/sections/$(printf '%02d' "$extra_count")-stub.md"

extra_file_out="$(cd "$EXTRA_FILE_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
extra_file_rc=$?

if [[ $extra_file_rc -ne 0 ]]; then
  _pass "extra-section-file fixture exits non-zero"
else
  _fail "extra-section-file fixture exited 0 (expected non-zero): $extra_file_out"
fi

if echo "$extra_file_out" | grep -q "a new section source file was added"; then
  _pass "extra-section-file fixture reports the added-file direction, not the deleted-file direction"
else
  _fail "extra-section-file fixture did not report the added-file direction: $extra_file_out"
fi

# --- Scenario 7: an outright DELETED section source file (count below
#     EXPECTED_SECTION_COUNT) fails as "embed incomplete" with the
#     deleted-file direction message. ---
MISSING_FILE_DIR="$TMP_ROOT/missing_file"
build_fixture "$MISSING_FILE_DIR" "$midpoint2"
rm "$MISSING_FILE_DIR/content/sections/01-stub.md"

missing_file_out="$(cd "$MISSING_FILE_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
missing_file_rc=$?

if [[ $missing_file_rc -ne 0 ]]; then
  _pass "missing-section-file fixture exits non-zero"
else
  _fail "missing-section-file fixture exited 0 (expected non-zero): $missing_file_out"
fi

if echo "$missing_file_out" | grep -q "a section source file went missing"; then
  _pass "missing-section-file fixture reports the deleted-file direction, not the added-file direction"
else
  _fail "missing-section-file fixture did not report the deleted-file direction: $missing_file_out"
fi

# --- Scenario 8: the duplicate-heading guard. Two distinct source files
#     sharing the same top-level heading text means the per-file presence
#     check cannot tell which file's copy it matched. ---
DUPLICATE_HEADING_DIR="$TMP_ROOT/duplicate_heading"
build_fixture "$DUPLICATE_HEADING_DIR" "$midpoint2"
printf '## Section 1\n\nstub body.\n' > "$DUPLICATE_HEADING_DIR/content/sections/02-stub.md"

duplicate_heading_out="$(cd "$DUPLICATE_HEADING_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
duplicate_heading_rc=$?

if [[ $duplicate_heading_rc -ne 0 ]]; then
  _pass "duplicate-heading fixture exits non-zero"
else
  _fail "duplicate-heading fixture exited 0 (expected non-zero): $duplicate_heading_out"
fi

if echo "$duplicate_heading_out" | grep -q "duplicate top-level heading"; then
  _pass "duplicate-heading fixture reports the duplicate-heading guard, not a false pass"
else
  _fail "duplicate-heading fixture did not report the duplicate-heading guard: $duplicate_heading_out"
fi

# --- Scenario 9: STUB_CEILING axis - a GEMINI.md stub above STUB_CEILING
#     fails as a DS-184 regression, distinct from the SKILL axis (a
#     passing in-range SKILL.md alongside an oversized stub still fails
#     the run). This is the mutation this suite exists to catch: nothing
#     else in this repo measures GEMINI.md at all, so a silent re-embed of
#     the full body back into the stub would otherwise pass every other
#     check here. ---
OVER_STUB_DIR="$TMP_ROOT/over_stub"
over_stub_size=$(( STUB_CEILING + 1 ))
build_fixture "$OVER_STUB_DIR" "$midpoint2" "$over_stub_size"

over_stub_out="$(cd "$OVER_STUB_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
over_stub_rc=$?

if [[ $over_stub_rc -ne 0 ]]; then
  _pass "over-stub-ceiling fixture exits non-zero"
else
  _fail "over-stub-ceiling fixture exited 0 (expected non-zero): $over_stub_out"
fi

if echo "$over_stub_out" | grep -q "STUB ABOVE CEILING"; then
  _pass "over-stub-ceiling fixture prints STUB ABOVE CEILING"
else
  _fail "over-stub-ceiling fixture did not print STUB ABOVE CEILING: $over_stub_out"
fi

if echo "$over_stub_out" | grep -q "DS-184 regression"; then
  _pass "over-stub-ceiling fixture frames the failure as a DS-184 regression"
else
  _fail "over-stub-ceiling fixture did not frame the failure as a DS-184 regression: $over_stub_out"
fi

# --- Scenario 10: exact STUB_CEILING passes (inclusive bound), same
#     inclusivity convention as the SKILL_FLOOR/SKILL_CEILING checks. ---
AT_STUB_CEILING_DIR="$TMP_ROOT/at_stub_ceiling"
build_fixture "$AT_STUB_CEILING_DIR" "$midpoint2" "$STUB_CEILING"

at_stub_ceiling_out="$(cd "$AT_STUB_CEILING_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
at_stub_ceiling_rc=$?

if [[ $at_stub_ceiling_rc -eq 0 ]]; then
  _pass "fixture at exactly STUB_CEILING exits 0"
else
  _fail "fixture at exactly STUB_CEILING exited $at_stub_ceiling_rc (expected 0): $at_stub_ceiling_out"
fi

# --- Scenario 11: a missing SKILL.md or GEMINI.md input file exits
#     non-zero naming the missing path, rather than crashing on an
#     unhandled read error. ---
MISSING_SKILL_DIR="$TMP_ROOT/missing_skill"
build_fixture "$MISSING_SKILL_DIR" "$midpoint2"
rm "$MISSING_SKILL_DIR/.gemini/skills/dinostack/SKILL.md"

missing_skill_out="$(cd "$MISSING_SKILL_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
missing_skill_rc=$?

if [[ $missing_skill_rc -ne 0 ]]; then
  _pass "missing SKILL.md fixture exits non-zero"
else
  _fail "missing SKILL.md fixture exited 0 (expected non-zero): $missing_skill_out"
fi

if echo "$missing_skill_out" | grep -q "missing file"; then
  _pass "missing SKILL.md fixture names the missing file"
else
  _fail "missing SKILL.md fixture did not name the missing file: $missing_skill_out"
fi

MISSING_STUB_DIR="$TMP_ROOT/missing_stub"
build_fixture "$MISSING_STUB_DIR" "$midpoint2"
rm "$MISSING_STUB_DIR/.gemini/GEMINI.md"

missing_stub_out="$(cd "$MISSING_STUB_DIR" && bash scripts/check-gemini-skill-budget.sh 2>&1)"
missing_stub_rc=$?

if [[ $missing_stub_rc -ne 0 ]]; then
  _pass "missing GEMINI.md fixture exits non-zero"
else
  _fail "missing GEMINI.md fixture exited 0 (expected non-zero): $missing_stub_out"
fi

if echo "$missing_stub_out" | grep -q "missing file"; then
  _pass "missing GEMINI.md fixture names the missing file"
else
  _fail "missing GEMINI.md fixture did not name the missing file: $missing_stub_out"
fi

# --- Scenario 12: the gemini-skill-budget.yml workflow's checkout carries
#     fetch-depth: 0, matching the precedent
#     test_check_skill_embed_budget.sh already asserts for
#     resident-budget.yml's check-skill-embed-budget job - needed so the
#     burn line can resolve origin/main. ---
GEMINI_WORKFLOW_FILE="$REPO_DIR/.github/workflows/gemini-skill-budget.yml"
if [[ ! -f "$GEMINI_WORKFLOW_FILE" ]]; then
  _fail "$GEMINI_WORKFLOW_FILE not found"
else
  if grep -q 'fetch-depth: 0' "$GEMINI_WORKFLOW_FILE"; then
    _pass "gemini-skill-budget.yml carries fetch-depth: 0"
  else
    _fail "gemini-skill-budget.yml is missing fetch-depth: 0"
  fi
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
