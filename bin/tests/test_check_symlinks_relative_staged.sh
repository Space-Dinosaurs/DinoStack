#!/usr/bin/env bash
# Purpose: Regression guard for the --staged mode of
#          scripts/check-symlinks-relative.sh (DS-136). The --staged path had
#          zero coverage prior to this file, which is exactly why a Critical
#          field-position bug (git ls-tree emits <mode> <type> <sha>; git
#          ls-files -s emits <mode> <sha> <stage> - sharing one awk parse
#          across both modes crashes staged mode with `git cat-file -p 0` ->
#          "fatal: Not a valid object name") nearly shipped into
#          hooks/pre-commit, where it would have blocked every commit in the
#          repository. This test operates entirely inside scratch clones of
#          the real repo under mktemp -d - never the live checkout - so the
#          "critical reproduction" assertion below needs real watched paths
#          (SKILL_DIR/LINKS in check-symlinks-relative.sh are hardcoded to
#          the four real .claude/skills/agentic-engineering/* symlinks, not
#          synthetic ones).
#
# Public API: ./bin/tests/test_check_symlinks_relative_staged.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, mktemp. Clones the live checkout (committed
#                state - see the "clone captures HEAD, not the working tree"
#                gotcha below) into scratch dirs.
#
# Downstream consumers: developer running locally before commit; CI
#                        (auto-picked-up by the bin-sh-tests job's
#                        `files=(bin/tests/test_*.sh)` glob - no extra
#                        wiring needed).
#
# Failure modes: any failing assertion prints and exits 1. All git mutations
#                (git rm, staging an absolutized symlink) happen in a scratch
#                clone under mktemp -d with unconditional `trap ... EXIT`
#                cleanup - the live checkout is never touched. Gotcha: `git
#                clone <path>` clones committed history (HEAD), not
#                uncommitted working-tree changes - a scratch clone taken
#                before this repo's own uncommitted edits are committed will
#                not see them.
#
# Performance: a few seconds - one `git clone --no-hardlinks` of the repo
#              plus a handful of git plumbing calls per assertion.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAILS=0
pass() { echo "  ok: $1"; }
fail() {
  echo "  FAIL: $1" >&2
  FAILS=$((FAILS + 1))
}

SCRATCH="$(mktemp -d)"
cleanup() {
  rm -rf "$SCRATCH"
}
trap cleanup EXIT

CHECKER_REL="scripts/check-symlinks-relative.sh"
WATCHED_LINK="agents"

_fresh_clone() {
  local dest="$1"
  git clone -q --no-hardlinks "$REPO_DIR" "$dest" >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# Test 1: positive - a clean index exits 0.
# ---------------------------------------------------------------------------
CLONE1="$SCRATCH/clean"
_fresh_clone "$CLONE1"
if (cd "$CLONE1" && bash "$CHECKER_REL" --staged >/dev/null 2>&1); then
  pass "clean index: --staged exits 0"
else
  fail "clean index: --staged did not exit 0"
fi

# ---------------------------------------------------------------------------
# Test 2: Critical reproduction - stage an absolutized symlink at a watched
# path, assert exit 1, AND assert stderr does NOT contain a field-position
# crash signature (fatal: / Not a valid object name). A reintroduction of
# the field-position bug would crash with exactly that signature, and
# asserting only on exit code would not distinguish a crash from a correct
# rejection (both exit nonzero).
# ---------------------------------------------------------------------------
CLONE2="$SCRATCH/absolutized"
_fresh_clone "$CLONE2"
(
  cd "$CLONE2"
  link_path=".claude/skills/agentic-engineering/$WATCHED_LINK"
  rm "$link_path"
  ln -s "/tmp/nonexistent-absolute-target" "$link_path"
  git add "$link_path"
)
set +e
staged_out="$(cd "$CLONE2" && bash "$CHECKER_REL" --staged 2>&1)"
staged_rc=$?
set -e

if [[ "$staged_rc" -eq 1 ]]; then
  pass "absolutized symlink staged: exits 1"
else
  fail "absolutized symlink staged: expected exit 1, got $staged_rc"
fi

if [[ "$staged_out" == *"fatal:"* || "$staged_out" == *"Not a valid object name"* ]]; then
  fail "absolutized symlink staged: field-position crash signature reappeared: $staged_out"
else
  pass "absolutized symlink staged: no field-position crash signature"
fi

# ---------------------------------------------------------------------------
# Test 3: deletion skip - stage a deletion of a watched path, assert exit 0.
# ---------------------------------------------------------------------------
CLONE3="$SCRATCH/deleted"
_fresh_clone "$CLONE3"
(
  cd "$CLONE3"
  link_path=".claude/skills/agentic-engineering/$WATCHED_LINK"
  git rm -q "$link_path"
)
if (cd "$CLONE3" && bash "$CHECKER_REL" --staged >/dev/null 2>&1); then
  pass "staged deletion of watched symlink: --staged exits 0"
else
  fail "staged deletion of watched symlink: --staged did not exit 0"
fi

if [[ "$FAILS" -gt 0 ]]; then
  echo "FAILED: $FAILS assertion(s)"
  exit 1
fi
echo "All check-symlinks-relative --staged tests passed."
