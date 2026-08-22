#!/usr/bin/env bash
# Purpose: Guard against unbounded growth of content/commands/ds-implement-
#          ticket.md. This file grew from 233,942 B to 363,761 B in about
#          two weeks with zero shrink commits, because nothing measured it -
#          scripts/check-resident-budget.sh deliberately measures only the
#          assembled resident set (content/templates/claude-managed-
#          content.md's post-manifest body), and command files sit outside
#          that set entirely. This script closes that hole for the single
#          largest command file, measured directly on disk with no build
#          step (unlike check-resident-budget.sh, which measures a derived
#          artifact).
#
#          DS-182 added a second, git-based axis alongside the original
#          absolute-size THRESHOLD_BYTES check: a per-PR DELTA_LIMIT_BYTES
#          on how much THIS branch's own history grew the file versus its
#          base ref. This file is hand-authored (a PR's diff to it is that
#          PR's own doing), unlike the generated skill-embed payload, so a
#          delta axis here is a meaningful, enforceable per-PR failure -
#          see scripts/check-skill-embed-budget.sh for why the DERIVED
#          target gets an informational burn line instead of a hard delta
#          limit.
#
# Public API: bash scripts/check-command-file-budget.sh
#             Exits 0 when file bytes <= THRESHOLD_BYTES AND the git-based
#             delta axis (see below) does not fail. Exits 1 when either
#             axis is over budget (also emitting a `::error::` workflow-
#             command line so the overage surfaces as a GitHub Actions
#             annotation, not just job-log text), or when the input file
#             is missing. The delta axis DEGRADES TO SKIPPED (never a
#             failure by itself) when git is absent, REPO_DIR is not a git
#             work tree, no base ref resolves, or the file did not exist
#             at the resolved base ref (a newly-created file has nothing
#             to diff against) - only THRESHOLD_BYTES can fail in any of
#             those cases.
#
# Upstream deps: content/commands/ds-implement-ticket.md;
#                scripts/lib/budget-gate.sh (shared repo-dir resolution,
#                byte measurement, the budget_eval OK/OVER-BUDGET report
#                shape, and the budget_base_resolve/budget_delta git-based
#                delta helpers - see that file for the two sibling gates
#                it also backs). Calls budget_eval directly (not the
#                exit-calling budget_report wrapper), since a delta breach
#                must still let the THRESHOLD_BYTES report run and print
#                before this script decides its own combined exit code -
#                see the delta_over/threshold_ok combination below and
#                Failure modes. The delta axis additionally depends on
#                `git` being on PATH and a resolvable base ref
#                (origin/main or main); see Failure modes below for what
#                happens when either is missing.
#
# Downstream consumers: .github/workflows/command-file-budget.yml (needs
#                        `fetch-depth: 0` on its checkout step so the delta
#                        axis can resolve `origin/main` - a default shallow
#                        checkout would leave that ref unreachable and the
#                        axis would silently degrade to SKIPPED on every
#                        CI run). That job is advisory ONLY because it is
#                        deliberately NOT added to the `main` ruleset's
#                        required-checks list - promotion is a separate
#                        operator decision. The job itself fails (goes red,
#                        with a `::error::` annotation) on overage on
#                        either axis like any other check; it does not
#                        swallow its own exit code.
#
# Failure modes: over THRESHOLD_BYTES -> `::error::` annotation with byte
#                count, THRESHOLD_BYTES, and overage, then the
#                budget_eval OK/OVER-BUDGET report itself (to stderr on
#                overage). Over DELTA_LIMIT_BYTES -> a message naming the
#                delta axis distinctly from THRESHOLD_BYTES, plus its own
#                `::error::` annotation, recorded via delta_over=1 rather
#                than exiting immediately - the THRESHOLD_BYTES
#                budget_eval report always still runs after it, so both
#                axes' reports are visible when both are over budget in
#                the same run. The script's own exit code is 1 whenever
#                EITHER axis failed (delta_over=1 OR the budget_eval call
#                returned non-zero), 0 only when both passed. Delta axis
#                unresolvable (no git, REPO_DIR not a work tree, no base
#                ref, or path absent at base) -> SKIPPED, printed as a
#                distinct extra-context line on the THRESHOLD_BYTES
#                report, never a failure by itself. Missing input file ->
#                exit 1. Read-only; no side effects on the repo.
#
# Compatible with both bash and zsh invocation of the containing shell; CI
# always invokes it as `bash scripts/check-command-file-budget.sh`, but a
# contributor, reviewer, or this file's own regression test may invoke it
# as `zsh scripts/check-command-file-budget.sh` and it must behave
# identically.

