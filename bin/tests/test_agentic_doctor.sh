#!/usr/bin/env bash
# Purpose: Regression and smoke tests for bin/agentic-doctor.
#
# Public API: ./bin/tests/test_agentic_doctor.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, mktemp.
#
# Downstream consumers: developer running locally before commit; can be
#                       wired into CI.
#
# Failure modes: any test failure prints the failing assertion and exits 1.
#                Tests use isolated TEMP_HOME dirs with a fake ~/.claude
#                and fake ~/.agentic to avoid touching real user state.
#                NEVER points at the real ~/.claude.
#
# Performance: <2 s wall time on a developer machine.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOCTOR="$SCRIPT_DIR/agentic-doctor"

if [[ ! -x "$DOCTOR" ]]; then
  echo "FAIL: $DOCTOR not executable" >&2
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

# ---------------------------------------------------------------------------
# Test fixture setup
# ---------------------------------------------------------------------------
# Build a TEMP_HOME with:
#   - TEMP_HOME/.agentic/agentic-engineering-config.json  pointing at FAKE_REPO
#   - FAKE_REPO/   (a fake git repo with .claude/agents/ tree)
#   - TEMP_HOME/.claude/agents/correct.md -> FAKE_REPO/.claude/agents/correct.md  [OK]
#   - TEMP_HOME/.claude/agents/stale.md  -> OLD_REPO/.claude/agents/stale.md      [FAIL/ours]
#   - TEMP_HOME/.claude/agents/broken.md -> /nonexistent/broken.md                 [FAIL/ours]
#   - TEMP_HOME/.claude/agents/realfile.md  (a real file, not a symlink)            [SKIP]
#   - TEMP_HOME/.claude/agents/foreign.md -> EXTERNAL_FILE                         [SKIP/not-ours]
#
# The "ours" heuristic requires the existing target to contain "DinoStack" in
# its path, or be broken. For stale.md we point at a path under a sibling
# DinoStack clone; for foreign.md we point at an external file that exists
# outside any DinoStack path, which must NOT be touched.

setup_fixture() {
  TEMP_HOME="$(mktemp -d)"
  FAKE_REPO="$TEMP_HOME/fake-DinoStack"
  OLD_REPO="$TEMP_HOME/old-DinoStack"
  EXTERNAL_DIR="$TEMP_HOME/external"
  # Resolve via realpath so comparisons work on macOS where /var -> /private/var
  REAL_FAKE_REPO="$(python3 -c "import os; print(os.path.realpath('$TEMP_HOME/fake-DinoStack'))")"

  # Create fake git repos
  mkdir -p "$FAKE_REPO/.git" "$FAKE_REPO/.claude/agents"
  mkdir -p "$OLD_REPO/.git"
  mkdir -p "$EXTERNAL_DIR"

  # Populate repo targets so correct.md link resolves
  echo "correct" > "$FAKE_REPO/.claude/agents/correct.md"
  echo "stale"   > "$OLD_REPO/stale-target.md"

  # External file (exists, outside any DinoStack path)
  echo "foreign" > "$EXTERNAL_DIR/foreign.md"

  # ~/.agentic config pointing at FAKE_REPO
  mkdir -p "$TEMP_HOME/.agentic"
  cat > "$TEMP_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$FAKE_REPO"
}
EOF

  # ~/.claude/agents/
  mkdir -p "$TEMP_HOME/.claude/agents"

  # [OK] correct link
  ln -s "$FAKE_REPO/.claude/agents/correct.md" "$TEMP_HOME/.claude/agents/correct.md"

  # [FAIL/ours] stale link - points at old DinoStack clone (target exists, ours by name)
  ln -s "$OLD_REPO/stale-target.md" "$TEMP_HOME/.claude/agents/stale.md"

  # [FAIL/ours] broken link
  ln -s "/nonexistent/path/broken.md" "$TEMP_HOME/.claude/agents/broken.md"

  # [SKIP] real file - must never be touched
  echo "real content" > "$TEMP_HOME/.claude/agents/realfile.md"

  # [SKIP] foreign symlink - target exists outside DinoStack; must not be touched
  ln -s "$EXTERNAL_DIR/foreign.md" "$TEMP_HOME/.claude/agents/foreign.md"

  # No settings.json (skip hooks check)
  # No local/bin (skip local_bin check - no bin/ in FAKE_REPO either,
  # we just confirm FAKE_REPO/.git exists so check(a) passes)
}

