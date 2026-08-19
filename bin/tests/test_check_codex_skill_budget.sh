#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-codex-skill-budget.sh (DS-183
#          round 2 - the missing suite the Skeptic flagged Major: every
#          other budget gate under scripts/ has one
#          (bin/tests/test_check_{resident,skill_embed,command_file}_budget.sh
#          and test_budget_gate_lib.sh) and this one shipped without.
#          Exercises, one mutation per axis: (1) missing METHODOLOGY.md,
#          (2) missing AGENTS.md, (3) section file count above
#          EXPECTED_SECTION_COUNT, (4) section file count below it, (5) a
#          section file's heading dropped from METHODOLOGY.md, (6)
#          duplicate section headings across two source files, (7) the
#          rules symlink missing, (8) the rules symlink resolving to a
#          directory with the wrong file count, (9) METHODOLOGY.md below
#          METHODOLOGY_FLOOR, (10) AGENTS.md above AGENTS_STUB_CEILING, and
#          (11) the OK pass path with a correct fixture. Also asserts bash
#          and zsh (when available; hard-fails under CI=true rather than
#          skipping - see the CI guard below) invoke the gate identically.
#
# Public API: ./bin/tests/test_check_codex_skill_budget.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc, python3, grep, cut. METHODOLOGY_FLOOR,
#                AGENTS_STUB_CEILING, EXPECTED_SECTION_COUNT, and
#                EXPECTED_RULES_COUNT are parsed out of the real gate
#                script with grep|cut, never hardcoded here, so this suite
#                cannot silently drift from the live values as they
#                ratchet over time.
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script or shared lib missing -> immediate FAIL. Any
#                scenario's observed exit code or message does not match
#                the expected shape -> FAIL naming the scenario and what
#                was observed. The bash/zsh parity assertion FAILs (not
#                skips) when zsh is absent AND CI=true - a shell gate whose
#                assertion silently skips under a guard that never fires in
#                CI asserts nothing while looking green (the exact class of
#                defect recorded against check-resident-budget.sh's own
#                zsh guard in this repo's history).
#
# Test hygiene: never mutates any tracked file in the working tree. All
#               fixture repos live under a mktemp -d directory removed on
#               exit via trap. Runs correctly from any cwd.
#
# Fixture design note: check-codex-skill-budget.sh resolves REPO_DIR as the
#               parent of its own script directory (scripts/lib/
#               budget-gate.sh's budget_repo_dir, called with the gate
#               script's OWN location) - not overridable via an env var -
#               so every fixture below is a full scratch tree with copies
#               of the gate script and shared lib under
#               <fixture>/scripts/, exactly the pattern
#               test_check_skill_embed_budget.sh already established for
#               the sibling gate.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-codex-skill-budget.sh"
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

METHODOLOGY_FLOOR="$(grep -E '^METHODOLOGY_FLOOR=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
AGENTS_STUB_CEILING="$(grep -E '^AGENTS_STUB_CEILING=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
EXPECTED_SECTION_COUNT="$(grep -E '^EXPECTED_SECTION_COUNT=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
EXPECTED_RULES_COUNT="$(grep -E '^EXPECTED_RULES_COUNT=' "$GATE_SCRIPT" | head -1 | cut -d= -f2)"
for name in METHODOLOGY_FLOOR AGENTS_STUB_CEILING EXPECTED_SECTION_COUNT EXPECTED_RULES_COUNT; do
  if [[ -z "${!name}" ]]; then
    _fail "could not read $name out of $GATE_SCRIPT"
    echo ""
    echo "Results: $PASS passed, $FAIL failed"
    exit 1
  fi
done

