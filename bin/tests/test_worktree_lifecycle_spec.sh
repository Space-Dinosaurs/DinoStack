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
#                either could be deleted silently without this);
#                bin/ds-cleanup-worktrees (CLEANUP_BIN, grepped by
#                check_manifest_reconciliation and check_activity_window_prose
#                for its NOTE text and module docstring);
#                hooks/session-start-wrap.sh (SESSION_START_WRAP, grepped by
#                check_manifest_reconciliation for its call-site disclosure);
#                content/rules/conventions.md (CONVENTIONS_DOC) and
#                content/sections/11-worktree-lifecycle.md (SECTION_DOC),
#                both grepped by check_lock_caveat_pointers for the
#                by-path pointer to bin/ds-cleanup-worktrees' canonical
#                "Locked handling:" lock-state caveat.
#
# Downstream consumers: CI; qa_criteria scenario 8 (this ticket's QA gate) -
#                       "demonstrates two distinct exit codes across three
#                       runs (0, 1, 1)"; check_prose_wiring additionally
#                       guards against a re-drift of DS-118 Critical 1;
#                       check_reap_wiring guards against a silent deletion
#                       of the DS-196 automatic session-start reap
#                       invocation or its kill-switch guard (qa_criteria
#                       scenario 5 / rubric R3); check_lock_caveat_pointers
#                       guards the single-source lock-state caveat against
#                       a pointer losing its target path, being deleted, or
#                       being re-homed away from the prose it qualifies, and
#                       against the caveat being deleted or having its
#                       trailing clause rewritten.
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
#                1/2 regression guard, corrected round-4 Minor 4) finds
#                bin/ds-cleanup-worktrees' module docstring
#                (--activity-window-hours entry) or its runtime
#                --activity-window-hours=0 NOTE re-drifting to any pre-fix
#                false claim: "lift this specific floor" outright disabling
#                the gate; "`None < 0` is never true either way" as the
#                None-branch mechanism; or "no non-None activity reading is
#                ever recent enough to skip" (false for a negative/
#                future-mtime reading); OR if check_activity_window_prose's
#                presence assertion finds bin/ds-cleanup-worktrees missing
#                the corrected "is None" short-circuit mechanism explanation
#                entirely (e.g. the module docstring's --activity-window-hours
#                entry deleted outright, not merely reworded back to a false
#                claim), OR if check_lock_caveat_pointers finds any of five
#                rot paths on the single-source lock-state caveat: either
#                content/rules/conventions.md or content/sections/11-worktree-
#                lifecycle.md no longer naming `bin/ds-cleanup-worktrees` in
#                its pointer (a pointer that loses its PATH still reads fine
#                to a human, which is why the path is part of the pinned
#                literal); either pointer deleted outright; either pointer
#                surviving verbatim but orphaned from that file's own lock
#                prose, whether by being re-homed, duplicated, or by that
#                prose being deleted out from under it - EVERY line carrying
#                the pointer must also carry that prose (each anchor is lock
#                prose, never
#                a paragraph label - a label-based anchor stayed green when
#                the lock sentence was deleted); or bin/ds-cleanup-
#                worktrees missing its "Locked handling:" note or the caveat
#                sentence, which would leave both pointers aimed at nothing.
#                The caveat is pinned as a WHOLE sentence, opening plus
#                trailing clause, so rewriting only the trailing clause back
#                to a lock-released-on-agent-completion cause reddens it too;
#                it is matched whitespace-normalized, so re-wrapping the
#                docstring paragraph does not. Cleans up its scratch repo on
#                exit via a trap regardless of outcome.
#
# Performance: sub-second; two `git worktree add`/`remove` calls in a
#              throwaway repo, plus several grep passes over the doc/bin
#              files named above.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLEANUP_DOC="$REPO_ROOT/content/commands/ds-cleanup-worktrees.md"
LIFECYCLE_DOC="$REPO_ROOT/content/references/worktree-lifecycle.md"
CLEANUP_BIN="$REPO_ROOT/bin/ds-cleanup-worktrees"
SESSION_START_WRAP="$REPO_ROOT/hooks/session-start-wrap.sh"
CONVENTIONS_DOC="$REPO_ROOT/content/rules/conventions.md"
SECTION_DOC="$REPO_ROOT/content/sections/11-worktree-lifecycle.md"
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
#
# Round-4 Minor 5: unlike check_manifest_reconciliation below (whose
# assertions are DERIVED from whether the invocation exists, so a
# legitimate future removal of the feature flips the expected claim
# instead of reddening the suite), this guard is DELIBERATELY
# unconditional - the entire point of "wiring" assertion is that the
# auto-reap invocation and its kill-switch guard must exist, not merely
# that other prose agree about whether they exist. A future, deliberate
# removal of the DS-196 automatic session-start reap feature must edit
# THIS function (delete or gate its `grep -qF` assertions - re-derive the
# current count from the function body, don't hand-pin a number here) in
# the same commit that removes the invocation from worktree-lifecycle.md -
# that is the expected, correct failure mode, not a defect in this guard.
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
  if ! grep -qF '>> "$REPO_ROOT/.agentic/worktree-reap.log" 2>&1 || true ) >>"$REPO_ROOT/.agentic/worktree-reap.log" 2>&1 &' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc's session-start reap invocation is not backgrounded with its own fds redirected to the log (missing the trailing ') >>\"\$REPO_ROOT/.agentic/worktree-reap.log\" 2>&1 &' subshell form)" >&2
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