invoke_doctor() {
  # Run agentic-doctor with HOME and FAKE_REPO via config; capture output + exit
  (
    HOME="$TEMP_HOME"
    export HOME
    python3 "$DOCTOR" "$@"
  ) > "$TEMP_HOME/.out" 2>&1
  echo $? > "$TEMP_HOME/.exit"
}

# ---------------------------------------------------------------------------
# Test 1: read-only mode reports correct OK/FAIL/SKIP set, exits 1
# ---------------------------------------------------------------------------
setup_fixture
invoke_doctor  # no flags - read-only

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" != "1" ]]; then
  _fail "T1 read-only exit code: expected 1, got $RC\n$OUT"
else
  _pass "T1 read-only: exits 1 (findings present)"
fi

if echo "$OUT" | grep -q "^OK managed_links:.*correct.md"; then
  _pass "T1 read-only: correct link reported OK"
else
  _fail "T1 read-only: correct link should be OK\n$OUT"
fi

# stale.md (ours, wrong target) must be a FAIL or FIX
if echo "$OUT" | grep -q "stale.md"; then
  _pass "T1 read-only: stale link appears in output"
else
  _fail "T1 read-only: stale link not mentioned\n$OUT"
fi

# broken.md must be a FAIL or FIX
if echo "$OUT" | grep -qE "(FAIL|FIX).*broken.md"; then
  _pass "T1 read-only: broken link reported as FAIL or FIX"
else
  _fail "T1 read-only: broken link should be FAIL/FIX\n$OUT"
fi

# realfile.md must be SKIP (real file)
if echo "$OUT" | grep -q "^SKIP.*realfile.md"; then
  _pass "T1 read-only: real file is SKIPped"
else
  _fail "T1 read-only: real file should be SKIP\n$OUT"
fi

# foreign.md must be SKIP (not ours)
if echo "$OUT" | grep -q "^SKIP.*foreign.md"; then
  _pass "T1 read-only: foreign symlink is SKIPped"
else
  _fail "T1 read-only: foreign symlink should be SKIP\n$OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 2: --fix re-points ours-to-own, prints each FIX line, leaves others alone
# ---------------------------------------------------------------------------
setup_fixture

# Ensure the expected target exists for stale.md repair
mkdir -p "$FAKE_REPO/.claude/agents"
echo "stale repaired" > "$FAKE_REPO/.claude/agents/stale.md"
# broken.md expected target: FAKE_REPO/.claude/agents/broken.md
echo "broken repaired" > "$FAKE_REPO/.claude/agents/broken.md"

invoke_doctor --fix

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" || "$RC" == "2" ]]; then
  _pass "T2 --fix: exits 0 or 2 (fix ran)"
else
  _fail "T2 --fix exit code: expected 0 or 2, got $RC\n$OUT"
fi

# FIX lines must have been printed for stale and broken
if echo "$OUT" | grep -q "^FIX symlink:.*stale.md"; then
  _pass "T2 --fix: FIX line printed for stale.md"
else
  _fail "T2 --fix: missing FIX line for stale.md\n$OUT"
fi

if echo "$OUT" | grep -q "^FIX symlink:.*broken.md"; then
  _pass "T2 --fix: FIX line printed for broken.md"
else
  _fail "T2 --fix: missing FIX line for broken.md\n$OUT"
fi

