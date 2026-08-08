#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-skill-embed-budget.sh. The
#          round-2 defects were a byte band that could not detect a whole
#          embedded content/rules/*.md or content/sections/*.md file
#          silently dropped from assembly (it can land inside the
#          FLOOR..CEILING dead zone undetected), and a deleted-file
#          tautology where deriving the "expected" file set from the same
#          working-tree glob that assembly itself reads makes an outright
#          `rm` of a source file invisible to the check (both sides move
#          together). The round-3 defect was that every scenario below sized
#          its fixture at exactly (FLOOR + CEILING) / 2, so the FLOOR and
#          CEILING checks themselves - the two bounds the gate exists to
#          enforce - had zero coverage; both bound checks could be deleted
#          wholesale and this suite stayed green. This test exercises the
#          gate script directly against a scratch fixture repo (never the
#          working tree itself), reproducing all four embed-completeness
#          mutations found during round 1/2 review (a rules file dropped
#          from the .claude/build.sh embed loop - conventions.md and
#          code-standards.md, tested separately since they sort on either
#          side of each other; a section dropped from
#          scripts/build-methodology.sh's assembly while the source file
#          stays on disk; a section file deleted outright from disk) plus
#          the two round-3 bound scenarios (a fixture sized below FLOOR, a
#          fixture padded past CEILING) - each asserting the specific bound
#          message, not just the exit code, since a bound violation and an
#          embed-incomplete failure both exit 1 and must be told apart.
#
# Public API: ./bin/tests/test_check_skill_embed_budget.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc, python3, grep, cut (build_fixture() calls
#                python3 to write deterministic padded fixture files;
#                FLOOR, CEILING, EXPECTED_SECTION_COUNT, and
#                EXPECTED_RULES_COUNT are parsed out of the gate script with
#                grep|cut so the fixture always matches the live ratchet
#                values instead of a copy that can drift). zsh is required
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
# Failure modes: gate script missing -> immediate FAIL. Any scenario's
#                observed exit code or message does not match the expected
#                shape -> FAIL naming the scenario and what was observed.
#
# Test hygiene: never mutates any tracked file in the working tree. All
#               fixture repos, stub scripts, and content live under a
#               mktemp -d directory removed on exit via trap. Does not touch
#               network. Runs correctly from any cwd.

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

# --- Read the live ratchet constants out of the real gate script so the
#     fixture always matches the current EXPECTED_SECTION_COUNT /
#     EXPECTED_RULES_COUNT / FLOOR / CEILING instead of a copy that can
#     drift when those values ratchet in a future PR.
FLOOR="$(grep -E '^FLOOR=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
CEILING="$(grep -E '^CEILING=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
EXPECTED_SECTION_COUNT="$(grep -E '^EXPECTED_SECTION_COUNT=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
EXPECTED_RULES_COUNT="$(grep -E '^EXPECTED_RULES_COUNT=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"

for name_val in "FLOOR:$FLOOR" "CEILING:$CEILING" "EXPECTED_SECTION_COUNT:$EXPECTED_SECTION_COUNT" "EXPECTED_RULES_COUNT:$EXPECTED_RULES_COUNT"; do
  cname="${name_val%%:*}"
  cval="${name_val#*:}"
  if [[ -z "$cval" ]]; then
    _fail "could not read $cname out of $GATE_SCRIPT"
    echo ""
    echo "Results: $PASS passed, $FAIL failed"
    exit 1
  fi
done

if [[ "$EXPECTED_RULES_COUNT" -ne 2 ]]; then
  _fail "this test hardcodes two rules fixture files named code-standards.md and conventions.md - EXPECTED_RULES_COUNT is $EXPECTED_RULES_COUNT, not 2. Update this test's fixture to match before trusting its results."
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

