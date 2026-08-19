#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-copilot-skill-budget.sh, the
#          Copilot sibling of scripts/check-skill-embed-budget.sh (this
#          suite is modeled directly on
#          bin/tests/test_check_skill_embed_budget.sh, same fixture
#          discipline). Exercises the four axes the gate claims to check:
#            - FLOOR: below-floor fails as an embed regression, at-FLOOR
#              passes (inclusive bound).
#            - STUB CEILING: above-stub-ceiling fails as a re-embed
#              regression, at-STUB_CEILING passes (inclusive bound). This
#              gate has NO hard ceiling on the skill body itself (only an
#              informational burn line - see below) - only the stub file
#              is bounded above.
#            - EMBED COMPLETENESS: a dropped section heading, an outright
#              added source file, an outright deleted source file, and the
#              duplicate-heading ambiguity guard.
#            - BURN LINE: the informational git-based burn line on the
#              skill body renders its SKIPPED-degrade variant against a
#              non-git fixture and never affects the exit code.
#          Also covers bash/zsh parity and the two "required input
#          missing" failure paths (SKILL_FILE absent, STUB_FILE absent).
#
# Public API: ./bin/tests/test_check_copilot_skill_budget.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc, python3, grep, cut (build_fixture()
#                calls python3 to write deterministic-size stub SKILL.md
#                and copilot-instructions.md files; FLOOR, STUB_CEILING,
#                EXPECTED_SECTION_COUNT, and EXPECTED_RULES_COUNT are
#                parsed out of the gate script with grep|cut, so this
#                suite never hardcodes a copy that can drift from the real
#                values). zsh is required for the bash/zsh parity
#                assertion when running in CI (the assertion FAILs if zsh
#                is absent under CI=true); locally, without zsh on PATH it
#                is skipped (not failed) so contributors without zsh
#                installed can still run the rest of the suite.
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script or its shared lib missing -> immediate FAIL.
#                Any scenario's observed exit code or message does not
#                match the expected shape -> FAIL naming the scenario and
#                what was observed.
#
# Test hygiene: never mutates any tracked file in the working tree. All
#               fixture repos and stub files live under a mktemp -d
#               directory that is removed on exit via trap. Does not
#               touch network. Runs correctly from any cwd.
#
# Fixture design note: the gate script's embed-completeness check requires
# content/sections/[0-9][0-9]-*.md and content/rules/*.md (excluding
# module-manifest.md) to exist under the fixture's own REPO_DIR, with each
# file's own top-level "## " heading present verbatim in the fixture
# SKILL.md - otherwise every fixture below would fail with "embed
# incomplete" before ever reaching the FLOOR/STUB_CEILING logic this suite
# exists to exercise. build_fixture() therefore generates
# EXPECTED_SECTION_COUNT section stubs and EXPECTED_RULES_COUNT rules
# stubs (each with a distinct heading), embeds every one of those headings
# into the fixture SKILL.md, then pads with filler bytes to reach the
# exact requested size. The stub copilot-instructions.md file is padded
# independently to its own requested size - it carries no headings, since
# the gate never checks the stub for embed completeness (only its byte
# ceiling).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-copilot-skill-budget.sh"
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

# FLOOR, STUB_CEILING, EXPECTED_SECTION_COUNT, and EXPECTED_RULES_COUNT
# are fixed inside the real gate script and ratchet over time - we don't
# hardcode a copy that can drift from the real value; read them out of
# the script instead.
FLOOR="$(grep -E '^FLOOR=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
if [[ -z "$FLOOR" ]]; then
  _fail "could not read FLOOR out of $GATE_SCRIPT"
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

