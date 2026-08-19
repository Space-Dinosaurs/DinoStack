#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-skill-embed-budget.sh. Exercises
#          bash/zsh parity, the floor-fail path (embed regression to a
#          pointer-only skill), the ceiling-fail path (payload above the
#          verified-safe injection range), the pass path (in range), the
#          exact-bound (inclusive) cases at FLOOR and CEILING, and the
#          embed-completeness check (DS-143 follow-up): a source file's
#          heading dropped from SKILL.md while the file count still
#          matches, an outright added source file (count above
#          EXPECTED_SECTION_COUNT), and an outright deleted source file
#          (count below EXPECTED_SECTION_COUNT) - the deleted-section
#          tautology this gate exists to close.
#
#          DS-182 added an informational git-based "burn" line (a B/day
#          rate, not a raw delta) to EVERY exit path - OK, BELOW FLOOR, and
#          ABOVE CEILING alike (no delta axis, deliberately - see the gate
#          script's own header comment for why a generated artifact gets a
#          burn line instead of a hard per-PR delta limit). build_fixture()
#          above has always built a pure-filesystem-copy fixture with NO
#          `git init` at all - verified by its absence in that function -
#          so every existing scenario above already exercises the burn
#          line's SKIPPED-degrade path (it never prints a blank line, per
#          budget_burn_line's contract) without a single line changed; the
#          new scenarios below add an explicit assertion for that instead
#          of leaving it implicit, plus a second, git-backed fixture
#          builder (build_git_fixture) for the scenario that needs a real
#          base commit to diff against: the burn line rendering before the
#          final `headroom to ceiling:` line (the restored pre-DS-182
#          wording bin/ds-evaluate's summary depends on) with the exit
#          code unchanged.
#
# Public API: ./bin/tests/test_check_skill_embed_budget.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc, python3, grep, cut (build_fixture() calls
#                python3 to write a deterministic-size stub SKILL.md; FLOOR,
#                CEILING, EXPECTED_SECTION_COUNT, and EXPECTED_RULES_COUNT
#                are parsed out of the gate script with grep|cut, so this
#                suite never hardcodes a copy that can drift from the real
#                values). git is required for the DS-182 git-backed
#                scenario - no soft-skip, since bin-tests.yml always
#                provides one. zsh is required for the bash/zsh parity
#                assertion when running in CI (the assertion FAILs if zsh
#                is absent under CI=true); locally, without zsh on PATH it
#                is skipped (not failed) so contributors without zsh
#                installed can still run the rest of the suite.
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
#               fixture repos and stub files (including the DS-182
#               git-backed one) live under a mktemp -d directory that is
#               removed on exit via trap. Does not touch network - the
#               "origin" remote used by build_git_fixture is a local bare
#               repo under the same mktemp -d. Runs correctly from any cwd.
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
#     touching the real working tree. It needs: scripts/ (copies of the
#     real gate script and the shared lib it sources), content/sections/
#     and content/rules/ (stub source files satisfying the embed-
#     completeness check - see the fixture design note above), and
#     .claude/skills/dinostack/SKILL.md embedding every stub's
#     heading, padded to a controlled total size.
# $1 = fixture dir; $2 = SKILL.md byte count.
build_fixture() {
  local dir="$1" skill_bytes="$2"
  mkdir -p "$dir/scripts/lib" "$dir/.claude/skills/dinostack" \
    "$dir/content/sections" "$dir/content/rules"

  cp "$GATE_SCRIPT" "$dir/scripts/check-skill-embed-budget.sh"
  cp "$GATE_LIB" "$dir/scripts/lib/budget-gate.sh"

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

skill_path = os.path.join(fixture_dir, '.claude', 'skills', 'dinostack', 'SKILL.md')
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

# --- Scenario 1b (DS-182): build_fixture() above never runs `git init` -
#     the burn line therefore renders its "SKIPPED (base unresolvable)"
#     variant against this same non-git PARITY_DIR fixture (never a blank
#     line, per budget_burn_line's contract), and $bash_out from
#     Scenario 1 already captured that run's output - assert the SKIPPED
#     text explicitly, and that the output still ends with the
#     `headroom to ceiling:` line (the restored pre-DS-182 wording;
#     bin/ds-evaluate's _collect_budget_gates depends on this exact
#     lines[-1] text as this gate's summary). ---
if echo "$bash_out" | grep -q "burn: SKIPPED (base unresolvable)"; then
  _pass "burn line renders its SKIPPED variant (not a crash, not a blank line) against a non-git fixture"
else
  _fail "burn line did not render SKIPPED against a non-git fixture: $bash_out"
fi

parity_last_line="$(echo "$bash_out" | grep -v '^[[:space:]]*$' | tail -1)"
if [[ "$parity_last_line" == "  headroom to ceiling:"*"B" ]]; then
  _pass "non-git fixture's last output line is still the headroom to ceiling: line"
else
  _fail "non-git fixture's last output line is [$parity_last_line], expected a headroom to ceiling: line"
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

# DS-182 Major 2 regression coverage: the burn line must render on the
# BELOW FLOOR failure path too, not only the OK path - mutation that
# would redden this: move the `burn_line="$(budget_burn_line ...)"` call
# back to after the FLOOR/CEILING checks (its pre-fix position).
if echo "$floor_out" | grep -q "burn: SKIPPED"; then
  _pass "below-floor fixture still renders the burn line before exiting"
else
  _fail "below-floor fixture did not render the burn line: $floor_out"
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

# DS-182 Major 2 regression coverage: the burn line must render on the
# ABOVE CEILING failure path too, not only the OK path.
if echo "$ceiling_out" | grep -q "burn: SKIPPED"; then
  _pass "above-ceiling fixture still renders the burn line before exiting"
else
  _fail "above-ceiling fixture did not render the burn line: $ceiling_out"
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
path = '$DROPPED_HEADING_DIR/.claude/skills/dinostack/SKILL.md'
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

# --- Scenario 8: the duplicate-heading guard. Two distinct source files
#     sharing the same top-level heading text means the per-file presence
#     check (`grep -qxF "$heading" "$SKILL_FILE"`) cannot tell which file's
#     copy it matched - if section 2 shares section 1's exact heading, its
#     presence check finds section 1's real occurrence in the built
#     SKILL.md and passes even if section 2 itself was dropped entirely.
#     Rewriting section 2's own source heading to duplicate section 1's
#     (SKILL.md is left untouched, still carrying only ONE occurrence of
#     that heading text - the real one from section 1) reproduces exactly
#     that ambiguity and must be caught by the duplicate guard, not silently
#     pass because presence alone was satisfied.
# ---------------------------------------------------------------------------
DUPLICATE_HEADING_DIR="$TMP_ROOT/duplicate_heading"
build_fixture "$DUPLICATE_HEADING_DIR" "$midpoint2"
printf '## Section 1\n\nstub body.\n' > "$DUPLICATE_HEADING_DIR/content/sections/02-stub.md"

duplicate_heading_out="$(cd "$DUPLICATE_HEADING_DIR" && bash scripts/check-skill-embed-budget.sh 2>&1)"
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

# --- Scenario 9 (DS-182): git-backed burn-line fixture. A real git repo
#     (not a mock) with one commit on "main" pushed to a local bare
#     "origin" remote under the same mktemp -d, so budget_base_resolve/
#     budget_delta (called internally by budget_burn_line) exercise the
#     actual git plumbing they shell out to. $1 = fixture dir; $2 =
#     base-commit SKILL.md byte count.
build_git_fixture() {
  local dir="$1" base_bytes="$2"
  build_fixture "$dir" "$base_bytes"
  git -C "$dir" init -q -b main
  git -C "$dir" add -A
  git -C "$dir" -c user.email="test@example.com" -c user.name="test" commit -q -m base
  git -C "$dir" init -q --bare "$dir.origin.git"
  git -C "$dir" remote add origin "$dir.origin.git"
  git -C "$dir" push -q origin main
}

# Rewrites the fixture's SKILL.md to a new byte count while preserving
# every section/rule heading the embed-completeness check requires -
# used to simulate an uncommitted (working-tree-only) size change against
# the git fixture's committed base.
_resize_skill_md() {
  local dir="$1" new_bytes="$2"
  python3 -c "
import sys, os

fixture_dir = sys.argv[1]
new_bytes = int(sys.argv[2])
section_count = int(sys.argv[3])
rules_count = int(sys.argv[4])

headings = []
for i in range(1, section_count + 1):
    headings.append('## Section %d' % i)
for i in range(1, rules_count + 1):
    headings.append('## Rule %d' % i)

header_block = '\n'.join(headings) + '\n'
header_bytes = len(header_block.encode())
pad_len = new_bytes - header_bytes
if pad_len < 0:
    sys.stderr.write('_resize_skill_md: new_bytes too small to hold headings\n')
    sys.exit(1)

skill_path = os.path.join(fixture_dir, '.claude', 'skills', 'dinostack', 'SKILL.md')
with open(skill_path, 'w') as f:
    f.write(header_block)
    f.write('x' * pad_len)
" "$dir" "$new_bytes" "$EXPECTED_SECTION_COUNT" "$EXPECTED_RULES_COUNT"
}

if command -v git >/dev/null 2>&1; then
  BURN_DIR="$TMP_ROOT/burn"
  base_size="$midpoint2"
  build_git_fixture "$BURN_DIR" "$base_size"
  current_size=$(( base_size + 777 ))
  _resize_skill_md "$BURN_DIR" "$current_size"

  burn_out="$(cd "$BURN_DIR" && bash scripts/check-skill-embed-budget.sh 2>&1)"
  burn_rc=$?

  if [[ $burn_rc -eq 0 ]]; then
    _pass "burn-line fixture (git-backed) still exits 0 - the burn line never affects the exit code"
  else
    _fail "burn-line fixture exited $burn_rc (expected 0): $burn_out"
  fi

  # base_size's commit was made moments ago by build_git_fixture, so the
  # whole-day span floors to 1 and burn_per_day == the raw delta (+777 B)
  # exactly - deterministic, not time-dependent. days_to_limit =
  # (CEILING - current_size) / 777, same integer-division truncation the
  # gate script itself performs.
  expected_headroom_to_ceiling=$(( CEILING - current_size ))
  expected_days_to_limit=$(( expected_headroom_to_ceiling / 777 ))
  expected_burn_line="burn: 777 B/day over 1 d - ${expected_days_to_limit} d to limit"

  if echo "$burn_out" | grep -qF "$expected_burn_line"; then
    _pass "burn-line fixture reports the correct B/day burn rate and days-to-limit"
  else
    _fail "burn-line fixture did not report [$expected_burn_line]: $burn_out"
  fi

  burn_line_pos="$(echo "$burn_out" | grep -n "^  burn:" | head -1 | cut -d: -f1)"
  headroom_line_pos="$(echo "$burn_out" | grep -n "headroom to ceiling:" | head -1 | cut -d: -f1)"
  if [[ -n "$burn_line_pos" && -n "$headroom_line_pos" && "$burn_line_pos" -lt "$headroom_line_pos" ]]; then
    _pass "burn line renders before the final headroom to ceiling: line"
  else
    _fail "burn line did not render before headroom to ceiling: line (burn@[$burn_line_pos], headroom@[$headroom_line_pos]): $burn_out"
  fi

  burn_last_line="$(echo "$burn_out" | grep -v '^[[:space:]]*$' | tail -1)"
  if [[ "$burn_last_line" == "  headroom to ceiling:"*"B" ]]; then
    _pass "burn-line fixture's lines[-1] is still the headroom to ceiling: line (the exact pre-DS-182 wording bin/ds-evaluate's summary depends on)"
  else
    _fail "burn-line fixture's lines[-1] is [$burn_last_line], expected a headroom to ceiling: line"
  fi
elif [[ -n "${CI:-}" ]]; then
  _fail "git absent on PATH in CI - the DS-182 git-backed burn-line scenario cannot be skipped here"
else
  echo "SKIP: git not found on PATH - skipping the DS-182 git-backed burn-line scenario (non-git SKIPPED-degrade coverage above still applies)"
fi

# --- Scenario 10 (DS-182): the resident-budget.yml check-skill-embed-
#     budget job's checkout step carries fetch-depth: 0 (needed for the
#     burn line's origin/main resolution), while the sibling
#     check-resident-budget job's checkout is deliberately left alone -
#     that gate gained no git axis. Asserted against the real workflow
#     file, since checkout depth is a workflow property, not a
#     gate-script property. ---
RESIDENT_WORKFLOW_FILE="$REPO_DIR/.github/workflows/resident-budget.yml"
if [[ ! -f "$RESIDENT_WORKFLOW_FILE" ]]; then
  _fail "$RESIDENT_WORKFLOW_FILE not found"
else
  # Bounded to the check-skill-embed-budget job's own block: stops at the
  # next 2-space-indented "key:"-only line (i.e. the next job header), not
  # read-to-EOF - a job appended after this one in the workflow file would
  # otherwise silently bleed into the asserted block.
  skill_embed_job_block="$(awk '
    /^  check-skill-embed-budget:$/ { found=1; print; next }
    found && /^  [A-Za-z0-9_-]+:$/ { exit }
    found { print }
  ' "$RESIDENT_WORKFLOW_FILE")"
  if echo "$skill_embed_job_block" | grep -q 'fetch-depth: 0'; then
    _pass "resident-budget.yml's check-skill-embed-budget job carries fetch-depth: 0"
  else
    _fail "resident-budget.yml's check-skill-embed-budget job is missing fetch-depth: 0: $skill_embed_job_block"
  fi

  resident_job_block="$(awk '/^  check-resident-budget:/,/^  check-skill-embed-budget:/' "$RESIDENT_WORKFLOW_FILE")"
  if echo "$resident_job_block" | grep -q 'fetch-depth: 0'; then
    _fail "resident-budget.yml's check-resident-budget job unexpectedly carries fetch-depth: 0 - that job gained no git axis and should be left alone"
  else
    _pass "resident-budget.yml's check-resident-budget job correctly has no fetch-depth: 0 (no git axis)"
  fi
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