# stale.md should now resolve into FAKE_REPO (compare against realpath)
STALE_TARGET="$(readlink "$TEMP_HOME/.claude/agents/stale.md" 2>/dev/null || echo "(not a link)")"
if [[ "$STALE_TARGET" == "$FAKE_REPO/.claude/agents/stale.md" ]] || [[ "$STALE_TARGET" == "$REAL_FAKE_REPO/.claude/agents/stale.md" ]]; then
  _pass "T2 --fix: stale.md re-pointed to FAKE_REPO"
else
  _fail "T2 --fix: stale.md target is '$STALE_TARGET', expected '$FAKE_REPO/.claude/agents/stale.md' or realpath variant"
fi

# broken.md should now resolve into FAKE_REPO (compare against realpath)
BROKEN_TARGET="$(readlink "$TEMP_HOME/.claude/agents/broken.md" 2>/dev/null || echo "(not a link)")"
if [[ "$BROKEN_TARGET" == "$FAKE_REPO/.claude/agents/broken.md" ]] || [[ "$BROKEN_TARGET" == "$REAL_FAKE_REPO/.claude/agents/broken.md" ]]; then
  _pass "T2 --fix: broken.md re-pointed to FAKE_REPO"
else
  _fail "T2 --fix: broken.md target is '$BROKEN_TARGET', expected '$FAKE_REPO/.claude/agents/broken.md' or realpath variant"
fi

# realfile.md must still be a real file (not a symlink, not removed)
if [[ -f "$TEMP_HOME/.claude/agents/realfile.md" ]] && [[ ! -L "$TEMP_HOME/.claude/agents/realfile.md" ]]; then
  _pass "T2 --fix: realfile.md untouched (still a real file)"
else
  _fail "T2 --fix: realfile.md was modified (must never touch real files)"
fi

# foreign.md must still point at the external target (untouched)
FOREIGN_TARGET="$(readlink "$TEMP_HOME/.claude/agents/foreign.md" 2>/dev/null || echo "(not a link)")"
EXTERNAL_FILE="$TEMP_HOME/external/foreign.md"
if [[ "$FOREIGN_TARGET" == "$EXTERNAL_FILE" ]]; then
  _pass "T2 --fix: foreign.md untouched (not ours)"
else
  _fail "T2 --fix: foreign.md target changed from '$EXTERNAL_FILE' to '$FOREIGN_TARGET'"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 3: idempotent re-run after --fix exits 0
# ---------------------------------------------------------------------------
setup_fixture

mkdir -p "$FAKE_REPO/.claude/agents"
echo "stale repaired" > "$FAKE_REPO/.claude/agents/stale.md"
echo "broken repaired" > "$FAKE_REPO/.claude/agents/broken.md"

# First --fix pass
invoke_doctor --fix

# Second --fix pass - should exit 0 (nothing to fix)
invoke_doctor --fix
RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T3 idempotent: second --fix exits 0"
else
  _fail "T3 idempotent: second --fix exited $RC (expected 0)\n$OUT"
fi

# Should be no FAIL lines on second pass (for the managed links we fixed)
FAIL_LINES=$(echo "$OUT" | grep "^FAIL" | grep -v "not found" || true)
if [[ -z "$FAIL_LINES" ]]; then
  _pass "T3 idempotent: no FAIL lines on second pass (for repaired links)"
else
  _fail "T3 idempotent: unexpected FAIL lines on second pass:\n$FAIL_LINES"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 4: --dry-run does not change anything
# ---------------------------------------------------------------------------
setup_fixture

mkdir -p "$FAKE_REPO/.claude/agents"
echo "stale content" > "$FAKE_REPO/.claude/agents/stale.md"
echo "broken content" > "$FAKE_REPO/.claude/agents/broken.md"

# Record original targets
STALE_ORIG="$(readlink "$TEMP_HOME/.claude/agents/stale.md")"
BROKEN_ORIG="$(readlink "$TEMP_HOME/.claude/agents/broken.md")"

