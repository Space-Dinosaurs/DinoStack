#!/usr/bin/env bash
# Purpose: Regression and smoke tests for bin/agentic-update.
#
# Public API: ./bin/tests/test_agentic_update.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, git, mktemp.
#
# Downstream consumers: developer running locally before commit; can be
#                       wired into CI.
#
# Failure modes: any test failure prints the failing assertion and exits 1.
#                Tests use isolated TEMP_HOME dirs with a fake config and
#                fake local-only git repos. Never touches the real ~/.agentic
#                or network; all git operations use local bare remotes.
#
# Performance: <10 s wall time on a developer machine.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UPDATER="$SCRIPT_DIR/agentic-update"

if [[ ! -x "$UPDATER" ]]; then
  echo "FAIL: $UPDATER not executable" >&2
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
# Fixture helpers
# ---------------------------------------------------------------------------

# setup_git_fixture: create a TEMP_HOME with an isolated local-only git
# setup. Sets globals:
#   TEMP_HOME     - isolated HOME; also holds the config
#   FAKE_REMOTE   - bare git repo acting as "origin"
#   FAKE_REPO     - working clone of FAKE_REMOTE, on branch main
setup_git_fixture() {
  TEMP_HOME="$(mktemp -d)"
  FAKE_REMOTE="$TEMP_HOME/remote.git"
  FAKE_REPO="$TEMP_HOME/repo"

  # Create bare remote
  git init --bare --initial-branch=main "$FAKE_REMOTE" -q 2>/dev/null \
    || git init --bare "$FAKE_REMOTE" -q

  # Clone into working repo
  git clone --quiet "$FAKE_REMOTE" "$FAKE_REPO" 2>/dev/null

  # Bootstrap: one commit on main so rev-parse + refs/heads/main exist
  (
    cd "$FAKE_REPO"
    git config user.email "test@test.com"
    git config user.name "Test"
    echo "init" > README.md
    git add README.md
    git commit -m "init" -q
    git push -q origin main 2>/dev/null
  )

  # Write config pointing at FAKE_REPO
  mkdir -p "$TEMP_HOME/.agentic"
  cat > "$TEMP_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$FAKE_REPO"
}
EOF
}

# push_ahead_commit: add a commit to FAKE_REMOTE after FAKE_REPO was cloned,
# making local main genuinely 1 behind origin/main.
# Creates a no-op .claude/install.sh in the commit so the real update path
# can run its adapter-install step without side effects when .claude/install.sh
# (an exact-path REBUILD_TRIGGER) appears in the changed files.
# Must be called after setup_git_fixture.
push_ahead_commit() {
  local pusher_dir="$TEMP_HOME/pusher"
  git clone --quiet "$FAKE_REMOTE" "$pusher_dir" 2>/dev/null
  (
    cd "$pusher_dir"
    git config user.email "test@test.com"
    git config user.name "Test"
    mkdir -p .claude
    printf '#!/usr/bin/env bash\nexit 0\n' > .claude/install.sh
    chmod +x .claude/install.sh
    git add .claude/install.sh
    git commit -m "add no-op .claude/install.sh" -q
    git push -q origin main 2>/dev/null
  )
  rm -rf "$pusher_dir"
}

# invoke_updater: run agentic-update with AGENTIC_CONFIG_PATH pointing at
# the temp config. HOME is also overridden so version-check-cache writes
# go to TEMP_HOME rather than the real user home.
invoke_updater() {
  local config_path="$TEMP_HOME/.agentic/agentic-engineering-config.json"
  (
    HOME="$TEMP_HOME"
    export HOME
    AGENTIC_CONFIG_PATH="$config_path"
    export AGENTIC_CONFIG_PATH
    python3 "$UPDATER" "$@"
  ) > "$TEMP_HOME/.out" 2>&1
  echo $? > "$TEMP_HOME/.exit"
}

# ---------------------------------------------------------------------------
# Test 1: --check resolves repo from arbitrary cwd, exits 0 with a message
# Scenario: run from /tmp with config pointing at a temp git repo.
# Must NOT fail with "repo not found" because resolution uses the config,
# not cwd.
# ---------------------------------------------------------------------------
setup_git_fixture