# Round-3 Minor 1/2 regression guard, corrected round-4 (Minor 4): neither
# the operator-facing --activity-window-hours=0 NOTE nor the module
# docstring's --activity-window-hours entry may re-drift back to any of
# three now-disproven claims: (1) that passing 0 "lifts this specific
# floor" outright (it does not: the None branch still fails CLOSED at 0,
# same as any other window value); (2) that "`None < 0` is never true
# either way" (a real `None < 0` comparison raises TypeError in Python 3 -
# the real mechanism is the `is None` check short-circuiting the `or`
# before `<` ever runs); (3) the round-3 replacement claim that "no
# non-None activity reading is ever recent enough to skip" at window 0 (a
# NEGATIVE reading - e.g. a future-mtime file - is non-None and still
# skips at 0, since `activity_hours < 0` is True for it; empirically
# verified against a future-mtime fixture during the round-4 fix). Rather
# than restate claim (3) a fourth time, the fix deletes it outright (see
# the round-4 fix commit); this guard only requires its absence, plus the
# continued presence of the true `None`-branch/TypeError mechanism text.
check_activity_window_prose() {
  local ok=0

  if grep -qF 'Pass --activity-window-hours 0 to lift this specific' "$CLEANUP_BIN"; then
    echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN still carries the stale 'lift this specific floor' claim for --activity-window-hours 0" >&2
    ok=1
  fi
  if grep -qF 'no non-None activity reading is ever recent enough' "$CLEANUP_BIN"; then
    echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN still carries the false 'no non-None activity reading is ever recent enough to skip' claim (a negative/future-mtime reading is non-None and still skips at window 0)" >&2
    ok=1
  fi
  if grep -qF 'narrow this floor to' "$CLEANUP_BIN" || grep -qF 'narrow the window to' "$CLEANUP_BIN"; then
    echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN still carries a 'narrow ... to' framing of the disproven --activity-window-hours 0 claim" >&2
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

# Lock-caveat pointer check. content/rules/conventions.md and
# content/sections/11-worktree-lifecycle.md each defer to the single
# canonical caveat on what a worktree's lock state proves, which lives in
# bin/ds-cleanup-worktrees' "Locked handling:" module-docstring note. Five
# ways this can rot, all pinned positively (fail-loud) here:
#   (a) either pointer loses the target PATH, leaving "see the Locked
#       handling note" with no file named - the pointer still reads fine to
#       a human, and a pin omitting the path would stay green;
#   (b) either pointer is deleted outright;
#   (c) either pointer survives verbatim but is orphaned from the lock prose
#       it qualifies - re-homed elsewhere in the file, or left in place
#       while the lock prose itself is deleted out from under it, or
#       duplicated so that a co-located copy masks an orphaned one. Guarded
#       by requiring EVERY line carrying the pointer to also carry that
#       file's own lock prose, which in both files is a single line - an
#       any-line test would pass while an orphaned duplicate sat at EOF.
#       Each anchor must be
#       LOCK PROSE, never a section or paragraph label: an earlier revision
#       anchored CONVENTIONS_DOC on the bold "Multi-session support:" label,
#       which left the check green when the lock sentence was deleted and
#       only the label and the pointer remained;
#   (d) the caveat itself is deleted from bin/ds-cleanup-worktrees, which
#       would leave both pointers aimed at nothing;
#   (e) the caveat keeps its pinned opening clause but has its trailing
#       clause rewritten to reassert the false "the harness releases the
#       lock once an agent finishes a TURN" cause. Guarded by pinning the
#       WHOLE sentence, opening and trailing clause together, rather than
#       the memorable opening alone.
# The caveat is matched against a whitespace-normalized read, so a pure
# re-wrap of that docstring paragraph does not redden the check. No pin
# here is placed on a deleted string: a negative pin would go permanently
# and silently green once the wording it forbids is gone.
check_lock_caveat_pointers() {
  local ok=0
  local pointer='the `Locked handling:` note in `bin/ds-cleanup-worktrees`'
  local caveat='Absence of a lock does NOT prove a worktree is abandoned - a session can be resumed into an unlocked, clean worktree later'

  local pair doc anchor
  for pair in \
    "$CONVENTIONS_DOC"'|Claude Code locks (`git worktree lock`) each isolation worktree' \
    "$SECTION_DOC"'|Claude Code locks each isolation worktree'; do
    doc="${pair%%|*}"
    anchor="${pair#*|}"
    if [ ! -f "$doc" ]; then
      echo "PROSE-WIRING VIOLATION: $doc not found" >&2
      ok=1
      continue
    fi
    local total anchored
    total=$(grep -cF "$pointer" "$doc")
    anchored=$(grep -F "$pointer" "$doc" | grep -cF "$anchor")
    if [ "$total" -eq 0 ]; then
      echo "PROSE-WIRING VIOLATION: $doc does not point at the canonical lock caveat by path (expected the literal '$pointer')" >&2
      ok=1
    elif [ "$anchored" -ne "$total" ]; then
      echo "PROSE-WIRING VIOLATION: $doc carries the lock-caveat pointer on $total line(s) but only $anchored of them also carry the lock prose it qualifies (expected every such line to carry '$anchor') - a pointer not co-located with that prose qualifies nothing, whether it was re-homed or duplicated" >&2
      ok=1
    fi
  done

  if ! grep -qF 'Locked handling:' "$CLEANUP_BIN"; then
    echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN has no 'Locked handling:' note - both pointers above now aim at nothing" >&2
    ok=1
  fi
  if ! tr '\n' ' ' < "$CLEANUP_BIN" | tr -s ' ' | grep -qF "$caveat"; then
    echo "PROSE-WIRING VIOLATION: $CLEANUP_BIN is missing the canonical caveat sentence in full ('$caveat') - note the WHOLE sentence is pinned, so rewriting only its trailing clause (e.g. back to a lock-released-on-agent-completion cause) reddens this too" >&2
    ok=1
  fi

  return "$ok"
}

echo "== Lock-caveat pointer check: $CONVENTIONS_DOC and $SECTION_DOC point at $CLEANUP_BIN's Locked handling note, and that note still exists =="
check_lock_caveat_pointers
r0e=$?
echo "lock-caveat-pointers exit=$r0e"

echo "== Activity-window prose check: $CLEANUP_BIN's --activity-window-hours 0 NOTE and module docstring state the real mechanism =="
check_activity_window_prose
r0d=$?
echo "activity-window-prose exit=$r0d"

# DS-245 caller-enumeration pin. The soundness of DS-245's whole argument -
# that demoting `--min-age-hours` to explicit-supply widens no UNATTENDED
# caller's removal set - is a property of the CALLER SET, not of the gate
# order. Two successive plan-review rounds each found one caller the prior
# round had assumed attended (`--archive-unproven`, then `/ds-wrap` Step 5),
# which is precisely the failure this pin exists to stop recurring silently.
#
# Three assertions:
#   (iii) the set of MUTATING invocations under content/, hooks/, bin/ and
#         scripts/ EQUALS a pinned two-element allowlist. An equality, never
#         a containment: a NEW mutating caller appearing anywhere under those
#         paths reddens this, which is the whole point - it cannot land
#         without someone deciding whether it is attended and, if not,
#         giving it a floor.
#   (iv)  the session-start reap's own continuation block carries
#         `--min-age-hours 24`, and `/ds-cleanup-worktrees` Step 2's shell
#         block carries the `DS_CLEANUP_MIN_AGE_HOURS` passthrough.
#   (v)   `content/commands/ds-wrap.md` sets `DS_CLEANUP_MIN_AGE_HOURS=24`
#         for Step 5, the unattended caller that routes through Step 2.
#
# The reduction to "mutating invocation" is mechanical and its three
# exclusions are deliberate, each stated in the Python below: the tool's own
# file (a tool is not its own caller, and its `--help`/Public-API blocks
# spell usage lines that are documentation, not invocations), the two test
# directories (a scratch-fixture invocation is not an operational caller,
# and THIS file's own pinned literals live there), and non-executable
# context (markdown prose outside a shell fence is a suggestion, per the
# same rule that makes `content/commands/ds-wrap.md:722` assertion (v)'s
# business rather than assertion (iii)'s; shell/python comment lines are
# likewise not invocations).
#
# Reddening mutations, all three EXECUTED during development:
#   - delete `--min-age-hours 24` from the reap block          -> fires (iv)
#   - delete `DS_CLEANUP_MIN_AGE_HOURS=24` from ds-wrap.md     -> fires (v)
#   - add any new mutating invocation under the swept paths    -> fires (iii)
check_unattended_callers_carry_floor() {
  python3 - "$REPO_ROOT" <<'PYEOF'
import re
import subprocess
import sys

repo_root = sys.argv[1]

# The step-9a enumeration pattern, verbatim.
PATTERN = (
    r'(^|[^A-Za-z0-9_./-])(ds-cleanup-worktrees|/ds-cleanup-worktrees|DS_CLEANUP_BIN)'
    r'([^A-Za-z0-9_.-]|$)'
)
PATHS = ["content", "hooks", "bin", "scripts"]

# See this function's shell-side comment for why each exclusion is sound.
EXCLUDED_PREFIXES = (
    "bin/ds-cleanup-worktrees",  # the tool itself is not one of its callers
    "bin/tests/",                # scratch-fixture runs; this file's own pins
    "hooks/tests/",              # same
)

# An invocation passes the tool at least one flag. `command -v <tool>` is a
# probe, not an invocation (step 9a says so explicitly).
INVOCATION_RE = re.compile(
    r'(?:"?\$\{?DS_CLEANUP_BIN\}?"?|(?<![A-Za-z0-9_./-])ds-cleanup-worktrees)\s+-'
)
PROBE_RE = re.compile(r'command\s+-v\s+ds-cleanup-worktrees')
NON_MUTATING_FLAGS = ("--count-only", "--report", "--dry-run")
SHELL_INFO = ("bash", "sh", "shell", "zsh")

# (iii) The allowlist, as (path, the literal the invocation must contain).
ALLOWLIST = {
    "content/references/worktree-lifecycle.md",   # session-start reap (unattended)
    "content/commands/ds-cleanup-worktrees.md",   # Step 2 (attended; honours the env var)
}

violations = []


def run_grep():
    proc = subprocess.run(
        ["git", "-C", repo_root, "grep", "-n", "-E", PATTERN, "--"] + PATHS,
        capture_output=True,
        text=True,
    )
    # `git grep` exits 1 on zero matches - which here means the enumeration
    # itself broke, never a clean result. Fail loudly rather than reporting
    # an empty mutating set as agreement with an empty allowlist.
    if proc.returncode not in (0, 1):
        violations.append(
            "CALLER-ENUMERATION VIOLATION: the step-9a git grep failed (rc=%d): %s"
            % (proc.returncode, proc.stderr.strip())
        )
        return []
    if not proc.stdout.strip():
        violations.append(
            "CALLER-ENUMERATION VIOLATION: the step-9a git grep matched NOTHING - "
            "the pattern or the swept paths have drifted, so this check would "
            "otherwise pass having asserted nothing"
        )
        return []
    return proc.stdout.splitlines()


def executable_lines(path):
    """Line numbers of `path` that are executable shell, comments removed.

    For markdown that is the inside of a bash/sh/shell/zsh fence and nothing
    else; for every other file it is every non-comment line.
    """
    with open("%s/%s" % (repo_root, path), encoding="utf-8", errors="replace") as fh:
        text = fh.read().splitlines()
    ok = set()
    if path.endswith(".md"):
        in_fence = False
        for i, raw in enumerate(text, 1):
            stripped = raw.strip()
            if stripped.startswith("```"):
                if in_fence:
                    in_fence = False
                else:
                    info = stripped[3:].strip().split()
                    in_fence = bool(info) and info[0] in SHELL_INFO
                continue
            if in_fence and not stripped.startswith("#"):
                ok.add(i)
    else:
        for i, raw in enumerate(text, 1):
            if not raw.strip().startswith("#"):
                ok.add(i)
    return ok, text


hits = {}
for line in run_grep():
    path, lineno, _rest = line.split(":", 2)
    hits.setdefault(path, set()).add(int(lineno))

mutating = []
for path in sorted(hits):
    if path.startswith(EXCLUDED_PREFIXES):
        continue
    ok, text = executable_lines(path)
    for lineno in sorted(hits[path]):
        if lineno not in ok:
            continue
        raw = text[lineno - 1]
        if PROBE_RE.search(raw) or not INVOCATION_RE.search(raw):
            continue
        if any(flag in raw for flag in NON_MUTATING_FLAGS):
            continue
        mutating.append((path, lineno, raw, text))

# (iii) SET EQUALITY, both directions reported separately so a reader can
# tell "a new caller appeared" from "a pinned caller vanished".
found = set(path for path, _l, _r, _t in mutating)
for extra in sorted(found - ALLOWLIST):
    violations.append(
        "CALLER-ENUMERATION VIOLATION: %s carries a MUTATING ds-cleanup-worktrees "
        "invocation that is not on the DS-245 allowlist. Classify it attended or "
        "unattended (see bin/ds-cleanup-worktrees' Callers note); if unattended it "
        "must supply --min-age-hours, and either way this allowlist must be updated "
        "in the same commit." % extra
    )
for missing in sorted(ALLOWLIST - found):
    violations.append(
        "CALLER-ENUMERATION VIOLATION: %s no longer carries a mutating "
        "ds-cleanup-worktrees invocation - if that removal is deliberate, drop it "
        "from this check's ALLOWLIST in the same commit." % missing
    )

# (iv) The reap's own continuation block, and Step 2's own shell block.
for path, lineno, raw, text in mutating:
    if path == "content/references/worktree-lifecycle.md":
        block = [raw]
        i = lineno - 1
        while block[-1].rstrip().endswith("\\") and i < len(text):
            block.append(text[i])
            i += 1
        if "--min-age-hours 24" not in "\n".join(block):
            violations.append(
                "CALLER-ENUMERATION VIOLATION: the session-start reap invocation at "
                "%s:%d does not pass `--min-age-hours 24`. That reap is UNATTENDED "
                "(backgrounded, output to a log, 30-min idle re-fire) and the age "
                "floor is off unless supplied, so dropping the flag widens what an "
                "unattended destructive pass removes." % (path, lineno)
            )
    if path == "content/commands/ds-cleanup-worktrees.md":
        start = lineno
        while start > 1 and not text[start - 1].strip().startswith("```"):
            start -= 1
        end = lineno
        while end < len(text) and not text[end - 1].strip().startswith("```"):
            end += 1
        if "DS_CLEANUP_MIN_AGE_HOURS" not in "\n".join(text[start - 1:end]):
            violations.append(
                "CALLER-ENUMERATION VIOLATION: %s's Step 2 shell block no longer "
                "reads DS_CLEANUP_MIN_AGE_HOURS - an unattended caller routing "
                "through Step 2 (/ds-wrap Step 5) then has no way to supply the "
                "age floor at all." % path
            )

# (v) /ds-wrap Step 5 sets the variable Step 2 passes through.
with open("%s/content/commands/ds-wrap.md" % repo_root, encoding="utf-8") as fh:
    wrap = fh.read()
if "DS_CLEANUP_MIN_AGE_HOURS=24" not in wrap:
    violations.append(
        "CALLER-ENUMERATION VIOLATION: content/commands/ds-wrap.md does not set "
        "DS_CLEANUP_MIN_AGE_HOURS=24 for Step 5. A wrap is UNATTENDED under the "
        "Callers note's predicate (one step of a longer automated flow), so Step 5 "
        "must supply the floor Step 2 otherwise omits."
    )

for v in violations:
    print(v, file=sys.stderr)
sys.exit(1 if violations else 0)
PYEOF
}

echo "== Caller-enumeration check: every mutating ds-cleanup-worktrees invocation is on the DS-245 allowlist, and every unattended one supplies the age floor =="
check_unattended_callers_carry_floor
r0f=$?
echo "unattended-callers exit=$r0f"

# DS-245 regression pin, found by execution during implementation. Step 2's
# DS_CLEANUP_MIN_AGE_HOURS passthrough must pass ZERO extra arguments when
# the variable is unset or empty. The obvious `set -u` guard for an empty
# bash array, `"${ARR[@]-}"`, expands to ONE EMPTY WORD under bash 3.2.57
# and bash 5.3.9 alike - and `ds-cleanup-worktrees` rejects an empty
# positional with "positional root arguments require --multi-repo" and
# exit 2, which would break the DEFAULT attended operator run. This check
# EXECUTES the block's own construct against a stub that reports its argc,
# rather than pattern-matching the expansion's spelling: a spelling pin
# would pass for any construct that merely looks right.
#
# Reddening mutation (EXECUTED): change the block's expansion back to
# `"${DS_CLEANUP_AGE_ARGS[@]-}"` - the unset leg reports argc=3.
check_step2_age_passthrough_argv() {
  local ok=0
  local block
  # Extract the fenced shell block that actually carries the passthrough,
  # so this runs the shipped text rather than a copy that can drift.
  block="$(python3 - "$CLEANUP_DOC" <<'PYEOF'
import sys

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
start = end = None
in_fence = False
fence_start = None
for i, raw in enumerate(lines):
    if raw.strip().startswith("```"):
        if in_fence:
            if start is not None and end is None:
                end = i
            in_fence = False
        else:
            in_fence = True
            fence_start = i
        continue
    if in_fence and "DS_CLEANUP_AGE_ARGS" in raw and start is None:
        start = fence_start
print("\n".join(lines[start + 1:end]) if start is not None and end is not None else "")
PYEOF
)"

  if [ -z "$block" ]; then
    echo "STEP2-ARGV VIOLATION: could not locate the Step 2 shell block carrying DS_CLEANUP_AGE_ARGS in $CLEANUP_DOC" >&2
    return 1
  fi
  if ! printf '%s' "$block" | grep -qF 'DS_CLEANUP_AGE_ARGS'; then
    echo "STEP2-ARGV VIOLATION: extracted block does not carry DS_CLEANUP_AGE_ARGS - the extractor has drifted" >&2
    return 1
  fi

  local stub_dir stub
  stub_dir="$(mktemp -d)"
  stub="$stub_dir/ds-cleanup-worktrees"
  cat > "$stub" <<'STUBEOF'
#!/bin/sh
printf 'ARGC=%s\n' "$#"
STUBEOF
  chmod +x "$stub"

  # Replay the block with DS_CLEANUP_BIN bound to the stub, under `set -u`,
  # for each of the three cases. REPO_DIR is unset so the block's own
  # resolution falls through to the PATH probe, which finds the stub.
  local case_label expected out argc
  for case_label in unset:2 empty:2 set:4; do
    expected="${case_label#*:}"
    out="$(
      PATH="$stub_dir:$PATH"
      unset REPO_DIR DS_CLEANUP_MIN_AGE_HOURS
      case "${case_label%%:*}" in
        empty) DS_CLEANUP_MIN_AGE_HOURS="" ;;
        set) DS_CLEANUP_MIN_AGE_HOURS=24 ;;
      esac
      export DS_CLEANUP_MIN_AGE_HOURS 2>/dev/null || true
      set -u
      eval "$block" 2>/dev/null
    )"
    argc="$(printf '%s\n' "$out" | sed -n 's/^ARGC=//p' | head -1)"
    if [ "$argc" != "$expected" ]; then
      echo "STEP2-ARGV VIOLATION: with DS_CLEANUP_MIN_AGE_HOURS ${case_label%%:*}, Step 2 passed argc=${argc:-<none>}, expected $expected. An empty-array expansion that yields one EMPTY word makes ds-cleanup-worktrees exit 2 ('positional root arguments require --multi-repo') on the default attended run - use \${ARR[@]+\"\${ARR[@]}\"}, never \"\${ARR[@]-}\"." >&2
      ok=1
    fi
  done

  rm -rf "$stub_dir" 2>/dev/null || true
  return "$ok"
}

