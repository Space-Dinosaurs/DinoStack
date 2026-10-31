#!/usr/bin/env bash
# Purpose: shell-level regression spec for the Phase 8 push and isolation
#          worktree cleanup in bin/ds-ticket-commit (the "worktree-reaper
#          automatic trigger" ticket, Part C, moved out of
#          content/commands/ds-implement-ticket.md). Runs the real CLI
#          against disposable scratch git repositories, each with a local
#          bare origin - never touches the real DinoStack checkout,
#          worktree, or branch state. Literal execution (not a
#          grep-based prose-invariant check) is deliberate: this repo's own
#          MEMORY.md records a Major finding surviving a green 41-assertion
#          grep-only suite once, on the same class of bash-block content.
#
# Public API: none (standalone script;
#             `bash bin/tests/test_phase8_worktree_cleanup.sh`).
#
# Upstream deps: bin/ds-ticket-commit (under test); bin/ds-resolve-worktree
#                and bin/ds-retire-carrier (which it calls); real `git` CLI.
#
# Downstream consumers: CI (bin-sh-tests, auto-collected per
#                       .github/workflows/bin-tests.yml's shell-test glob).
#
# Failure modes: exits non-zero on the first scenario assertion that fails.
#                Each scenario builds its own throwaway repo/origin pair
#                under a temp directory, cleaned up via a trap on exit.
#
# Performance: a handful of real `git` subprocess calls (init, bare clone,
#              worktree add/lock/remove) per scenario, plus one CLI run per
#              scenario. A few seconds total.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLI="$REPO_ROOT/bin/ds-ticket-commit"
SCRATCH="$(mktemp -d)"

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

if [ ! -x "$CLI" ]; then
  echo "FAIL: $CLI not found or not executable" >&2
  exit 1
fi

