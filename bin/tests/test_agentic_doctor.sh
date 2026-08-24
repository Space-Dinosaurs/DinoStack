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
  printf 'FAIL: %b\n' "$1" >&2
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
  # Run agentic-doctor with HOME and FAKE_REPO via config; capture output + exit.
  # unset CLAUDE_CONFIG_DIR: a real value set in the invoking session (e.g.
  # ~/.claude-spacedinosaurs) would make _plugins_dir() resolve OUTSIDE
  # TEMP_HOME and silently scan the real machine's plugins instead of these
  # HOME-relative fixtures (DS-198 round 3, Skeptic Major 2).
  (
    HOME="$TEMP_HOME"
    export HOME
    unset CLAUDE_CONFIG_DIR
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
# Test 12: check_hook_scripts_exist recognizes enforce-worktree-read.py as a
# managed hook basename (MAJOR-2, DS-150 fix-pass). Before this fix,
# MANAGED_HOOK_BASENAMES omitted it, so a settings.json registration whose
# script was missing on disk was silently skipped by
# check_hook_scripts_exist() and doctor certified "all managed hook scripts
# exist on disk" while the dangling registration (CRITICAL-1's blast
# radius) went undiagnosed.
# ---------------------------------------------------------------------------
setup_fixture

mkdir -p "$FAKE_REPO/hooks"
# enforce-worktree-read.py is referenced by settings.json but MISSING from
# disk - must now be reported as a FAIL, not silently skipped.
cat > "$TEMP_HOME/.claude/settings.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          {"type": "command", "command": "test -f $FAKE_REPO/hooks/enforce-worktree-read.py && python3 $FAKE_REPO/hooks/enforce-worktree-read.py || exit 0", "timeout": 5}
        ]
      }
    ]
  }
}
EOF

invoke_doctor
OUT=$(cat "$TEMP_HOME/.out")

if echo "$OUT" | grep -q "^FAIL hook_scripts:.*enforce-worktree-read.py.*does not exist on disk"; then
  _pass "T12 hook_scripts: missing enforce-worktree-read.py reported as FAIL (MAJOR-2 regression guard)"
else
  _fail "T12 hook_scripts: expected FAIL for missing enforce-worktree-read.py (MANAGED_HOOK_BASENAMES omission regressed)\n$OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 12b: check_hook_scripts_exist recognizes enforce-worktree-write.py as
# a managed hook basename - the write-side counterpart of T12 above. Same
# omission class: if MANAGED_HOOK_BASENAMES ever drops
# "enforce-worktree-write.py" (e.g. bin/ds-doctor:170 deleted), a
# settings.json registration whose script is missing on disk would be
# silently skipped by check_hook_scripts_exist() and doctor would certify
# "all managed hook scripts exist on disk" while the dangling registration
# (CRITICAL-1-class blast radius, and larger here: all three of
# Write/Edit/MultiEdit rather than Read alone) went undiagnosed.
# ---------------------------------------------------------------------------
setup_fixture

mkdir -p "$FAKE_REPO/hooks"
# enforce-worktree-write.py is referenced by settings.json but MISSING from
# disk - must be reported as a FAIL, not silently skipped.
cat > "$TEMP_HOME/.claude/settings.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          {"type": "command", "command": "test -f $FAKE_REPO/hooks/enforce-worktree-write.py && python3 $FAKE_REPO/hooks/enforce-worktree-write.py || exit 0", "timeout": 5}
        ]
      }
    ]
  }
}
EOF

invoke_doctor
OUT=$(cat "$TEMP_HOME/.out")

if echo "$OUT" | grep -q "^FAIL hook_scripts:.*enforce-worktree-write.py.*does not exist on disk"; then
  _pass "T12b hook_scripts: missing enforce-worktree-write.py reported as FAIL (MANAGED_HOOK_BASENAMES omission regression guard)"
else
  _fail "T12b hook_scripts: expected FAIL for missing enforce-worktree-write.py (MANAGED_HOOK_BASENAMES omission regressed)\n$OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Tests 13-15 (DS-54): hooks-snapshot staleness check
# (check_hooks_snapshot_staleness / _fix_hooks_snapshot).
#
# Unlike the fixtures above (a bare .git marker dir), this check needs a
# repo_dir that actually ships hooks/lib/hooks-staleness-core.sh and
# scripts/lib/hooks-snapshot.sh - so these tests point repo_dir at THIS
# checkout itself (REPO_ROOT, resolved from SCRIPT_DIR), never at a
# synthetic FAKE_REPO. This is read-only-safe: hooks-staleness-core.sh only
# reads; sync_hooks_snapshot (invoked by T14's --fix) writes exclusively
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
# Test 13: never_migrated - a fresh TEMP_HOME with no hooks-snapshot ever
# created for REPO_ROOT is reported as a FIX finding (exit 1 in read-only
# mode), classified never_migrated.
# ---------------------------------------------------------------------------
setup_hooks_snapshot_fixture
invoke_doctor --json

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "1" ]]; then
  _pass "T13 hooks_snapshot never_migrated: exits 1 (finding present)"
else
  _fail "T13 hooks_snapshot never_migrated: expected exit 1, got $RC\n$OUT"
fi

if echo "$OUT" | grep -q 'hooks_snapshot \[never_migrated\]'; then
  _pass "T13 hooks_snapshot never_migrated: classified never_migrated"
else
  _fail "T13 hooks_snapshot never_migrated: missing never_migrated classification\n$OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 14: --fix calls sync_hooks_snapshot, which creates the snapshot dir
# under the isolated TEMP_HOME (never under REPO_ROOT) and a subsequent
# read-only re-scan reports OK (current).
# ---------------------------------------------------------------------------
setup_hooks_snapshot_fixture
invoke_doctor --fix

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if echo "$OUT" | grep -qi "hooks_snapshot"; then
  _pass "T14 hooks_snapshot --fix: hooks_snapshot finding present in --fix output"
else
  _fail "T14 hooks_snapshot --fix: no hooks_snapshot finding in --fix output\n$OUT"
fi

if [[ -d "$TEMP_HOME/.agentic/hooks-snapshot" ]] && [[ -n "$(ls -A "$TEMP_HOME/.agentic/hooks-snapshot" 2>/dev/null)" ]]; then
  _pass "T14 hooks_snapshot --fix: snapshot dir created under isolated TEMP_HOME"
else
  _fail "T14 hooks_snapshot --fix: no snapshot dir created under TEMP_HOME/.agentic/hooks-snapshot"
fi

invoke_doctor --json
RC2=$(cat "$TEMP_HOME/.exit")
OUT2=$(cat "$TEMP_HOME/.out")

if echo "$OUT2" | grep -q "hooks_snapshot: hooks snapshot is current"; then
  _pass "T14 hooks_snapshot --fix: subsequent scan reports current"
else
  _fail "T14 hooks_snapshot --fix: subsequent scan did not report current\n$OUT2"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 15: a repo_dir without hooks/lib/hooks-staleness-core.sh (the
# synthetic FAKE_REPO fixture used by Tests 1-12) is SKIPPED, not FAILed -
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
  _pass "T15 hooks_snapshot on repo without hooks-staleness-core.sh: SKIP, not FAIL"
else
  _fail "T15 hooks_snapshot on repo without hooks-staleness-core.sh: expected a SKIP finding\n$OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 15 (DS-54, Skeptic round-2 Major 3): half_applied is NOT reported as
# resolved by --fix. sync_hooks_snapshot only refreshes snapshot CONTENT -
# it never rewrites an adapter's own hook config. Construct a fixture with a
# REAL synced snapshot (so it's not never_migrated) plus a
# TEMP_HOME/.claude/settings.json whose session-start-wrap.sh command still
# points at the checkout, not the snapshot (half_applied's own trigger
# condition per hooks/lib/hooks-staleness-core.sh). --fix must exit 2
# (unfixable) with an actionable message, and a subsequent read-only scan
# must still report the identical half_applied finding.
# ---------------------------------------------------------------------------
setup_hooks_snapshot_fixture

# Pre-sync a real snapshot for REPO_ROOT under this isolated TEMP_HOME, so
# the fixture starts from "snapshot exists and is current", not
# never_migrated - isolating the half_applied trigger from the other two
# states.
(
  HOME="$TEMP_HOME"
  export HOME
  # shellcheck source=/dev/null
  source "$REPO_ROOT/scripts/lib/hooks-snapshot.sh"
  sync_hooks_snapshot "$REPO_ROOT" >/dev/null
)

# Adapter config still points its session-start-wrap.sh command AT THE
# CHECKOUT (no "hooks-snapshot" substring) - the exact half_applied trigger.
mkdir -p "$TEMP_HOME/.claude"
cat > "$TEMP_HOME/.claude/settings.json" <<EOF
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {"type": "command", "command": "bash $REPO_ROOT/hooks/session-start-wrap.sh"}
        ]
      }
    ]
  }
}
EOF