# build_fixture <dir> <methodology_bytes> <agents_bytes>
#   Builds a full scratch repo: scripts/{check-codex-skill-budget.sh,lib/
#   budget-gate.sh} (copies of the real ones), content/sections/ (
#   EXPECTED_SECTION_COUNT stubs, each with a distinct heading),
#   content/rules/ (EXPECTED_RULES_COUNT stubs), a real rules/ symlink
#   under .codex/skills/dinostack/ pointing at content/rules, and
#   METHODOLOGY.md/AGENTS.md padded to the requested byte counts (embedding
#   every section heading so the embed-completeness check passes by
#   default - individual scenarios mutate from there).
build_fixture() {
  local dir="$1" methodology_bytes="$2" agents_bytes="$3"
  mkdir -p "$dir/scripts/lib" "$dir/content/sections" "$dir/content/rules" \
    "$dir/.codex/skills/dinostack"

  cp "$GATE_SCRIPT" "$dir/scripts/check-codex-skill-budget.sh"
  cp "$GATE_LIB" "$dir/scripts/lib/budget-gate.sh"

  python3 -c "
import sys, os

fixture_dir, methodology_bytes, agents_bytes, section_count, rules_count = sys.argv[1:6]
methodology_bytes = int(methodology_bytes)
agents_bytes = int(agents_bytes)
section_count = int(section_count)
rules_count = int(rules_count)

headings = []
for i in range(1, section_count + 1):
    heading = '## Section %d' % i
    headings.append(heading)
    path = os.path.join(fixture_dir, 'content', 'sections', '%02d-stub.md' % i)
    with open(path, 'w') as f:
        f.write(heading + '\n\nstub body.\n')

for i in range(1, rules_count + 1):
    path = os.path.join(fixture_dir, 'content', 'rules', 'rule%d.md' % i)
    with open(path, 'w') as f:
        f.write('## Rule %d\n\nstub body.\n' % i)

header_block = '\n'.join(headings) + '\n'
header_bytes = len(header_block.encode())
pad_len = methodology_bytes - header_bytes
if pad_len < 0:
    sys.stderr.write('build_fixture: methodology_bytes too small for headings\n')
    sys.exit(1)

methodology_path = os.path.join(fixture_dir, '.codex', 'skills', 'dinostack', 'METHODOLOGY.md')
with open(methodology_path, 'w') as f:
    f.write(header_block)
    f.write('x' * pad_len)

agents_path = os.path.join(fixture_dir, 'AGENTS.md')
os.makedirs(os.path.dirname(agents_path), exist_ok=True)
with open(agents_path, 'w') as f:
    f.write('x' * agents_bytes)
" "$dir" "$methodology_bytes" "$agents_bytes" "$EXPECTED_SECTION_COUNT" "$EXPECTED_RULES_COUNT"

  mkdir -p "$dir/.codex"
  mv "$dir/AGENTS.md" "$dir/.codex/AGENTS.md"

  ln -s "../../../content/rules" "$dir/.codex/skills/dinostack/rules"
}

# run_gate <dir> -> stdout on fd1, stderr on fd2, sets RC
run_gate() {
  local dir="$1"
  GATE_STDOUT="$(bash "$dir/scripts/check-codex-skill-budget.sh" 2>"$TMP_ROOT/stderr.tmp")"
  RC=$?
  GATE_STDERR="$(cat "$TMP_ROOT/stderr.tmp")"
}

MID_METHODOLOGY=$(( (METHODOLOGY_FLOOR * 2) ))
MID_AGENTS=$(( AGENTS_STUB_CEILING / 2 ))

# --- Scenario: OK pass path ------------------------------------------------
FIX="$TMP_ROOT/ok"
build_fixture "$FIX" "$MID_METHODOLOGY" "$MID_AGENTS"
run_gate "$FIX"
if [[ "$RC" -eq 0 ]] && [[ "$GATE_STDOUT" == *"codex skill budget check: OK"* ]]; then
  _pass "OK fixture exits 0 with the expected summary line"
else
  _fail "OK fixture: expected rc=0 and 'OK' summary, got rc=$RC stdout=$GATE_STDOUT stderr=$GATE_STDERR"
fi

# --- Scenario: missing METHODOLOGY.md --------------------------------------
FIX="$TMP_ROOT/missing-methodology"
build_fixture "$FIX" "$MID_METHODOLOGY" "$MID_AGENTS"
rm "$FIX/.codex/skills/dinostack/METHODOLOGY.md"
run_gate "$FIX"
if [[ "$RC" -ne 0 ]] && [[ "$GATE_STDERR" == *"missing file"* ]]; then
  _pass "missing METHODOLOGY.md fails with a 'missing file' message"