(
  HOME="$TEMP_HOME"
  export HOME
  AGENTIC_CONFIG_PATH="$TEMP_HOME/.agentic/agentic-engineering-config.json"
  export AGENTIC_CONFIG_PATH
  cd /tmp
  python3 "$UPDATER" --check
) > "$TEMP_HOME/.out" 2>&1
echo $? > "$TEMP_HOME/.exit"

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T1 --check from /tmp: exits 0"
else
  _fail "T1 --check from /tmp: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$OUT" | grep -qE "(Up to date|commit\(s\) behind)"; then
  _pass "T1 --check: output contains status message"
else
  _fail "T1 --check: unexpected output: $OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 2: Non-main branch exits 1, output contains "main"
# ---------------------------------------------------------------------------
setup_git_fixture

(
  cd "$FAKE_REPO"
  git checkout -b other-branch -q
)

invoke_updater --no-doctor

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "1" ]]; then
  _pass "T2 non-main branch: exits 1"
else
  _fail "T2 non-main branch: expected exit 1, got $RC"
fi

if echo "$OUT" | grep -qi "main"; then
  _pass "T2 non-main branch: output mentions 'main'"
else
  _fail "T2 non-main branch: output does not mention 'main' (got: $OUT)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 3: Dirty working tree exits 1 and lists the dirty file in output
# ---------------------------------------------------------------------------
setup_git_fixture

DIRTY_FILE="$FAKE_REPO/dirty_file.txt"
echo "dirty" > "$DIRTY_FILE"

invoke_updater --no-doctor

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "1" ]]; then
  _pass "T3 dirty tree: exits 1"
else
  _fail "T3 dirty tree: expected exit 1, got $RC"
fi

if echo "$OUT" | grep -q "dirty_file.txt"; then
  _pass "T3 dirty tree: dirty file listed in output"
else
  _fail "T3 dirty tree: dirty file not listed in output (got: $OUT)"
fi

rm -f "$DIRTY_FILE"
rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 4: --check on up-to-date repo - HEAD unchanged (smoke test)
# Note: T7 provides the falsifiable version of this assertion (remote ahead).
# ---------------------------------------------------------------------------
setup_git_fixture

HEAD_BEFORE="$(git -C "$FAKE_REPO" rev-parse HEAD 2>/dev/null)"
invoke_updater --check

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T4 --check up-to-date: exits 0"
else
  _fail "T4 --check up-to-date: expected exit 0, got $RC"
fi

HEAD_AFTER="$(git -C "$FAKE_REPO" rev-parse HEAD 2>/dev/null)"
if [[ "$HEAD_BEFORE" == "$HEAD_AFTER" ]]; then
  _pass "T4 --check: HEAD unchanged"
else
  _fail "T4 --check: HEAD changed ($HEAD_BEFORE -> $HEAD_AFTER)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 5: Invalid repo_dir exits 1 with actionable message
# ---------------------------------------------------------------------------
TEMP_HOME="$(mktemp -d)"
mkdir -p "$TEMP_HOME/.agentic"
cat > "$TEMP_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "/nonexistent/path/that/does/not/exist"
}
EOF

(
  HOME="$TEMP_HOME"
  export HOME
  AGENTIC_CONFIG_PATH="$TEMP_HOME/.agentic/agentic-engineering-config.json"
  export AGENTIC_CONFIG_PATH
  python3 "$UPDATER" --check
) > "$TEMP_HOME/.out" 2>&1
echo $? > "$TEMP_HOME/.exit"

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "1" ]]; then
  _pass "T5 invalid repo_dir: exits 1"
else
  _fail "T5 invalid repo_dir: expected exit 1, got $RC"
fi

if echo "$OUT" | grep -qi "does not exist\|not a git\|not found"; then
  _pass "T5 invalid repo_dir: actionable message in output"
else
  _fail "T5 invalid repo_dir: missing actionable message (got: $OUT)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 6: Already up-to-date update exits 0
# ---------------------------------------------------------------------------
setup_git_fixture

invoke_updater --no-doctor

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T6 up-to-date update: exits 0"
else
  _fail "T6 up-to-date update: expected exit 0, got $RC"
fi

if echo "$OUT" | grep -qiE "Already up to date"; then
  _pass "T6 up-to-date update: reports 'Already up to date'"