invoke_doctor --dry-run
RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

# Should still exit 1 (findings present, not fixed)
if [[ "$RC" == "1" ]]; then
  _pass "T4 --dry-run: exits 1 (not fixed)"
else
  _fail "T4 --dry-run: expected exit 1, got $RC\n$OUT"
fi

# Symlinks must NOT have been changed
STALE_AFTER="$(readlink "$TEMP_HOME/.claude/agents/stale.md" 2>/dev/null)"
BROKEN_AFTER="$(readlink "$TEMP_HOME/.claude/agents/broken.md" 2>/dev/null)"

if [[ "$STALE_AFTER" == "$STALE_ORIG" ]]; then
  _pass "T4 --dry-run: stale.md target unchanged"
else
  _fail "T4 --dry-run: stale.md was modified (dry-run must not change files)"
fi

if [[ "$BROKEN_AFTER" == "$BROKEN_ORIG" ]]; then
  _pass "T4 --dry-run: broken.md target unchanged"
else
  _fail "T4 --dry-run: broken.md was modified (dry-run must not change files)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 5: invalid repo_dir path exits 1 with FAIL repo_dir: line, not a crash
# ---------------------------------------------------------------------------
setup_fixture

# Overwrite config to point repo_dir at a path that does not exist
cat > "$TEMP_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "/nonexistent/path"
}
EOF

invoke_doctor
RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "1" ]]; then
  _pass "T5 invalid repo_dir: exits 1 (not a crash)"
else
  _fail "T5 invalid repo_dir: expected exit 1, got $RC (possible NameError crash?)\n$OUT"
fi

if echo "$OUT" | grep -q "^FAIL repo_dir:"; then
  _pass "T5 invalid repo_dir: FAIL repo_dir: line present"
else
  _fail "T5 invalid repo_dir: missing FAIL repo_dir: line\n$OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 6: --fix exits 2 (not 0) when repo_dir is invalid/missing
# Regression test for: --fix silently returning 0 when repo_dir FAIL is
# not appended to doc.unfixable, which caused has_unfixable() to return
# False and the exit path to return 0 instead of 2.
# ---------------------------------------------------------------------------
setup_fixture

# Point repo_dir at a path that does not exist (not auto-fixable by doctor)
cat > "$TEMP_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "/nonexistent/path"
}
EOF

invoke_doctor --fix
RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "2" ]]; then
  _pass "T6 --fix with invalid repo_dir: exits 2 (unfixable)"
else
  _fail "T6 --fix with invalid repo_dir: expected exit 2, got $RC (regression: unfixable not recorded)\n$OUT"
fi

if echo "$OUT" | grep -q "^FAIL repo_dir:"; then
  _pass "T6 --fix with invalid repo_dir: FAIL repo_dir: line present"
else
  _fail "T6 --fix with invalid repo_dir: missing FAIL repo_dir: line\n$OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 7: check_hook_scripts_exist FAILs on a managed hook command whose
# script does not exist on disk (orphaned-hook detection, DS-94).
# ---------------------------------------------------------------------------
setup_fixture

mkdir -p "$FAKE_REPO/hooks"
# One managed hook script that DOES exist on disk...
cat > "$FAKE_REPO/hooks/enforce-orchestrator-singularity.py" <<'EOF'
# fixture stub
EOF
# ...and settings.json references it plus a second managed hook basename
# whose script is MISSING from disk.
cat > "$TEMP_HOME/.claude/settings.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Agent",
        "hooks": [
          {"type": "command", "command": "python3 $FAKE_REPO/hooks/enforce-orchestrator-singularity.py", "timeout": 5},
          {"type": "command", "command": "python3 $FAKE_REPO/hooks/enforce-shippable-edit.py", "timeout": 5}
        ]
      }
    ]
  }
}
EOF

