#!/usr/bin/env bash
# Purpose: THE core DS-54 acceptance proof. After install.sh runs, mutating a
#          checkout hooks/ file WITHOUT re-running install.sh must leave the
#          hooks snapshot byte-for-byte unchanged, and every in-scope
#          adapter's wired hook command must keep resolving to the
#          now-stale-but-still-served snapshot content, not the mutated
#          checkout - i.e. a bare `git pull` cannot silently rewire what a
#          live session's hooks do.
#
# Public API: ./bin/tests/test_hooks_snapshot_no_live_rewire.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, git, node (transitively, via build.sh), mktemp.
#
# Downstream consumers: developer running locally before commit; CI.
#
# Failure modes: any assertion failure prints the failing assertion and exits
#                1. A temporary fake HOME is used; the real ~/.claude,
#                ~/.codex, ~/.gemini, ~/.kimi, and ~/.agentic/hooks-snapshot
#                are never touched. The checkout's own hooks/ file IS mutated
#                during the test and is always restored via `git checkout --`
#                in a trap, even on failure.
#
# Performance: ~10-15 s wall time (one .claude/install.sh run, which builds
#              all adapters via .claude/build.sh + .cursor/build.sh).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
MUTATE_TARGET="$REPO_DIR/hooks/skill-auto-load-check.sh"

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
  git -C "$REPO_DIR" checkout -- "$MUTATE_TARGET" 2>/dev/null || true
}
trap _cleanup EXIT

# Ensure a clean starting point regardless of prior state.
git -C "$REPO_DIR" checkout -- "$MUTATE_TARGET" 2>/dev/null || true

FAKE_HOME="$TMP_ROOT/home"
mkdir -p "$FAKE_HOME/.claude"

# ---------------------------------------------------------------------------
# 1. Install (syncs the hooks snapshot + wires ~/.claude/settings.json at it).
# ---------------------------------------------------------------------------
echo ""
echo "=== 1. Install ==="

HOME="$FAKE_HOME" bash "$REPO_DIR/.claude/install.sh" --mode=opt-out --profile=default \
  < /dev/null > "$FAKE_HOME/.install_out" 2>&1
INSTALL_RC=$?

# Known, pre-existing, out-of-scope environmental limitation (see
# bin/tests/test_hooks_snapshot_migration.sh for the full explanation): when
# this test runs from inside a git worktree, .claude/install.sh's UNRELATED
# "Installing pre-commit hook" step fails after the hooks-snapshot sync and
# settings.json wiring this test asserts on have already completed
# successfully. Tolerate exactly that signature; fail on anything else.
if [[ $INSTALL_RC -ne 0 ]]; then
  if grep -q "Installing pre-commit hook" "$FAKE_HOME/.install_out" 2>/dev/null && \
     tail -n 5 "$FAKE_HOME/.install_out" | grep -q "\.git/hooks/pre-commit: Not a directory"; then
    echo "  [warn] install.sh exited $INSTALL_RC at the known worktree-only pre-commit-hook step (unrelated to DS-54, pre-existing) - tolerated" >&2
  else
    echo "  [install.sh output]:" >&2
    cat "$FAKE_HOME/.install_out" >&2
    _fail "install.sh exited $INSTALL_RC for an unexpected reason"
  fi
fi

SETTINGS="$FAKE_HOME/.claude/settings.json"
if [[ -f "$SETTINGS" ]]; then
  _pass "install.sh wrote ~/.claude/settings.json"
else
  _fail "install.sh did not write ~/.claude/settings.json"
fi

SKILL_CMD_1="$(python3 -c "
import json
with open('$SETTINGS') as f:
    d = json.load(f)
for block in d['hooks'].get('UserPromptSubmit', []):
    for h in block.get('hooks', []):
        if 'skill-auto-load-check.sh' in h.get('command', ''):
            print(h['command'])
" 2>/dev/null)"

if [[ "$SKILL_CMD_1" == *"hooks-snapshot"* ]]; then
  _pass "skill-auto-load-check.sh hook command points at the hooks snapshot"
else
  _fail "skill-auto-load-check.sh hook command does not point at the hooks snapshot: '$SKILL_CMD_1'"
fi

