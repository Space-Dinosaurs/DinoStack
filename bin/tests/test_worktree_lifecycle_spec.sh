#!/usr/bin/env bash
# Purpose: shell-level determinism smoke spec for the DS-118 worktree model
#          (bin/tests/worktree_model.py). Demonstrates that a violation the
#          model can detect is found DETERMINISTICALLY across repeated runs
#          (not flaky), by building a disposable scratch git repository
#          under a temp directory and never touching the real DinoStack
#          checkout, worktree, or branch state. Also carries a prose-wiring
#          regression check (check_prose_wiring): the model shipped once
#          with zero content/ references at all (DS-118 Critical 1, fixed in
#          a follow-up pass) - this assertion pins that fix so a future edit
#          to content/commands/ds-cleanup-worktrees.md cannot silently
#          re-drift back to classifying worktree entries by branch name.
#
# Public API: none (standalone script; `bash bin/tests/test_worktree_lifecycle_spec.sh`).
#
# Upstream deps: bin/tests/worktree_model.py (imported via PYTHONPATH);
#                content/commands/ds-cleanup-worktrees.md (grepped by
#                check_prose_wiring, resolved relative to this script's
#                repo root - not the caller's cwd).
#
# Downstream consumers: CI; qa_criteria scenario 8 (this ticket's QA gate) -
#                       "demonstrates two distinct exit codes across three
#                       runs (0, 1, 1)"; check_prose_wiring additionally
#                       guards against a re-drift of DS-118 Critical 1.
#
# Failure modes: exits non-zero if the observed exit-code sequence across
#                the three runs is anything other than (0, 1, 1), OR if
#                check_prose_wiring finds content/commands/ds-cleanup-
#                worktrees.md missing a `classify_entry`/`disposition_for`
#                reference, or re-introduces branch-name-based
#                classification prose. Cleans up its scratch repo on exit
#                via a trap regardless of outcome.
#
# Performance: sub-second; two `git worktree add`/`remove` calls in a
#              throwaway repo, plus two grep passes over one file.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLEANUP_DOC="$REPO_ROOT/content/commands/ds-cleanup-worktrees.md"
SCRATCH="$(mktemp -d)"

cleanup() {
  rm -rf "$SCRATCH" 2>/dev/null || true
}
trap cleanup EXIT

REPO="$SCRATCH/repo"

setup_repo() {
  git init -q "$REPO"
  git -C "$REPO" config user.email spec@example.com
  git -C "$REPO" config user.name spec
  git -C "$REPO" commit -q --allow-empty -m init
}

# Parses the scratch repo's live `git worktree list --porcelain` via the
# model and exits 1 if any entry OTHER than the main worktree resolves to
# anything but UNMANAGED - a minimal "no unexpected managed worktree is
# present" assertion, used purely as a deterministic, injectable signal for
# this smoke spec (not a claim about what SHOULD exist in a real repo).
run_check() {
  local repo="$1"
  PYTHONPATH="$SCRIPT_DIR" python3 - "$repo" <<'PYEOF'
import subprocess
import sys

import os

from worktree_model import WorktreeClass, classify_entry, parse_porcelain

repo = sys.argv[1]
out = subprocess.run(
    ["git", "-C", repo, "worktree", "list", "--porcelain"],
    capture_output=True,
    text=True,
    check=True,
).stdout
entries = parse_porcelain(out)

# git reports worktree paths through their PHYSICAL (symlink-resolved) form
# (e.g. `/private/var/...` on macOS even when invoked via a `/var/...`
# logical path) - realpath() here so host/repo_root match what the
# porcelain output actually emits.
repo_real = os.path.realpath(repo)

violations = []
for i, entry in enumerate(entries):
    wt_class = classify_entry(entry, host=repo_real, repo_root=repo_real, is_main=(i == 0))
    if i > 0 and wt_class is not WorktreeClass.UNMANAGED:
        violations.append((entry.path, wt_class))

if violations:
    for path, wt_class in violations:
        print(f"VIOLATION: {path} classified {wt_class}", file=sys.stderr)
    sys.exit(1)

print("clean")
sys.exit(0)
PYEOF
}

# DS-118 Critical 1 regression guard: content/commands/ds-cleanup-worktrees.md
# must NAME classify_entry/disposition_for as the classification/disposition
# authority, and must NOT classify a worktree entry by branch name (the
# exact defect-1 collision this ticket was filed against: a renamed branch
# living inside an admin directory). Fails on either condition.
check_prose_wiring() {
  local doc="$1"
  local ok=0

  if [ ! -f "$doc" ]; then
    echo "PROSE-WIRING VIOLATION: $doc not found" >&2
    return 1
  fi

  if ! grep -q 'classify_entry' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not reference classify_entry" >&2
    ok=1
  fi
  if ! grep -q 'disposition_for' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not reference disposition_for" >&2
    ok=1
  fi
  # The exact pre-fix phrasing (branch-name-first classification) and its
  # defining verb ("Categorize"/"branch matches") must not reappear.
  if grep -qi 'categorize each remaining entry by its branch name' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc has re-drifted to branch-name-based classification prose" >&2
    ok=1
  fi
  if grep -qE 'branch matches .(worktree-agent-\*|feature/\*)' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc classifies a worktree class by 'branch matches' pattern" >&2
    ok=1
  fi

  return "$ok"
}

echo "== Prose-wiring check: $CLEANUP_DOC names classify_entry/disposition_for, not branch-name classification =="
check_prose_wiring "$CLEANUP_DOC"
r0=$?
echo "prose-wiring exit=$r0"

echo "== Run 1: clean scratch repo (expect exit 0) =="
setup_repo
run_check "$REPO"
r1=$?
echo "run1 exit=$r1"

echo "== Run 2: inject a managed-looking worktree under .agentic/worktrees/ (expect exit 1) =="
mkdir -p "$REPO/.agentic"
git -C "$REPO" worktree add -q -b spec-fixture-branch "$REPO/.agentic/worktrees/spec-fixture" >/dev/null 2>&1
run_check "$REPO"
r2=$?
echo "run2 exit=$r2"

echo "== Run 3: same state, no remediation applied (expect exit 1 again - deterministic, not flaky) =="
run_check "$REPO"
r3=$?
echo "run3 exit=$r3"

git -C "$REPO" worktree remove --force "$REPO/.agentic/worktrees/spec-fixture" >/dev/null 2>&1 || true

echo "Exit codes observed: prose-wiring=$r0 run1=$r1 run2=$r2 run3=$r3"
if [ "$r0" = "0" ] && [ "$r1" = "0" ] && [ "$r2" = "1" ] && [ "$r3" = "1" ]; then
  echo "PASS: prose-wiring check clean, and two distinct exit codes across three runs (0, 1, 1)"
  exit 0
fi

echo "FAIL: expected prose-wiring=0 and run exit codes 0 1 1, got prose-wiring=$r0 $r1 $r2 $r3"
exit 1
