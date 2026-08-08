#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-skill-embed-budget.sh. Exercises
#          bash/zsh parity, the floor-fail path (embed regression to a
#          pointer-only skill), the ceiling-fail path (payload above the
#          verified-safe injection range), the pass path (in range), and the
#          exact-bound (inclusive) cases at FLOOR and CEILING.
#
# Public API: ./bin/tests/test_check_skill_embed_budget.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc, python3, grep, cut (build_fixture() calls
#                python3 to write a deterministic-size stub SKILL.md; FLOOR,
#                CEILING, EXPECTED_SECTION_COUNT, and EXPECTED_RULES_COUNT
#                are parsed out of the gate script with grep|cut, so this
#                suite never hardcodes a copy that can drift from the real
#                values). zsh is required for the bash/zsh parity assertion
#                when running in CI (the assertion FAILs if zsh is absent
#                under CI=true); locally, without zsh on PATH it is skipped
#                (not failed) so contributors without zsh installed can
#                still run the rest of the suite.
#
# Downstream consumers: developer running locally before commit; CI
#                        (bin-sh-tests.yml auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script missing -> immediate FAIL. Any scenario's
#                observed exit code or message does not match the expected
#                shape -> FAIL naming the scenario and what was observed.
#
# Test hygiene: never mutates any tracked file in the working tree. All
#               fixture repos and stub files live under a mktemp -d
#               directory that is removed on exit via trap. Does not touch
#               network. Runs correctly from any cwd.
#
# Fixture design note: the gate script's embed-completeness check (added
# alongside the FLOOR/CEILING bound check) requires content/sections/
# [0-9][0-9]-*.md and content/rules/*.md (excluding module-manifest.md) to
# exist under the fixture's own REPO_DIR, with each file's own top-level
# "## " heading present verbatim in the fixture SKILL.md - otherwise every
# fixture below would fail with "embed incomplete" before ever reaching the
# FLOOR/CEILING logic this suite exists to exercise. build_fixture()
# therefore generates EXPECTED_SECTION_COUNT section stubs and
# EXPECTED_RULES_COUNT rules stubs (each with a distinct heading), embeds
# every one of those headings into the fixture SKILL.md, then pads with
# filler bytes to reach the exact requested size.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-skill-embed-budget.sh"

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

# FLOOR, CEILING, EXPECTED_SECTION_COUNT, and EXPECTED_RULES_COUNT are fixed
# inside the real gate script and ratchet over time - we don't hardcode a
# copy that can drift from the real value; read them out of the script
# instead.
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
#     touching the real working tree. It needs: scripts/ (a copy of the
#     real gate script), content/sections/ and content/rules/ (stub source
#     files satisfying the embed-completeness check - see the fixture
#     design note above), and .claude/skills/agentic-engineering/SKILL.md
#     embedding every stub's heading, padded to a controlled total size.
# $1 = fixture dir; $2 = SKILL.md byte count.
build_fixture() {
  local dir="$1" skill_bytes="$2"
  mkdir -p "$dir/scripts" "$dir/.claude/skills/agentic-engineering" \
    "$dir/content/sections" "$dir/content/rules"

  cp "$GATE_SCRIPT" "$dir/scripts/check-skill-embed-budget.sh"

  python3 -c "
import sys, os

fixture_dir = sys.argv[1]
skill_bytes = int(sys.argv[2])
section_count = int(sys.argv[3])
rules_count = int(sys.argv[4])

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

skill_path = os.path.join(fixture_dir, '.claude', 'skills', 'agentic-engineering', 'SKILL.md')
with open(skill_path, 'w') as f:
    f.write(header_block)
    f.write('x' * pad_len)
" "$dir" "$skill_bytes" "$EXPECTED_SECTION_COUNT" "$EXPECTED_RULES_COUNT"
}

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

# --- Scenario 5: a source file dropped from the built SKILL.md (heading
#     missing) fails as "embed incomplete", distinct from and checked
#     before the FLOOR/CEILING bound check. Regression coverage for the
#     DS-143 follow-up gap where a whole embedded source file could go
#     missing and still land inside the FLOOR..CEILING byte band undetected.
# ---------------------------------------------------------------------------
DROPPED_HEADING_DIR="$TMP_ROOT/dropped_heading"
midpoint2=$(( (FLOOR + CEILING) / 2 ))
build_fixture "$DROPPED_HEADING_DIR" "$midpoint2"
# Remove Section 1's heading from the built SKILL.md (rewrite without that
# line) while leaving the source stub file itself in place - simulates the
# live-verified defect (a build-loop exclusion) rather than a count
# mismatch.
python3 -c "
path = '$DROPPED_HEADING_DIR/.claude/skills/agentic-engineering/SKILL.md'
with open(path) as f:
    lines = f.readlines()
lines = [l for l in lines if l.strip() != '## Section 1']
with open(path, 'w') as f:
    f.writelines(lines)
"

dropped_heading_out="$(cd "$DROPPED_HEADING_DIR" && bash scripts/check-skill-embed-budget.sh 2>&1)"
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
#     added-file direction message, not the deleted-file message.
# ---------------------------------------------------------------------------
EXTRA_FILE_DIR="$TMP_ROOT/extra_file"
build_fixture "$EXTRA_FILE_DIR" "$midpoint2"
extra_count=$(( EXPECTED_SECTION_COUNT + 1 ))
printf '## Section %d\n\nstub body.\n' "$extra_count" \
  > "$EXTRA_FILE_DIR/content/sections/$(printf '%02d' "$extra_count")-stub.md"

extra_file_out="$(cd "$EXTRA_FILE_DIR" && bash scripts/check-skill-embed-budget.sh 2>&1)"
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
#     deleted-file direction message. This is the deleted-section
#     tautology this gate exists to close - deriving the expected count
#     from the working tree instead of a pinned constant would make this
#     scenario silently pass, since deleting the file also removes it from
#     what is expected.
# ---------------------------------------------------------------------------
MISSING_FILE_DIR="$TMP_ROOT/missing_file"
build_fixture "$MISSING_FILE_DIR" "$midpoint2"
rm "$MISSING_FILE_DIR/content/sections/01-stub.md"

missing_file_out="$(cd "$MISSING_FILE_DIR" && bash scripts/check-skill-embed-budget.sh 2>&1)"
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

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
