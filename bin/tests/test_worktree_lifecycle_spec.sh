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
#                repo root - not the caller's cwd);
#                content/references/worktree-lifecycle.md (grepped by
#                check_reap_wiring, DS-196 round-2 Major 3 fix - the
#                session-start reap block and its AE_WORKTREE_REAP_DISABLE
#                guard are prose that nothing else executes or tests, so
#                either could be deleted silently without this).
#
# Downstream consumers: CI; qa_criteria scenario 8 (this ticket's QA gate) -
#                       "demonstrates two distinct exit codes across three
#                       runs (0, 1, 1)"; check_prose_wiring additionally
#                       guards against a re-drift of DS-118 Critical 1;
#                       check_reap_wiring guards against a silent deletion
#                       of the DS-196 automatic session-start reap
#                       invocation or its kill-switch guard (qa_criteria
#                       scenario 5 / rubric R3).
#
# Failure modes: exits non-zero if the observed exit-code sequence across
#                the three runs is anything other than (0, 1, 1), OR if
#                check_prose_wiring finds content/commands/ds-cleanup-
#                worktrees.md missing a `classify_entry`/`disposition_for`
#                reference, or re-introduces branch-name-based
#                classification prose, OR if check_reap_wiring finds
#                content/references/worktree-lifecycle.md missing the
#                backgrounded `ds-cleanup-worktrees --repo "$REPO_ROOT"`
#                invocation or the `AE_WORKTREE_REAP_DISABLE` guard, OR if
#                check_manifest_reconciliation finds bin/ds-cleanup-worktrees
#                or hooks/session-start-wrap.sh disagreeing with whether the
#                mutating auto-reap invocation actually exists (derived, not
#                pinned - a legitimate future removal flips the expected
#                claim), OR if check_activity_window_prose (round-3 Minor
#                1/2 regression guard) finds bin/ds-cleanup-worktrees'
#                --activity-window-hours 0 NOTE/--help text re-drifting to
#                either pre-fix false claim ("lift this specific floor"
#                outright disables the gate; "`None < 0` is never true
#                either way" as the None-branch mechanism). Cleans up its
#                scratch repo on exit via a trap regardless of outcome.
#
# Performance: sub-second; two `git worktree add`/`remove` calls in a
#              throwaway repo, plus grep passes over two files.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLEANUP_DOC="$REPO_ROOT/content/commands/ds-cleanup-worktrees.md"
LIFECYCLE_DOC="$REPO_ROOT/content/references/worktree-lifecycle.md"
CLEANUP_BIN="$REPO_ROOT/bin/ds-cleanup-worktrees"
SESSION_START_WRAP="$REPO_ROOT/hooks/session-start-wrap.sh"
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

# DS-196 round-2 Major 3 regression guard: content/references/worktree-lifecycle.md
# must still contain the automatic, backgrounded session-start worktree reap
# invocation AND its AE_WORKTREE_REAP_DISABLE kill-switch guard - this is
# prose that nothing else executes, so a silent deletion of either would
# otherwise pass every other gate in this repo unnoticed.
check_reap_wiring() {
  local doc="$1"
  local ok=0

  if [ ! -f "$doc" ]; then
    echo "PROSE-WIRING VIOLATION: $doc not found" >&2
    return 1
  fi

  if ! grep -qF 'ds-cleanup-worktrees --repo "$REPO_ROOT"' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not invoke the automatic session-start worktree reap (ds-cleanup-worktrees --repo \"\$REPO_ROOT\")" >&2
    ok=1
  fi
  if ! grep -qF '>> "$REPO_ROOT/.agentic/worktree-reap.log" 2>&1 || true ) &' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc's session-start reap invocation is not backgrounded (missing the trailing ') &' subshell form)" >&2
    ok=1
  fi
  if ! grep -qF 'AE_WORKTREE_REAP_DISABLE' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not reference the AE_WORKTREE_REAP_DISABLE guard for the automatic reap" >&2
    ok=1
  fi

  return "$ok"
}

echo "== Prose-wiring check: $CLEANUP_DOC names classify_entry/disposition_for, not branch-name classification =="
check_prose_wiring "$CLEANUP_DOC"
r0=$?
echo "prose-wiring exit=$r0"

echo "== Reap-wiring check: $LIFECYCLE_DOC still invokes the backgrounded session-start reap and its AE_WORKTREE_REAP_DISABLE guard =="
check_reap_wiring "$LIFECYCLE_DOC"
r0b=$?
echo "reap-wiring exit=$r0b"