invoke_doctor --fix

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "2" ]]; then
  _pass "T15 hooks_snapshot half_applied: --fix exits 2 (unfixable), not 0"
else
  _fail "T15 hooks_snapshot half_applied: expected exit 2, got $RC\n$OUT"
fi

if echo "$OUT" | grep -qi "half_applied is NOT resolved"; then
  _pass "T15 hooks_snapshot half_applied: --fix reports half_applied unresolved, not silently claimed fixed"
else
  _fail "T15 hooks_snapshot half_applied: --fix did not report half_applied as unresolved\n$OUT"
fi

if echo "$OUT" | grep -qi "install.sh"; then
  _pass "T15 hooks_snapshot half_applied: unfixable message names the install.sh remedy"
else
  _fail "T15 hooks_snapshot half_applied: unfixable message does not name install.sh\n$OUT"
fi

invoke_doctor --json
RC2=$(cat "$TEMP_HOME/.exit")
OUT2=$(cat "$TEMP_HOME/.out")

if echo "$OUT2" | grep -q 'hooks_snapshot \[half_applied\]'; then
  _pass "T15 hooks_snapshot half_applied: subsequent read-only scan still reports half_applied (not silently cleared)"
else
  _fail "T15 hooks_snapshot half_applied: subsequent scan no longer reports half_applied\n$OUT2"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 16 (DS-54, Skeptic round-2 Major 4): a hooks-staleness-core.sh that
# exits NONZERO must be reported WARN, not silently treated as "current"
# (OK). The classifier's own contract is "always exits 0" (fail-open); a
# nonzero exit means it broke mid-run, and empty stdout in that case is NOT
# evidence of "nothing to report" - it is evidence the check never
# completed. Uses a standalone broken repo_dir (not REPO_ROOT) whose
# hooks/lib/hooks-staleness-core.sh is a deliberate `exit 3` stub.
# ---------------------------------------------------------------------------
TEMP_HOME="$(mktemp -d)"
BROKEN_REPO="$TEMP_HOME/broken-repo"
mkdir -p "$BROKEN_REPO/.git" "$BROKEN_REPO/hooks/lib"
cat > "$BROKEN_REPO/hooks/lib/hooks-staleness-core.sh" <<'BROKENEOF'
#!/usr/bin/env bash
exit 3
BROKENEOF
mkdir -p "$TEMP_HOME/.agentic"
cat > "$TEMP_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$BROKEN_REPO"
}
EOF

invoke_doctor --json

OUT=$(cat "$TEMP_HOME/.out")

if python3 -c "
import json, sys
data = json.load(open('$TEMP_HOME/.out'))
found = [f for f in data['findings'] if f['message'].startswith('hooks_snapshot:')]
sys.exit(0 if found and found[0]['status'] == 'WARN' else 1)
" 2>/dev/null; then
  _pass "T16 hooks_snapshot nonzero classifier exit: WARN, not OK/FAIL"
else
  _fail "T16 hooks_snapshot nonzero classifier exit: expected a WARN finding\n$OUT"
fi

if echo "$OUT" | grep -q "hooks snapshot is current"; then
  _fail "T16 hooks_snapshot nonzero classifier exit: falsely reported current (affirmative green for a check that did not run)\n$OUT"
else
  _pass "T16 hooks_snapshot nonzero classifier exit: did NOT falsely report current"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 17 (Skeptic round-2 Minor): pin the three literal substrings
# check_hooks_snapshot_staleness parses out of hooks-staleness-core.sh's
# stdout to classify never_migrated/half_applied/stale_but_stable. Without
# this pin, a wording change in hooks-staleness-core.sh silently degrades
# every classification to "unknown" (fails safe - the finding is still
# surfaced as a FIX, just mislabeled - hence Minor, not Major) with no test
# failure anywhere else to catch it.
# ---------------------------------------------------------------------------
_HSC_SCRIPT="$REPO_ROOT/hooks/lib/hooks-staleness-core.sh"

if grep -qF "not yet snapshotted" "$_HSC_SCRIPT"; then
  _pass "T17 literal pin: 'not yet snapshotted' (never_migrated) present in hooks-staleness-core.sh"
else
  _fail "T17 literal pin: 'not yet snapshotted' (never_migrated) NOT found in hooks-staleness-core.sh - ds-doctor's classifier will mislabel this state 'unknown'"
fi

if grep -qF "partially applied" "$_HSC_SCRIPT"; then
  _pass "T17 literal pin: 'partially applied' (half_applied) present in hooks-staleness-core.sh"
else
  _fail "T17 literal pin: 'partially applied' (half_applied) NOT found in hooks-staleness-core.sh - ds-doctor's classifier will mislabel this state 'unknown'"
fi

if grep -qF "changed since the last snapshot sync" "$_HSC_SCRIPT"; then
  _pass "T17 literal pin: 'changed since the last snapshot sync' (stale_but_stable) present in hooks-staleness-core.sh"
else
  _fail "T17 literal pin: 'changed since the last snapshot sync' (stale_but_stable) NOT found in hooks-staleness-core.sh - ds-doctor's classifier will mislabel this state 'unknown'"
fi

# ---------------------------------------------------------------------------
# Test 18 (routed cross-unit item, precommit/worktree alignment): repo_dir
# being a git WORKTREE (".git" is a FILE - a gitdir pointer - not a
# directory there) must not crash check_git_precommit with a
# NotADirectoryError. Before this fix, the hardcoded
# `repo_dir / ".git" / "hooks" / "pre-commit"` path broke `mkdir(parents=True)`
# the moment repo_dir's ".git" component turned out to be a file instead of
# a directory - exactly the git-worktree case. Uses a REAL `git worktree
# add` linked worktree (not a synthetic stand-in), since only real git
# plumbing reproduces the file-vs-directory ".git" distinction.
#
# PRIMARY_REPO commits the REPO'S OWN real scripts/lib/precommit.sh (cp'd
# from REPO_ROOT, not an embedded stand-in) - _resolve_hook_src in
# bin/ds-doctor shells into it, and this fixture must exercise the actual
# shipped resolve_hook_src, not a copy that can silently drift from it. A
# prior round of this test embedded a hand-written stand-in function here;
# a Skeptic review demonstrated that renaming the real resolve_hook_src to
# resolve_precommit_source (an ordinary refactor of the shared lib) left
# this test - and the parity test in
# bin/tests/test_ds_doctor_precommit_source_parity.sh - fully green while
# silently reintroducing the exact Major this branch exists to close. A
# hard failure below (not a SKIP) is required if the real library is
# missing the function this test depends on - a silently-skipped assertion
# is indistinguishable from a passing one in a job log.
# ---------------------------------------------------------------------------
if ! grep -qE '^resolve_hook_src[[:space:]]*\(\)' "$REPO_ROOT/scripts/lib/precommit.sh" 2>/dev/null; then
  _fail "T18 precondition: $REPO_ROOT/scripts/lib/precommit.sh does not define resolve_hook_src - this fixture cannot exercise the real function (hard failure, not a skip)"
else
  _pass "T18 precondition: $REPO_ROOT/scripts/lib/precommit.sh defines resolve_hook_src"
fi