# Resolve the snapshot dir + the on-disk snapshot copy of the mutated script.
SNAP_DIR="$(HOME="$FAKE_HOME" bash -c "source '$REPO_DIR/scripts/lib/hooks-snapshot.sh'; hooks_snapshot_dir '$REPO_DIR'")"
SNAP_SCRIPT="$SNAP_DIR/hooks/skill-auto-load-check.sh"

if [[ -f "$SNAP_SCRIPT" ]]; then
  _pass "snapshot copy of skill-auto-load-check.sh exists at $SNAP_SCRIPT"
else
  _fail "snapshot copy of skill-auto-load-check.sh not found at $SNAP_SCRIPT"
fi

SNAP_CONTENT_BEFORE="$(cat "$SNAP_SCRIPT" 2>/dev/null)"
CHECKOUT_CONTENT_BEFORE="$(cat "$MUTATE_TARGET")"

if [[ "$SNAP_CONTENT_BEFORE" == "$CHECKOUT_CONTENT_BEFORE" ]]; then
  _pass "snapshot content matches the checkout content immediately after install"
else
  _fail "snapshot content differs from the checkout content immediately after install"
fi

# ---------------------------------------------------------------------------
# 2. THE core proof: mutate the checkout's hooks/ file WITHOUT re-running
#    install.sh, and assert the snapshot is byte-for-byte unchanged.
# ---------------------------------------------------------------------------
echo ""
echo "=== 2. Mutate checkout WITHOUT re-running install.sh ==="

MARKER="# DS-54-no-live-rewire-test-marker-$$"
printf '\n%s\n' "$MARKER" >> "$MUTATE_TARGET"

SNAP_CONTENT_AFTER="$(cat "$SNAP_SCRIPT" 2>/dev/null)"

if [[ "$SNAP_CONTENT_AFTER" == "$SNAP_CONTENT_BEFORE" ]]; then
  _pass "snapshot is byte-for-byte unchanged after mutating the checkout (THE core acceptance proof)"
else
  _fail "snapshot CHANGED after mutating the checkout - a bare 'git pull' would silently rewire a live session's hooks"
fi

if ! grep -q "$MARKER" "$SNAP_SCRIPT" 2>/dev/null; then
  _pass "the mutation marker did not leak into the snapshot"
else
  _fail "the mutation marker leaked into the snapshot"
fi

# The wired hook command (still pointing at the snapshot dir) must resolve to
# the pre-mutation content, not the mutated checkout content, proving a live
# session invoking that exact command would still run the pre-mutation script.
SKILL_CMD_AFTER="$(python3 -c "
import json
with open('$SETTINGS') as f:
    d = json.load(f)
for block in d['hooks'].get('UserPromptSubmit', []):
    for h in block.get('hooks', []):
        if 'skill-auto-load-check.sh' in h.get('command', ''):
            print(h['command'])
" 2>/dev/null)"

WIRED_PATH="$(echo "$SKILL_CMD_AFTER" | sed -E 's/^bash //')"
if [[ -f "$WIRED_PATH" ]] && ! grep -q "$MARKER" "$WIRED_PATH" 2>/dev/null; then
  _pass "the exact wired hook command path is unaffected by the checkout mutation"
else
  _fail "the exact wired hook command path ('$WIRED_PATH') was affected by the checkout mutation"
fi

# ---------------------------------------------------------------------------
# 3. Re-running install.sh refreshes the snapshot in place (documented,
#    intended scope - only a bare pull without a re-install is silent).
# ---------------------------------------------------------------------------
echo ""
echo "=== 3. Re-running install.sh refreshes the snapshot in place ==="

HOME="$FAKE_HOME" bash "$REPO_DIR/.claude/install.sh" --mode=opt-out --profile=default \
  < /dev/null > "$FAKE_HOME/.install_out2" 2>&1 || true

SNAP_CONTENT_REFRESHED="$(cat "$SNAP_SCRIPT" 2>/dev/null)"

if grep -q "$MARKER" <<< "$SNAP_CONTENT_REFRESHED"; then
  _pass "re-running install.sh refreshes the snapshot with the mutated content (expected, documented scope)"
else
  _fail "re-running install.sh did not refresh the snapshot with the mutated content"
fi

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