# --- Build a scratch fixture repo the gate script can run against
#     unmodified: it resolves REPO_DIR from its own path, so a copy of the
#     gate script placed at $dir/scripts/check-skill-embed-budget.sh treats
#     $dir as the repo root. The fixture supplies EXPECTED_SECTION_COUNT
#     content/sections/*.md files, a code-standards.md + conventions.md +
#     module-manifest.md under content/rules/, a stub
#     scripts/build-methodology.sh that assembles the section files (same
#     glob/sort shape as the real one), and a stub .claude/build.sh that
#     calls it and then embeds the rules files (skipping module-manifest.md,
#     same as the real one) - deterministic and network-free. $2, if given,
#     overrides the target total byte size (default: roughly midway between
#     FLOOR and CEILING) - used by the round-3 FLOOR/CEILING scenarios below
#     to size a fixture that actually crosses one of the bounds instead of
#     always landing safely inside them.
build_fixture() {
  local dir="$1"
  mkdir -p "$dir/scripts" "$dir/content/sections" "$dir/content/rules" "$dir/.claude/skills/agentic-engineering"

  cp "$GATE_SCRIPT" "$dir/scripts/check-skill-embed-budget.sh"

  local total_files=$(( EXPECTED_SECTION_COUNT + 2 ))
  local target_total="${2:-$(( (FLOOR + CEILING) / 2 ))}"
  local per_file=$(( target_total / total_files ))
  if [[ $per_file -lt 1 ]]; then
    per_file=1
  fi

  local i
  for (( i = 1; i <= EXPECTED_SECTION_COUNT; i++ )); do
    # NOTE: `local padded` and its assignment must stay on ONE line. Under
    # zsh, a bare `local padded` (declaration only) re-executed on a later
    # iteration of a C-style for loop - while `padded` already holds a
    # value from the previous iteration - echoes "padded=<value>" to
    # stdout as a side effect (reproduced in isolation; not a bash
    # behavior). Combining declaration and assignment avoids it entirely.
    local padded="$(printf '%02d' "$i")"
    python3 -c "
import sys
n = int(sys.argv[1])
heading = sys.argv[2]
body = 'x' * max(n - len(heading) - 1, 0)
sys.stdout.write(heading + '\n' + body)
" "$per_file" "## Section $i" > "$dir/content/sections/${padded}-fixture.md"
  done

  python3 -c "
import sys
n = int(sys.argv[1])
heading = '## Documentation Lookups'
body = 's' * max(n - len(heading) - 1, 0)
sys.stdout.write(heading + '\n' + body)
" "$per_file" > "$dir/content/rules/code-standards.md"

  python3 -c "
import sys
n = int(sys.argv[1])
heading = '## Writing Style'
body = 'c' * max(n - len(heading) - 1, 0)
sys.stdout.write(heading + '\n' + body)
" "$per_file" > "$dir/content/rules/conventions.md"

  cat > "$dir/content/rules/module-manifest.md" <<'EOF'
## Module Manifests
Excluded from the embed - must not be counted or checked.
EOF

  cat > "$dir/scripts/build-methodology.sh" <<'BUILDMETH'
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
LC_ALL=C find "$DIR/content/sections" -maxdepth 1 -type f -name '[0-9][0-9]-*.md' | LC_ALL=C sort | while IFS= read -r f; do
  cat "$f"
  echo
done
BUILDMETH
  chmod +x "$dir/scripts/build-methodology.sh"

  cat > "$dir/.claude/build.sh" <<'BUILDSH'
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
SKILL_DST="$DIR/.claude/skills/agentic-engineering"
mkdir -p "$SKILL_DST"
bash "$DIR/scripts/build-methodology.sh" > "$SKILL_DST/METHODOLOGY.md"
{
  cat "$SKILL_DST/METHODOLOGY.md"
  echo
  for f in "$DIR/content/rules/"*.md; do
    name=$(basename "$f")
    [[ "$name" == "module-manifest.md" ]] && continue
    cat "$f"
    echo
  done
} > "$SKILL_DST/SKILL.md"
BUILDSH
  chmod +x "$dir/.claude/build.sh"
}

run_gate() {
  # $1 = fixture dir, $2 = shell (bash|zsh)
  (cd "$1" && "$2" scripts/check-skill-embed-budget.sh 2>&1)
}

# --- Scenario 0: clean fixture passes, and bash/zsh agree (parity) ---
BASELINE_DIR="$TMP_ROOT/baseline"
build_fixture "$BASELINE_DIR"

bash_out="$(run_gate "$BASELINE_DIR" bash)"
bash_rc=$?

if [[ $bash_rc -eq 0 ]]; then
  _pass "clean fixture exits 0 under bash"
else
  _fail "clean fixture exited $bash_rc under bash (expected 0): $bash_out"
fi

if echo "$bash_out" | grep -q "skill embed budget check: OK"; then
  _pass "clean fixture reports OK under bash"
else
  _fail "clean fixture did not report OK under bash: $bash_out"
