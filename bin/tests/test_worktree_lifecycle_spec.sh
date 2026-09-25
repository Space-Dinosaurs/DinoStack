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
#                "Locked handling:" lock-state caveat;
#                content/** in full (EVERY file under it, grepped
#                whitespace-normalized by check_process_lifetime_prose) plus,
#                via LIFETIME_EXTRA_SITES, the two shipped-prose sites outside
#                content/ that restate the rule - .claude/install.sh and
#                .claude/README.md, each existence-checked - plus
#                content/references/qa-gate.md,
#                content/references/code-standards-detail.md,
#                content/agents/engineer.md and
#                content/agents/qa-engineer.md (the four points of use, each
#                asserted to still carry a §section pointer at the canonical
#                rule).
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
#                       trailing clause rewritten;
#                       check_process_lifetime_prose guards the DS-254
#                       process-lifetime repair in both directions (rubric
#                       R5) - the canonical section plus its four pointers
#                       present, and every retired claim absent from all of
#                       content/, so a regenerated adapter cannot resurrect
#                       one.
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
#                exit via a trap regardless of outcome, OR if
#                check_process_lifetime_prose finds
#                content/references/worktree-lifecycle.md missing its
#                "## Agent-spawned process lifetime ownership" heading, OR
#                one of the four points of use missing either its
#                §pointer or the path it points at, OR any of the retired
#                claims - "Dev-server process lifetime ownership",
#                "will not survive", "run-scoped only", "survive the
#                agent's run on this harness", "lingers (visibly)",
#                "browser lingers open", "nothing here bounds how long it
#                stays up", "keeps holding its profile, which is what
#                blocks the next run", "the one thing that ends a session",
#                "stays open, holding its profile" - still present in ANY
#                file under content/ or at any LIFETIME_EXTRA_SITES path. OR
#                a LIFETIME_EXTRA_SITES path that no longer exists, OR a
#                flatten_prose that fails on a swept file (an empty haystack
#                would make every phrase below read as absent, so this check
#                would pass having compared nothing). Matched
#                whitespace-normalized with any leading comment marker
#                stripped, so a phrase re-wrapped across two source lines is
#                still caught in a shell file as well as in prose; matched as
#                literal prefixes, never whole sentences, so rewording the
#                surrounding prose does not redden it.
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

# DS-254 R5: the canonical title the one process-lifetime rule lives under, and
# the title it replaced. The retired title is swept for as well, because a
# pointer at a section that no longer exists reads as a live cross-reference
# and resolves to nothing.
CANONICAL_LIFETIME_TITLE='Agent-spawned process lifetime ownership'
RETIRED_LIFETIME_TITLE='Dev-server process lifetime ownership'

# The four files that restate the rule at its points of use. Each must keep a
# pointer back at the canonical section; the restatement text around it is free
# to change, the pointer is not.
LIFETIME_POINTER_FILES="content/agents/engineer.md
content/agents/qa-engineer.md
content/references/qa-gate.md
content/references/code-standards-detail.md"

# Shipped prose that restates the rule outside content/, so the absence sweep
# below covers the sites the rule is actually written at rather than only its
# home directory. Explicit rather than derived: each path is existence-checked
# in the sweep, because a path that silently stops resolving drops a site from
# the sweep and reads as clean. docs/ is deliberately NOT here - its copies are
# public-facing restatements this list has never covered, and adding a surface
# to it is a decision, not a side effect of retiring one claim.
LIFETIME_EXTRA_SITES=".claude/install.sh
.claude/README.md"

# Claims measured false against the shipped mechanism (the process reparents to
# launchd and outlives the agent's run), plus the retired section title. This is
# a denylist: it can only catch a phrasing someone already added here, so a
# claim a later fix falsifies stays invisible to it unless that fix adds the old
# wording in the same commit, and a paraphrase of an entry escapes the pin.
RETIRED_LIFETIME_CLAIMS="$RETIRED_LIFETIME_TITLE
will not survive
run-scoped only
survive the agent's run on this harness
lingers (visibly)
browser lingers open
nothing here bounds how long it stays up
keeps holding its profile, which is what blocks the next run
the one thing that ends a session
stays open, holding its profile"

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