else
  _fail "T6 up-to-date update: unexpected output (got: $OUT)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 7 (MAJOR fix): --check reports behind count when local is behind origin
#
# This test is falsifiable: if --check accidentally pulled, HEAD would move
# to the new commit and the HEAD-unchanged assertion below would FAIL.
# The prior fixture always had origin == local so --check could vacuously
# pass even if it pulled. This fixture sets origin 1 commit ahead first.
# ---------------------------------------------------------------------------
setup_git_fixture
push_ahead_commit   # remote now 1 ahead; FAKE_REPO has NOT pulled yet

HEAD_BEFORE="$(git -C "$FAKE_REPO" rev-parse HEAD 2>/dev/null)"
invoke_updater --check

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T7 --check behind: exits 0"
else
  _fail "T7 --check behind: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$OUT" | grep -q "1 commit(s) behind"; then
  _pass "T7 --check behind: reports '1 commit(s) behind'"
else
  _fail "T7 --check behind: expected '1 commit(s) behind' (got: $OUT)"
fi

# Falsifiable no-pull assertion: HEAD must NOT move after --check
HEAD_AFTER="$(git -C "$FAKE_REPO" rev-parse HEAD 2>/dev/null)"
if [[ "$HEAD_BEFORE" == "$HEAD_AFTER" ]]; then
  _pass "T7 --check behind: HEAD unchanged (--check did not pull)"
else
  _fail "T7 --check behind: HEAD changed $HEAD_BEFORE -> $HEAD_AFTER (--check must not pull)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 8 (MAJOR fix): Real update moves HEAD and runs adapter when local
# is behind origin.
#
# push_ahead_commit adds .claude/install.sh (an exact REBUILD_TRIGGER),
# so _needs_rebuild must return True, the adapter must run (no-op exit 0),
# and HEAD must advance. This exercises the full update path including
# needsRebuild, adapter selection, install, cache reset, and Done. output.
# ---------------------------------------------------------------------------
setup_git_fixture
push_ahead_commit   # remote 1 ahead; commit contains .claude/install.sh

HEAD_BEFORE="$(git -C "$FAKE_REPO" rev-parse HEAD 2>/dev/null)"
invoke_updater --no-doctor

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T8 real update: exits 0"
else
  _fail "T8 real update: expected exit 0, got $RC (output: $OUT)"
fi

HEAD_AFTER="$(git -C "$FAKE_REPO" rev-parse HEAD 2>/dev/null)"
if [[ "$HEAD_BEFORE" != "$HEAD_AFTER" ]]; then
  _pass "T8 real update: HEAD moved (pull happened)"
else
  _fail "T8 real update: HEAD unchanged ($HEAD_BEFORE); pull did not advance HEAD"
fi

# .claude/install.sh is an exact REBUILD_TRIGGER -> rebuild must fire
if echo "$OUT" | grep -q "Rebuild triggered by"; then
  _pass "T8 real update: rebuild triggered (.claude/install.sh is a REBUILD_TRIGGER)"
else
  _fail "T8 real update: 'Rebuild triggered by' not in output (got: $OUT)"
fi

# Done. must appear at the end of a successful update (tests the fixed
# output-symmetry between rebuild and no-rebuild branches)
if echo "$OUT" | grep -q "Done\."; then
  _pass "T8 real update: 'Done.' printed at end"
else
  _fail "T8 real update: 'Done.' missing from output (got: $OUT)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 9 (MAJOR fix): Direct _needs_rebuild unit test via importlib
#
# Loads bin/agentic-update as a Python module (no .py extension).
# importlib.util.spec_from_file_location sets module __name__ to the spec
# name ("agentic_update"), NOT "__main__", so the guard at the bottom of
# the script (`if __name__ == "__main__": sys.exit(main())`) does not fire.
# This gives direct access to _needs_rebuild without spawning the CLI.
#
# Cases covered:
#   content/x.md          -> rebuild (directory-prefix trigger)
#   .cursor/build.sh      -> rebuild (*/build.sh catch-all)
#   docs/x.md             -> NO rebuild (not a trigger)
#   bin/agentic-update    -> rebuild (bin/ directory-prefix trigger)
#   empty old_head        -> always rebuild (safety case)
#   same old_head==new    -> never rebuild
# ---------------------------------------------------------------------------
python3 - "$UPDATER" > /tmp/t9_agentic_update_out.$$ 2>&1 <<'PYEOF'
import importlib.util, importlib.machinery, sys

