#!/usr/bin/env bash
# Purpose: CLI-level regression spec for bin/ds-ticket-finish: argument
#          handling (flags only, never inherited environment), the
#          `knowledge` and `merge` step wiring end to end against scratch
#          git repositories with local bare origins, and the merge step's
#          carrier retirement (ticket carriers retired, this session's
#          automatic holds re-evaluated, explicit and foreign-session holds
#          left alone, exit code unaffected by holds). The moved blocks
#          themselves are covered region by region in
#          bin/tests/test_phase11e_knowledge_commit_shell.py,
#          bin/tests/test_pr_delivery_record.py and
#          bin/tests/test_ticket_rework_ledger.sh.
#
# Public API: none (standalone script;
#             `bash bin/tests/test_ticket_finish_cli.sh`).
#
# Upstream deps: bin/ds-ticket-finish (under test), bin/ds-retire-carrier,
#                bin/ds-base-sync, real `git`, python3. `gh` and
#                `ds-pr-delivery-record` are stubbed on PATH, so no
#                network call is ever made.
#
# Downstream consumers: CI (bin-sh-tests, auto-collected per
#                       .github/workflows/bin-tests.yml's shell-test glob).
#
# Failure modes: exits 1 when any assertion fails. All state lives under a
#                mktemp directory removed on exit.
#
# Performance: a few seconds (local git only).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLI="$REPO_ROOT/bin/ds-ticket-finish"
RETIRE="$REPO_ROOT/bin/ds-retire-carrier"
SCRATCH="$(mktemp -d)"
trap 'chmod -R u+w "$SCRATCH" 2>/dev/null; rm -rf "$SCRATCH" 2>/dev/null' EXIT

fail_count=0
assert() {
  if [ "$1" -eq 0 ]; then
    echo "  PASS: $2"
  else
    echo "  FAIL: $2"
    fail_count=$((fail_count + 1))
  fi
}

mkdir -p "$SCRATCH/stub-bin"
# gh answers every query with an empty auto-merge request: the knowledge
# step's queue check passes and the merge step's draft/mergeable gate fails.
printf '%s\n' '#!/bin/sh' "echo '{\"autoMergeRequest\":null}'" > "$SCRATCH/stub-bin/gh"
printf '#!/bin/sh\nexit 1\n' > "$SCRATCH/stub-bin/ds-pr-delivery-record"
chmod +x "$SCRATCH/stub-bin/gh" "$SCRATCH/stub-bin/ds-pr-delivery-record"
export PATH="$SCRATCH/stub-bin:$PATH"
export REPO_DIR="$REPO_ROOT"
unset AE_SESSION_ID

build_repo() {
  local name="$1"
  local origin="$SCRATCH/${name}-origin.git"
  local repo="$SCRATCH/${name}"
  git init -q --bare -b main "$origin" >/dev/null
  git clone -q "$origin" "$repo" >/dev/null 2>&1
  git -C "$repo" config user.email spec@example.com
  git -C "$repo" config user.name spec
  echo init > "$repo/README.md"
  printf '/.agentic/*\n' > "$repo/.gitignore"
  git -C "$repo" add README.md .gitignore
  git -C "$repo" commit -q -m init
  git -C "$repo" push -q -u origin main
  echo "$repo"
}

# add_carrier <repo> <path> <branch>: a pushed, clean worktree on its own branch.
add_carrier() {
  git -C "$1" worktree add -q "$2" -b "$3"
  git -C "$1" push -q origin "$3"
}

echo "== Usage: flags only =="
REPO0="$(build_repo usage)"
"$CLI" bogus --repo "$REPO0" --branch b >/dev/null 2>&1
[ $? -eq 2 ]
assert $? "unknown step exits 2"
REPO="$REPO0" BRANCH_NAME=b "$CLI" merge >/dev/null 2>&1
[ $? -eq 2 ]
assert $? "inherited REPO/BRANCH_NAME are never read (exit 2 without flags)"
"$CLI" merge --repo "$REPO0" >/dev/null 2>&1
[ $? -eq 2 ]
assert $? "missing --branch exits 2"

echo ""
echo "== knowledge: new MEMORY.md rides a chore(knowledge) commit onto the PR branch =="
REPOK="$(build_repo knowledge)"
git -C "$REPOK" push -q origin main:feature/k
git -C "$REPOK" fetch -q origin
echo "a durable fact" > "$REPOK/MEMORY.md"
"$CLI" knowledge --repo "$REPOK" --branch feature/k --ticket DS-1 --gh-repo o/r >/dev/null 2>&1
assert $? "knowledge step exits 0"
git -C "$REPOK" fetch -q origin
git -C "$REPOK" log -1 --format=%s origin/feature/k | grep -q '^chore(knowledge):'
assert $? "origin tip is a chore(knowledge) commit"
[ "$(git -C "$REPOK" show --name-only --format= origin/feature/k)" = "MEMORY.md" ]
assert $? "the commit carries MEMORY.md"
git -C "$REPOK" log -1 --format=%B origin/feature/k | grep -qx "Signed-off-by: spec <spec@example.com>"
assert $? "the commit is DCO-signed from repo-local config"
[ "$(git -C "$REPOK" rev-parse --abbrev-ref HEAD)" = "main" ]
assert $? "the conductor checkout's HEAD never moved"

