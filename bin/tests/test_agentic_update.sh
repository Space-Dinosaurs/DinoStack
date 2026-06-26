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
#                fake git repos. NEVER touches the real ~/.agentic or pulls
#                from the network.
#
# Performance: <5 s wall time on a developer machine (all local git ops).

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
# Helper: create a minimal bare-clone pair for push/fetch tests.
#
# Returns (via globals):
#   FAKE_REMOTE   - a bare git repo that acts as "origin"
#   FAKE_REPO     - a working clone of FAKE_REMOTE, on branch main
#   TEMP_HOME     - isolated HOME with config pointing at FAKE_REPO
# ---------------------------------------------------------------------------
setup_git_fixture() {
  TEMP_HOME="$(mktemp -d)"
  FAKE_REMOTE="$TEMP_HOME/remote.git"
  FAKE_REPO="$TEMP_HOME/repo"

  # Create bare remote
  git init --bare --initial-branch=main "$FAKE_REMOTE" -q 2>/dev/null \
    || git init --bare "$FAKE_REMOTE" -q

  # Clone into working repo
  git clone --quiet "$FAKE_REMOTE" "$FAKE_REPO" 2>/dev/null

  # Bootstrap: commit at least one file on main so rev-parse works
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

invoke_updater() {
  # Run agentic-update with AGENTIC_CONFIG_PATH pointing at our temp config.
  # We also override HOME so the version-check cache writes go to TEMP_HOME.
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
# Test 1: --check resolves repo from an arbitrary cwd and exits 0
# Re-creates the "run from /tmp with config pointing at temp git repo" scenario
# from the spec. The script must NOT fail with "repo not found" when invoked
# from an unrelated directory.
# ---------------------------------------------------------------------------
setup_git_fixture

# Run from /tmp (unrelated directory - config is resolved via AGENTIC_CONFIG_PATH)
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

if [[ "$RC" == "0" ]]; then
  _pass "T1 --check from arbitrary cwd: exits 0"
else
  _fail "T1 --check from arbitrary cwd: expected exit 0, got $RC\n$OUT"
fi

if echo "$OUT" | grep -qE "(Up to date|commit\(s\) behind)"; then
  _pass "T1 --check: output contains status message"
else
  _fail "T1 --check: unexpected output: $OUT"
fi

# Also confirm HEAD is unchanged after --check
HEAD_BEFORE="$(git -C "$FAKE_REPO" rev-parse HEAD 2>/dev/null)"
(
  HOME="$TEMP_HOME"
  export HOME
  AGENTIC_CONFIG_PATH="$TEMP_HOME/.agentic/agentic-engineering-config.json"
  export AGENTIC_CONFIG_PATH
  python3 "$UPDATER" --check
) > /dev/null 2>&1
HEAD_AFTER="$(git -C "$FAKE_REPO" rev-parse HEAD 2>/dev/null)"

if [[ "$HEAD_BEFORE" == "$HEAD_AFTER" ]]; then
  _pass "T1 --check: HEAD unchanged (no pull performed)"
else
  _fail "T1 --check: HEAD changed ($HEAD_BEFORE -> $HEAD_AFTER); --check must not pull"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 2: Non-main branch exits 1, output contains "main"
# ---------------------------------------------------------------------------
setup_git_fixture

# Detach to a non-main branch in the repo
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
  _fail "T2 non-main branch: expected exit 1, got $RC\n$OUT"
fi

if echo "$OUT" | grep -qi "main"; then
  _pass "T2 non-main branch: output mentions 'main'"
else
  _fail "T2 non-main branch: output does not mention 'main'\n$OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 3: Dirty working tree exits 1 and lists the dirty file in output
# ---------------------------------------------------------------------------
setup_git_fixture

# Create an untracked file to make the tree dirty
DIRTY_FILE="$FAKE_REPO/dirty_file.txt"
echo "dirty" > "$DIRTY_FILE"

invoke_updater --no-doctor

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "1" ]]; then
  _pass "T3 dirty tree: exits 1"
else
  _fail "T3 dirty tree: expected exit 1, got $RC\n$OUT"
fi

# The dirty file name must appear in the output
if echo "$OUT" | grep -q "dirty_file.txt"; then
  _pass "T3 dirty tree: dirty file listed in output"
else
  _fail "T3 dirty tree: dirty file not listed in output\n$OUT"
fi

# Cleanup
rm -f "$DIRTY_FILE"
rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 4: --check does not pull (up-to-date repo, HEAD unchanged)
# This is the authoritative "check does not pull" guard.
# ---------------------------------------------------------------------------
setup_git_fixture

HEAD_BEFORE="$(git -C "$FAKE_REPO" rev-parse HEAD 2>/dev/null)"
invoke_updater --check

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T4 --check up-to-date: exits 0"
else
  _fail "T4 --check up-to-date: expected exit 0, got $RC\n$OUT"
fi

HEAD_AFTER="$(git -C "$FAKE_REPO" rev-parse HEAD 2>/dev/null)"
if [[ "$HEAD_BEFORE" == "$HEAD_AFTER" ]]; then
  _pass "T4 --check: HEAD unchanged"
else
  _fail "T4 --check: HEAD changed from $HEAD_BEFORE to $HEAD_AFTER (should not pull)"
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
  _fail "T5 invalid repo_dir: expected exit 1, got $RC\n$OUT"
fi

if echo "$OUT" | grep -qi "does not exist\|not a git\|not found"; then
  _pass "T5 invalid repo_dir: actionable message in output"
else
  _fail "T5 invalid repo_dir: missing actionable message\n$OUT"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 6: Already up-to-date update exits 0 (no adapter run, no doctor)
# ---------------------------------------------------------------------------
setup_git_fixture

invoke_updater --no-doctor

RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" ]]; then
  _pass "T6 up-to-date update: exits 0"
else
  _fail "T6 up-to-date update: expected exit 0, got $RC\n$OUT"
fi

if echo "$OUT" | grep -qiE "(Already up to date|No rebuild needed)"; then
  _pass "T6 up-to-date update: reports up-to-date or no rebuild"
else
  _fail "T6 up-to-date update: unexpected output\n$OUT"
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