invoke_doctor
RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if echo "$OUT" | grep -q "^FAIL hook_scripts:.*enforce-shippable-edit.py.*does not exist on disk"; then
  _pass "T7 hook_scripts: missing managed hook script reported as FAIL"
else
  _fail "T7 hook_scripts: expected FAIL for missing enforce-shippable-edit.py\n$OUT"
fi

if echo "$OUT" | grep -q "FAIL hook_scripts:.*enforce-orchestrator-singularity.py"; then
  _fail "T7 hook_scripts: enforce-orchestrator-singularity.py exists on disk and must NOT be reported as FAIL\n$OUT"
else
  _pass "T7 hook_scripts: existing managed hook script not falsely flagged"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 8: check_hook_scripts_exist reports OK when every referenced managed
# hook script exists on disk.
# ---------------------------------------------------------------------------
setup_fixture

mkdir -p "$FAKE_REPO/hooks"
cat > "$FAKE_REPO/hooks/enforce-orchestrator-singularity.py" <<'EOF'
# fixture stub
EOF
cat > "$FAKE_REPO/hooks/enforce-shippable-edit.py" <<'EOF'
# fixture stub
EOF
cat > "$TEMP_HOME/.claude/settings.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Agent",
        "hooks": [
          {"type": "command", "command": "python3 $FAKE_REPO/hooks/enforce-orchestrator-singularity.py", "timeout": 5},
          {"type": "command", "command": "python3 $FAKE_REPO/hooks/enforce-shippable-edit.py", "timeout": 5}
        ]
      }
    ]
  }
}
EOF

invoke_doctor
OUT=$(cat "$TEMP_HOME/.out")

if echo "$OUT" | grep -q "^OK hook_scripts:.*all managed hook scripts exist on disk"; then
  _pass "T8 hook_scripts: all-present case reports OK"
else
  _fail "T8 hook_scripts: expected OK hook_scripts line when all scripts exist\n$OUT"
fi

if echo "$OUT" | grep -q "^FAIL hook_scripts:"; then
  _fail "T8 hook_scripts: unexpected FAIL hook_scripts line when all scripts exist\n$OUT"
else
  _pass "T8 hook_scripts: no FAIL hook_scripts lines when all scripts exist"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 9/10: renamed-upstream-artifact regression (DS-133).
#
# repoint_symlink previously recreated a dangling link whenever the computed
# expected target did not exist in the repo (e.g. a command that was renamed
# upstream, not merely relocated). Reproduced pre-fix: read-only reports a
# finding, --fix "resolves" it by recreating the SAME dangling link, and a
# second read-only run still exits 1. The fix (remove_stale_symlink) must
# instead remove the link, and a subsequent read-only run must exit 0.
# ---------------------------------------------------------------------------
setup_fixture_stale() {
  TEMP_HOME="$(mktemp -d)"
  FAKE_REPO="$TEMP_HOME/fake-DinoStack"
  OLD_REPO="$TEMP_HOME/old-DinoStack"

  mkdir -p "$FAKE_REPO/.git" "$FAKE_REPO/.claude/commands"
  mkdir -p "$OLD_REPO/.git"

  # The old command's content still exists somewhere under a DinoStack path
  # (so the "ours" heuristic fires), but the repo no longer ships it under
  # .claude/commands/renamed-away.md - it was renamed to a different basename.
  echo "old content" > "$OLD_REPO/renamed-away-target.md"

  mkdir -p "$TEMP_HOME/.agentic"
  cat > "$TEMP_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$FAKE_REPO"
}
EOF

  mkdir -p "$TEMP_HOME/.claude/commands"
  ln -s "$OLD_REPO/renamed-away-target.md" "$TEMP_HOME/.claude/commands/renamed-away.md"

  # Deliberately do NOT create $FAKE_REPO/.claude/commands/renamed-away.md -
  # this is the renamed-upstream-artifact case under test.
}

setup_fixture_stale
invoke_doctor  # read-only

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "1" ]]; then
  _pass "T9 read-only: renamed-away link is a finding (exits 1)"