echo ""
echo "== merge: auto-merge off, open-PR notice, base sync, carrier retirement =="
REPOM="$(build_repo merge)"
BR="feature/m"
add_carrier "$REPOM" "$REPOM/.agentic/worktrees/$BR" "$BR"
add_carrier "$REPOM" "$REPOM/.agentic/worktrees/qa-$BR" qa-branch
echo dirty > "$REPOM/.agentic/worktrees/qa-$BR/dirty.txt"
add_carrier "$REPOM" "$REPOM/.claude/worktrees/auto" auto-branch
add_carrier "$REPOM" "$REPOM/.claude/worktrees/explicit" explicit-branch
add_carrier "$REPOM" "$REPOM/.claude/worktrees/foreign" foreign-branch
echo dirty > "$REPOM/.claude/worktrees/auto/dirty.txt"
echo dirty > "$REPOM/.claude/worktrees/foreign/dirty.txt"
CLAUDE_CODE_SESSION_ID=sess-A "$RETIRE" --repo "$REPOM" "$REPOM/.claude/worktrees/auto" >/dev/null 2>&1
CLAUDE_CODE_SESSION_ID=sess-B "$RETIRE" --repo "$REPOM" "$REPOM/.claude/worktrees/foreign" >/dev/null 2>&1
CLAUDE_CODE_SESSION_ID=sess-A "$RETIRE" --repo "$REPOM" --hold --reason "still needed" \
  --revisit "operator says" "$REPOM/.claude/worktrees/explicit" >/dev/null 2>&1
rm "$REPOM/.claude/worktrees/auto/dirty.txt" "$REPOM/.claude/worktrees/foreign/dirty.txt"
mkdir -p "$REPOM/.agentic"
touch "$REPOM/.agentic/qa.md.snapshot-DS-2"

OUTM="$(CLAUDE_CODE_SESSION_ID=sess-A "$CLI" merge --repo "$REPOM" --branch "$BR" --ticket DS-2 \
  --gh-repo o/r --pr 7 --auto-merge false --base-branch main 2>&1)"
assert $? "merge step exits 0 although carriers are held"
echo "$OUTM" | grep -q "PR #7 is open and ready for review"
assert $? "auto-merge off prints the open-PR notice"
echo "$OUTM" | grep -q "\[phase: base-sync | status="
assert $? "base sync ran"
[ ! -e "$REPOM/.agentic/qa.md.snapshot-DS-2" ]
assert $? "qa.md snapshot removed"
[ ! -d "$REPOM/.agentic/worktrees/$BR" ]
assert $? "ticket integration carrier retired"
[ -d "$REPOM/.agentic/worktrees/qa-$BR" ]
assert $? "dirty QA carrier held, not removed"
[ ! -d "$REPOM/.claude/worktrees/auto" ]
assert $? "this session's automatic hold re-evaluated and retired"
[ -d "$REPOM/.claude/worktrees/explicit" ]
assert $? "explicit hold left alone"
[ -d "$REPOM/.claude/worktrees/foreign" ]
assert $? "another session's hold left alone"
git -C "$REPOM" show-ref --verify --quiet "refs/heads/$BR"
assert $? "retirement never deletes a branch"

echo ""
echo "== merge: --auto-merge is the only source; config is never read here =="
printf '{"auto_merge_on_ci_green": true}\n' > "$REPOM/.agentic/config.json"
OUTA="$("$CLI" merge --repo "$REPOM" --branch "$BR" --gh-repo o/r --pr 7 --base-branch main 2>&1)"
echo "$OUTA" | grep -q "PR #7 is open and ready for review"
assert $? "flag absent takes the no-merge branch even with config true"
OUTC="$("$CLI" merge --repo "$REPOM" --branch "$BR" --gh-repo o/r --pr 7 --auto-merge true --base-branch main 2>&1)"
echo "$OUTC" | grep -q "\[phase: auto-merge-skipped | isDraft="
assert $? "--auto-merge true enters the auto-merge block (stubbed gh fails its draft gate)"
OUTN="$("$CLI" merge --repo "$REPOM" --branch "$BR" --gh-repo o/r --base-branch main 2>&1)"
echo "$OUTN" | grep -q "\[phase: auto-merge-skipped | reason=no PR number\]"
assert $? "no --pr skips the auto-merge block"
echo "$OUTN" | grep -q "\[phase: base-sync | status="
assert $? "base sync still runs without --pr"

echo ""
if [ "$fail_count" -eq 0 ]; then
  echo "PASS: all ds-ticket-finish CLI scenarios passed"
  exit 0
fi
echo "FAIL: $fail_count assertion(s) failed"
exit 1