fi

if command -v zsh >/dev/null 2>&1; then
  zsh_out="$(run_gate "$BASELINE_DIR" zsh)"
  zsh_rc=$?

  if [[ $zsh_rc -eq 0 ]]; then
    _pass "clean fixture exits 0 under zsh"
  else
    _fail "clean fixture exited $zsh_rc under zsh (expected 0): $zsh_out"
  fi

  if [[ "$bash_out" == "$zsh_out" ]]; then
    _pass "bash and zsh produce byte-identical output on the clean fixture"
  else
    _fail "bash and zsh output diverged on the clean fixture - bash: [$bash_out] zsh: [$zsh_out]"
  fi
elif [[ -n "${CI:-}" ]]; then
  _fail "zsh absent on PATH in CI - parity assertion cannot be skipped here"
else
  echo "SKIP: zsh not found on PATH - skipping zsh parity assertion (bash-only coverage below still applies)"
fi

# --- Scenario 1: conventions.md dropped from the .claude/build.sh embed
#     loop - the file remains in content/rules/ but never reaches SKILL.md.
CONV_DIR="$TMP_ROOT/conventions-dropped"
build_fixture "$CONV_DIR"
python3 - "$CONV_DIR/.claude/build.sh" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
old = '[[ "$name" == "module-manifest.md" ]] && continue'
new = old + '\n    [[ "$name" == "conventions.md" ]] && continue'
assert old in s, "fixture .claude/build.sh shape changed - update this mutation"
open(p, "w").write(s.replace(old, new))
PYEOF

conv_out="$(run_gate "$CONV_DIR" bash)"
conv_rc=$?

if [[ $conv_rc -ne 0 ]]; then
  _pass "conventions.md-dropped fixture exits non-zero"
else
  _fail "conventions.md-dropped fixture exited 0 (expected non-zero, this is the round-2 Major 1 regression): $conv_out"
fi

if echo "$conv_out" | grep -q "embed incomplete" && echo "$conv_out" | grep -q "conventions.md"; then
  _pass "conventions.md-dropped fixture reports embed incomplete naming conventions.md"
else
  _fail "conventions.md-dropped fixture did not report embed incomplete for conventions.md: $conv_out"
fi

if command -v zsh >/dev/null 2>&1; then
  conv_zsh_out="$(run_gate "$CONV_DIR" zsh)"
  conv_zsh_rc=$?
  if [[ $conv_zsh_rc -ne 0 ]] && echo "$conv_zsh_out" | grep -q "embed incomplete"; then
    _pass "conventions.md-dropped fixture fails identically under zsh"
  else
    _fail "conventions.md-dropped fixture did not fail identically under zsh (rc=$conv_zsh_rc): $conv_zsh_out"
  fi
fi

# --- Scenario 2: code-standards.md dropped from the .claude/build.sh embed
#     loop - sorts BEFORE conventions.md, so this is a distinct code path
#     from Scenario 1 (reaching the alphabetically-last file proves nothing
#     about an earlier one).
CS_DIR="$TMP_ROOT/code-standards-dropped"
build_fixture "$CS_DIR"
python3 - "$CS_DIR/.claude/build.sh" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
old = '[[ "$name" == "module-manifest.md" ]] && continue'
new = old + '\n    [[ "$name" == "code-standards.md" ]] && continue'
assert old in s, "fixture .claude/build.sh shape changed - update this mutation"
open(p, "w").write(s.replace(old, new))
PYEOF

cs_out="$(run_gate "$CS_DIR" bash)"
cs_rc=$?

if [[ $cs_rc -ne 0 ]]; then
  _pass "code-standards.md-dropped fixture exits non-zero"
else
  _fail "code-standards.md-dropped fixture exited 0 (expected non-zero, this is the round-2 Major 1 regression): $cs_out"
fi

if echo "$cs_out" | grep -q "embed incomplete" && echo "$cs_out" | grep -q "code-standards.md"; then
  _pass "code-standards.md-dropped fixture reports embed incomplete naming code-standards.md"
else
  _fail "code-standards.md-dropped fixture did not report embed incomplete for code-standards.md: $cs_out"
fi