# T18 previously asserted the CONFLICTING behavior here: with a hardcoded
# expected_src, a worktree repo_dir's own hooks/pre-commit and its
# resolved git-hooks-dir agreed with EACH OTHER (both hardcodes point
# inside the worktree), so the scan reported OK/FIX and looked healthy
# while actually repointing the shared hook into an ephemeral worktree -
# exactly the Major this branch fixes. T18 below keeps asserting "no
# crash" and "OK/FIX status" (both still true post-fix), but those two
# assertions alone cannot distinguish the reconciled behavior from the
# conflicting one - see Test 19, which reads the actual symlink target.
# ---------------------------------------------------------------------------
TEMP_HOME="$(mktemp -d)"
PRIMARY_REPO="$TEMP_HOME/primary-repo"
mkdir -p "$PRIMARY_REPO"
(
  cd "$PRIMARY_REPO"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p hooks scripts/lib
  printf '#!/usr/bin/env bash\nexit 0\n' > hooks/pre-commit
  chmod +x hooks/pre-commit
  cp "$REPO_ROOT/scripts/lib/precommit.sh" scripts/lib/precommit.sh
  git add hooks/pre-commit scripts/lib/precommit.sh
  git commit -q -m init
)
WORKTREE_REPO="$TEMP_HOME/linked-worktree"
(
  cd "$PRIMARY_REPO"
  git worktree add -q -b t18-wt-branch "$WORKTREE_REPO"
)

mkdir -p "$TEMP_HOME/.agentic"
cat > "$TEMP_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$WORKTREE_REPO"
}
EOF

invoke_doctor --fix

OUT=$(cat "$TEMP_HOME/.out")

if echo "$OUT" | grep -qi "NotADirectoryError\|could not re-point.*Not a directory"; then
  _fail "T18 git_precommit on a worktree repo_dir: crashed with NotADirectoryError (the pre-fix bug reproduces here)\n$OUT"
else
  _pass "T18 git_precommit on a worktree repo_dir: no NotADirectoryError crash"
fi

invoke_doctor --json
OUT2=$(cat "$TEMP_HOME/.out")

if python3 -c "
import json, sys
data = json.load(open('$TEMP_HOME/.out'))
found = [f for f in data['findings'] if f['message'].startswith('git_precommit:')]
sys.exit(0 if found and found[0]['status'] in ('OK', 'FIX') else 1)
" 2>/dev/null; then
  _pass "T18 git_precommit on a worktree repo_dir: subsequent scan reports OK/FIX, not FAIL"
else
  _fail "T18 git_precommit on a worktree repo_dir: subsequent scan did not report OK/FIX\n$OUT2"
fi

# ---------------------------------------------------------------------------
# Test 19 (the Major itself): after --fix, the ACTUAL filesystem symlink
# written for the shared git hook must resolve into PRIMARY_REPO (the
# real, non-ephemeral checkout) - never into WORKTREE_REPO's own
# hooks/pre-commit copy. A hardcoded `expected_src = repo_dir /
# "hooks" / "pre-commit"` (the pre-fix bin/ds-doctor behavior) passes T18's
# OK/FIX assertions above while still writing a symlink that dangles the
# instant WORKTREE_REPO is removed - this is the exact Major reproduced
# against a merged tree in this ticket. Reads the real symlink with
# os.readlink, not merely test -L (a dangling symlink also satisfies
# test -L), and fails explicitly, quoting both paths, if the target
# resolves into the worktree instead of the primary checkout.
# ---------------------------------------------------------------------------
if python3 -c "
import os, sys

git_hooks_dir = '$PRIMARY_REPO/.git/hooks'
hook = os.path.join(git_hooks_dir, 'pre-commit')
primary_src = os.path.realpath('$PRIMARY_REPO/hooks/pre-commit')
worktree_src = os.path.realpath('$WORKTREE_REPO/hooks/pre-commit')

if not os.path.islink(hook):
    print(f'T19: {hook} is not a symlink at all', file=sys.stderr)
    sys.exit(1)

target = os.path.realpath(hook)

if target == worktree_src:
    print(f'T19: hook symlink resolves into the WORKTREE ({target}) - the exact Major (dangles once the worktree is removed)', file=sys.stderr)
    sys.exit(1)

if target != primary_src:
    print(f'T19: hook symlink resolves to neither the primary ({primary_src}) nor the worktree ({worktree_src}) - unexpected target {target}', file=sys.stderr)
    sys.exit(1)

sys.exit(0)
"; then
  _pass "T19 --fix repoints the shared hook at PRIMARY_REPO, not the worktree (the Major, closed)"
else
  _fail "T19 --fix repointed the shared hook at the wrong checkout - see stderr above"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 20: check_output_style_staleness (DS-171 round 4, Skeptic Minor 5).
# Own isolated TEMP_HOME/FAKE_REPO, independent of the fixtures above.
# ---------------------------------------------------------------------------
T20_HOME="$(mktemp -d)"
T20_REPO="$T20_HOME/fake-DinoStack"
mkdir -p "$T20_REPO/.git" "$T20_REPO/.claude/skills/dinostack/output-styles"
echo "built style v1" > "$T20_REPO/.claude/skills/dinostack/output-styles/dinostack.md"

mkdir -p "$T20_HOME/.agentic"
cat > "$T20_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$T20_REPO"
}
EOF

t20_invoke() {
  # unset CLAUDE_CONFIG_DIR: see invoke_doctor()'s comment above (DS-198
  # round 3, Skeptic Major 2) - same leak, different fixture family.
  (
    HOME="$T20_HOME"
    export HOME
    unset CLAUDE_CONFIG_DIR
    python3 "$DOCTOR" "$@"
  ) > "$T20_HOME/.out" 2>&1
  echo $? > "$T20_HOME/.exit"
}

# 20a: not installed at all -> SKIP, never FAIL
t20_invoke
OUT=$(cat "$T20_HOME/.out")
if echo "$OUT" | grep -q "^SKIP output_style:.*not installed"; then
  _pass "T20a output_style: not-installed reported as SKIP"
else
  _fail "T20a output_style: not-installed should be SKIP\n$OUT"
fi

# 20b: installed but stale -> FIX finding in read-only mode
mkdir -p "$T20_HOME/.claude/output-styles"
echo "stale installed copy" > "$T20_HOME/.claude/output-styles/dinostack.md"
t20_invoke
OUT=$(cat "$T20_HOME/.out")
if echo "$OUT" | grep -q "^FIX output_style:.*is stale relative to"; then
  _pass "T20b output_style: stale installed copy reported as FIX"
else
  _fail "T20b output_style: stale copy should be reported as FIX\n$OUT"
fi

# 20c: --fix refreshes the installed copy to match repo_dir exactly
t20_invoke --fix
if diff -q "$T20_REPO/.claude/skills/dinostack/output-styles/dinostack.md" "$T20_HOME/.claude/output-styles/dinostack.md" >/dev/null 2>&1; then
  _pass "T20c output_style: --fix refreshed the installed copy to match repo_dir"
else
  _fail "T20c output_style: installed copy still does not match repo_dir after --fix"
fi

# 20d: idempotent - a second read-only scan after --fix reports OK, not FIX
t20_invoke
OUT=$(cat "$T20_HOME/.out")
if echo "$OUT" | grep -q "^OK output_style:.*matches repo_dir"; then
  _pass "T20d output_style: subsequent scan after --fix reports OK (current)"
else
  _fail "T20d output_style: subsequent scan after --fix should report OK\n$OUT"
fi

rm -rf "$T20_HOME"

# 20e: built output style missing from repo_dir entirely -> SKIP, never FAIL
# (DS-171 round 5, Skeptic Minor 5 - the src-missing branch had no coverage).
T20E_HOME="$(mktemp -d)"
T20E_REPO="$T20E_HOME/fake-DinoStack"
mkdir -p "$T20E_REPO/.git"
# Deliberately do NOT create .claude/skills/dinostack/output-styles/dinostack.md.

mkdir -p "$T20E_HOME/.agentic"
cat > "$T20E_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$T20E_REPO"
}
EOF

(
  HOME="$T20E_HOME"
  export HOME
  unset CLAUDE_CONFIG_DIR
  python3 "$DOCTOR"
) > "$T20E_HOME/.out" 2>&1

OUT=$(cat "$T20E_HOME/.out")
if echo "$OUT" | grep -q "^SKIP output_style:.*built output style not found in repo_dir"; then
  _pass "T20e output_style: built style missing from repo_dir reported as SKIP"
else
  _fail "T20e output_style: missing built style should be SKIP, not FAIL\n$OUT"
fi

rm -rf "$T20E_HOME"

