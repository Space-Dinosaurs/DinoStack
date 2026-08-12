#!/usr/bin/env bash
# Purpose: shell-level regression spec for the HARDENED Phase 8 isolation
#          worktree cleanup block in content/commands/ds-implement-ticket.md
#          (the "worktree-reaper automatic trigger" ticket, Part C). Extracts
#          the literal bash block between the "# --- Isolation worktree
#          cleanup (post-push) ---" and "# --- End isolation worktree
#          cleanup ---" markers and LITERALLY EXECUTES it against disposable
#          scratch git repositories - never touches the real DinoStack
#          checkout, worktree, or branch state. Literal execution (not a
#          grep-based prose-invariant check) is deliberate: this repo's own
#          MEMORY.md records a Major finding surviving a green 41-assertion
#          grep-only suite once, on the same class of bash-block content.
#
# Public API: none (standalone script;
#             `bash bin/tests/test_phase8_worktree_cleanup.sh`).
#
# Upstream deps: content/commands/ds-implement-ticket.md (the block under
#                test, extracted by marker); real `git` CLI.
#
# Downstream consumers: CI (bin-sh-tests, auto-collected per
#                       .github/workflows/bin-tests.yml's shell-test glob).
#
# Failure modes: exits non-zero on the first scenario assertion that fails.
#                Each scenario builds its own throwaway repo/origin pair
#                under a temp directory, cleaned up via a trap on exit.
#
# Performance: a handful of real `git` subprocess calls (init, bare clone,
#              worktree add/lock/remove) per scenario, plus one extracted-
#              block execution per scenario. Sub-second total.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOC="$REPO_ROOT/content/commands/ds-implement-ticket.md"
SCRATCH="$(mktemp -d)"
BLOCK_FILE="$SCRATCH/extracted-block.sh"

cleanup() {
  chmod -R u+w "$SCRATCH" 2>/dev/null || true
  rm -rf "$SCRATCH" 2>/dev/null || true
}
trap cleanup EXIT

fail_count=0
assert() {
  local condition="$1"
  local message="$2"
  if [ "$condition" -eq 0 ]; then
    echo "  PASS: $message"
  else
    echo "  FAIL: $message"
    fail_count=$((fail_count + 1))
  fi
}

# --------------------------------------------------------------------------
# Extract the literal bash block from the command file, by marker.
# --------------------------------------------------------------------------
if [ ! -f "$DOC" ]; then
  echo "FAIL: $DOC not found" >&2
  exit 1
fi

awk '
  /# --- Isolation worktree cleanup \(post-push\) ---/ { capture=1 }
  capture { print }
  /# --- End isolation worktree cleanup ---/ { if (capture) exit }
' "$DOC" > "$BLOCK_FILE"

if [ ! -s "$BLOCK_FILE" ]; then
  echo "FAIL: extracted block is empty - markers not found in $DOC" >&2
  exit 1
fi
echo "== Extracted $(wc -l < "$BLOCK_FILE" | tr -d ' ') lines from $DOC =="

run_block() {
  local repo="$1"
  local branch="$2"
  ( REPO="$repo" BRANCH_NAME="$branch" REPO_DIR="$REPO_ROOT" bash "$BLOCK_FILE" )
}

# --------------------------------------------------------------------------
# Shared repo fixture builder: bare origin + one commit on main.
# --------------------------------------------------------------------------
build_repo() {
  local name="$1"
  local origin="$SCRATCH/${name}-origin.git"
  local repo="$SCRATCH/${name}"
  git init -q --bare -b main "$origin" >/dev/null
  git clone -q "$origin" "$repo" >/dev/null 2>&1
  git -C "$repo" config user.email spec@example.com
  git -C "$repo" config user.name spec
  echo init > "$repo/README.md"
  git -C "$repo" add README.md
  git -C "$repo" commit -q -m init
  git -C "$repo" push -q -u origin main
  echo "$repo"
}

# --------------------------------------------------------------------------
# Scenario 1: clean, unlocked, pushed worktree -> removed, branch deleted.
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 1: clean pushed worktree -> removed =="
REPO1="$(build_repo scenario1)"
BRANCH1="feature/scenario-1"
git -C "$REPO1" worktree add -q "$REPO1/.claude/worktrees/wt1" -b "$BRANCH1"
git -C "$REPO1" push -q -u origin "$BRANCH1"
OUT1="$(run_block "$REPO1" "$BRANCH1")"
assert $? "scenario 1: block exits 0"
echo "$OUT1" | grep -q "\[phase: worktree-cleanup | branch=$BRANCH1"
assert $? "scenario 1: breadcrumb line printed"
[ ! -d "$REPO1/.claude/worktrees/wt1" ]
assert $? "scenario 1: worktree directory removed"
! git -C "$REPO1" show-ref --verify --quiet "refs/heads/$BRANCH1"
assert $? "scenario 1: local branch deleted"