updater_path = sys.argv[1]
# spec_from_file_location cannot infer the loader for extensionless files;
# supply SourceFileLoader explicitly so Python treats it as a .py source.
loader = importlib.machinery.SourceFileLoader("agentic_update", updater_path)
spec = importlib.util.spec_from_file_location("agentic_update", updater_path, loader=loader)
mod = importlib.util.module_from_spec(spec)
# __name__ is "agentic_update" when exec_module runs, so the
# `if __name__ == "__main__"` guard at the bottom does NOT invoke main().
spec.loader.exec_module(mod)

nr = mod._needs_rebuild
old = "abc123"
new = "def456"
failures = []

if not nr(old, new, ["content/x.md"]):
    failures.append("content/x.md should trigger rebuild (content/ prefix)")
if not nr(old, new, [".cursor/build.sh"]):
    failures.append(".cursor/build.sh should trigger rebuild (*/build.sh catch-all)")
if nr(old, new, ["docs/x.md"]):
    failures.append("docs/x.md should NOT trigger rebuild")
if not nr(old, new, ["bin/agentic-update"]):
    failures.append("bin/agentic-update should trigger rebuild (bin/ prefix)")
if not nr("", new, ["docs/x.md"]):
    failures.append("empty old_head should always rebuild")
if nr(old, old, ["content/x.md"]):
    failures.append("same old_head==new_head should NOT rebuild")

if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("all cases ok")
sys.exit(0)
PYEOF
NR_RC=$?
NR_OUT=$(cat /tmp/t9_agentic_update_out.$$ 2>/dev/null)
rm -f /tmp/t9_agentic_update_out.$$

if [[ "$NR_RC" == "0" ]]; then
  _pass "T9 _needs_rebuild: content/ prefix triggers rebuild"
  _pass "T9 _needs_rebuild: */build.sh catch-all triggers rebuild"
  _pass "T9 _needs_rebuild: docs/ does not trigger rebuild"
  _pass "T9 _needs_rebuild: bin/ prefix triggers rebuild"
  _pass "T9 _needs_rebuild: empty old_head always rebuilds"
  _pass "T9 _needs_rebuild: same heads never rebuild"
else
  _fail "T9 _needs_rebuild: one or more cases wrong: $NR_OUT"
fi

# ---------------------------------------------------------------------------
# Test 10 (MINOR m5): --check on a non-main branch exits 0
#
# Proves --check is reachable and exits 0 from a non-main branch.
# `some-feature` is branched from local main with no divergent commit, so
# HEAD == local main; both HEAD..origin/main and refs/heads/main..origin/main
# yield the same count. This test cannot distinguish which ref-range the code
# uses - that is verified by reading the implementation. What it does assert:
# --check does not hard-error or refuse to run when the current branch is not
# main (only the non-check update path enforces the branch guard).
# ---------------------------------------------------------------------------
setup_git_fixture
push_ahead_commit   # remote 1 ahead so there is actually something to count

# Switch FAKE_REPO to a non-main branch
(
  cd "$FAKE_REPO"
  git checkout -b some-feature -q
)

invoke_updater --check

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T10 --check on non-main branch: exits 0 (branch-independent)"
else
  _fail "T10 --check on non-main branch: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$OUT" | grep -qE "(commit\(s\) behind|Up to date)"; then
  _pass "T10 --check on non-main branch: output has status message"
else
  _fail "T10 --check on non-main branch: unexpected output: $OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 11 (DS-54): Direct _hooks_touched unit test via importlib
#
# Mirrors Test 9's importlib pattern. Covers the same case table as
# scripts/test/update-hookstouched.test.js so the JS and Python ports of
# the predicate agree.
# ---------------------------------------------------------------------------
python3 - "$UPDATER" > /tmp/t11_agentic_update_out.$$ 2>&1 <<'PYEOF'
import importlib.util, importlib.machinery, sys