else
  _fail "T9 read-only: expected exit 1, got $RC\n$OUT"
fi

if echo "$OUT" | grep -q "^FIX symlink:.*renamed-away.md.*(removed, stale)"; then
  _pass "T9 read-only: renamed-away link reported as stale removal candidate"
else
  _fail "T9 read-only: expected a '(removed, stale)' FIX line for renamed-away.md\n$OUT"
fi

rm -rf "$TEMP_HOME"

setup_fixture_stale
invoke_doctor --fix

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T10 --fix: renamed-away link resolved, exits 0"
else
  _fail "T10 --fix: expected exit 0, got $RC\n$OUT"
fi

if [[ -L "$TEMP_HOME/.claude/commands/renamed-away.md" || -e "$TEMP_HOME/.claude/commands/renamed-away.md" ]]; then
  _fail "T10 --fix: renamed-away.md should have been removed, but still exists"
else
  _pass "T10 --fix: renamed-away.md was removed (not recreated as a dangling link)"
fi

# Idempotency: a second read-only run after --fix must exit 0 (DS-133's
# core regression - the pre-fix code recreated the dangling link here).
invoke_doctor
RC2=$(cat "$TEMP_HOME/.exit")
OUT2=$(cat "$TEMP_HOME/.out")

if [[ "$RC2" == "0" ]]; then
  _pass "T10 idempotent: second read-only run after --fix exits 0"
else
  _fail "T10 idempotent: second read-only run exited $RC2, expected 0 (link was recreated?)\n$OUT2"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 11: --help describes removal behavior for --fix and --dry-run.
#
# Regression guard for the closed-enumeration pattern where --fix/--dry-run
# help text described only "re-points" and silently dropped the delete
# path (a stale link with no repo-side target). This pins two literal
# strings; it does not prove no fourth surface with the same gap exists.
# ---------------------------------------------------------------------------
HELP_OUT="$(python3 "$DOCTOR" --help 2>&1)"
HELP_NORM="$(echo "$HELP_OUT" | tr '\n' ' ' | tr -s ' ')"
HELP_OPTS="${HELP_NORM#*options: }"

FIX_HELP="${HELP_OPTS#*--fix }"
FIX_HELP="${FIX_HELP%%--dry-run*}"

DRYRUN_HELP="${HELP_OPTS#*--dry-run }"
DRYRUN_HELP="${DRYRUN_HELP%%--cross-harness*}"

if echo "$FIX_HELP" | grep -q "remove"; then
  _pass "T11 --help: --fix text mentions removal"
else
  _fail "T11 --help: --fix text does not mention removal\n$FIX_HELP"
fi

if echo "$DRYRUN_HELP" | grep -q "repairs"; then
  _pass "T11 --help: --dry-run text uses the open 'repairs' wording"
else
  _fail "T11 --help: --dry-run text missing 'repairs' wording\n$DRYRUN_HELP"
fi

if echo "$DRYRUN_HELP" | grep -q "re-points"; then
  _fail "T11 --help: --dry-run text reverted to closed 're-points' enumeration\n$DRYRUN_HELP"
else
  _pass "T11 --help: --dry-run text does not use the stale 're-points' enumeration"
fi

# ---------------------------------------------------------------------------
# Tests 12-14 (DS-54): hooks-snapshot staleness check
# (check_hooks_snapshot_staleness / _fix_hooks_snapshot).
#
# Unlike the fixtures above (a bare .git marker dir), this check needs a
# repo_dir that actually ships hooks/lib/hooks-staleness-core.sh and
# scripts/lib/hooks-snapshot.sh - so these tests point repo_dir at THIS
# checkout itself (REPO_ROOT, resolved from SCRIPT_DIR), never at a
# synthetic FAKE_REPO. This is read-only-safe: hooks-staleness-core.sh only
# reads; sync_hooks_snapshot (invoked by T13's --fix) writes exclusively
# under the ISOLATED TEMP_HOME's $HOME/.agentic/hooks-snapshot/ (per-checkout
# snapshot storage keyed by realpath(repo_dir), see
# scripts/lib/hooks-snapshot.sh) - never under REPO_ROOT itself, so the real
# checkout on disk is never mutated by these tests.
# ---------------------------------------------------------------------------
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