# --- Scenario 3: a middle section dropped from build-methodology.sh's own
#     assembly, while the section file stays on disk - the deleted-file
#     tautology fix (pinned EXPECTED_SECTION_COUNT) must NOT be what catches
#     this; the per-file heading check must catch it, since the file count
#     on disk is unchanged.
MID_DIR="$TMP_ROOT/middle-section-dropped"
build_fixture "$MID_DIR"
# Pick a middle section (not first, not last) so this cannot be mistaken
# for a head/tail-only check passing by coincidence.
mid_index="$(printf '%02d' $(( EXPECTED_SECTION_COUNT / 2 )))"
mid_file="content/sections/${mid_index}-fixture.md"
if [[ ! -f "$MID_DIR/$mid_file" ]]; then
  _fail "expected fixture file $mid_file not found - fixture generation shape changed"
else
  python3 - "$MID_DIR/scripts/build-methodology.sh" "${mid_index}-fixture.md" <<'PYEOF'
import sys
p, excl = sys.argv[1], sys.argv[2]
s = open(p).read()
old = "LC_ALL=C sort | while IFS= read -r f; do"
new = f"LC_ALL=C sort | grep -v {excl} | while IFS= read -r f; do"
assert old in s, "fixture build-methodology.sh shape changed - update this mutation"
open(p, "w").write(s.replace(old, new))
PYEOF

  mid_out="$(run_gate "$MID_DIR" bash)"
  mid_rc=$?

  if [[ $mid_rc -ne 0 ]]; then
    _pass "middle-section-dropped fixture exits non-zero"
  else
    _fail "middle-section-dropped fixture exited 0 (expected non-zero): $mid_out"
  fi

  if echo "$mid_out" | grep -q "embed incomplete" && echo "$mid_out" | grep -q "${mid_index}-fixture.md"; then
    _pass "middle-section-dropped fixture reports embed incomplete naming the dropped section"
  else
    _fail "middle-section-dropped fixture did not report embed incomplete for the dropped section: $mid_out"
  fi

  # The file is still on disk in this scenario - confirm the failure is NOT
  # attributed to a file-count mismatch (that would mean the wrong check is
  # firing and the heading loop itself is not actually being exercised).
  if echo "$mid_out" | grep -q "file count mismatch"; then
    _fail "middle-section-dropped fixture was caught by the count check, not the heading loop - the file is still on disk, so this indicates the wrong detector fired: $mid_out"
  else
    _pass "middle-section-dropped fixture was caught by the heading loop, not the count check (file remains on disk, as expected)"
  fi
fi

# --- Scenario 4: a section file deleted outright from disk - the
#     deleted-file tautology (round-2 Major 2). Before the fix, deriving
#     the expected heading set from the same working-tree glob that
#     assembly reads made this invisible: the deleted file vanishes from
#     both sides at once. EXPECTED_SECTION_COUNT is a pinned constant
#     specifically so this trips a count mismatch instead.
DEL_DIR="$TMP_ROOT/section-deleted"
build_fixture "$DEL_DIR"
del_index="$(printf '%02d' 1)"
del_file="$DEL_DIR/content/sections/${del_index}-fixture.md"
if [[ ! -f "$del_file" ]]; then
  _fail "expected fixture file content/sections/${del_index}-fixture.md not found - fixture generation shape changed"
else
  rm "$del_file"

  del_out="$(run_gate "$DEL_DIR" bash)"
  del_rc=$?

  if [[ $del_rc -ne 0 ]]; then
    _pass "section-deleted fixture exits non-zero"
  else
    _fail "section-deleted fixture exited 0 (expected non-zero, this is the round-2 Major 2 deleted-file tautology): $del_out"
  fi

  if echo "$del_out" | grep -q "embed incomplete" && echo "$del_out" | grep -q "file count mismatch"; then
    _pass "section-deleted fixture reports embed incomplete via a file count mismatch"
  else
    _fail "section-deleted fixture did not report a file count mismatch: $del_out"
  fi

  if command -v zsh >/dev/null 2>&1; then
    del_zsh_out="$(run_gate "$DEL_DIR" zsh)"
    del_zsh_rc=$?
    if [[ $del_zsh_rc -ne 0 ]] && echo "$del_zsh_out" | grep -q "file count mismatch"; then
      _pass "section-deleted fixture fails identically under zsh"
    else
      _fail "section-deleted fixture did not fail identically under zsh (rc=$del_zsh_rc): $del_zsh_out"
    fi
  fi
fi