updater_path = sys.argv[1]
loader = importlib.machinery.SourceFileLoader("agentic_update_t11", updater_path)
spec = importlib.util.spec_from_file_location("agentic_update_t11", updater_path, loader=loader)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ht = mod._hooks_touched
failures = []

if not ht(["hooks/enforce-background-spawn.py"]):
    failures.append("hooks/-prefixed path should be touched")
if ht(["content/agents/engineer.md"]):
    failures.append("non-hooks path should NOT be touched")
if not ht(["README.md", "hooks/x.sh"]):
    failures.append("mixed paths (one hooks/) should be touched")
if ht([]):
    failures.append("empty changed_paths should NOT be touched")
if not ht(["hooks\\foo.py"]):
    failures.append("backslash-normalized hooks path should be touched")
if not ht(["/hooks/foo.py"]):
    failures.append("leading-slash hooks path should be touched")

if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("all cases ok")
sys.exit(0)
PYEOF
HT_RC=$?
HT_OUT=$(cat /tmp/t11_agentic_update_out.$$ 2>/dev/null)
rm -f /tmp/t11_agentic_update_out.$$

if [[ "$HT_RC" == "0" ]]; then
  _pass "T11 _hooks_touched: hooks/-prefixed path -> touched"
  _pass "T11 _hooks_touched: non-hooks path -> not touched"
  _pass "T11 _hooks_touched: mixed paths -> touched"
  _pass "T11 _hooks_touched: empty changed_paths -> not touched"
  _pass "T11 _hooks_touched: backslash-normalized path -> touched"
  _pass "T11 _hooks_touched: leading-slash path -> touched"
else
  _fail "T11 _hooks_touched: one or more cases wrong: $HT_OUT"
fi

# push_ahead_hooks_commit: like push_ahead_commit, but the pushed commit adds
# a file under hooks/ instead of .claude/install.sh. Used to exercise the
# hooks-changed warning (DS-54) integration test.
push_ahead_hooks_commit() {
  local pusher_dir="$TEMP_HOME/pusher"
  git clone --quiet "$FAKE_REMOTE" "$pusher_dir" 2>/dev/null
  (
    cd "$pusher_dir"
    git config user.email "test@test.com"
    git config user.name "Test"
    mkdir -p hooks
    printf '#!/usr/bin/env python3\n# test hook\n' > hooks/fake-hook.py
    git add hooks/fake-hook.py
    git commit -m "add fake hook under hooks/" -q
    git push -q origin main 2>/dev/null
  )
  rm -rf "$pusher_dir"
}

# ---------------------------------------------------------------------------
# Test 11b (DS-54): integration - pulling a commit that adds a hooks/ file
# prints the warning substring.
# ---------------------------------------------------------------------------
setup_git_fixture
push_ahead_hooks_commit   # remote 1 ahead; commit adds hooks/fake-hook.py

invoke_updater --no-doctor

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T11b hooks-changed update: exits 0"
else
  _fail "T11b hooks-changed update: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$OUT" | grep -q "this update changed files under hooks/"; then
  _pass "T11b hooks-changed update: warning PRESENT in output"
else
  _fail "T11b hooks-changed update: warning missing (got: $OUT)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 11c (DS-54, negative): pulling a commit that touches only a non-hooks
# file must NOT print the warning.
# ---------------------------------------------------------------------------
setup_git_fixture
push_ahead_commit   # adds .claude/install.sh only - no hooks/ files

invoke_updater --no-doctor

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T11c non-hooks update: exits 0"
else
  _fail "T11c non-hooks update: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$OUT" | grep -q "this update changed files under hooks/"; then
  _fail "T11c non-hooks update: warning present but should be ABSENT (got: $OUT)"
else
  _pass "T11c non-hooks update: warning ABSENT (no hooks/ files changed)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 11d (DS-54, negative): a no-op pull (already up to date) must NOT
# print the warning.
# ---------------------------------------------------------------------------
setup_git_fixture
# No push_ahead_commit call - remote and local are identical (already up to date).

invoke_updater --no-doctor

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T11d no-op pull: exits 0"
else
  _fail "T11d no-op pull: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$OUT" | grep -q "this update changed files under hooks/"; then
  _fail "T11d no-op pull: warning present but should be ABSENT (already up to date)"
else
  _pass "T11d no-op pull: warning ABSENT (no-op / already up to date)"
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