# --- Build a scratch fixture repo the gate script can run against
#     without touching the real working tree. It needs: scripts/ (copies
#     of the real gate script and the shared lib it sources),
#     content/sections/ and content/rules/ (stub source files satisfying
#     the embed-completeness check), .github/skills/dinostack/SKILL.md
#     (embedding every stub's heading, padded to a controlled total
#     size), and .github/copilot-instructions.md (padded to a controlled
#     total size, independent of the skill body).
# $1 = fixture dir; $2 = SKILL.md byte count; $3 = stub byte count.
build_fixture() {
  local dir="$1" skill_bytes="$2" stub_bytes="$3"
  mkdir -p "$dir/scripts/lib" "$dir/.github/skills/dinostack" \
    "$dir/content/sections" "$dir/content/rules"

  cp "$GATE_SCRIPT" "$dir/scripts/check-copilot-skill-budget.sh"
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

skill_path = os.path.join(fixture_dir, '.github', 'skills', 'dinostack', 'SKILL.md')
with open(skill_path, 'w') as f:
    f.write(header_block)
    f.write('x' * pad_len)

stub_header = '# Agentic Engineering Protocol\n\n'
stub_header_bytes = len(stub_header.encode())
stub_pad_len = stub_bytes - stub_header_bytes
if stub_pad_len < 0:
    sys.stderr.write(
        'build_fixture: requested stub_bytes=%d too small to hold the '
        'stub header (%d B) - widen the fixture size\n'
        % (stub_bytes, stub_header_bytes)
    )
    sys.exit(1)

stub_path = os.path.join(fixture_dir, '.github', 'copilot-instructions.md')
with open(stub_path, 'w') as f:
    f.write(stub_header)
    f.write('x' * stub_pad_len)
" "$dir" "$skill_bytes" "$stub_bytes" "$EXPECTED_SECTION_COUNT" "$EXPECTED_RULES_COUNT"
}

# A representative in-range skill body size and in-range stub size, reused
# across most scenarios below.
skill_midpoint=$(( FLOOR + 5000 ))
stub_midpoint=$(( STUB_CEILING / 2 ))

# --- Scenario 1: bash/zsh parity on a passing (in-range) fixture ---
PARITY_DIR="$TMP_ROOT/parity"
build_fixture "$PARITY_DIR" "$skill_midpoint" "$stub_midpoint"

bash_out="$(cd "$PARITY_DIR" && bash scripts/check-copilot-skill-budget.sh 2>&1)"
bash_rc=$?

if [[ $bash_rc -eq 0 ]]; then
  _pass "bash invocation exits 0 on an in-range fixture"
else
  _fail "bash invocation exited $bash_rc on an in-range fixture (expected 0): $bash_out"
fi

if command -v zsh >/dev/null 2>&1; then
  zsh_out="$(cd "$PARITY_DIR" && zsh scripts/check-copilot-skill-budget.sh 2>&1)"
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

# --- Scenario 1b: the burn line (git-based, on the skill body) renders
#     its SKIPPED-degrade variant against this non-git fixture (never a
#     blank line, per budget_burn_line's contract), and the final output
#     line is still "headroom to floor:" (no CEILING axis on the skill
#     body itself for this gate). ---
if echo "$bash_out" | grep -q "burn: SKIPPED (base unresolvable)"; then
  _pass "burn line renders its SKIPPED variant (not a crash, not a blank line) against a non-git fixture"
else
  _fail "burn line did not render SKIPPED against a non-git fixture: $bash_out"
fi

parity_last_line="$(echo "$bash_out" | grep -v '^[[:space:]]*$' | tail -1)"
if [[ "$parity_last_line" == "  headroom to floor:"*"B" ]]; then
  _pass "non-git fixture's last output line is still the headroom to floor: line"
else
  _fail "non-git fixture's last output line is [$parity_last_line], expected a headroom to floor: line"
fi

# --- Scenario 2: below FLOOR fails as an embed regression ---
FLOOR_DIR="$TMP_ROOT/floor"
floor_fail_size=$(( FLOOR - 1 ))
build_fixture "$FLOOR_DIR" "$floor_fail_size" "$stub_midpoint"

floor_out="$(cd "$FLOOR_DIR" && bash scripts/check-copilot-skill-budget.sh 2>&1)"
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

if echo "$floor_out" | grep -q "burn: SKIPPED"; then
  _pass "below-floor fixture still renders the burn line before exiting"