else
  _fail "missing METHODOLOGY.md: expected nonzero rc + 'missing file', got rc=$RC stderr=$GATE_STDERR"
fi

# --- Scenario: missing AGENTS.md -------------------------------------------
FIX="$TMP_ROOT/missing-agents"
build_fixture "$FIX" "$MID_METHODOLOGY" "$MID_AGENTS"
rm "$FIX/.codex/AGENTS.md"
run_gate "$FIX"
if [[ "$RC" -ne 0 ]] && [[ "$GATE_STDERR" == *"missing file"* ]]; then
  _pass "missing AGENTS.md fails with a 'missing file' message"
else
  _fail "missing AGENTS.md: expected nonzero rc + 'missing file', got rc=$RC stderr=$GATE_STDERR"
fi

# --- Scenario: section file count ABOVE EXPECTED_SECTION_COUNT ------------
FIX="$TMP_ROOT/section-count-over"
build_fixture "$FIX" "$MID_METHODOLOGY" "$MID_AGENTS"
printf '## Extra Section\n\nextra.\n' > "$FIX/content/sections/99-extra.md"
run_gate "$FIX"
if [[ "$RC" -ne 0 ]] && [[ "$GATE_STDERR" == *"embed incomplete"* ]] && [[ "$GATE_STDERR" == *"section file count mismatch"* ]]; then
  _pass "extra section file fails as embed incomplete (count mismatch)"
else
  _fail "extra section file: expected embed-incomplete count mismatch, got rc=$RC stderr=$GATE_STDERR"
fi

# --- Scenario: section file count BELOW EXPECTED_SECTION_COUNT ------------
FIX="$TMP_ROOT/section-count-under"
build_fixture "$FIX" "$MID_METHODOLOGY" "$MID_AGENTS"
rm "$FIX/content/sections/01-stub.md"
run_gate "$FIX"
if [[ "$RC" -ne 0 ]] && [[ "$GATE_STDERR" == *"embed incomplete"* ]] && [[ "$GATE_STDERR" == *"section file count mismatch"* ]]; then
  _pass "deleted section file fails as embed incomplete (count mismatch)"
else
  _fail "deleted section file: expected embed-incomplete count mismatch, got rc=$RC stderr=$GATE_STDERR"
fi

# --- Scenario: a section heading dropped from METHODOLOGY.md --------------
FIX="$TMP_ROOT/section-heading-dropped"
build_fixture "$FIX" "$MID_METHODOLOGY" "$MID_AGENTS"
python3 -c "
import sys
p = sys.argv[1]
with open(p) as f:
    text = f.read()
text = text.replace('## Section 1\n', '', 1)
with open(p, 'w') as f:
    f.write(text)
" "$FIX/.codex/skills/dinostack/METHODOLOGY.md"
run_gate "$FIX"
if [[ "$RC" -ne 0 ]] && [[ "$GATE_STDERR" == *"embed incomplete"* ]] && [[ "$GATE_STDERR" == *"missing section heading"* ]]; then
  _pass "dropped section heading fails as embed incomplete (missing heading)"
else
  _fail "dropped section heading: expected embed-incomplete missing-heading, got rc=$RC stderr=$GATE_STDERR"
fi

# --- Scenario: duplicate section headings across two source files ---------
FIX="$TMP_ROOT/section-heading-dup"
build_fixture "$FIX" "$MID_METHODOLOGY" "$MID_AGENTS"
printf '## Section 1\n\nduplicate heading, different file.\n' > "$FIX/content/sections/02-stub.md"
# Re-embed so the duplicate heading is still present at least once (it
# already is, from 01-stub's own heading) - this scenario tests the
# cross-file duplicate detector itself, not heading absence.
run_gate "$FIX"
if [[ "$RC" -ne 0 ]] && [[ "$GATE_STDERR" == *"embed incomplete"* ]] && [[ "$GATE_STDERR" == *"duplicate top-level heading"* ]]; then
  _pass "duplicate section heading across files fails as embed incomplete (duplicate)"