echo "== Step 2 argv check: the DS_CLEANUP_MIN_AGE_HOURS passthrough passes zero extra args when unset/empty =="
check_step2_age_passthrough_argv
r0g=$?
echo "step2-argv exit=$r0g"

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

echo "Exit codes observed: prose-wiring=$r0 reap-wiring=$r0b manifest-reconciliation=$r0c activity-window-prose=$r0d lock-caveat-pointers=$r0e unattended-callers=$r0f step2-argv=$r0g run1=$r1 run2=$r2 run3=$r3"
if [ "$r0" = "0" ] && [ "$r0b" = "0" ] && [ "$r0c" = "0" ] && [ "$r0d" = "0" ] && [ "$r0e" = "0" ] && [ "$r0f" = "0" ] && [ "$r0g" = "0" ] && [ "$r1" = "0" ] && [ "$r2" = "1" ] && [ "$r3" = "1" ]; then
  echo "PASS: prose-wiring check clean, reap-wiring check clean, manifest-reconciliation check clean, activity-window-prose check clean, lock-caveat-pointers check clean, unattended-callers check clean, step2-argv check clean, and two distinct exit codes across three runs (0, 1, 1)"
  exit 0
fi

echo "FAIL: expected prose-wiring=0, reap-wiring=0, manifest-reconciliation=0, activity-window-prose=0, lock-caveat-pointers=0, unattended-callers=0, step2-argv=0, and run exit codes 0 1 1, got prose-wiring=$r0 reap-wiring=$r0b manifest-reconciliation=$r0c activity-window-prose=$r0d lock-caveat-pointers=$r0e unattended-callers=$r0f step2-argv=$r0g $r1 $r2 $r3"
exit 1