# 20f: installed copy present but unreadable -> WARN, not a crash or FAIL
# (DS-171 round 5, Skeptic Minor 5 - the unreadable-file branch had no
# coverage). Skipped when running as root, since root ignores file mode
# bits and the induced read failure would never occur.
if [[ "$(id -u)" != "0" ]]; then
  T20F_HOME="$(mktemp -d)"
  T20F_REPO="$T20F_HOME/fake-DinoStack"
  mkdir -p "$T20F_REPO/.git" "$T20F_REPO/.claude/skills/dinostack/output-styles"
  echo "built style v1" > "$T20F_REPO/.claude/skills/dinostack/output-styles/dinostack.md"

  mkdir -p "$T20F_HOME/.agentic"
  cat > "$T20F_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$T20F_REPO"
}
EOF

  mkdir -p "$T20F_HOME/.claude/output-styles"
  echo "installed copy" > "$T20F_HOME/.claude/output-styles/dinostack.md"
  chmod 000 "$T20F_HOME/.claude/output-styles/dinostack.md"

  (
    HOME="$T20F_HOME"
    export HOME
    unset CLAUDE_CONFIG_DIR
    python3 "$DOCTOR"
  ) > "$T20F_HOME/.out" 2>&1

  OUT=$(cat "$T20F_HOME/.out")
  if echo "$OUT" | grep -q "^WARN output_style:.*could not compare"; then
    _pass "T20f output_style: unreadable installed copy reported as WARN"
  else
    _fail "T20f output_style: unreadable installed copy should be WARN\n$OUT"
  fi

  chmod 644 "$T20F_HOME/.claude/output-styles/dinostack.md"
  rm -rf "$T20F_HOME"
else
  _pass "T20f output_style: unreadable-file WARN branch skipped (running as root)"
fi

# ---------------------------------------------------------------------------
# T21: foreign PreToolUse:Agent/Task hook detection (DS-198)
# Own isolated TEMP_HOME/FAKE_REPO, independent of the fixtures above.
# ---------------------------------------------------------------------------
T21_HOME="$(mktemp -d)"
T21_REPO="$T21_HOME/fake-DinoStack"
mkdir -p "$T21_REPO/.git"

mkdir -p "$T21_HOME/.agentic"
cat > "$T21_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$T21_REPO"
}
EOF

t21_invoke() {
  (
    HOME="$T21_HOME"
    export HOME
    # T21 fixtures are HOME-relative; a real CLAUDE_CONFIG_DIR set in the
    # invoking session (e.g. ~/.claude-spacedinosaurs) would make
    # _plugins_dir() resolve OUTSIDE T21_HOME and silently scan the real
    # machine's plugins instead of the fixture - unset it here.
    unset CLAUDE_CONFIG_DIR
    python3 "$DOCTOR" "$@"
  ) > "$T21_HOME/.out" 2>&1
  echo $? > "$T21_HOME/.exit"
}

# T21a: clean machine - no ~/.claude/plugins directory at all -> OK, never FAIL
mkdir -p "$T21_HOME/.claude"
cat > "$T21_HOME/.claude/settings.json" <<EOF
{}
EOF
t21_invoke
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^OK foreign_agent_hook:" && ! echo "$OUT" | grep -q "^FAIL foreign_agent_hook:"; then
  _pass "T21a foreign_agent_hook: clean machine (no plugins dir) reported as OK"
else
  _fail "T21a foreign_agent_hook: clean machine should be OK, no FAIL\n$OUT"
fi

# T21b: enabled plugin whose hooks.json has no hazardous matcher -> OK, no FAIL
# (flat {"PreToolUse": [...]} shape, no "hooks" wrapper.)
SAFE_PLUGIN_DIR="$T21_HOME/plugin-installs/safe"
mkdir -p "$SAFE_PLUGIN_DIR/hooks"
cat > "$SAFE_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "PreToolUse": [
    {"matcher": "Bash", "hooks": [{"command": "echo safe"}]}
  ]
}
EOF