else
  _fail "below-floor fixture did not render the burn line: $floor_out"
fi

# --- Scenario 3: exact FLOOR passes (inclusive bound) ---
AT_FLOOR_DIR="$TMP_ROOT/at_floor"
build_fixture "$AT_FLOOR_DIR" "$FLOOR" "$stub_midpoint"

at_floor_out="$(cd "$AT_FLOOR_DIR" && bash scripts/check-copilot-skill-budget.sh 2>&1)"
at_floor_rc=$?

if [[ $at_floor_rc -eq 0 ]]; then
  _pass "fixture at exactly FLOOR exits 0"
else
  _fail "fixture at exactly FLOOR exited $at_floor_rc (expected 0): $at_floor_out"
fi

# --- Scenario 4: above STUB_CEILING fails as a re-embed regression ---
STUB_CEIL_DIR="$TMP_ROOT/stub_ceiling"
stub_fail_size=$(( STUB_CEILING + 1 ))
build_fixture "$STUB_CEIL_DIR" "$skill_midpoint" "$stub_fail_size"

stub_ceil_out="$(cd "$STUB_CEIL_DIR" && bash scripts/check-copilot-skill-budget.sh 2>&1)"
stub_ceil_rc=$?

if [[ $stub_ceil_rc -ne 0 ]]; then
  _pass "above-stub-ceiling fixture exits non-zero"
else
  _fail "above-stub-ceiling fixture exited 0 (expected non-zero): $stub_ceil_out"
fi

if echo "$stub_ceil_out" | grep -q "STUB ABOVE CEILING"; then
  _pass "above-stub-ceiling fixture prints STUB ABOVE CEILING"
else
  _fail "above-stub-ceiling fixture did not print STUB ABOVE CEILING: $stub_ceil_out"
fi

expected_stub_overage=1
if echo "$stub_ceil_out" | grep -q "($expected_stub_overage B over)"; then
  _pass "above-stub-ceiling fixture reports correct overage ($expected_stub_overage B)"
else
  _fail "above-stub-ceiling fixture did not report overage=$expected_stub_overage B: $stub_ceil_out"
fi

# --- Scenario 5: exact STUB_CEILING passes (inclusive bound) ---
AT_STUB_CEIL_DIR="$TMP_ROOT/at_stub_ceiling"
build_fixture "$AT_STUB_CEIL_DIR" "$skill_midpoint" "$STUB_CEILING"

at_stub_ceil_out="$(cd "$AT_STUB_CEIL_DIR" && bash scripts/check-copilot-skill-budget.sh 2>&1)"
at_stub_ceil_rc=$?

if [[ $at_stub_ceil_rc -eq 0 ]]; then
  _pass "fixture at exactly STUB_CEILING exits 0"
else
  _fail "fixture at exactly STUB_CEILING exited $at_stub_ceil_rc (expected 0): $at_stub_ceil_out"
fi

# --- Scenario 6: a source file dropped from the built SKILL.md (heading
#     missing) fails as "embed incomplete", distinct from and checked
#     before the FLOOR/STUB_CEILING checks. ---
DROPPED_HEADING_DIR="$TMP_ROOT/dropped_heading"
build_fixture "$DROPPED_HEADING_DIR" "$skill_midpoint" "$stub_midpoint"
python3 -c "
path = '$DROPPED_HEADING_DIR/.github/skills/dinostack/SKILL.md'
with open(path) as f:
    lines = f.readlines()
lines = [l for l in lines if l.strip() != '## Section 1']
with open(path, 'w') as f:
    f.writelines(lines)
"

dropped_heading_out="$(cd "$DROPPED_HEADING_DIR" && bash scripts/check-copilot-skill-budget.sh 2>&1)"
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