# Whitespace-normalized read of a file, for phrase sweeps that must not be
# defeated by a hard wrap. A line-based `grep -F` silently misses a phrase split
# across two source lines - which is how the retired section title survived the
# DS-254 rename inside worktree-lifecycle.md's own manifest block, where it is
# wrapped as "...the Dev-server process" / "lifetime ownership section".
#
# The leading comment marker is stripped first for the same reason. In a shell
# file every wrapped prose line carries one, so a phrase spanning two lines comes
# out of a bare newline collapse with the next line's "#" embedded mid-phrase and
# can never match - measured on .claude/install.sh, where an entry spanning
# "which is" / "what blocks the next run" flattened to "which is # what blocks
# the next run". A denylist entry longer than one source line was therefore
# unfireable at exactly the sites this sweep now reads.
flatten_prose() {
  sed -E 's/^[[:space:]]*(#|\/\/)[[:space:]]?//' "$1" | tr '\n' ' ' | tr -s '[:space:]' ' '
}

# DS-254 R5 regression guard, asserted in BOTH directions deliberately: a
# negative-only assertion ("$RETIRED_LIFETIME_TITLE is gone") goes silently green
# the moment the wording changes, which is the defect class the DS-254 plan's M1
# was itself scoped into. The absence sweep covers every file under content/,
# not only the four the U5 edit touched - a falsified claim left behind in a file
# outside the edit still ships, and that is precisely how M1 arose. Both sides
# are pinned as stable structural prefixes (the section heading, the section
# pointer), never as whole sentences, so a legitimate rewording of the prose
# around either one does not redden this.
check_process_lifetime_prose() {
  local ok=0
  local tool

  # This repo's rule for a shell gate that would otherwise guard its assertions
  # on `command -v <tool>` is to hard-fail under ${CI} rather than skip, or the
  # job goes green having asserted nothing. Here the tools are load-bearing, so
  # there is no skip path at all, in CI or out of it.
  for tool in find grep tr sed; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "PROCESS-LIFETIME VIOLATION: required tool '$tool' is not on PATH, so no verdict is available (CI=${CI:-unset}) - refusing to report a pass" >&2
      ok=1
    fi
  done
  [ "$ok" -eq 0 ] || return 1

  # Positive 1: the canonical rule exists, under the canonical title.
  if ! grep -qF "## $CANONICAL_LIFETIME_TITLE" "$LIFECYCLE_DOC"; then
    echo "PROCESS-LIFETIME VIOLATION: $LIFECYCLE_DOC has no '## $CANONICAL_LIFETIME_TITLE' heading - the canonical rule was renamed or deleted" >&2
    ok=1
  fi

  # Positive 2: each point of use still carries a followable pointer at it.
  local rel
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    if [ ! -f "$REPO_ROOT/$rel" ]; then
      echo "PROCESS-LIFETIME VIOLATION: $rel not found - it is one of the files that restates the process-lifetime rule" >&2
      ok=1
      continue
    fi
    if ! grep -qF "§$CANONICAL_LIFETIME_TITLE" "$REPO_ROOT/$rel"; then
      echo "PROCESS-LIFETIME VIOLATION: $rel no longer carries a '§$CANONICAL_LIFETIME_TITLE' pointer at the canonical rule" >&2
      ok=1
    fi
    if ! grep -qF 'content/references/worktree-lifecycle.md' "$REPO_ROOT/$rel"; then
      echo "PROCESS-LIFETIME VIOLATION: $rel's pointer no longer names its target file (content/references/worktree-lifecycle.md), so it cannot be followed" >&2
      ok=1
    fi
  done <<< "$LIFETIME_POINTER_FILES"

  # Negative: no retired claim survives anywhere under content/, nor at any of
  # the extra shipped-prose sites the rule is restated at.
  local content_files extra
  content_files="$(find "$REPO_ROOT/content" -type f 2>/dev/null)"
  if [ -z "$content_files" ]; then
    echo "PROCESS-LIFETIME VIOLATION: find matched no files under content/ - the absence sweep would assert nothing, so this is broken discovery, not a clean result" >&2
    return 1
  fi

  # A listed site that is not there is a dropped site, not a clean one: the
  # sweep would pass having read nothing at that path.
  local sweep_files
  sweep_files="$content_files"
  while IFS= read -r extra; do
    [ -n "$extra" ] || continue
    if [ -f "$REPO_ROOT/$extra" ]; then
      sweep_files="$sweep_files
$REPO_ROOT/$extra"
    else
      echo "PROCESS-LIFETIME VIOLATION: $extra is listed as a restatement site but does not exist, so the absence sweep does not cover it" >&2
      ok=1
    fi
  done <<< "$LIFETIME_EXTRA_SITES"

  local f flat phrase
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    # A flatten that fails yields an empty string, and an empty haystack makes
    # every grep below report "not present" - the sweep would pass having read
    # nothing. Measured with a `sed` that exits 1: this check reported exit 0
    # while no phrase was ever compared. The pipeline status is checked rather
    # than the result's emptiness, so a file that legitimately flattens to
    # nothing is unaffected.
    if ! flat="$(flatten_prose "$f")"; then
      echo "PROCESS-LIFETIME VIOLATION: flatten_prose failed on ${f#"$REPO_ROOT"/}, so no retired claim was checked against it" >&2
      ok=1
      continue
    fi
    while IFS= read -r phrase; do
      [ -n "$phrase" ] || continue
      # Here-string, not a pipe into `grep -q`: under `set -o pipefail` an early
      # grep exit can SIGPIPE the writer and turn a match into a non-zero
      # pipeline status, which would read here as "clean".
      if grep -qF "$phrase" <<< "$flat"; then
        echo "PROCESS-LIFETIME VIOLATION: retired claim [$phrase] is still present in ${f#"$REPO_ROOT"/}" >&2
        ok=1
      fi
    done <<< "$RETIRED_LIFETIME_CLAIMS"
  done <<< "$sweep_files"

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

echo "== Process-lifetime prose check: the canonical rule is present and every retired claim is gone from content/ =="
check_process_lifetime_prose
r0h=$?
echo "process-lifetime-prose exit=$r0h"

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
# The detector itself now lives in `bin/tests/caller_scan.py`, with its own
# regression suite `bin/tests/test_caller_scan.py` (DS-245 review round 2,
# CM2-3). It was inline here for two rounds and was wrong in both, each time
# found only by a reviewer hand-injecting a shape, because nothing committed
# exercised it. Read that module for what the scan can and cannot see; this
# file asserts what the RESULT must be, not how it is computed.
#
# Three assertions:
#   (iii) the set of MUTATING invocations under content/, hooks/, bin/ and
#         scripts/ EQUALS a pinned two-element allowlist. An equality, never
#         a containment: a NEW mutating caller appearing anywhere under those
#         paths reddens this, which is the whole point - it cannot land
#         without someone deciding whether it is attended and, if not,
#         giving it a floor. Its scope is exactly what `caller_scan` can
#         see; that module states its residuals and `test_caller_scan.py`
#         pins them.
#   (iv)  the session-start reap's own continuation block carries
#         `--min-age-hours 24`, and `/ds-cleanup-worktrees` Step 2's shell
#         block reads `DS_CLEANUP_MIN_AGE_HOURS`.
#   (v)   `/ds-wrap` Step 5 both STATES that Step 2 derives the floor from
#         the wrap lock, and SITS INSIDE the lock window - i.e. ahead of the
#         Step 6 release. Round 1 wrote this as a grep for the literal
#         `DS_CLEANUP_MIN_AGE_HOURS=24`, which round 2 found vacuous: after
#         Step 5 correctly stopped exporting anything, the only remaining
#         occurrence of that literal is inside the sentence explaining it is
#         NOT the mechanism, so the assertion passed on text meaning the
#         opposite of what it claimed. Ordering is the property the floor
#         actually depends on: move the release ahead of Step 5, or move
#         Step 5 out of the window as Parts F and G already are, and the
#         floor silently disappears from the one unattended mutating caller.
#
# Reddening mutations, all EXECUTED:
#   - delete `--min-age-hours 24` from the reap block          -> fires (iv)
#   - delete Step 5's wrap-lock derivation sentence            -> fires (v)
#   - move `ds-wrap-release-lock` ahead of Step 5               -> fires (v)
#   - add any new mutating invocation under the swept paths    -> fires (iii)
check_unattended_callers_carry_floor() {
  python3 - "$REPO_ROOT" <<'PYEOF'
import os
import sys

repo_root = sys.argv[1]
sys.path.insert(0, os.path.join(repo_root, "bin", "tests"))

import caller_scan

# (iii) The allowlist: the files that may carry a mutating invocation.
ALLOWLIST = {
    # Session-start reap: unattended, pins --min-age-hours 24 at the call.
    "content/references/worktree-lifecycle.md",
    # Step 2: attended when an operator types it directly, and ALSO the
    # conduit the unattended /ds-wrap Step 5 path reaches this tool through.
    # It is therefore not simply "the attended caller" - it is where the
    # floor is applied for both, from DS_CLEANUP_MIN_AGE_HOURS or from the
    # wrap lock.
    "content/commands/ds-cleanup-worktrees.md",
}

violations = []

try:
    mutating = caller_scan.find_mutating(repo_root)
except RuntimeError as exc:
    print("CALLER-ENUMERATION VIOLATION: %s" % exc, file=sys.stderr)
    sys.exit(1)

found = set(path for path, _l, _r in mutating)
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
for path, lineno, raw in mutating:
    with open("%s/%s" % (repo_root, path), encoding="utf-8") as fh:
        text = fh.read().splitlines()
    if path == "content/references/worktree-lifecycle.md":
        block = [raw]
        i = lineno
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
                "reads DS_CLEANUP_MIN_AGE_HOURS - a caller able to set it in the "
                "same shell invocation then has no way to supply the floor." % path
            )

# (v) /ds-wrap Step 5 states the derivation AND sits inside the lock window.
WRAP = "content/commands/ds-wrap.md"
with open("%s/%s" % (repo_root, WRAP), encoding="utf-8") as fh:
    wrap_lines = fh.read().splitlines()


def _find(predicate, label):
    for idx, line in enumerate(wrap_lines, 1):
        if predicate(line):
            return idx
    violations.append(
        "CALLER-ENUMERATION VIOLATION: %s no longer contains %s, so neither the "
        "position of /ds-wrap Step 5 relative to the wrap-lock release nor the "
        "mechanism that gives it an age floor can be checked at all." % (WRAP, label)
    )
    return None


step5 = _find(lambda l: l.strip().startswith("**Step 5") and "Worktree cleanup" in l,
              "a `**Step 5 - Worktree cleanup.**` heading")
step6 = _find(lambda l: l.strip().startswith("**Step 6"), "a `**Step 6` heading")
release = _find(lambda l: "Release the pre-flight lock" in l and "ds-wrap-release-lock" in l,
                "the Step 6 `Release the pre-flight lock: run ds-wrap-release-lock` instruction")

if step5 and step6 and release:
    if not step5 < release:
        violations.append(
            "CALLER-ENUMERATION VIOLATION: %s runs `ds-wrap-release-lock` (line %d) "
            "BEFORE Step 5 (line %d). Step 2 derives the 24h floor from the presence "
            "of `<cwd>/.agentic/wrap/lock`, so releasing the lock first silently "
            "removes the floor from the one unattended mutating caller."
            % (WRAP, release, step5)
        )
    region = "\n".join(wrap_lines[step5 - 1:step6 - 1])
    if "applies the floor whenever" not in region or ".agentic/wrap/lock" not in region:
        violations.append(
            "CALLER-ENUMERATION VIOLATION: %s's Step 5 region no longer states that "
            "`/ds-cleanup-worktrees` Step 2 applies the floor whenever "
            "`<cwd>/.agentic/wrap/lock` is present. That sentence is the only "
            "operator-facing record of why this unattended caller has a floor at "
            "all, and without it the next maintainer's obvious move is to restore "
            "an exported DS_CLEANUP_MIN_AGE_HOURS, which cannot work across a tool "
            "call." % WRAP
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

# DS-245 regression pin on Step 2's argument construction. It EXECUTES the
# shipped block against a stub that reports its own argv, rather than
# pattern-matching the block's spelling: a spelling pin passes for any
# construct that merely looks right. Two separate defects are pinned here.
#
# (1) Found by execution during implementation: the block must pass ZERO
#     extra arguments when no floor applies. The obvious `set -u` guard for
#     an empty bash array, `"${ARR[@]-}"`, expands to ONE EMPTY WORD under
#     bash 3.2.57 and bash 5.3.9 alike - and `ds-cleanup-worktrees` rejects
#     an empty positional with "positional root arguments require
#     --multi-repo" and exit 2, which would break the DEFAULT attended
#     operator run.
#     Reddening mutation (EXECUTED): change the expansion back to
#     `"${DS_CLEANUP_AGE_ARGS[@]-}"` - the no-floor legs report argc 3.
#
# (2) DS-245 review round 1, CM2: the /ds-wrap Step 5 handoff. Step 5
#     reaches this block as a SEPARATE shell invocation and shell state does
#     not survive between invocations, so an exported
#     DS_CLEANUP_MIN_AGE_HOURS cannot carry the floor there. The block
#     derives it from `<cwd>/.agentic/wrap/lock` instead - a filesystem
#     fact /ds-wrap already maintains across the whole of Step 5. The
#     `wraplock` case below tests THAT handoff: the lock directory is real
#     and the environment variable is unset, which is the actual Step 5
#     condition, not the destination with the value pre-set.
#     Reddening mutation (EXECUTED): delete the `.agentic/wrap/lock` branch
#     from the block - the wraplock case drops to 2 arguments.
#
# Every case asserts the FULL argv, not just its length, so a floor applied
# with the wrong value is caught too.
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

  local stub_dir stub work
  stub_dir="$(mktemp -d)"
  work="$(mktemp -d)"
  stub="$stub_dir/ds-cleanup-worktrees"
  cat > "$stub" <<'STUBEOF'
#!/bin/sh
printf 'ARGV='; for a in "$@"; do printf '[%s]' "$a"; done; printf '\n'
STUBEOF
  chmod +x "$stub"

  local base='[--explain][--measure-size]'

  # Replay the block with DS_CLEANUP_BIN bound to the stub, under `set -u`,
  # once per case. REPO_DIR is unset so the block's own resolution falls
  # through to the PATH probe, which finds the stub. Each case runs in its
  # own scratch cwd so the wrap-lock probe reads real filesystem state.
  #
  # case := <label>:<wrap-lock present>:<env value, - for unset>:<expected argv>
  local spec label lock envval expected out argv
  for spec in \
    "unset:no:-:${base}" \
    "empty:no::${base}" \
    "set:no:24:${base}[--min-age-hours][24]" \
    "wraplock:yes:-:${base}[--min-age-hours][24]" \
    "wraplock-env-wins:yes:6:${base}[--min-age-hours][6]" \
    "spaces:no:2 4:${base}[--min-age-hours][2 4]"; do
    label="${spec%%:*}"
    local rest="${spec#*:}"
    lock="${rest%%:*}"
    rest="${rest#*:}"
    envval="${rest%%:*}"
    expected="${rest#*:}"

    rm -rf "$work/.agentic" 2>/dev/null || true
    if [ "$lock" = "yes" ]; then
      mkdir -p "$work/.agentic/wrap/lock"
    fi

    out="$(
      cd "$work" || exit 1
      PATH="$stub_dir:$PATH"
      unset REPO_DIR DS_CLEANUP_MIN_AGE_HOURS
      if [ "$envval" != "-" ]; then
        DS_CLEANUP_MIN_AGE_HOURS="$envval"
        export DS_CLEANUP_MIN_AGE_HOURS
      fi
      set -u
      eval "$block" 2>/dev/null
    )"
    argv="$(printf '%s\n' "$out" | sed -n 's/^ARGV=//p' | head -1)"
    if [ "$argv" != "$expected" ]; then
      echo "STEP2-ARGV VIOLATION: case '$label' (wrap lock: $lock, DS_CLEANUP_MIN_AGE_HOURS: $envval) produced argv ${argv:-<none>}, expected $expected." >&2
      case "$label" in
        wraplock*)
          echo "  The wrap-lock branch is what carries the floor onto /ds-wrap Step 5: that step reaches this block as a separate shell invocation, so an exported variable cannot reach it and only a filesystem fact can." >&2
          ;;
        *)
          echo "  An empty-array expansion that yields one EMPTY word makes ds-cleanup-worktrees exit 2 ('positional root arguments require --multi-repo') on the default attended run - use \${ARR[@]+\"\${ARR[@]}\"}, never \"\${ARR[@]-}\"." >&2
          ;;
      esac
      ok=1
    fi
  done

  rm -rf "$stub_dir" "$work" 2>/dev/null || true
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