# DS-196 round-2 Major 1/2 regression guard: neither manifest may re-drift
# back to the pre-fix (false) claims that full mode "is not the mode either
# automatic call site uses" (Major 1) or that session-start-wrap.sh's
# worktree nudge is unqualified report-only (Major 2) - both were false once
# the DS-196 automatic session-start reap shipped.
#
# Round-3 Minor 3 fix: the two positive claims below ("Full mode IS now the
# mode an automatic call site uses" / "report-only for THIS --count-only
# call site") are true only because the mutating, non---count-only auto-reap
# invocation currently exists in $LIFECYCLE_DOC. Pinning them as unconditional
# literals would compel a manifest to keep asserting a claim that a
# legitimate FUTURE removal of that call site would make false, and would
# fail a correct revert. Instead, derive ground truth from whether that exact
# invocation (the same string check_reap_wiring already asserts) is present,
# and require the manifest to agree with reality either way.
check_manifest_reconciliation() {
  local ok=0

  local auto_reap_exists=0
  if grep -qF 'ds-cleanup-worktrees --repo "$REPO_ROOT"' "$LIFECYCLE_DOC" 2>/dev/null; then
    auto_reap_exists=1
  fi

  if grep -qF 'is not the mode either' "$CLEANUP_BIN"; then
    echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN still carries the stale 'is not the mode either automatic call site uses' claim" >&2
    ok=1
  fi

  if [ "$auto_reap_exists" = "1" ]; then
    if ! grep -qF 'Full mode IS now the mode an automatic call site uses' "$CLEANUP_BIN"; then
      echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN is missing the corrected DS-196 full-mode-is-automatic claim (the mutating auto-reap invocation exists in $LIFECYCLE_DOC, so the manifest must say so)" >&2
      ok=1
    fi
  else
    if grep -qF 'Full mode IS now the mode an automatic call site uses' "$CLEANUP_BIN"; then
      echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN still claims an automatic call site uses full mode, but $LIFECYCLE_DOC no longer invokes the mutating auto-reap - this claim is now false and must be updated to reflect the removal" >&2
      ok=1
    fi
  fi

  if grep -qF 'removal remains operator-invoked via' "$SESSION_START_WRAP"; then
    echo "PROSE-WIRING VIOLATION: $SESSION_START_WRAP still carries the stale unqualified 'removal remains operator-invoked' claim" >&2
    ok=1
  fi

  if [ "$auto_reap_exists" = "1" ]; then
    if ! grep -qF 'report-only for THIS --count-only call site' "$SESSION_START_WRAP"; then
      echo "PROSE-WIRING VIOLATION: $SESSION_START_WRAP is missing the corrected DS-196 call-site-scoped disclosure (the mutating auto-reap invocation exists elsewhere, so this call site's report-only scope must be qualified)" >&2
      ok=1
    fi
  fi
  # When auto_reap_exists=0, the qualified "report-only for THIS
  # --count-only call site" phrasing is not required to disappear - it
  # remains a true (if no longer necessary) statement, since --count-only
  # is always report-only regardless of what other call sites exist - so no
  # negative assertion is added for that half.

  return "$ok"
}

echo "== Manifest-reconciliation check: $CLEANUP_BIN and $SESSION_START_WRAP reflect the DS-196 automatic-reap call site accurately =="
check_manifest_reconciliation
r0c=$?
echo "manifest-reconciliation exit=$r0c"

# Round-3 Minor 1/2 regression guard: neither the operator-facing
# --activity-window-hours=0 NOTE nor its --help mechanism explanation may
# re-drift back to the two pre-fix (false) claims - that passing 0 "lifts
# this specific floor" outright (it does not: the None branch still fails
# CLOSED at 0, same as any other window value), and that this is because
# "`None < 0` is never true either way" (a real `None < 0` comparison raises
# TypeError in Python 3 - the real mechanism is the `is None` check
# short-circuiting the `or` before `<` ever runs).
check_activity_window_prose() {
  local ok=0

  if grep -qF 'Pass --activity-window-hours 0 to lift this specific' "$CLEANUP_BIN"; then
    echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN still carries the stale 'lift this specific floor' claim for --activity-window-hours 0" >&2
    ok=1
  fi
  if ! grep -qF 'to narrow this floor to' "$CLEANUP_BIN"; then
    echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN is missing the corrected --activity-window-hours 0 NOTE disclosure ('narrow this floor to')" >&2
    ok=1
  fi

  if grep -qF 'None < 0` is never true either' "$CLEANUP_BIN"; then
    echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN still carries the false '\`None < 0\` is never true either way' mechanism claim (a real None < 0 comparison raises TypeError in Python 3)" >&2
    ok=1
  fi
  if ! grep -qF '(a real `None < 0` comparison raises TypeError in' "$CLEANUP_BIN"; then
    echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN is missing the corrected 'is None' short-circuit mechanism explanation" >&2
    ok=1
  fi

  return "$ok"
}

echo "== Activity-window prose check: $CLEANUP_BIN's --activity-window-hours 0 NOTE and --help text state the real mechanism =="
check_activity_window_prose
r0d=$?
echo "activity-window-prose exit=$r0d"

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

echo "Exit codes observed: prose-wiring=$r0 reap-wiring=$r0b manifest-reconciliation=$r0c activity-window-prose=$r0d run1=$r1 run2=$r2 run3=$r3"
if [ "$r0" = "0" ] && [ "$r0b" = "0" ] && [ "$r0c" = "0" ] && [ "$r0d" = "0" ] && [ "$r1" = "0" ] && [ "$r2" = "1" ] && [ "$r3" = "1" ]; then
  echo "PASS: prose-wiring check clean, reap-wiring check clean, manifest-reconciliation check clean, activity-window-prose check clean, and two distinct exit codes across three runs (0, 1, 1)"
  exit 0
fi

echo "FAIL: expected prose-wiring=0, reap-wiring=0, manifest-reconciliation=0, activity-window-prose=0, and run exit codes 0 1 1, got prose-wiring=$r0 reap-wiring=$r0b manifest-reconciliation=$r0c activity-window-prose=$r0d $r1 $r2 $r3"
exit 1