# Extra arguments after <repo> <branch> pass through to the CLI.
run_block() {
  local repo="$1"
  local branch="$2"
  shift 2
  ( REPO_DIR="$REPO_ROOT" "$CLI" --repo "$repo" --branch "$branch" "$@" )
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
  printf '/.agentic/*\nnode_modules/\n*.log\n' > "$repo/.gitignore"
  git -C "$repo" add README.md .gitignore
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
# Scenario 2 (round-2 Skeptic Critical fix): locked worktree -> `git worktree
# remove` REFUSES (no override), the refusal is surfaced to stderr and
# recorded in the skip ledger, and the worktree is left fully intact. An
# earlier version of this block unlocked + force-removed on a bare "agent may
# have just finished" assumption - that violates
# content/references/worktree-lifecycle.md §Guardrail verbatim ("No cleanup
# or prune path in this document may call `git worktree remove -f -f`...
# Never unlock... a worktree whose directory still exists") and has been
# removed entirely. A refusal here is the CORRECT, safe outcome, never a
# bug to route around.
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 2: locked worktree -> remove REFUSES, recorded, never overridden =="
REPO2="$(build_repo scenario2)"
BRANCH2="feature/scenario-2"
git -C "$REPO2" worktree add -q "$REPO2/.claude/worktrees/wt2" -b "$BRANCH2"
git -C "$REPO2" push -q -u origin "$BRANCH2"
git -C "$REPO2" worktree lock "$REPO2/.claude/worktrees/wt2"
OUT2="$(run_block "$REPO2" "$BRANCH2" 2>&1)"
BLOCK2_RC=$?
assert $BLOCK2_RC "scenario 2: block exits 0 (soft-fail - a refusal never blocks Phase 8)"
echo "$OUT2" | grep -q "is locked; skipping cleanup"
assert $? "scenario 2: lock refusal is surfaced to stderr, not silently swallowed"
[ -d "$REPO2/.claude/worktrees/wt2" ]
assert $? "scenario 2: locked worktree directory is STILL PRESENT (never unlocked or force-removed)"
git -C "$REPO2" show-ref --verify --quiet "refs/heads/$BRANCH2"
assert $? "scenario 2: branch NOT deleted (removal never happened)"
LOCK_CHECK="$(git -C "$REPO2" worktree list --porcelain)"
echo "$LOCK_CHECK" | grep -q "locked"
assert $? "scenario 2: worktree is STILL genuinely locked (unlock was never called)"
LEDGER2="$REPO2/.agentic/worktree-cleanup-skips.jsonl"
[ -f "$LEDGER2" ]
assert $? "scenario 2: skip ledger file created for the refused removal"
LEDGER2_LINE="$(tail -n1 "$LEDGER2" 2>/dev/null)"
python3 -c "
import json, sys
rec = json.loads(sys.argv[1])
assert rec['branch'] == sys.argv[2], rec
assert 'wt2' in rec['path'], rec
assert rec['stderr'], rec
" "$LEDGER2_LINE" "$BRANCH2"
assert $? "scenario 2: skip ledger line is valid JSON recording the refusal"
git -C "$REPO2" worktree unlock "$REPO2/.claude/worktrees/wt2" >/dev/null 2>&1 || true
git -C "$REPO2" worktree remove --force "$REPO2/.claude/worktrees/wt2" >/dev/null 2>&1 || true

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
assert $? "scenario 4: block exits 0 (a hold never fails Phase 8)"
echo "$OUT4" | grep -q "uncommitted changes; skipping cleanup"
assert $? "scenario 4: dirty-skip warning printed"
echo "$OUT4" | grep -q "\[phase: worktree-cleanup | HELD | branch=$BRANCH4"
assert $? "scenario 4: HELD breadcrumb printed"
[ -d "$REPO4/.claude/worktrees/wt4" ]
assert $? "scenario 4: dirty worktree directory NEVER removed"
git -C "$REPO4" show-ref --verify --quiet "refs/heads/$BRANCH4"
assert $? "scenario 4: dirty worktree's branch NEVER deleted"

# --------------------------------------------------------------------------
# Scenario 5: ignored authored .agentic/plan.md -> held, file and branch kept,
# hold record written (the pre-retire-carrier block deleted it with the
# worktree, since `git status --porcelain` never reports ignored files).
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 5: ignored .agentic/plan.md -> held, file kept =="
REPO5="$(build_repo scenario5)"
BRANCH5="feature/scenario-5"
git -C "$REPO5" worktree add -q "$REPO5/.claude/worktrees/wt5" -b "$BRANCH5"
git -C "$REPO5" push -q -u origin "$BRANCH5"
mkdir -p "$REPO5/.claude/worktrees/wt5/.agentic"
echo plan > "$REPO5/.claude/worktrees/wt5/.agentic/plan.md"
run_block "$REPO5" "$BRANCH5" >/dev/null 2>&1
assert $? "scenario 5: block exits 0"
[ -f "$REPO5/.claude/worktrees/wt5/.agentic/plan.md" ]
assert $? "scenario 5: ignored plan file survives"
git -C "$REPO5" show-ref --verify --quiet "refs/heads/$BRANCH5"
assert $? "scenario 5: branch NOT deleted"
python3 -c "
import json, sys
rec = json.loads(open(sys.argv[1]).read().splitlines()[-1])
assert rec['kind'] == 'hold' and 'wt5' in rec['path'] and 'protected ignored content' in rec['reason'], rec
" "$REPO5/.agentic/worktree-cleanup-skips.jsonl"
assert $? "scenario 5: hold record names the protected content"

# --------------------------------------------------------------------------
# Scenario 6: origin rejects the push -> nothing retired, explicit BLOCKED
# hold recorded, branch kept at the unpushed tip, CLI exits 1.
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 6: rejected push -> explicit hold, worktree and branch kept =="
REPO6="$(build_repo scenario6)"
BRANCH6="feature/scenario-6"
git -C "$REPO6" worktree add -q "$REPO6/.claude/worktrees/wt6" -b "$BRANCH6"
git -C "$REPO6" push -q -u origin "$BRANCH6"
echo ahead > "$REPO6/.claude/worktrees/wt6/ahead.txt"
git -C "$REPO6/.claude/worktrees/wt6" add ahead.txt
git -C "$REPO6/.claude/worktrees/wt6" -c user.email=spec@example.com -c user.name=spec commit -q -m ahead
AHEAD6="$(git -C "$REPO6/.claude/worktrees/wt6" rev-parse HEAD)"
printf '#!/bin/sh\necho "rejected by spec hook" >&2\nexit 1\n' > "$SCRATCH/scenario6-origin.git/hooks/pre-receive"
chmod +x "$SCRATCH/scenario6-origin.git/hooks/pre-receive"
OUT6="$(run_block "$REPO6" "$BRANCH6" 2>&1)"
RC6=$?
[ "$RC6" -eq 1 ]
assert $? "scenario 6: CLI exits 1 (push not verified)"
echo "$OUT6" | grep -q "push=FAILED"
assert $? "scenario 6: push failure reported"
[ -d "$REPO6/.claude/worktrees/wt6" ]
assert $? "scenario 6: worktree directory kept"
[ "$(git -C "$REPO6" rev-parse "refs/heads/$BRANCH6" 2>/dev/null)" = "$AHEAD6" ]
assert $? "scenario 6: branch kept at the unpushed tip"
python3 -c "
import json, sys
rec = json.loads(open(sys.argv[1]).read().splitlines()[-1])
assert rec['kind'] == 'hold' and rec['explicit'] and 'wt6' in rec['path'], rec
assert rec['reason'] == 'BLOCKED: unpushed commit', rec
" "$REPO6/.agentic/worktree-cleanup-skips.jsonl"
assert $? "scenario 6: explicit BLOCKED hold recorded"

# --------------------------------------------------------------------------
# Scenario 7: feature commit from file arguments on the sequential path
# ($REPO itself on the branch) -> committed with the given message and a
# Signed-off-by trailer, pushed, CLI exits 0.
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 7: files given -> feature commit pushed =="
REPO7="$(build_repo scenario7)"
BRANCH7="feature/scenario-7"
git -C "$REPO7" checkout -q -b "$BRANCH7"
echo feature > "$REPO7/feature.txt"
echo untouched > "$REPO7/other.txt"
run_block "$REPO7" "$BRANCH7" --message "feat: add feature file" -- feature.txt >/dev/null 2>&1
assert $? "scenario 7: CLI exits 0"
[ "$(git -C "$REPO7" log -1 --format=%s "origin/$BRANCH7")" = "feat: add feature file" ]
assert $? "scenario 7: origin tip carries the given subject"
git -C "$REPO7" log -1 --format=%B "origin/$BRANCH7" | grep -qx "Signed-off-by: spec <spec@example.com>"
assert $? "scenario 7: Signed-off-by trailer from repo-local git config"
[ "$(git -C "$REPO7" show --name-only --format= "origin/$BRANCH7")" = "feature.txt" ]
assert $? "scenario 7: only the named file was staged"

# --------------------------------------------------------------------------
# Scenario 8: a pre-commit hook rejects the feature commit -> exit 3, nothing
# pushed, worktree not retired, the change left staged.
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 8: rejected feature commit -> exit 3, no push, no retire =="
REPO8="$(build_repo scenario8)"
BRANCH8="feature/scenario-8"
git -C "$REPO8" worktree add -q "$REPO8/.claude/worktrees/wt8" -b "$BRANCH8"
git -C "$REPO8" push -q -u origin "$BRANCH8"
ORIGIN8_TIP="$(git -C "$REPO8" rev-parse "origin/$BRANCH8")"
echo feature > "$REPO8/.claude/worktrees/wt8/feature.txt"
printf '#!/bin/sh\necho "rejected by spec pre-commit" >&2\nexit 1\n' > "$REPO8/.git/hooks/pre-commit"
chmod +x "$REPO8/.git/hooks/pre-commit"
OUT8="$(run_block "$REPO8" "$BRANCH8" --integration-worktree "$REPO8/.claude/worktrees/wt8" \
  --message "feat: add feature file" -- feature.txt 2>&1)"
RC8=$?
[ "$RC8" -eq 3 ]
assert $? "scenario 8: CLI exits 3 (feature commit failed), got $RC8"
echo "$OUT8" | grep -q "push=verified"
[ $? -ne 0 ]
assert $? "scenario 8: never reports push=verified"
[ "$(git ls-remote "$SCRATCH/scenario8-origin.git" "refs/heads/$BRANCH8" | cut -f1)" = "$ORIGIN8_TIP" ]
assert $? "scenario 8: origin branch unchanged"
[ -d "$REPO8/.claude/worktrees/wt8" ]
assert $? "scenario 8: worktree not retired"
[ "$(git -C "$REPO8/.claude/worktrees/wt8" diff --cached --name-only)" = "feature.txt" ]
assert $? "scenario 8: the change is left staged"

# --------------------------------------------------------------------------
# Scenario 9: relative script path with no REPO_DIR in the environment, push
# rejected -> the install is still found and the BLOCKED hold is recorded.
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 9: relative invocation still records the BLOCKED hold =="
REPO9="$(build_repo scenario9)"
BRANCH9="feature/scenario-9"
git -C "$REPO9" worktree add -q "$REPO9/.claude/worktrees/wt9" -b "$BRANCH9"
printf '#!/bin/sh\nexit 1\n' > "$SCRATCH/scenario9-origin.git/hooks/pre-receive"
chmod +x "$SCRATCH/scenario9-origin.git/hooks/pre-receive"
( cd "$REPO_ROOT" && env -u REPO_DIR bin/ds-ticket-commit --repo "$REPO9" --branch "$BRANCH9" ) >/dev/null 2>&1
[ $? -eq 1 ]
assert $? "scenario 9: CLI exits 1"
python3 -c "
import json, sys
rec = json.loads(open(sys.argv[1]).read().splitlines()[-1])
assert rec['explicit'] and rec['reason'] == 'BLOCKED: unpushed commit' and 'wt9' in rec['path'], rec
" "$REPO9/.agentic/worktree-cleanup-skips.jsonl"
assert $? "scenario 9: explicit BLOCKED hold recorded"

# --------------------------------------------------------------------------
# Scenario 10: push rejected and ds-retire-carrier cannot record the hold ->
# a loud ERROR, never a silent skip.
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 10: failed BLOCKED hold is reported =="
REPO10="$(build_repo scenario10)"
BRANCH10="feature/scenario-10"
git -C "$REPO10" worktree add -q "$REPO10/.claude/worktrees/wt10" -b "$BRANCH10"
printf '#!/bin/sh\nexit 1\n' > "$SCRATCH/scenario10-origin.git/hooks/pre-receive"
chmod +x "$SCRATCH/scenario10-origin.git/hooks/pre-receive"
FAKE10="$SCRATCH/fake-install"
mkdir -p "$FAKE10/bin"
printf '#!/bin/sh\nexec "%s" "$@"\n' "$REPO_ROOT/bin/ds-resolve-worktree" > "$FAKE10/bin/ds-resolve-worktree"
printf '#!/bin/sh\nexit 1\n' > "$FAKE10/bin/ds-retire-carrier"
chmod +x "$FAKE10/bin/ds-retire-carrier" "$FAKE10/bin/ds-resolve-worktree"
ERR10="$( (REPO_DIR="$FAKE10" "$CLI" --repo "$REPO10" --branch "$BRANCH10") 2>&1 >/dev/null)"
echo "$ERR10" | grep -q "ERROR: BLOCKED hold NOT recorded for .*/wt10 "
assert $? "scenario 10: unrecorded hold is reported on stderr"

# --------------------------------------------------------------------------
# Scenario 11: single-engineer path - the engineer already committed and
# pushed in its own worktree, $REPO stays on main, and the call still names a
# file -> nothing to commit, not a failure: exit 0, push verified, retired.
# --------------------------------------------------------------------------
echo ""
echo "== Scenario 11: engineer already committed -> files stage nothing, exit 0 =="
REPO11="$(build_repo scenario11)"
BRANCH11="feature/scenario-11"
git -C "$REPO11" worktree add -q "$REPO11/.claude/worktrees/wt11" -b "$BRANCH11"
echo feature > "$REPO11/.claude/worktrees/wt11/feature.txt"
git -C "$REPO11/.claude/worktrees/wt11" add feature.txt
git -C "$REPO11/.claude/worktrees/wt11" -c user.email=spec@example.com -c user.name=spec commit -q -m "feat: add feature file"
git -C "$REPO11/.claude/worktrees/wt11" push -q -u origin "$BRANCH11"
OUT11="$(run_block "$REPO11" "$BRANCH11" --worktree-path "$REPO11/.claude/worktrees/wt11" \
  --message "feat: add feature file" -- feature.txt 2>&1)"
RC11=$?
[ "$RC11" -eq 0 ]
assert $? "scenario 11: CLI exits 0, got $RC11"
echo "$OUT11" | grep -q "push=verified"
assert $? "scenario 11: push verified"
echo "$OUT11" | grep -q "feature-commit=skipped | reason=nothing to commit"
assert $? "scenario 11: feature commit reported as nothing to commit"
[ ! -d "$REPO11/.claude/worktrees/wt11" ]
assert $? "scenario 11: engineer worktree retired"

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