echo "Exit codes observed: prose-wiring=$r0 reap-wiring=$r0b process-lifetime-prose=$r0h manifest-reconciliation=$r0c activity-window-prose=$r0d lock-caveat-pointers=$r0e unattended-callers=$r0f step2-argv=$r0g run1=$r1 run2=$r2 run3=$r3"
if [ "$r0" = "0" ] && [ "$r0b" = "0" ] && [ "$r0h" = "0" ] && [ "$r0c" = "0" ] && [ "$r0d" = "0" ] && [ "$r0e" = "0" ] && [ "$r0f" = "0" ] && [ "$r0g" = "0" ] && [ "$r1" = "0" ] && [ "$r2" = "1" ] && [ "$r3" = "1" ]; then
  echo "PASS: prose-wiring check clean, reap-wiring check clean, process-lifetime-prose check clean, manifest-reconciliation check clean, activity-window-prose check clean, lock-caveat-pointers check clean, unattended-callers check clean, step2-argv check clean, and two distinct exit codes across three runs (0, 1, 1)"
  exit 0
fi

echo "FAIL: expected prose-wiring=0, reap-wiring=0, process-lifetime-prose=0, manifest-reconciliation=0, activity-window-prose=0, lock-caveat-pointers=0, unattended-callers=0, step2-argv=0, and run exit codes 0 1 1, got prose-wiring=$r0 reap-wiring=$r0b process-lifetime-prose=$r0h manifest-reconciliation=$r0c activity-window-prose=$r0d lock-caveat-pointers=$r0e unattended-callers=$r0f step2-argv=$r0g $r1 $r2 $r3"
exit 1
