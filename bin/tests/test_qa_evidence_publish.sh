#!/usr/bin/env bash
# Purpose: Regression spec for bin/ds-qa-evidence-publish (the Phase 8.5 QA
#          evidence publish) against scratch repositories with local bare
#          origins, run under /bin/bash, the PATH bash and zsh, called
#          through a link to its agentic-* link so the install path
#          resolves through both: a steady-state publish lands the
#          screenshots on origin's qa-evidence branch and prints one URL
#          record per screenshot on stdout, retires its worktree and
#          deletes the consumed files; a rejected push prints no URLs;
#          nothing to copy publishes nothing; missing flags exit 2.
#
# Public API: none (standalone script;
#             `bash bin/tests/test_qa_evidence_publish.sh`).
#
# Upstream deps: bin/ds-qa-evidence-publish (under test),
#                bin/ds-retire-carrier, real git, jq, zsh (hard-required
#                under ${CI}, skipped with a notice locally when absent).
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
SCRATCH="$(mktemp -d)"
# Called the way an operator install does: a link in another directory to
# the agentic-* link, so REPO_DIR must come from resolving both links.
mkdir -p "$SCRATCH/link-bin"
ln -s "$REPO_ROOT/bin/agentic-qa-evidence-publish" "$SCRATCH/link-bin/ds-qa-evidence-publish"
CLI="$SCRATCH/link-bin/ds-qa-evidence-publish"
trap 'chmod -R u+w "$SCRATCH" 2>/dev/null; find "$SCRATCH" -depth -delete 2>/dev/null' EXIT
unset REPO_DIR AE_SESSION_ID CLAUDE_CODE_SESSION_ID

fail_count=0
assert() {
  if [ "$1" -eq 0 ]; then
    echo "  PASS: $2"
  else
    echo "  FAIL: $2"
    fail_count=$((fail_count + 1))
  fi
}

# build_repo <name>: a clone of a bare origin that already has qa-evidence.
build_repo() {
  local origin="$SCRATCH/$1-origin.git" repo="$SCRATCH/$1"
  git init -q --bare -b main "$origin"
  git clone -q "$origin" "$repo" 2>/dev/null
  git -C "$repo" config user.email spec@example.com
  git -C "$repo" config user.name spec
  echo init > "$repo/README.md"
  printf '/.agentic/*\n' > "$repo/.gitignore"
  git -C "$repo" add README.md .gitignore
  git -C "$repo" commit -q -m init
  git -C "$repo" push -q -u origin main
  git -C "$repo" push -q origin main:qa-evidence
  echo "$repo"
}

entry() {
  jq -cn --arg p "$1" --arg d "$2" --arg c "$3" '{path:$p, description:$d, criterion_id:$c, result:"PASS"}'
}

run_suite() {
  local SH_NAME="$1" SH="$2"
  echo ""
  echo "== $SH_NAME ($SH) =="

  local REPO SHOTS OUT ERR ORIGIN
  REPO="$(build_repo "$SH_NAME-steady")"
  ORIGIN="$SCRATCH/$SH_NAME-steady-origin.git"
  SHOTS="$SCRATCH/$SH_NAME-shots"
  mkdir -p "$SHOTS"
  echo one > "$SHOTS/qa_one.png"
  echo two > "$SHOTS/qa_two.png"
  OUT="$("$SH" "$CLI" --repo "$REPO" --ticket ENG-12 --branch feature/zoom/view --gh-repo o/r -- \
    "$(entry "$SHOTS/qa_one.png" 'opens "zoom"' AC1)" "$(entry "$SHOTS/qa_two.png" 'closes' AC2)" \
    2>"$SCRATCH/$SH_NAME-steady.err")"
  assert $? "steady-state publish exits 0"
  [ "$(git --git-dir="$ORIGIN" show qa-evidence:eng-12/zoom-view/qa_one.png)" = one ] \
    && [ "$(git --git-dir="$ORIGIN" show qa-evidence:eng-12/zoom-view/qa_two.png)" = two ]
  assert $? "origin qa-evidence holds both screenshots under <ticket-slug>/<branch-slug>/"
  [ "$(printf '%s\n' "$OUT" | grep -c .)" -eq 2 ]
  assert $? "stdout is exactly one line per screenshot"
  printf '%s\n' "$OUT" | head -1 | jq -e '.url == "https://github.com/o/r/blob/qa-evidence/eng-12/zoom-view/qa_one.png" and .criterion_id == "AC1" and .description == "opens \"zoom\"" and .result == "PASS"' >/dev/null
  assert $? "each line is a compact {url, criterion_id, description, result} record"
  [ ! -e "$SHOTS/qa_one.png" ] && [ ! -e "$SHOTS/qa_two.png" ]
  assert $? "consumed screenshot files deleted"
  ! ls -d "$REPO"/.agentic/worktrees/qa-evidence-* >/dev/null 2>&1
  assert $? "the qa-evidence worktree was retired"
  grep -q '\[phase: qa-evidence | screenshots=2 | urls=2 | branch=qa-evidence\]' "$SCRATCH/$SH_NAME-steady.err"
  assert $? "breadcrumb on stderr"

  REPO="$(build_repo "$SH_NAME-reject")"
  ORIGIN="$SCRATCH/$SH_NAME-reject-origin.git"
  printf '#!/bin/sh\nexit 1\n' > "$ORIGIN/hooks/pre-receive"
  chmod +x "$ORIGIN/hooks/pre-receive"
  echo three > "$SHOTS/qa_three.png"
  OUT="$("$SH" "$CLI" --repo "$REPO" --ticket ENG-12 --branch fix/x --gh-repo o/r -- \
    "$(entry "$SHOTS/qa_three.png" d AC1)" 2>/dev/null)"
  assert $? "rejected push still exits 0 (soft-fail)"
  [ -z "$OUT" ]
  assert $? "rejected push prints no URL records"

  REPO="$(build_repo "$SH_NAME-empty")"
  ORIGIN="$SCRATCH/$SH_NAME-empty-origin.git"
  OUT="$("$SH" "$CLI" --repo "$REPO" --ticket ENG-12 --branch fix/x --gh-repo o/r -- \
    "$(entry "$SHOTS/missing.png" d AC1)" 2>/dev/null)"
  assert $? "nothing to copy exits 0"
  [ -z "$OUT" ] && [ "$(git --git-dir="$ORIGIN" rev-parse qa-evidence)" = "$(git --git-dir="$ORIGIN" rev-parse main)" ]
  assert $? "nothing to copy publishes nothing"

  "$SH" "$CLI" --repo "$REPO" --ticket ENG-12 --branch fix/x >/dev/null 2>&1
  [ $? -eq 2 ]
  assert $? "missing --gh-repo exits 2"
}

run_suite bash3 /bin/bash
run_suite bash "$(command -v bash)"
if command -v zsh >/dev/null 2>&1; then
  run_suite zsh "$(command -v zsh)"
elif [ -n "${CI:-}" ]; then
  echo "  FAIL: zsh not installed under CI"
  fail_count=$((fail_count + 1))
else
  echo "NOTICE: zsh not installed; zsh suite skipped"
fi

echo ""
if [ "$fail_count" -eq 0 ]; then
  echo "ALL PASS"
  exit 0
fi
echo "$fail_count FAILED"
exit 1
