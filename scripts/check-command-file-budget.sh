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
# Public API: bash scripts/check-command-file-budget.sh
#             Exits 0 when file bytes <= THRESHOLD_BYTES. Exits 1 when over
#             budget (also emitting a `::error::` workflow-command line so
#             the overage surfaces as a GitHub Actions annotation, not just
#             job-log text), or when the input file is missing.
#
# Upstream deps: content/commands/ds-implement-ticket.md;
#                scripts/lib/budget-gate.sh (shared repo-dir resolution,
#                byte measurement, and OK/OVER-BUDGET report shape - see
#                that file for the two sibling gates it also backs).
#
# Downstream consumers: .github/workflows/command-file-budget.yml. That
#                        job is advisory ONLY because it is deliberately
#                        NOT added to the `main` ruleset's required-checks
#                        list - promotion is a separate operator decision.
#                        The job itself fails (goes red, with a
#                        `::error::` annotation) on overage like any other
#                        check; it does not swallow its own exit code.
#
# Failure modes: over budget -> exit 1 with byte count, THRESHOLD_BYTES,
#                and overage printed to stderr plus a `::error::`
#                annotation line. Missing input file -> exit 1. Read-only;
#                no side effects on the repo.
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
THRESHOLD_BYTES=371000

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

remediation="content/commands/ds-implement-ticket.md grew past its budget.
Trim content or, if the growth is deliberate and justified, raise
THRESHOLD_BYTES in scripts/check-command-file-budget.sh in the same PR."

budget_report \
  "command file budget check" \
  "ds-implement-ticket.md" \
  "$file_bytes" \
  "$THRESHOLD_BYTES" \
  "$remediation"