setup_hooks_snapshot_fixture() {
  TEMP_HOME="$(mktemp -d)"
  mkdir -p "$TEMP_HOME/.agentic"
  cat > "$TEMP_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$REPO_ROOT"
}
EOF
}

# ---------------------------------------------------------------------------
# Test 12: never_migrated - a fresh TEMP_HOME with no hooks-snapshot ever
# created for REPO_ROOT is reported as a FIX finding (exit 1 in read-only
# mode), classified never_migrated.
# ---------------------------------------------------------------------------
setup_hooks_snapshot_fixture
invoke_doctor --json

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "1" ]]; then
  _pass "T12 hooks_snapshot never_migrated: exits 1 (finding present)"
else
  _fail "T12 hooks_snapshot never_migrated: expected exit 1, got $RC\n$OUT"
fi

if echo "$OUT" | grep -q 'hooks_snapshot \[never_migrated\]'; then
  _pass "T12 hooks_snapshot never_migrated: classified never_migrated"
else
  _fail "T12 hooks_snapshot never_migrated: missing never_migrated classification\n$OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 13: --fix calls sync_hooks_snapshot, which creates the snapshot dir
# under the isolated TEMP_HOME (never under REPO_ROOT) and a subsequent
# read-only re-scan reports OK (current).
# ---------------------------------------------------------------------------
setup_hooks_snapshot_fixture
invoke_doctor --fix

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if echo "$OUT" | grep -qi "hooks_snapshot"; then
  _pass "T13 hooks_snapshot --fix: hooks_snapshot finding present in --fix output"
else
  _fail "T13 hooks_snapshot --fix: no hooks_snapshot finding in --fix output\n$OUT"
fi

if [[ -d "$TEMP_HOME/.agentic/hooks-snapshot" ]] && [[ -n "$(ls -A "$TEMP_HOME/.agentic/hooks-snapshot" 2>/dev/null)" ]]; then
  _pass "T13 hooks_snapshot --fix: snapshot dir created under isolated TEMP_HOME"
else
  _fail "T13 hooks_snapshot --fix: no snapshot dir created under TEMP_HOME/.agentic/hooks-snapshot"
fi

invoke_doctor --json
RC2=$(cat "$TEMP_HOME/.exit")
OUT2=$(cat "$TEMP_HOME/.out")

if echo "$OUT2" | grep -q "hooks_snapshot: hooks snapshot is current"; then
  _pass "T13 hooks_snapshot --fix: subsequent scan reports current"
else
  _fail "T13 hooks_snapshot --fix: subsequent scan did not report current\n$OUT2"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 14: a repo_dir without hooks/lib/hooks-staleness-core.sh (the
# synthetic FAKE_REPO fixture used by Tests 1-11) is SKIPPED, not FAILed -
# the check must degrade gracefully on a partial/older checkout rather than
# treating a missing script as drift.
# ---------------------------------------------------------------------------
setup_fixture
invoke_doctor --json

OUT=$(cat "$TEMP_HOME/.out")

if python3 -c "
import json, sys
data = json.load(open('$TEMP_HOME/.out'))
found = [f for f in data['findings'] if f['message'].startswith('hooks_snapshot:')]
sys.exit(0 if found and found[0]['status'] == 'SKIP' else 1)
" 2>/dev/null; then
  _pass "T14 hooks_snapshot on repo without hooks-staleness-core.sh: SKIP, not FAIL"
else
  _fail "T14 hooks_snapshot on repo without hooks-staleness-core.sh: expected a SKIP finding\n$OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