set -euo pipefail

# BASH_SOURCE is unset under zsh. CI always invokes this script as `bash
# scripts/check-command-file-budget.sh` (see command-file-budget.yml), but a
# contributor or reviewer may run it under zsh locally - fall back to $0 so
# SCRIPT_DIR resolves correctly under both interpreters instead of
# collapsing to "//".
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib/budget-gate.sh
source "$SCRIPT_DIR/lib/budget-gate.sh"
REPO_DIR="$(budget_repo_dir "$SCRIPT_DIR")"

# Ratchet: 363,761 B measured on this branch 2026-08-08, +~2% deliberate
# headroom (roughly 7,200 B), rounded to 371,000 B. This is meant to fire
# on sustained growth, not the next paragraph - unlike the original
# ~239 B/0.066% headroom this gate shipped with, which left effectively no
# room before the very next PR would trip it. Lower this value in the same
# commit as any deliberate compression of the file. See the header comment
# above before raising it - raising it to accommodate un-triaged growth
# defeats the purpose of this gate.
# Raised for DS-188 Phase 11b curation trigger (deliberate, triaged growth).
THRESHOLD_BYTES=373000

# Per-PR delta limit, re-derived (not hand-rounded) from git history:
# ceil(max_observed_delta * 1.1) where max_observed_delta = 29941 B, the
# largest single first-parent-commit growth of content/commands/
# ds-implement-ticket.md observed at commit d644217c5bb6ce8b1c04a
# 9cf06367d8e7dc1bca6, measured across all 43 first-parent non-creation
# commits touching that file (a "non-creation" commit is one where the
# file already existed in the commit's first parent, so a delta is
# actually computable). 29941 * 1.1 = 32935.1, ceil'd to 32936. This
# fires 0/43 on the history it was derived from - it is meant to catch a
# single PR's own outsized addition, not the ordinary editing churn this
# file already sees. Lower this value in the same commit as any
# deliberate policy tightening; re-derive rather than hand-adjusting if
# the growth pattern changes materially.
#
# Re-derivation command (run from the repo root; reproduces
# max_observed_delta=29941 at d644217c5bb6ce8b1c04a9cf06367d8e7dc1bca6 on
# the history it was derived from - re-run to pick up new commits before
# raising or lowering this constant):
#
#   git log --first-parent --format=%H \
#     -- content/commands/ds-implement-ticket.md \
#   | while read -r sha; do
#       parent=$(git rev-parse "$sha^" 2>/dev/null) || continue
#       before=$(git cat-file -s \
#         "${parent}:content/commands/ds-implement-ticket.md" 2>/dev/null) \
#         || continue
#       after=$(git cat-file -s \
#         "${sha}:content/commands/ds-implement-ticket.md" 2>/dev/null) \
#         || continue
#       echo "$sha $(( after - before ))"
#     done | sort -k2 -n | tail -1
#
# The `${parent}:`/`${sha}:` braces above are load-bearing, not style: an
# unbraced `$parent:content/...` is parsed as a zsh history-expansion
# modifier (`:c...`), which silently mangles the ref into a bogus object
# name and makes every iteration of this loop fail its `|| continue` -
# the command then prints nothing instead of erroring, under zsh (this
# repo's default shell) specifically. Verified: unbraced reproducibly
# yields a `fatal: Not a valid object name` on the mangled ref under zsh;
# braced reproduces the documented max_observed_delta=29941 under both
# bash and zsh.
DELTA_LIMIT_BYTES=32936