mkdir -p "$T21_HOME/.claude/plugins"
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "safe@mkt": [{"installPath": "$SAFE_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"safe@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^OK foreign_agent_hook:" && ! echo "$OUT" | grep -q "^FAIL foreign_agent_hook:" && [[ "$RC" == "0" ]]; then
  _pass "T21b foreign_agent_hook: enabled plugin with non-hazardous matcher reported as OK (flat shape)"
else
  _fail "T21b foreign_agent_hook: non-hazardous matcher should be OK, exit 0\nrc=$RC\n$OUT"
fi

# T21c: the real defect - enabled plugin registers a PreToolUse hook with
# matcher "Agent" -> FAIL naming the plugin and matcher, exit code 1.
# Uses the REAL nested {"description": ..., "hooks": {"PreToolUse": [...]}}
# shape copied from an actual installed plugin's packaged hooks.json (both
# context-mode and vercel on the dev machine use this nested form, never
# the flat form) - this is the fixture that must prove the schema-level
# Critical (DS-198 round 2) is fixed.
EVIL_PLUGIN_DIR="$T21_HOME/plugin-installs/evil"
mkdir -p "$EVIL_PLUGIN_DIR/hooks"
cat > "$EVIL_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "description": "evil plugin hooks",
  "hooks": {
    "PreToolUse": [
      {"matcher": "Agent", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF

cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "evil@mkt": [{"installPath": "$EVIL_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"evil@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^FAIL foreign_agent_hook:.*evil@mkt.*Agent" && [[ "$RC" == "1" ]]; then
  _pass "T21c foreign_agent_hook: hazardous Agent matcher (nested real shape) reported as FAIL, exit 1"
else
  _fail "T21c foreign_agent_hook: hazardous Agent matcher (nested shape) should FAIL naming evil@mkt and Agent, exit 1\nrc=$RC\n$OUT"
fi

# T21c2: a hazard-detected run must NEVER also print an OK line for
# foreign_agent_hook (the `if not found_any` guard, DS-198 round 3 Skeptic
# Minor 8 - un-reddenable by mutation before this assertion existed).
if ! echo "$OUT" | grep -q "^OK foreign_agent_hook:"; then
  _pass "T21c2 foreign_agent_hook: hazard-detected run prints no OK line"
else
  _fail "T21c2 foreign_agent_hook: hazard-detected run must not also print OK\n$OUT"
fi

# T21d: same hazard, but the flat (no "hooks" wrapper) shape - coverage
# retained for the non-nested form, which the check must also accept.
FLATEVIL_PLUGIN_DIR="$T21_HOME/plugin-installs/flatevil"
mkdir -p "$FLATEVIL_PLUGIN_DIR/hooks"
cat > "$FLATEVIL_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "PreToolUse": [
    {"matcher": "Task", "hooks": [{"command": "node routing.mjs"}]}
  ]
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "flatevil@mkt": [{"installPath": "$FLATEVIL_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"flatevil@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^FAIL foreign_agent_hook:.*flatevil@mkt.*Task" && [[ "$RC" == "1" ]]; then
  _pass "T21d foreign_agent_hook: hazardous Task matcher (flat shape) reported as FAIL, exit 1"
else
  _fail "T21d foreign_agent_hook: hazardous Task matcher (flat shape) should FAIL naming flatevil@mkt and Task, exit 1\nrc=$RC\n$OUT"
fi

# T21e: empty matcher ("") means match-all -> must FAIL, not be treated as
# an exemption.
EMPTY_PLUGIN_DIR="$T21_HOME/plugin-installs/emptymatcher"
mkdir -p "$EMPTY_PLUGIN_DIR/hooks"
cat > "$EMPTY_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "emptymatcher@mkt": [{"installPath": "$EMPTY_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"emptymatcher@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^FAIL foreign_agent_hook:.*emptymatcher@mkt" && [[ "$RC" == "1" ]]; then
  _pass "T21e foreign_agent_hook: empty matcher (match-all) reported as FAIL, exit 1"
else
  _fail "T21e foreign_agent_hook: empty matcher should FAIL naming emptymatcher@mkt, exit 1\nrc=$RC\n$OUT"
fi

# T21f: "*" wildcard matcher also means match-all -> must FAIL.
STAR_PLUGIN_DIR="$T21_HOME/plugin-installs/starmatcher"
mkdir -p "$STAR_PLUGIN_DIR/hooks"
cat > "$STAR_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "*", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "starmatcher@mkt": [{"installPath": "$STAR_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"starmatcher@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^FAIL foreign_agent_hook:.*starmatcher@mkt" && [[ "$RC" == "1" ]]; then
  _pass "T21f foreign_agent_hook: \"*\" wildcard matcher reported as FAIL, exit 1"
else
  _fail "T21f foreign_agent_hook: \"*\" wildcard matcher should FAIL naming starmatcher@mkt, exit 1\nrc=$RC\n$OUT"
fi

# T21g: substring false-positive guard - a matcher token that merely
# CONTAINS "Agent" or "Task" (e.g. context-mode's real PostToolUse
# alternation shape) must NOT match, since _matcher_covers_spawn_tool does
# exact-token comparison, not substring.
SUBSTR_PLUGIN_DIR="$T21_HOME/plugin-installs/substr"
mkdir -p "$SUBSTR_PLUGIN_DIR/hooks"
cat > "$SUBSTR_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "AgentX|TaskCreate", "hooks": [{"command": "echo safe"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "substr@mkt": [{"installPath": "$SUBSTR_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"substr@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^OK foreign_agent_hook:" && ! echo "$OUT" | grep -q "^FAIL foreign_agent_hook:" && [[ "$RC" == "0" ]]; then
  _pass "T21g foreign_agent_hook: AgentX/TaskCreate substring tokens reported as OK (no false positive), exit 0"
else
  _fail "T21g foreign_agent_hook: substring tokens should be OK (not a false positive), exit 0\nrc=$RC\n$OUT"
fi

# T21h: unparseable settings.json must not be reported as OK - the check
# could not establish enabledPlugins at all, so it must not claim clean.
cat > "$T21_HOME/.claude/settings.json" <<'EOF'
{ this is not valid json
EOF
t21_invoke
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^WARN foreign_agent_hook:" && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:"; then
  _pass "T21h foreign_agent_hook: unparseable settings.json WARNs, never reports OK"
else
  _fail "T21h foreign_agent_hook: unparseable settings.json should WARN and never OK\n$OUT"
fi

# T21i: CLAUDE_CONFIG_DIR override is honored by _plugins_dir() - a plugin
# enabled only under an ALTERNATE config dir's settings.json/plugins tree
# must be detected there, not silently missed by falling back to
# ~/.claude (whose settings.json here has no enabledPlugins at all).
ALT_CONFIG_DIR="$T21_HOME/alt-config"
mkdir -p "$ALT_CONFIG_DIR/plugins"
CFGDIR_EVIL="$T21_HOME/plugin-installs/cfgdirevil"
mkdir -p "$CFGDIR_EVIL/hooks"
cat > "$CFGDIR_EVIL/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Agent", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$ALT_CONFIG_DIR/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "cfgdirevil@mkt": [{"installPath": "$CFGDIR_EVIL", "scope": "user"}]
  }
}
EOF
cat > "$ALT_CONFIG_DIR/settings.json" <<EOF
{
  "enabledPlugins": {"cfgdirevil@mkt": true}
}
EOF
# ~/.claude/settings.json (HOME-default) stays clean/no-op for this case.
cat > "$T21_HOME/.claude/settings.json" <<EOF
{}
EOF
(
  HOME="$T21_HOME"
  export HOME
  CLAUDE_CONFIG_DIR="$ALT_CONFIG_DIR"
  export CLAUDE_CONFIG_DIR
  python3 "$DOCTOR"
) > "$T21_HOME/.out" 2>&1
RC=$?
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^FAIL foreign_agent_hook:.*cfgdirevil@mkt.*Agent" && [[ "$RC" == "1" ]]; then
  _pass "T21i foreign_agent_hook: CLAUDE_CONFIG_DIR override honored by _plugins_dir(), exit 1"
else
  _fail "T21i foreign_agent_hook: CLAUDE_CONFIG_DIR override should be honored, naming cfgdirevil@mkt, exit 1\nrc=$RC\n$OUT"
fi

# T21j: an installed_plugins.json entry whose value is not a list (malformed
# schema) must WARN, not silently `continue` with no signal at all.
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "malformed@mkt": {"installPath": "/nonexistent", "scope": "user"}
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"malformed@mkt": true}
}
EOF
t21_invoke
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^WARN foreign_agent_hook:.*malformed@mkt" && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:"; then
  _pass "T21j foreign_agent_hook: non-list plugins-map entry WARNs, never a masked OK"
else
  _fail "T21j foreign_agent_hook: non-list plugins-map entry should WARN naming malformed@mkt, never OK\n$OUT"
fi

# T21k: regex matcher semantics (DS-198 round 3, Skeptic Major 1) - a
# ".*" matcher means match-everything under real Claude Code matcher
# semantics (regex, not exact-token set) and must FAIL.
REGEX1_PLUGIN_DIR="$T21_HOME/plugin-installs/regex1"
mkdir -p "$REGEX1_PLUGIN_DIR/hooks"
cat > "$REGEX1_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "regex1@mkt": [{"installPath": "$REGEX1_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"regex1@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^FAIL foreign_agent_hook:.*regex1@mkt" && [[ "$RC" == "1" ]]; then
  _pass "T21k foreign_agent_hook: \".*\" regex matcher reported as FAIL, exit 1"
else
  _fail "T21k foreign_agent_hook: \".*\" regex matcher should FAIL naming regex1@mkt, exit 1\nrc=$RC\n$OUT"
fi

# T21l: "(Agent|Task)" alternation matcher must FAIL - the exact shape a
# prior exact-token-set-intersection implementation reported OK for.
REGEX2_PLUGIN_DIR="$T21_HOME/plugin-installs/regex2"
mkdir -p "$REGEX2_PLUGIN_DIR/hooks"
cat > "$REGEX2_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "(Agent|Task)", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "regex2@mkt": [{"installPath": "$REGEX2_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"regex2@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^FAIL foreign_agent_hook:.*regex2@mkt" && [[ "$RC" == "1" ]]; then
  _pass "T21l foreign_agent_hook: \"(Agent|Task)\" alternation matcher reported as FAIL, exit 1"
else
  _fail "T21l foreign_agent_hook: \"(Agent|Task)\" alternation matcher should FAIL naming regex2@mkt, exit 1\nrc=$RC\n$OUT"
fi

# T21m: "^Agent$" anchored matcher must FAIL - also mis-reported OK by the
# prior exact-token-set-intersection implementation.
REGEX3_PLUGIN_DIR="$T21_HOME/plugin-installs/regex3"
mkdir -p "$REGEX3_PLUGIN_DIR/hooks"
cat > "$REGEX3_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "^Agent\$", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "regex3@mkt": [{"installPath": "$REGEX3_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"regex3@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^FAIL foreign_agent_hook:.*regex3@mkt" && [[ "$RC" == "1" ]]; then
  _pass "T21m foreign_agent_hook: \"^Agent\$\" anchored matcher reported as FAIL, exit 1"
else
  _fail "T21m foreign_agent_hook: \"^Agent\$\" anchored matcher should FAIL naming regex3@mkt, exit 1\nrc=$RC\n$OUT"
fi

# T21n: a "mcp__"-style prefix matcher (the REAL context-mode PostToolUse
# matcher shape, present as direct evidence real plugins use regex
# semantics) does not itself name Agent/Task and must stay OK - confirms
# the regex rewrite did not turn every non-empty matcher into a false
# positive.
PREFIX_PLUGIN_DIR="$T21_HOME/plugin-installs/prefixmatcher"
mkdir -p "$PREFIX_PLUGIN_DIR/hooks"
cat > "$PREFIX_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "mcp__", "hooks": [{"command": "echo safe"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "prefixmatcher@mkt": [{"installPath": "$PREFIX_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"prefixmatcher@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^OK foreign_agent_hook:" && ! echo "$OUT" | grep -q "^FAIL foreign_agent_hook:" && [[ "$RC" == "0" ]]; then
  _pass "T21n foreign_agent_hook: \"mcp__\" prefix matcher reported as OK (no false positive), exit 0"
else
  _fail "T21n foreign_agent_hook: \"mcp__\" prefix matcher should be OK, exit 0\nrc=$RC\n$OUT"
fi

# T21o: an invalid/uncompilable regex matcher (a plugin author's typo)
# must not crash the whole check, and must never be silently treated as
# confirmed-clean - it WARNs and marks the scan incomplete (DS-198 round
# 4, Skeptic Major 1: the previous "|"-split token-comparison fallback
# silently returned False - a confirmed-clean signal - for THIS EXACT
# fixture-adjacent shape whenever the uncompilable matcher did not
# happen to contain a bare "Agent"/"Task" pipe-token; this fixture
# happens to contain "Agent" via "|" so the old fallback FAILed here,
# but T21o2 below pins the shape it silently missed). An unbalanced "("
# is an uncompilable regex.
BADREGEX_PLUGIN_DIR="$T21_HOME/plugin-installs/badregex"
mkdir -p "$BADREGEX_PLUGIN_DIR/hooks"
cat > "$BADREGEX_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Agent|(unterminated", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "badregex@mkt": [{"installPath": "$BADREGEX_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"badregex@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^WARN foreign_agent_hook:.*badregex@mkt" \
   && ! echo "$OUT" | grep -q "^FAIL foreign_agent_hook:" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21o foreign_agent_hook: uncompilable regex matcher does not crash, WARNs and never OKs"
else
  _fail "T21o foreign_agent_hook: uncompilable regex matcher should WARN naming badregex@mkt, never OK, exit 0\nrc=$RC\n$OUT"
fi

# T21o2: an uncompilable regex matcher that does NOT contain a bare
# "Agent"/"Task" pipe-token (DS-198 round 4, Skeptic Major 1 - the exact
# shape the prior "|"-split fallback silently reported as clean-False
# for, with no WARN and no scan_incomplete). Must still WARN, never OK.
for BADREGEX2_MATCHER in '(Agent' '[Agent' 'Agent)$[' '(?P<'; do
  BADREGEX2_PLUGIN_DIR="$T21_HOME/plugin-installs/badregex2"
  rm -rf "$BADREGEX2_PLUGIN_DIR"
  mkdir -p "$BADREGEX2_PLUGIN_DIR/hooks"
  cat > "$BADREGEX2_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$BADREGEX2_MATCHER"), "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
  cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "badregex2@mkt": [{"installPath": "$BADREGEX2_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
  cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"badregex2@mkt": true}
}
EOF
  t21_invoke
  RC=$(cat "$T21_HOME/.exit")
  OUT=$(cat "$T21_HOME/.out")
  if echo "$OUT" | grep -qE "^WARN foreign_agent_hook:.*badregex2@mkt" \
     && ! echo "$OUT" | grep -q "^FAIL foreign_agent_hook:" \
     && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
     && [[ "$RC" == "0" ]]; then
    _pass "T21o2 foreign_agent_hook: uncompilable matcher '$BADREGEX2_MATCHER' (no bare Agent/Task token) WARNs, never OK"
  else
    _fail "T21o2 foreign_agent_hook: uncompilable matcher '$BADREGEX2_MATCHER' should WARN naming badregex2@mkt, never OK, exit 0\nrc=$RC\n$OUT"
  fi
done
rm -rf "$BADREGEX2_PLUGIN_DIR"

# T21p: a PreToolUse entry missing the "matcher" key entirely must default
# to "" (match-all) and FAIL - the default arg at pre_entry.get("matcher",
# "") (DS-198 round 3, Skeptic Minor 8 - previously un-reddenable).
NOMATCHER_PLUGIN_DIR="$T21_HOME/plugin-installs/nomatcher"
mkdir -p "$NOMATCHER_PLUGIN_DIR/hooks"
cat > "$NOMATCHER_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "nomatcher@mkt": [{"installPath": "$NOMATCHER_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"nomatcher@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^FAIL foreign_agent_hook:.*nomatcher@mkt" && [[ "$RC" == "1" ]]; then
  _pass "T21p foreign_agent_hook: missing 'matcher' key defaults to match-all and FAILs"
else
  _fail "T21p foreign_agent_hook: missing 'matcher' key should default to match-all and FAIL naming nomatcher@mkt, exit 1\nrc=$RC\n$OUT"
fi

# T21p2: an explicit "matcher": null entry must be treated identically to
# a MISSING matcher key - match-all, FAIL - not silently skipped (DS-198
# round 4, Skeptic Minor 4: previously the opposite treatment of the
# semantically closest case - missing key -> FAIL, explicit null ->
# silent skip with no WARN).
NULLMATCHER_PLUGIN_DIR="$T21_HOME/plugin-installs/nullmatcher"
mkdir -p "$NULLMATCHER_PLUGIN_DIR/hooks"
cat > "$NULLMATCHER_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": null, "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "nullmatcher@mkt": [{"installPath": "$NULLMATCHER_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"nullmatcher@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^FAIL foreign_agent_hook:.*nullmatcher@mkt" && [[ "$RC" == "1" ]]; then
  _pass "T21p2 foreign_agent_hook: explicit 'matcher: null' defaults to match-all and FAILs (same as missing key)"
else
  _fail "T21p2 foreign_agent_hook: 'matcher: null' should default to match-all and FAIL naming nullmatcher@mkt, exit 1\nrc=$RC\n$OUT"
fi

# T21p3: a matcher of the wrong JSON type (a list, not a string or null)
# is a malformed schema, NOT an implicit match-all - it must WARN and
# mark the scan incomplete, never silently skip with a positive OK
# (DS-198 round 4, Skeptic Minor 4 / Major 1 unification).
LISTMATCHER_PLUGIN_DIR="$T21_HOME/plugin-installs/listmatcher"
mkdir -p "$LISTMATCHER_PLUGIN_DIR/hooks"
cat > "$LISTMATCHER_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": ["Agent"], "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "listmatcher@mkt": [{"installPath": "$LISTMATCHER_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"listmatcher@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^WARN foreign_agent_hook:.*listmatcher@mkt" \
   && ! echo "$OUT" | grep -q "^FAIL foreign_agent_hook:" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21p3 foreign_agent_hook: non-string, non-null matcher WARNs, never OK"
else
  _fail "T21p3 foreign_agent_hook: non-string matcher should WARN naming listmatcher@mkt, never OK, exit 0\nrc=$RC\n$OUT"
fi

# T21q: enabledPlugins filtering must compare `val is True` - a plugin
# whose enabledPlugins value is the STRING "true" (truthy in many
# languages, but not Python `is True`) or JSON `false` must NOT be
# scanned (DS-198 round 3, Skeptic Minor 8 - previously un-reddenable;
# scanning a disabled plugin would be a false positive with no test
# objecting).
DISABLED_PLUGIN_DIR="$T21_HOME/plugin-installs/disabled"
mkdir -p "$DISABLED_PLUGIN_DIR/hooks"
cat > "$DISABLED_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Agent", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "disabled@mkt": [{"installPath": "$DISABLED_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"disabled@mkt": "true"}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^OK foreign_agent_hook:" && ! echo "$OUT" | grep -q "^FAIL foreign_agent_hook:" && [[ "$RC" == "0" ]]; then
  _pass "T21q foreign_agent_hook: enabledPlugins value that is not JSON boolean true is never scanned"
else
  _fail "T21q foreign_agent_hook: a non-'is True' enabledPlugins value should not be scanned, exit 0\nrc=$RC\n$OUT"
fi

# T21r: installPath dedupe - the same resolved installPath appearing
# twice in a plugin's entries list must be scanned (and FAIL) exactly
# once, not twice (DS-198 round 3, Skeptic Minor 8 - previously
# un-reddenable).
DEDUPE_PLUGIN_DIR="$T21_HOME/plugin-installs/dedupe"
mkdir -p "$DEDUPE_PLUGIN_DIR/hooks"
cat > "$DEDUPE_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Agent", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "dedupe@mkt": [
      {"installPath": "$DEDUPE_PLUGIN_DIR", "scope": "user"},
      {"installPath": "$DEDUPE_PLUGIN_DIR", "scope": "project"}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"dedupe@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
FAIL_COUNT=$(echo "$OUT" | grep -cE "^FAIL foreign_agent_hook:.*dedupe@mkt")
if [[ "$FAIL_COUNT" == "1" ]] && [[ "$RC" == "1" ]]; then
  _pass "T21r foreign_agent_hook: duplicate installPath scanned exactly once (dedupe)"
else
  _fail "T21r foreign_agent_hook: duplicate installPath should FAIL exactly once, got $FAIL_COUNT\nrc=$RC\n$OUT"
fi

# T21s: a hooks.json whose top-level "hooks" key is present but is not an
# object (null here) must WARN, not silently mask a top-level
# "PreToolUse" sibling key and report a positive OK (DS-198 round 3,
# Skeptic Minor 4).
BADHOOKS_PLUGIN_DIR="$T21_HOME/plugin-installs/badhooksval"
mkdir -p "$BADHOOKS_PLUGIN_DIR/hooks"
cat > "$BADHOOKS_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": null,
  "PreToolUse": [
    {"matcher": "Agent", "hooks": [{"command": "node routing.mjs"}]}
  ]
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "badhooksval@mkt": [{"installPath": "$BADHOOKS_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"badhooksval@mkt": true}
}
EOF
t21_invoke
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^WARN foreign_agent_hook:.*badhooksval@mkt" && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:"; then
  _pass "T21s foreign_agent_hook: non-object top-level 'hooks' value WARNs, never a masked OK"
else
  _fail "T21s foreign_agent_hook: non-object top-level 'hooks' value should WARN naming badhooksval@mkt, never OK\n$OUT"
fi

# T21t: missing installed_plugins.json (enabledPlugins non-empty, but the
# plugins manifest itself is absent) must WARN, not OK (DS-198 round 3,
# Skeptic Major 3 - manifest previously asserted OK for this path).
rm -f "$T21_HOME/.claude/plugins/installed_plugins.json"
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"anything@mkt": true}
}
EOF
t21_invoke
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^WARN foreign_agent_hook:" && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:"; then
  _pass "T21t foreign_agent_hook: missing installed_plugins.json WARNs, never OK"
else
  _fail "T21t foreign_agent_hook: missing installed_plugins.json should WARN, never OK\n$OUT"
fi

# T21t2: a plugin enabled in settings.json but with NO entry at all in
# installed_plugins.json's "plugins" map must WARN, never silently be
# treated as "nothing to scan" (DS-198 round 4, Skeptic Minor 3).
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {}
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"missingentry@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^WARN foreign_agent_hook:.*missingentry@mkt" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21t2 foreign_agent_hook: enabled plugin with no plugins-map entry at all WARNs, never OK"
else
  _fail "T21t2 foreign_agent_hook: enabled plugin with no plugins-map entry should WARN naming missingentry@mkt, never OK, exit 0\nrc=$RC\n$OUT"
fi

# T21t3: a plugins-map list containing a non-object entry (malformed
# schema) must WARN, never be silently skipped (DS-198 round 4, Skeptic
# Minor 3).
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "badentry@mkt": ["not-an-object"]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"badentry@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^WARN foreign_agent_hook:.*badentry@mkt" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21t3 foreign_agent_hook: non-object plugins-map list entry WARNs, never OK"
else
  _fail "T21t3 foreign_agent_hook: non-object plugins-map list entry should WARN naming badentry@mkt, never OK, exit 0\nrc=$RC\n$OUT"
fi

# T21t4: an entry with a missing/invalid 'installPath' must WARN, never
# be silently skipped (DS-198 round 4, Skeptic Minor 3).
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "noinstallpath@mkt": [{"scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"noinstallpath@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^WARN foreign_agent_hook:.*noinstallpath@mkt" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21t4 foreign_agent_hook: missing 'installPath' WARNs, never OK"
else
  _fail "T21t4 foreign_agent_hook: missing 'installPath' should WARN naming noinstallpath@mkt, never OK, exit 0\nrc=$RC\n$OUT"
fi

# T21t4b: an entry whose 'installPath' key is PRESENT but is an empty
# string must also WARN, never be silently skipped - the empty-string
# sub-clause of `not isinstance(install_path_raw, str) or not
# install_path_raw` is distinct from the missing-key case T21t4 covers
# and had no fixture of its own (DS-198 round 5, Skeptic Minor 6).
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "emptyinstallpath@mkt": [{"installPath": "", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"emptyinstallpath@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^WARN foreign_agent_hook:.*emptyinstallpath@mkt" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21t4b foreign_agent_hook: empty-string 'installPath' WARNs, never OK"
else
  _fail "T21t4b foreign_agent_hook: empty-string 'installPath' should WARN naming emptyinstallpath@mkt, never OK, exit 0\nrc=$RC\n$OUT"
fi

# T21t5: a PRESENT "PreToolUse" key whose value is not a list (malformed,
# distinct from an ABSENT key which is the normal no-PreToolUse-hooks
# case and must stay silent) must WARN (DS-198 round 4, Skeptic Minor 3).
BADPTU_PLUGIN_DIR="$T21_HOME/plugin-installs/badptu"
mkdir -p "$BADPTU_PLUGIN_DIR/hooks"
cat > "$BADPTU_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": "not-a-list"
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "badptu@mkt": [{"installPath": "$BADPTU_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"badptu@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^WARN foreign_agent_hook:.*badptu@mkt" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21t5 foreign_agent_hook: non-list 'PreToolUse' value WARNs, never OK"
else
  _fail "T21t5 foreign_agent_hook: non-list 'PreToolUse' value should WARN naming badptu@mkt, never OK, exit 0\nrc=$RC\n$OUT"
fi

# T21t5b: an ABSENT "PreToolUse" key (the normal case - a plugin that
# only registers other event types) must stay a plain, un-warned OK -
# T21t5's malformed-value WARN must not regress this common case.
NOPTU_PLUGIN_DIR="$T21_HOME/plugin-installs/noptu"
mkdir -p "$NOPTU_PLUGIN_DIR/hooks"
cat > "$NOPTU_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "SessionStart": [{"matcher": "", "hooks": [{"command": "echo hi"}]}]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "noptu@mkt": [{"installPath": "$NOPTU_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"noptu@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
   && ! echo "$OUT" | grep -q "^WARN foreign_agent_hook:" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21t5b foreign_agent_hook: plugin with no PreToolUse key at all stays a clean OK"
else
  _fail "T21t5b foreign_agent_hook: plugin with no PreToolUse key should be a clean OK, exit 0\nrc=$RC\n$OUT"
fi

# T21t6: a non-object entry in the PreToolUse list (malformed schema)
# must WARN, never be silently skipped (DS-198 round 4, Skeptic Minor 3).
BADPTUENTRY_PLUGIN_DIR="$T21_HOME/plugin-installs/badptuentry"
mkdir -p "$BADPTUENTRY_PLUGIN_DIR/hooks"
cat > "$BADPTUENTRY_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": ["not-an-object"]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "badptuentry@mkt": [{"installPath": "$BADPTUENTRY_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"badptuentry@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^WARN foreign_agent_hook:.*badptuentry@mkt" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21t6 foreign_agent_hook: non-object PreToolUse list entry WARNs, never OK"
else
  _fail "T21t6 foreign_agent_hook: non-object PreToolUse list entry should WARN naming badptuentry@mkt, never OK, exit 0\nrc=$RC\n$OUT"
fi

# T21u: CLAUDE_CONFIG_DIR with a literal "~" prefix is expanduser()'d by
# _plugins_dir(), not treated as a literal relative "~" subdirectory
# (DS-198 round 3, Skeptic Minor 5).
TILDE_ALT_CONFIG_DIR="$T21_HOME/tilde-config"
mkdir -p "$TILDE_ALT_CONFIG_DIR/plugins"
TILDE_EVIL="$T21_HOME/plugin-installs/tildeevil"
mkdir -p "$TILDE_EVIL/hooks"
cat > "$TILDE_EVIL/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Agent", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$TILDE_ALT_CONFIG_DIR/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "tildeevil@mkt": [{"installPath": "$TILDE_EVIL", "scope": "user"}]
  }
}
EOF
cat > "$TILDE_ALT_CONFIG_DIR/settings.json" <<EOF
{
  "enabledPlugins": {"tildeevil@mkt": true}
}
EOF
(
  HOME="$T21_HOME"
  export HOME
  # HOME-relative "~" literal - expanduser() must resolve it against
  # THIS HOME, not the invoking session's real HOME.
  CLAUDE_CONFIG_DIR="~/tilde-config"
  export CLAUDE_CONFIG_DIR
  python3 "$DOCTOR"
) > "$T21_HOME/.out" 2>&1
RC=$?
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^FAIL foreign_agent_hook:.*tildeevil@mkt.*Agent" && [[ "$RC" == "1" ]]; then
  _pass "T21u foreign_agent_hook: CLAUDE_CONFIG_DIR with a literal ~ prefix is expanduser()'d"
else
  _fail "T21u foreign_agent_hook: CLAUDE_CONFIG_DIR=~/tilde-config should expanduser() and detect tildeevil@mkt, exit 1\nrc=$RC\n$OUT"
fi

# T21v: the two OK-path messages must be distinguishable - "no plugins
# enabled at all" is not the same claim as "scanned N plugins, all clean"
# (DS-198 round 3, Skeptic Minor 6).
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {}
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{}
EOF
t21_invoke
NOENABLED_OUT=$(cat "$T21_HOME/.out")
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"safe@mkt": true}
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "safe@mkt": [{"installPath": "$SAFE_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
t21_invoke
SCANNED_OUT=$(cat "$T21_HOME/.out")
NOENABLED_LINE=$(echo "$NOENABLED_OUT" | grep "^OK foreign_agent_hook:")
SCANNED_LINE=$(echo "$SCANNED_OUT" | grep "^OK foreign_agent_hook:")
if [[ -n "$NOENABLED_LINE" ]] && [[ -n "$SCANNED_LINE" ]] && [[ "$NOENABLED_LINE" != "$SCANNED_LINE" ]]; then
  _pass "T21v foreign_agent_hook: no-plugins-enabled OK message differs from scanned-clean OK message"
else
  _fail "T21v foreign_agent_hook: the two OK messages should differ\nno-enabled: $NOENABLED_LINE\nscanned: $SCANNED_LINE"
fi

# T21w: the enabled-plugin count in the "scanned N enabled plugin(s), none
# register..." OK message must be pinned to the ACTUAL number of enabled
# plugins - not merely present, and not merely differ from the
# no-plugins-enabled message (DS-198 round 4, Skeptic Minor 5: a mutation
# adding a constant offset to the count passed all 84 pre-existing
# tests).
SAFE2_PLUGIN_DIR="$T21_HOME/plugin-installs/safe2"
mkdir -p "$SAFE2_PLUGIN_DIR/hooks"
cat > "$SAFE2_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "PreToolUse": [
    {"matcher": "Bash", "hooks": [{"command": "echo safe2"}]}
  ]
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "safe@mkt": [{"installPath": "$SAFE_PLUGIN_DIR", "scope": "user"}],
    "safe2@mkt": [{"installPath": "$SAFE2_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"safe@mkt": true, "safe2@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^OK foreign_agent_hook: scanned 2 enabled plugin\(s\), none register" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21w foreign_agent_hook: OK message pins the exact enabled-plugin count (2)"
else
  _fail "T21w foreign_agent_hook: OK message should read 'scanned 2 enabled plugin(s), none register...', exit 0\nrc=$RC\n$OUT"
fi

# T21x: a pathologically nested, uncompilable-by-recursion-limit matcher
# must not crash the whole ds-doctor run - re.compile can raise
# RecursionError (not re.error) on deeply nested groups, and the check
# must catch it the same as any other uncompilable matcher: WARN, never
# a silent OK, never an uncaught exception (DS-198 round 4, Skeptic
# Minor 8).
RECURSIONBOMB_PLUGIN_DIR="$T21_HOME/plugin-installs/recursionbomb"
mkdir -p "$RECURSIONBOMB_PLUGIN_DIR/hooks"
python3 - "$RECURSIONBOMB_PLUGIN_DIR/hooks/hooks.json" <<'PYEOF'
import json
import sys

matcher = "(" * 5000 + "a" + ")" * 5000
doc = {"hooks": {"PreToolUse": [{"matcher": matcher, "hooks": [{"command": "node routing.mjs"}]}]}}
with open(sys.argv[1], "w") as f:
    json.dump(doc, f)
PYEOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "recursionbomb@mkt": [{"installPath": "$RECURSIONBOMB_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"recursionbomb@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^WARN foreign_agent_hook:.*recursionbomb@mkt" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
   && ! echo "$OUT" | grep -qi "Traceback" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21x foreign_agent_hook: RecursionError from a pathological matcher WARNs, never crashes"
else
  _fail "T21x foreign_agent_hook: pathological matcher should WARN naming recursionbomb@mkt, never crash or OK, exit 0\nrc=$RC\n$OUT"
fi

# T21y: an enabledPlugins value of the wrong JSON type (a list, not an
# object) must WARN, never silently collapse to "no plugins enabled" -
# an enabled, hazardous plugin exists in installed_plugins.json but the
# check could not confirm which plugins are enabled at all (DS-198
# round 5, Skeptic Major 1). This is the false-positive-OK repro: prior
# to the fix this printed "OK ... no plugins enabled" with the hazard
# fully installed and enabled.
Y_PLUGIN_DIR="$T21_HOME/plugin-installs/wrongtypeenabled"
mkdir -p "$Y_PLUGIN_DIR/hooks"
cat > "$Y_PLUGIN_DIR/hooks/hooks.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Agent", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "wrongtypeenabled@mkt": [{"installPath": "$Y_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<'EOF'
{"enabledPlugins": ["wrongtypeenabled@mkt"]}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^WARN foreign_agent_hook:.*enabledPlugins.*not an object" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*no plugins enabled" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21y foreign_agent_hook: list-typed enabledPlugins WARNs, never a masked 'no plugins enabled' OK"
else
  _fail "T21y foreign_agent_hook: list-typed enabledPlugins should WARN, never OK 'no plugins enabled', exit 0\nrc=$RC\n$OUT"
fi

# T21y2: same defect, non-dict top-level settings.json (a JSON array
# instead of an object) - the OTHER half of Major 1's fix.
cat > "$T21_HOME/.claude/settings.json" <<'EOF'
["not", "an", "object"]
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -q "^WARN foreign_agent_hook:.*unexpected schema" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*no plugins enabled" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21y2 foreign_agent_hook: non-dict top-level settings.json WARNs, never a masked OK"
else
  _fail "T21y2 foreign_agent_hook: non-dict settings.json should WARN, never OK 'no plugins enabled', exit 0\nrc=$RC\n$OUT"
fi

# T21z: a matcher whose repetition count overflows the regex engine's
# internal counters (re.compile raises OverflowError, NOT re.error or
# RecursionError) must not escape check_foreign_agent_hooks and abort
# the whole ds-doctor run (DS-198 round 5, Skeptic Major 2). Prior to
# the fix this produced an uncaught traceback and a nonzero exit with
# zero JSON output.
Z_PLUGIN_DIR="$T21_HOME/plugin-installs/overflowbomb"
mkdir -p "$Z_PLUGIN_DIR/hooks"
cat > "$Z_PLUGIN_DIR/hooks/hooks.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Agent{4294967296}", "hooks": [{"command": "node routing.mjs"}]}
    ]
  }
}
EOF
cat > "$T21_HOME/.claude/plugins/installed_plugins.json" <<EOF
{
  "version": 2,
  "plugins": {
    "overflowbomb@mkt": [{"installPath": "$Z_PLUGIN_DIR", "scope": "user"}]
  }
}
EOF
cat > "$T21_HOME/.claude/settings.json" <<EOF
{
  "enabledPlugins": {"overflowbomb@mkt": true}
}
EOF
t21_invoke
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if echo "$OUT" | grep -qE "^WARN foreign_agent_hook:.*overflowbomb@mkt" \
   && ! echo "$OUT" | grep -q "^OK foreign_agent_hook:.*none register" \
   && ! echo "$OUT" | grep -qi "Traceback" \
   && [[ "$RC" == "0" ]]; then
  _pass "T21z foreign_agent_hook: OverflowError from a repetition-count matcher WARNs, never crashes"
else
  _fail "T21z foreign_agent_hook: OverflowError matcher should WARN naming overflowbomb@mkt, never crash or OK, exit 0\nrc=$RC\n$OUT"
fi

# T21z2: the same OverflowError fixture, but confirming --json mode still
# emits well-formed JSON rather than zero bytes plus an uncaught traceback.
t21_invoke --json
RC=$(cat "$T21_HOME/.exit")
OUT=$(cat "$T21_HOME/.out")
if python3 -c "import json,sys; json.loads(sys.argv[1])" "$OUT" >/dev/null 2>&1 \
   && echo "$OUT" | grep -q "overflowbomb@mkt"; then
  _pass "T21z2 foreign_agent_hook: OverflowError matcher still emits well-formed --json output"
else
  _fail "T21z2 foreign_agent_hook: OverflowError matcher should still emit well-formed --json output naming overflowbomb@mkt\nrc=$RC\n$OUT"
fi

rm -rf "$T21_HOME"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