else
  _fail "duplicate section heading: expected embed-incomplete duplicate-heading, got rc=$RC stderr=$GATE_STDERR"
fi

# --- Scenario: rules symlink missing ---------------------------------------
FIX="$TMP_ROOT/rules-link-missing"
build_fixture "$FIX" "$MID_METHODOLOGY" "$MID_AGENTS"
rm "$FIX/.codex/skills/dinostack/rules"
run_gate "$FIX"
if [[ "$RC" -ne 0 ]] && [[ "$GATE_STDERR" == *"embed incomplete"* ]] && [[ "$GATE_STDERR" == *"does not exist"* ]]; then
  _pass "missing rules symlink fails as embed incomplete (unreachable)"
else
  _fail "missing rules symlink: expected embed-incomplete unreachable, got rc=$RC stderr=$GATE_STDERR"
fi

# --- Scenario: rules symlink resolves but wrong file count ----------------
FIX="$TMP_ROOT/rules-link-wrong-count"
build_fixture "$FIX" "$MID_METHODOLOGY" "$MID_AGENTS"
printf '## Extra Rule\n\nextra.\n' > "$FIX/content/rules/rule-extra.md"
run_gate "$FIX"
if [[ "$RC" -ne 0 ]] && [[ "$GATE_STDERR" == *"embed incomplete"* ]] && [[ "$GATE_STDERR" == *"rules file count mismatch"* ]]; then
  _pass "extra rules file fails as embed incomplete (rules count mismatch)"
else
  _fail "extra rules file: expected embed-incomplete rules-count mismatch, got rc=$RC stderr=$GATE_STDERR"
fi

# --- Scenario: METHODOLOGY.md below METHODOLOGY_FLOOR ----------------------
FIX="$TMP_ROOT/below-floor"
build_fixture "$FIX" 500 "$MID_AGENTS"
run_gate "$FIX"
if [[ "$RC" -ne 0 ]] && [[ "$GATE_STDERR" == *"BELOW METHODOLOGY FLOOR"* ]]; then
  _pass "undersized METHODOLOGY.md fails as BELOW METHODOLOGY FLOOR"
else
  _fail "below floor: expected BELOW METHODOLOGY FLOOR, got rc=$RC stderr=$GATE_STDERR"
fi

# --- Scenario: AGENTS.md above AGENTS_STUB_CEILING --------------------------
FIX="$TMP_ROOT/above-ceiling"
build_fixture "$FIX" "$MID_METHODOLOGY" $(( AGENTS_STUB_CEILING + 1000 ))
run_gate "$FIX"
if [[ "$RC" -ne 0 ]] && [[ "$GATE_STDERR" == *"ABOVE AGENTS STUB CEILING"* ]]; then
  _pass "oversized AGENTS.md fails as ABOVE AGENTS STUB CEILING"
else
  _fail "above ceiling: expected ABOVE AGENTS STUB CEILING, got rc=$RC stderr=$GATE_STDERR"
fi

# --- bash/zsh parity: hard-fail under CI, soft-skip locally ----------------
if command -v zsh >/dev/null 2>&1; then
  FIX="$TMP_ROOT/parity"
  build_fixture "$FIX" "$MID_METHODOLOGY" "$MID_AGENTS"
  bash_out="$(bash "$FIX/scripts/check-codex-skill-budget.sh" 2>&1)"
  bash_rc=$?
  zsh_out="$(zsh "$FIX/scripts/check-codex-skill-budget.sh" 2>&1)"
  zsh_rc=$?
  if [[ "$bash_rc" -eq "$zsh_rc" && "$bash_out" == "$zsh_out" ]]; then
    _pass "bash and zsh invocations produce identical output and exit code"
  else
    _fail "bash/zsh parity mismatch: bash_rc=$bash_rc zsh_rc=$zsh_rc bash_out=$bash_out zsh_out=$zsh_out"
  fi
elif [[ "${CI:-}" == "true" ]]; then
  _fail "zsh not found on PATH under CI=true - bash/zsh parity assertion cannot run (this must not silently pass)"
else
  echo "SKIP: zsh not found on PATH - skipping bash/zsh parity check locally (hard-fails under CI=true)"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