# --- Scenario 7: an outright ADDED section source file (count above
#     EXPECTED_SECTION_COUNT) fails as "embed incomplete" with the
#     added-file direction message. ---
EXTRA_FILE_DIR="$TMP_ROOT/extra_file"
build_fixture "$EXTRA_FILE_DIR" "$skill_midpoint" "$stub_midpoint"
extra_count=$(( EXPECTED_SECTION_COUNT + 1 ))
printf '## Section %d\n\nstub body.\n' "$extra_count" \
  > "$EXTRA_FILE_DIR/content/sections/$(printf '%02d' "$extra_count")-stub.md"

extra_file_out="$(cd "$EXTRA_FILE_DIR" && bash scripts/check-copilot-skill-budget.sh 2>&1)"
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

# --- Scenario 8: an outright DELETED section source file (count below
#     EXPECTED_SECTION_COUNT) fails as "embed incomplete" with the
#     deleted-file direction message. Deriving the expected count from
#     the working tree instead of a pinned constant would make this
#     scenario silently pass. ---
MISSING_FILE_DIR="$TMP_ROOT/missing_file"
build_fixture "$MISSING_FILE_DIR" "$skill_midpoint" "$stub_midpoint"
rm "$MISSING_FILE_DIR/content/sections/01-stub.md"

missing_file_out="$(cd "$MISSING_FILE_DIR" && bash scripts/check-copilot-skill-budget.sh 2>&1)"
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

# --- Scenario 9: the duplicate-heading guard. Two distinct source files
#     sharing the same top-level heading text means the per-file presence
#     check cannot tell which file's copy it matched. ---
DUPLICATE_HEADING_DIR="$TMP_ROOT/duplicate_heading"
build_fixture "$DUPLICATE_HEADING_DIR" "$skill_midpoint" "$stub_midpoint"
printf '## Section 1\n\nstub body.\n' > "$DUPLICATE_HEADING_DIR/content/sections/02-stub.md"

duplicate_heading_out="$(cd "$DUPLICATE_HEADING_DIR" && bash scripts/check-copilot-skill-budget.sh 2>&1)"
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

# --- Scenario 10: required-input-missing paths. Neither SKILL_FILE nor
#     STUB_FILE is present -> exit 1 naming the missing path. Exercised
#     independently: SKILL_FILE alone missing, then STUB_FILE alone
#     missing (with SKILL_FILE present), since the gate checks SKILL_FILE
#     first. ---
NO_SKILL_DIR="$TMP_ROOT/no_skill"
build_fixture "$NO_SKILL_DIR" "$skill_midpoint" "$stub_midpoint"
rm "$NO_SKILL_DIR/.github/skills/dinostack/SKILL.md"

no_skill_out="$(cd "$NO_SKILL_DIR" && bash scripts/check-copilot-skill-budget.sh 2>&1)"
no_skill_rc=$?

if [[ $no_skill_rc -ne 0 ]]; then
  _pass "fixture missing SKILL.md exits non-zero"
else
  _fail "fixture missing SKILL.md exited 0 (expected non-zero): $no_skill_out"
fi

if echo "$no_skill_out" | grep -q "missing file.*SKILL.md"; then
  _pass "fixture missing SKILL.md names the missing file"
else
  _fail "fixture missing SKILL.md did not name the missing file: $no_skill_out"
fi

NO_STUB_DIR="$TMP_ROOT/no_stub"
build_fixture "$NO_STUB_DIR" "$skill_midpoint" "$stub_midpoint"
rm "$NO_STUB_DIR/.github/copilot-instructions.md"

no_stub_out="$(cd "$NO_STUB_DIR" && bash scripts/check-copilot-skill-budget.sh 2>&1)"
no_stub_rc=$?

if [[ $no_stub_rc -ne 0 ]]; then
  _pass "fixture missing copilot-instructions.md exits non-zero"
else
  _fail "fixture missing copilot-instructions.md exited 0 (expected non-zero): $no_stub_out"
fi

if echo "$no_stub_out" | grep -q "missing file.*copilot-instructions.md"; then
  _pass "fixture missing copilot-instructions.md names the missing file"
else
  _fail "fixture missing copilot-instructions.md did not name the missing file: $no_stub_out"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