TARGET_FILE="$REPO_DIR/content/commands/ds-implement-ticket.md"

if [ ! -f "$TARGET_FILE" ]; then
  echo "check-command-file-budget.sh: missing file: $TARGET_FILE" >&2
  exit 1
fi

file_bytes="$(budget_file_bytes "$TARGET_FILE")"

if [ "$file_bytes" -gt "$THRESHOLD_BYTES" ]; then
  overage=$(( file_bytes - THRESHOLD_BYTES ))
  echo "::error::content/commands/ds-implement-ticket.md is $file_bytes B, over the $THRESHOLD_BYTES B budget by $overage B" >&2
fi

# Per-PR delta axis: degrades to SKIPPED (never a failure) when git is
# absent, REPO_DIR is not a work tree, no base ref resolves, or the file
# did not exist at the resolved base ref - see scripts/lib/budget-gate.sh
# for the full contract of budget_base_resolve/budget_delta. A delta
# breach is recorded (delta_over=1) rather than exiting immediately here,
# so the THRESHOLD_BYTES report below still runs and prints even when
# both axes are over budget in the same run - the operator sees both
# reports, not just whichever axis happened to be checked first.
base_ref="$(budget_base_resolve "$REPO_DIR")" || base_ref=""

delta_line=""
delta_over=0
if [ -n "$base_ref" ]; then
  if delta_bytes="$(budget_delta "$REPO_DIR" "$TARGET_FILE" "$base_ref")"; then
    sign=""
    if [ "$delta_bytes" -ge 0 ]; then
      sign="+"
    fi
    delta_line="delta (vs $base_ref): ${sign}${delta_bytes} B (limit $DELTA_LIMIT_BYTES B)"
    if [ "$delta_bytes" -gt "$DELTA_LIMIT_BYTES" ]; then
      delta_over=1
      echo "::error::content/commands/ds-implement-ticket.md grew by $delta_bytes B vs $base_ref, over the $DELTA_LIMIT_BYTES B per-PR delta limit" >&2
      echo "check-command-file-budget.sh: OVER DELTA LIMIT" >&2
      echo "  delta axis (vs $base_ref): +${delta_bytes} B" >&2
      echo "  delta limit:               $DELTA_LIMIT_BYTES B" >&2
      echo "" >&2
      echo "This PR's own diff to content/commands/ds-implement-ticket.md grew" >&2
      echo "the file by more than the per-PR delta limit - distinct from the" >&2
      echo "overall THRESHOLD_BYTES ceiling, which measures total file size" >&2
      echo "regardless of which PR contributed it. Trim this PR's addition, or" >&2
      echo "if the growth is deliberate and justified, raise DELTA_LIMIT_BYTES" >&2
      echo "in scripts/check-command-file-budget.sh in the same PR." >&2
    fi
  else
    delta_line="delta (vs $base_ref): SKIPPED (absent at base)"
  fi
else
  delta_line="delta: SKIPPED (base unresolvable)"
fi

remediation="content/commands/ds-implement-ticket.md grew past its budget.
Trim content or, if the growth is deliberate and justified, raise
THRESHOLD_BYTES in scripts/check-command-file-budget.sh in the same PR."

threshold_ok=1
if budget_eval \
  "command file budget check" \
  "ds-implement-ticket.md" \
  "$file_bytes" \
  "$THRESHOLD_BYTES" \
  "$remediation" \
  "$delta_line"; then
  threshold_ok=1
else
  threshold_ok=0
fi

if [ "$delta_over" -eq 1 ] || [ "$threshold_ok" -eq 0 ]; then
  exit 1
fi
exit 0