# --------------------------------------------------------------------------
# Scenario 2: locked worktree -> unlock-then-force-remove recovery fires,
# worktree still removed (this is the NEW behavior this ticket adds - the
# original block had no lock-recovery path at all and would silently no-op
# via `2>/dev/null || true`).
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 2: locked worktree -> unlock+force-remove recovery =="
REPO2="$(build_repo scenario2)"
BRANCH2="feature/scenario-2"
git -C "$REPO2" worktree add -q "$REPO2/.claude/worktrees/wt2" -b "$BRANCH2"
git -C "$REPO2" push -q -u origin "$BRANCH2"
git -C "$REPO2" worktree lock "$REPO2/.claude/worktrees/wt2"
OUT2="$(run_block "$REPO2" "$BRANCH2")"
assert $? "scenario 2: block exits 0"
echo "$OUT2" | grep -q "\[phase: worktree-cleanup | branch=$BRANCH2"
assert $? "scenario 2: breadcrumb line printed despite the lock"
[ ! -d "$REPO2/.claude/worktrees/wt2" ]
assert $? "scenario 2: worktree directory removed after unlock+force-remove"

# --------------------------------------------------------------------------
# Scenario 3: worktree remove fails for a reason OTHER than locking
# (permission-denied on the parent directory) -> stderr is surfaced (never
# discarded) AND a persisted skip record is appended to
# .agentic/worktree-cleanup-skips.jsonl - both of which the ORIGINAL block
# (bare `2>/dev/null || true`) could not do.
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 3: unrecoverable remove failure -> stderr surfaced + skip ledger =="
REPO3="$(build_repo scenario3)"
BRANCH3="feature/scenario-3"
git -C "$REPO3" worktree add -q "$REPO3/.claude/worktrees/wt3" -b "$BRANCH3"
git -C "$REPO3" push -q -u origin "$BRANCH3"
chmod 555 "$REPO3/.claude/worktrees"
ERR3="$(run_block "$REPO3" "$BRANCH3" 2>&1 1>/dev/null)"
BLOCK_RC=$?
chmod 755 "$REPO3/.claude/worktrees"
assert $? "scenario 3: chmod restore succeeds (fixture hygiene)"
[ "$BLOCK_RC" -eq 0 ]
assert $? "scenario 3: block still exits 0 (soft-fail - never blocks Phase 8)"
echo "$ERR3" | grep -q "WARNING: git worktree remove failed"
assert $? "scenario 3: WARNING with real git stderr is surfaced, not discarded"
LEDGER="$REPO3/.agentic/worktree-cleanup-skips.jsonl"
[ -f "$LEDGER" ]
assert $? "scenario 3: skip ledger file created"
LEDGER_LINE="$(tail -n1 "$LEDGER" 2>/dev/null)"
python3 -c "
import json, sys
rec = json.loads(sys.argv[1])
assert rec['branch'] == sys.argv[2], rec
assert 'wt3' in rec['path'], rec
assert rec['stderr'], rec
assert rec['ts'], rec
" "$LEDGER_LINE" "$BRANCH3"
assert $? "scenario 3: skip ledger line is valid JSON with branch/path/stderr/ts fields"
[ -d "$REPO3/.claude/worktrees/wt3" ]
assert $? "scenario 3: worktree directory is STILL PRESENT (never silently lost)"
# Cleanup for real, now that permissions are restored and the assertions ran.
git -C "$REPO3" worktree remove --force "$REPO3/.claude/worktrees/wt3" >/dev/null 2>&1 || true

# --------------------------------------------------------------------------
# Scenario 4: dirty worktree -> untouched, no removal, no branch delete.
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 4: dirty worktree -> skipped, never removed =="
REPO4="$(build_repo scenario4)"
BRANCH4="feature/scenario-4"
git -C "$REPO4" worktree add -q "$REPO4/.claude/worktrees/wt4" -b "$BRANCH4"
git -C "$REPO4" push -q -u origin "$BRANCH4"
echo "uncommitted" > "$REPO4/.claude/worktrees/wt4/dirty.txt"
OUT4="$(run_block "$REPO4" "$BRANCH4")"
assert $? "scenario 4: block exits 0"
echo "$OUT4" | grep -q "uncommitted changes; skipping cleanup"
assert $? "scenario 4: dirty-skip warning printed"
[ -d "$REPO4/.claude/worktrees/wt4" ]
assert $? "scenario 4: dirty worktree directory NEVER removed"
git -C "$REPO4" show-ref --verify --quiet "refs/heads/$BRANCH4"
assert $? "scenario 4: dirty worktree's branch NEVER deleted"

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
echo ""
if [ "$fail_count" -eq 0 ]; then
  echo "PASS: all Phase 8 worktree cleanup scenarios passed"
  exit 0
fi
echo "FAIL: $fail_count assertion(s) failed"
exit 1
