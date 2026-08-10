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
# go to TEMP_HOME rather than the real user home. If INSTALL_ARGS_LOG is set
# in the calling shell, it is forwarded so a fixture's install.sh can record
# the exact argv it received (used by the --mode/--profile/--identity
# forwarding tests below).
invoke_updater() {
  local config_path="$TEMP_HOME/.agentic/agentic-engineering-config.json"
  (
    HOME="$TEMP_HOME"
    export HOME
    AGENTIC_CONFIG_PATH="$config_path"
    export AGENTIC_CONFIG_PATH
    if [[ -n "${INSTALL_ARGS_LOG:-}" ]]; then
      export INSTALL_ARGS_LOG
    fi
    python3 "$UPDATER" "$@"
  ) > "$TEMP_HOME/.out" 2>&1
  echo $? > "$TEMP_HOME/.exit"
}

# push_ahead_flags_commit: like push_ahead_commit, but the pushed
# .claude/install.sh records its received argv (one arg per line) to
# $INSTALL_ARGS_LOG instead of being a pure no-op. Used to verify
# --mode/--profile/--identity/--no-identity are forwarded verbatim.
push_ahead_flags_commit() {
  local pusher_dir="$TEMP_HOME/pusher"
  git clone --quiet "$FAKE_REMOTE" "$pusher_dir" 2>/dev/null
  (
    cd "$pusher_dir"
    git config user.email "test@test.com"
    git config user.name "Test"
    mkdir -p .claude
    cat > .claude/install.sh <<'INSTALLEOF'
#!/usr/bin/env bash
if [[ -n "${INSTALL_ARGS_LOG:-}" ]]; then
  for arg in "$@"; do
    echo "$arg" >> "$INSTALL_ARGS_LOG"
  done
fi
exit 0
INSTALLEOF
    chmod +x .claude/install.sh
    git add .claude/install.sh
    git commit -m "add argv-recording .claude/install.sh" -q
    git push -q origin main 2>/dev/null
  )
  rm -rf "$pusher_dir"
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
# Test 12: --mode/--profile/--identity are forwarded verbatim to install.sh
#
# Regression coverage for the new passthrough flags added when
# content/commands/ds-update.md's UPDATE-FLOW was rewritten to delegate its
# adapter loop to agentic-update instead of reimplementing it. Before this
# option existed, agentic-update always invoked install.sh with zero flags -
# ds-update.md could not delegate without losing the user's chosen
# mode/profile/identity.
# ---------------------------------------------------------------------------
setup_git_fixture
push_ahead_flags_commit

INSTALL_ARGS_LOG="$TEMP_HOME/install_args.log"
export INSTALL_ARGS_LOG
invoke_updater --no-doctor --mode=opt-out --profile=strict --identity=octocat
unset INSTALL_ARGS_LOG

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")
ARGS_RECORDED="$(cat "$TEMP_HOME/install_args.log" 2>/dev/null)"

if [[ "$RC" == "0" ]]; then
  _pass "T12 flag forwarding: exits 0"
else
  _fail "T12 flag forwarding: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$ARGS_RECORDED" | grep -qx -- "--mode=opt-out"; then
  _pass "T12 flag forwarding: --mode=opt-out forwarded"
else
  _fail "T12 flag forwarding: --mode=opt-out NOT forwarded (recorded: $ARGS_RECORDED)"
fi

if echo "$ARGS_RECORDED" | grep -qx -- "--profile=strict"; then
  _pass "T12 flag forwarding: --profile=strict forwarded"
else
  _fail "T12 flag forwarding: --profile=strict NOT forwarded (recorded: $ARGS_RECORDED)"
fi

if echo "$ARGS_RECORDED" | grep -qx -- "--identity=octocat"; then
  _pass "T12 flag forwarding: --identity=octocat forwarded"
else
  _fail "T12 flag forwarding: --identity=octocat NOT forwarded (recorded: $ARGS_RECORDED)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 13: --no-identity is forwarded verbatim, and is mutually exclusive
# with --identity (argparse-enforced).
# ---------------------------------------------------------------------------
setup_git_fixture
push_ahead_flags_commit

INSTALL_ARGS_LOG="$TEMP_HOME/install_args.log"
export INSTALL_ARGS_LOG
invoke_updater --no-doctor --no-identity
unset INSTALL_ARGS_LOG

RC=$(cat "$TEMP_HOME/.exit")
ARGS_RECORDED="$(cat "$TEMP_HOME/install_args.log" 2>/dev/null)"

if [[ "$RC" == "0" ]]; then
  _pass "T13 --no-identity forwarding: exits 0"
else
  _fail "T13 --no-identity forwarding: expected exit 0, got $RC"
fi

if echo "$ARGS_RECORDED" | grep -qx -- "--no-identity"; then
  _pass "T13 --no-identity forwarding: --no-identity forwarded"
else
  _fail "T13 --no-identity forwarding: --no-identity NOT forwarded (recorded: $ARGS_RECORDED)"
fi

# Mutual exclusion: --identity and --no-identity together must be rejected
# by argparse before any git/adapter work happens.
(
  HOME="$TEMP_HOME"
  export HOME
  AGENTIC_CONFIG_PATH="$TEMP_HOME/.agentic/agentic-engineering-config.json"
  export AGENTIC_CONFIG_PATH
  python3 "$UPDATER" --check --identity=foo --no-identity
) > "$TEMP_HOME/.mutex_out" 2>&1
MUTEX_RC=$?

if [[ "$MUTEX_RC" != "0" ]]; then
  _pass "T13 mutual exclusion: --identity + --no-identity together exits non-zero"
else
  _fail "T13 mutual exclusion: --identity + --no-identity together should be rejected, got exit 0"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 14: no flags supplied -> install.sh receives zero args, matching
# pre-existing behavior exactly (non-regression for the default/omitted
# case introduced alongside the new flags).
# ---------------------------------------------------------------------------
setup_git_fixture
push_ahead_flags_commit

INSTALL_ARGS_LOG="$TEMP_HOME/install_args.log"
export INSTALL_ARGS_LOG
invoke_updater --no-doctor
unset INSTALL_ARGS_LOG

RC=$(cat "$TEMP_HOME/.exit")
ARGS_RECORDED="$(cat "$TEMP_HOME/install_args.log" 2>/dev/null)"

if [[ "$RC" == "0" ]]; then
  _pass "T14 no flags: exits 0"
else
  _fail "T14 no flags: expected exit 0, got $RC"
fi

if [[ -z "$ARGS_RECORDED" ]]; then
  _pass "T14 no flags: install.sh received zero args (default-omitted behavior preserved)"
else
  _fail "T14 no flags: install.sh unexpectedly received args: $ARGS_RECORDED"
fi

rm -rf "$TEMP_HOME"

# setup_git_fixture_with_argv_install: like setup_git_fixture, but commits
# an argv-recording .claude/install.sh directly to FAKE_REPO and pushes it,
# so local and remote HEAD stay identical (still "up to date") after this
# call - unlike push_ahead_flags_commit, which deliberately leaves the
# pushed commit unpulled so a subsequent update has something to pull.
# Must be called after setup_git_fixture.
setup_git_fixture_with_argv_install() {
  (
    cd "$FAKE_REPO"
    mkdir -p .claude
    cat > .claude/install.sh <<'INSTALLEOF'
#!/usr/bin/env bash
if [[ -n "${INSTALL_ARGS_LOG:-}" ]]; then
  # Unconditional marker line: proves install.sh actually ran even when it
  # receives zero forwarded flags (e.g. an --adapters-only forced install),
  # which the argv-only loop below would otherwise leave undetectable.
  echo "RAN" >> "$INSTALL_ARGS_LOG"
  for arg in "$@"; do
    echo "$arg" >> "$INSTALL_ARGS_LOG"
  done
fi
exit 0
INSTALLEOF
    chmod +x .claude/install.sh
    git add .claude/install.sh
    git commit -m "add argv-recording .claude/install.sh" -q
    git push -q origin main 2>/dev/null
  )
}

# push_ahead_docs_commit: like push_ahead_commit, but the pushed commit adds
# a doc-only file that does NOT match any REBUILD_TRIGGER, so _needs_rebuild
# returns False for it (unlike push_ahead_commit's .claude/install.sh, which
# is itself an exact-path trigger). Used to exercise the "no adapter source
# changed" (not-rebuild) early-return path with a real pulled commit.
push_ahead_docs_commit() {
  local pusher_dir="$TEMP_HOME/pusher"
  git clone --quiet "$FAKE_REMOTE" "$pusher_dir" 2>/dev/null
  (
    cd "$pusher_dir"
    git config user.email "test@test.com"
    git config user.name "Test"
    mkdir -p docs
    echo "docs-only change" > docs/somefile.md
    git add docs/somefile.md
    git commit -m "docs-only change" -q
    git push -q origin main 2>/dev/null
  )
  rm -rf "$pusher_dir"
}

# ---------------------------------------------------------------------------
# Test 15 (CRITICAL fix): a confirmed config change (--mode/--profile/
# --identity) must force the adapter install loop even on the
# old_head==new_head ("Already up to date") early-return path.
#
# Before the fix, this path printed "Already up to date" and returned 0
# WITHOUT ever invoking install.sh - so an operator who ran /ds-update
# specifically to flip profile=strict (or set an identity) got exit 0
# having silently applied nothing.
# ---------------------------------------------------------------------------
setup_git_fixture
setup_git_fixture_with_argv_install
# No push_ahead_* call: FAKE_REPO is already at the same commit as FAKE_REMOTE
# (setup_git_fixture_with_argv_install committed+pushed directly to both).

INSTALL_ARGS_LOG="$TEMP_HOME/install_args.log"
export INSTALL_ARGS_LOG
invoke_updater --no-doctor --mode=opt-out --profile=strict --identity=octocat
unset INSTALL_ARGS_LOG

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")
ARGS_RECORDED="$(cat "$TEMP_HOME/install_args.log" 2>/dev/null)"

if [[ "$RC" == "0" ]]; then
  _pass "T15 already-up-to-date + config change: exits 0"
else
  _fail "T15 already-up-to-date + config change: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$OUT" | grep -qiE "Already up to date"; then
  _pass "T15 already-up-to-date + config change: still reports 'Already up to date'"
else
  _fail "T15 already-up-to-date + config change: missing 'Already up to date' (got: $OUT)"
fi

if echo "$OUT" | grep -qi "forcing adapter install"; then
  _pass "T15 already-up-to-date + config change: reports forced install"
else
  _fail "T15 already-up-to-date + config change: missing forced-install message (got: $OUT)"
fi

if echo "$ARGS_RECORDED" | grep -qx -- "--mode=opt-out" && \
   echo "$ARGS_RECORDED" | grep -qx -- "--profile=strict" && \
   echo "$ARGS_RECORDED" | grep -qx -- "--identity=octocat"; then
  _pass "T15 already-up-to-date + config change: install.sh actually ran with the confirmed flags"
else
  _fail "T15 already-up-to-date + config change: install.sh did NOT run with confirmed flags (recorded: $ARGS_RECORDED) - the Critical bug reproduces here"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 16 (CRITICAL fix): a confirmed config change must also force the
# adapter install loop on the "no adapter source changed" (not-rebuild)
# early-return path, when a real pull DID happen but touched no
# REBUILD_TRIGGER path.
#
# Before the fix, this path printed "No rebuild needed" and returned 0
# WITHOUT ever invoking install.sh, identical failure shape to T15 but on
# the second of the two early-return sites.
# ---------------------------------------------------------------------------
setup_git_fixture
setup_git_fixture_with_argv_install
push_ahead_docs_commit   # remote 1 ahead; docs-only, not a REBUILD_TRIGGER

INSTALL_ARGS_LOG="$TEMP_HOME/install_args.log"
export INSTALL_ARGS_LOG
invoke_updater --no-doctor --mode=opt-out --profile=strict
unset INSTALL_ARGS_LOG

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")
ARGS_RECORDED="$(cat "$TEMP_HOME/install_args.log" 2>/dev/null)"

if [[ "$RC" == "0" ]]; then
  _pass "T16 no-rebuild-needed + config change: exits 0"
else
  _fail "T16 no-rebuild-needed + config change: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$OUT" | grep -qi "forcing adapter install"; then
  _pass "T16 no-rebuild-needed + config change: reports forced install"
else
  _fail "T16 no-rebuild-needed + config change: missing forced-install message (got: $OUT)"
fi

if echo "$ARGS_RECORDED" | grep -qx -- "--mode=opt-out" && \
   echo "$ARGS_RECORDED" | grep -qx -- "--profile=strict"; then
  _pass "T16 no-rebuild-needed + config change: install.sh actually ran with the confirmed flags"
else
  _fail "T16 no-rebuild-needed + config change: install.sh did NOT run with confirmed flags (recorded: $ARGS_RECORDED) - the Critical bug reproduces here"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 17 (Minor fix): an explicit --adapters selection alone (no --mode/
# --profile/--identity/--no-identity) must also force the adapter install
# loop on the old_head==new_head ("Already up to date") early-return path.
#
# Before the fix, forced_install was `bool(install_flags)` only, so
# --adapters=.claude on an up-to-date repo printed "Already up to date",
# exited 0, and never invoked install.sh at all - the operator's explicit
# adapter selection was silently dropped.
# ---------------------------------------------------------------------------
setup_git_fixture
setup_git_fixture_with_argv_install
# No push_ahead_* call: FAKE_REPO is already at the same commit as FAKE_REMOTE.

INSTALL_ARGS_LOG="$TEMP_HOME/install_args.log"
export INSTALL_ARGS_LOG
invoke_updater --no-doctor --adapters=.claude
unset INSTALL_ARGS_LOG

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")
ARGS_RECORDED="$(cat "$TEMP_HOME/install_args.log" 2>/dev/null)"

if [[ "$RC" == "0" ]]; then
  _pass "T17 already-up-to-date + --adapters only: exits 0"
else
  _fail "T17 already-up-to-date + --adapters only: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$OUT" | grep -qi "forcing adapter install"; then
  _pass "T17 already-up-to-date + --adapters only: reports forced install"
else
  _fail "T17 already-up-to-date + --adapters only: missing forced-install message (got: $OUT) - the Minor bug reproduces here"
fi

if echo "$ARGS_RECORDED" | grep -qx -- "RAN"; then
  _pass "T17 already-up-to-date + --adapters only: install.sh actually ran"
else
  _fail "T17 already-up-to-date + --adapters only: install.sh did NOT run (recorded: $ARGS_RECORDED) - the Minor bug reproduces here"
fi

rm -rf "$TEMP_HOME"

# write_matching_hooks_snapshot_meta: construct a .snapshot-meta.json under
# TEMP_HOME whose source_hash matches compute_hooks_source_hash's actual
# output for FAKE_REPO's (mostly-absent) hook paths, so
# _hooks_snapshot_diverged reports "not diverged" for this fixture. Sources
# the REAL scripts/lib/hooks-snapshot.sh from THIS checkout (the same file
# bin/ds-update itself sources) - not from FAKE_REPO, which never ships that
# asset. Must be called after setup_git_fixture.
write_matching_hooks_snapshot_meta() {
  local hooks_snapshot_lib="$SCRIPT_DIR/../scripts/lib/hooks-snapshot.sh"
  (
    HOME="$TEMP_HOME"
    export HOME
    # shellcheck source=/dev/null
    source "$hooks_snapshot_lib"
    snapshot_dir="$(hooks_snapshot_dir "$FAKE_REPO")"
    mkdir -p "$snapshot_dir"
    live_hash="$(compute_hooks_source_hash \
      "$FAKE_REPO/hooks" \
      "$FAKE_REPO/bin/ds-identity" \
      "$FAKE_REPO/.codex/config/hooks.json" \
      "$FAKE_REPO/.codex/hooks" \
      "$FAKE_REPO/.gemini/hooks" \
      "$FAKE_REPO/.kimi/hooks")"
    python3 -c "
import json, sys
with open(sys.argv[1], 'w') as f:
    json.dump({'source_hash': sys.argv[2]}, f)
" "$snapshot_dir/.snapshot-meta.json" "$live_hash"
  )
}

# ---------------------------------------------------------------------------
# Test 18 (DS-54): a hooks-snapshot that has drifted from the checkout's live
# hook source (here: no snapshot has EVER been created - the never_migrated
# state) forces the adapter install loop on the old_head==new_head
# ("Already up to date") early-return path, even with no --mode/--profile/
# --identity/--adapters forcing flag.
#
# Before this fix, this path printed "Already up to date" and returned 0
# WITHOUT ever invoking install.sh - an operator who manually `git pull`ed a
# hooks/ fix before running ds-update got a silent no-op (the dogfooding gap
# this ticket closes).
# ---------------------------------------------------------------------------
setup_git_fixture
setup_git_fixture_with_argv_install
# No push_ahead_* call: FAKE_REPO is already at the same commit as FAKE_REMOTE
# (old_head==new_head). No snapshot is ever written for FAKE_REPO in this
# TEMP_HOME, so _hooks_snapshot_diverged must report "diverged" (never_migrated).

INSTALL_ARGS_LOG="$TEMP_HOME/install_args.log"
export INSTALL_ARGS_LOG
invoke_updater --no-doctor
unset INSTALL_ARGS_LOG

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")
ARGS_RECORDED="$(cat "$TEMP_HOME/install_args.log" 2>/dev/null)"

if [[ "$RC" == "0" ]]; then
  _pass "T18 already-up-to-date + hooks-snapshot never migrated: exits 0"
else
  _fail "T18 already-up-to-date + hooks-snapshot never migrated: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$OUT" | grep -qi "hooks.*snapshot.*drifted\|forcing adapter install"; then
  _pass "T18 already-up-to-date + hooks-snapshot never migrated: reports forced install"
else
  _fail "T18 already-up-to-date + hooks-snapshot never migrated: missing forced-install message (got: $OUT)"
fi

if echo "$ARGS_RECORDED" | grep -qx -- "RAN"; then
  _pass "T18 already-up-to-date + hooks-snapshot never migrated: install.sh actually ran"
else
  _fail "T18 already-up-to-date + hooks-snapshot never migrated: install.sh did NOT run (recorded: $ARGS_RECORDED) - the DS-54 dogfooding gap reproduces here"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 19 (DS-54, negative/mutation-verification case): when the local
# hooks-snapshot's stored source_hash ALREADY matches the checkout's live
# hook source, the old_head==new_head path must NOT force an adapter
# install - proves _hooks_snapshot_diverged is not just "always true", and
# that T18 is exercising the actual comparison, not a constant.
# ---------------------------------------------------------------------------
setup_git_fixture
setup_git_fixture_with_argv_install
write_matching_hooks_snapshot_meta
# No push_ahead_* call: FAKE_REPO is already at the same commit as FAKE_REMOTE.

INSTALL_ARGS_LOG="$TEMP_HOME/install_args.log"
export INSTALL_ARGS_LOG
invoke_updater --no-doctor
unset INSTALL_ARGS_LOG

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")
ARGS_RECORDED="$(cat "$TEMP_HOME/install_args.log" 2>/dev/null)"

if [[ "$RC" == "0" ]]; then
  _pass "T19 already-up-to-date + hooks-snapshot matching: exits 0"
else
  _fail "T19 already-up-to-date + hooks-snapshot matching: expected exit 0, got $RC (output: $OUT)"
fi

if echo "$OUT" | grep -qi "forcing adapter install"; then
  _fail "T19 already-up-to-date + hooks-snapshot matching: unexpectedly forced adapter install (got: $OUT)"
else
  _pass "T19 already-up-to-date + hooks-snapshot matching: did NOT force adapter install"
fi

if [[ -z "$ARGS_RECORDED" ]]; then
  _pass "T19 already-up-to-date + hooks-snapshot matching: install.sh did NOT run"
else
  _fail "T19 already-up-to-date + hooks-snapshot matching: install.sh unexpectedly ran (recorded: $ARGS_RECORDED)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# push_ahead_nontrigger_commit: like push_ahead_commit, but the pushed
# commit only touches README.md - not a REBUILD_TRIGGER path - so
# _needs_rebuild() returns False and main()'s "No rebuild needed" branch
# (bin/ds-update:627-634, doctor call at :634) fires instead of the
# rebuild-triggered branch (Step 14, doctor call at :724).
# Must be called after setup_git_fixture.
# ---------------------------------------------------------------------------
push_ahead_nontrigger_commit() {
  local pusher_dir="$TEMP_HOME/pusher"
  git clone --quiet "$FAKE_REMOTE" "$pusher_dir" 2>/dev/null
  (
    cd "$pusher_dir"
    git config user.email "test@test.com"
    git config user.name "Test"
    echo "non-trigger update" >> README.md
    git add README.md
    git commit -m "non-trigger README update" -q
    git push -q origin main 2>/dev/null
  )
  rm -rf "$pusher_dir"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# ---------------------------------------------------------------------------
# _run_doctor_cwd_check: shared body for the T18a/T18b/T18c call-site
# variants below. Assumes setup_git_fixture (and, for T18b/T18c, the
# appropriate push_ahead_* helper) has already run for this scenario.
# A stub ds-doctor on PATH records the cwd it was invoked in (it never runs
# the real binary) so the assertion is deterministic and side-effect-free.
# Sets (globals, deliberately not `local` - read by the caller after return):
#   RC, OUT              - invoke_updater's exit code / captured output
#   DOCTOR_CWD_LOG        - path to the stub's recorded-cwd file
#   REAL_SUM_BEFORE/AFTER - checksums of the REAL bin/agentic-update (the
#                           test runner's own copy, not the FAKE_REPO
#                           fixture) asserting the test never escapes its
#                           sandbox.
# Args: $1 = test id/label (e.g. "T18a"), remainder = extra invoke_updater args.
# ---------------------------------------------------------------------------
_run_doctor_cwd_check() {
  local tid="$1"
  shift

  STUB_BIN="$TEMP_HOME/stubbin"
  mkdir -p "$STUB_BIN"
  DOCTOR_CWD_LOG="$TEMP_HOME/doctor_cwd.log"
  cat > "$STUB_BIN/ds-doctor" <<STUBEOF
#!/usr/bin/env bash
pwd > "$DOCTOR_CWD_LOG"
exit 0
STUBEOF
  chmod +x "$STUB_BIN/ds-doctor"

  REAL_SUM_BEFORE="$(sha256_of "$UPDATER")"

  OTHER_DIR="$(mktemp -d)"
  ORIGINAL_PATH="$PATH"
  PATH="$STUB_BIN:$PATH"
  export PATH

  (
    cd "$OTHER_DIR"
    invoke_updater "$@"
  )

  PATH="$ORIGINAL_PATH"
  export PATH

  RC=$(cat "$TEMP_HOME/.exit")
  OUT=$(cat "$TEMP_HOME/.out")
  REAL_SUM_AFTER="$(sha256_of "$UPDATER")"

  if [[ "$RC" == "0" ]]; then
    _pass "$tid doctor cwd: exits 0"
  else
    _fail "$tid doctor cwd: expected exit 0, got $RC (output: $OUT)"
  fi

  if [[ -f "$DOCTOR_CWD_LOG" ]]; then
    RECORDED_CWD="$(cat "$DOCTOR_CWD_LOG")"
    RECORDED_REAL="$(cd "$RECORDED_CWD" 2>/dev/null && pwd -P)"
    EXPECTED_REAL="$(cd "$FAKE_REPO" && pwd -P)"
    OTHER_REAL="$(cd "$OTHER_DIR" && pwd -P)"

    if [[ "$RECORDED_REAL" == "$EXPECTED_REAL" ]]; then
      _pass "$tid doctor cwd: ds-doctor invoked with cwd == repo_dir"
    else
      _fail "$tid doctor cwd: ds-doctor invoked with cwd '$RECORDED_REAL', expected repo_dir '$EXPECTED_REAL' - the sandbox-escape bug reproduces here"
    fi

    if [[ "$RECORDED_REAL" != "$OTHER_REAL" ]]; then
      _pass "$tid doctor cwd: ds-doctor cwd is NOT the invoking shell's cwd"
    else
      _fail "$tid doctor cwd: ds-doctor cwd equals the invoking shell's cwd ($OTHER_REAL) - inherited-cwd bug reproduces here"
    fi
  else
    _fail "$tid doctor cwd: stub ds-doctor was never invoked (no cwd log written)"
  fi

  if [[ "$REAL_SUM_BEFORE" == "$REAL_SUM_AFTER" ]]; then
    _pass "$tid doctor cwd: real repo's bin/agentic-update unchanged (sandbox intact)"
  else
    _fail "$tid doctor cwd: real repo's bin/agentic-update CHECKSUM CHANGED - test escaped its sandbox"
  fi

  rm -rf "$OTHER_DIR"
}

# ---------------------------------------------------------------------------
# Test 18a (regression, dormant sandbox-escape hazard fix): "Already up to
# date" branch. old_head == new_head (no push), so main() returns
# _run_doctor(repo_dir) directly at bin/ds-update:588.
# ---------------------------------------------------------------------------
setup_git_fixture

_run_doctor_cwd_check "T18a"

if echo "$OUT" | grep -q "Already up to date"; then
  _pass "T18a doctor cwd: reached the 'Already up to date' branch (:588)"
else
  _fail "T18a doctor cwd: did not reach 'Already up to date' (got: $OUT)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 18b (regression, dormant sandbox-escape hazard fix): "No rebuild
# needed" branch. old_head != new_head but the pulled commit only touches a
# non-REBUILD_TRIGGER path, so _needs_rebuild() is False and main() calls
# _run_doctor(repo_dir) at bin/ds-update:634.
# ---------------------------------------------------------------------------
setup_git_fixture
push_ahead_nontrigger_commit

_run_doctor_cwd_check "T18b"

if echo "$OUT" | grep -q "No rebuild needed"; then
  _pass "T18b doctor cwd: reached the 'No rebuild needed' branch (:634)"
else
  _fail "T18b doctor cwd: did not reach 'No rebuild needed' (got: $OUT)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 18c (regression, dormant sandbox-escape hazard fix): rebuild-triggered
# Step 14 branch. push_ahead_commit's pushed commit adds .claude/install.sh,
# an exact-path REBUILD_TRIGGER, so _needs_rebuild() is True and control
# reaches _run_adapter_installs -> Step 14's _run_doctor(repo_dir) at
# bin/ds-update:724.
# ---------------------------------------------------------------------------
setup_git_fixture
push_ahead_commit

_run_doctor_cwd_check "T18c"

if echo "$OUT" | grep -q "Rebuild triggered by"; then
  _pass "T18c doctor cwd: reached the rebuild-triggered Step 14 branch (:724)"
else
  _fail "T18c doctor cwd: did not reach 'Rebuild triggered by' (got: $OUT)"
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