# --- Scenario 5 (round-3 Major): fixture shrunk below FLOOR. Every scenario
#     above sizes its fixture at roughly (FLOOR + CEILING) / 2, so none of
#     them ever crossed either bound - both the FLOOR and CEILING checks
#     could be deleted wholesale and this suite stayed green (the round-3
#     defect this scenario and the next one close). Every file and heading
#     is still present here - only the padding shrinks - so this must be
#     caught by the byte-band check, not the embed-completeness check.
#     Assert the specific "UNDER FLOOR" message, not just the exit code: a
#     bound violation and an embed-incomplete failure both exit 1.
FLOOR_DIR="$TMP_ROOT/under-floor"
floor_target=$(( FLOOR - (FLOOR / 3) ))
if [[ $floor_target -lt 1 ]]; then
  floor_target=1
fi
build_fixture "$FLOOR_DIR" "$floor_target"

floor_out="$(run_gate "$FLOOR_DIR" bash)"
floor_rc=$?

if [[ $floor_rc -ne 0 ]]; then
  _pass "under-floor fixture exits non-zero"
else
  _fail "under-floor fixture exited 0 (expected non-zero, this is the round-3 Major missing-bound-coverage regression): $floor_out"
fi

if echo "$floor_out" | grep -q "UNDER FLOOR"; then
  _pass "under-floor fixture reports UNDER FLOOR"
else
  _fail "under-floor fixture did not report UNDER FLOOR: $floor_out"
fi

if echo "$floor_out" | grep -q "embed incomplete"; then
  _fail "under-floor fixture was misreported as embed incomplete instead of a bound violation - every file and heading is present in this fixture, only padding shrank: $floor_out"
else
  _pass "under-floor fixture is reported as a bound violation, not embed incomplete"
fi

if command -v zsh >/dev/null 2>&1; then
  floor_zsh_out="$(run_gate "$FLOOR_DIR" zsh)"
  floor_zsh_rc=$?
  if [[ $floor_zsh_rc -ne 0 ]] && echo "$floor_zsh_out" | grep -q "UNDER FLOOR"; then
    _pass "under-floor fixture fails identically under zsh"
  else
    _fail "under-floor fixture did not fail identically under zsh (rc=$floor_zsh_rc): $floor_zsh_out"
  fi
fi

# --- Scenario 6 (round-3 Major): a rules fixture padded past CEILING after
#     a normal, complete build. Every file and heading is still present -
#     only content/rules/conventions.md's body grows - so this must be
#     caught by the byte-band check, not the embed-completeness check.
CEIL_DIR="$TMP_ROOT/over-ceiling"
build_fixture "$CEIL_DIR"
ceiling_pad_bytes=$(( CEILING - (FLOOR + CEILING) / 2 + 10000 ))
python3 -c "
import sys
n = int(sys.argv[1])
path = sys.argv[2]
with open(path, 'a') as f:
    f.write('p' * n)
" "$ceiling_pad_bytes" "$CEIL_DIR/content/rules/conventions.md"

ceiling_out="$(run_gate "$CEIL_DIR" bash)"
ceiling_rc=$?

if [[ $ceiling_rc -ne 0 ]]; then
  _pass "over-ceiling fixture exits non-zero"
else
  _fail "over-ceiling fixture exited 0 (expected non-zero, this is the round-3 Major missing-bound-coverage regression): $ceiling_out"
fi

if echo "$ceiling_out" | grep -q "OVER CEILING"; then
  _pass "over-ceiling fixture reports OVER CEILING"
else
  _fail "over-ceiling fixture did not report OVER CEILING: $ceiling_out"
fi

if echo "$ceiling_out" | grep -q "embed incomplete"; then
  _fail "over-ceiling fixture was misreported as embed incomplete instead of a bound violation - every file and heading is present in this fixture, only conventions.md's body grew: $ceiling_out"
else
  _pass "over-ceiling fixture is reported as a bound violation, not embed incomplete"
fi

if command -v zsh >/dev/null 2>&1; then
  ceiling_zsh_out="$(run_gate "$CEIL_DIR" zsh)"
  ceiling_zsh_rc=$?
  if [[ $ceiling_zsh_rc -ne 0 ]] && echo "$ceiling_zsh_out" | grep -q "OVER CEILING"; then
    _pass "over-ceiling fixture fails identically under zsh"
  else
    _fail "over-ceiling fixture did not fail identically under zsh (rc=$ceiling_zsh_rc): $ceiling_zsh_out"
  fi
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
