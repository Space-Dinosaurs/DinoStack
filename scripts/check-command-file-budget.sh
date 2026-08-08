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
#             budget, or when the input file is missing.
#
# Upstream deps: content/commands/ds-implement-ticket.md.
#
# Downstream consumers: .github/workflows/command-file-budget.yml (advisory
#                        job - surfaces overage as a warning, does not block
#                        merge; promotion to a required check on the `main`
#                        ruleset is a separate operator decision, not made by
#                        this change).
#
# Failure modes: over budget -> exit 1 with byte count, THRESHOLD_BYTES, and
#                overage printed. Missing input file -> exit 1. Read-only;
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
# REPO_DIR resolves correctly under both interpreters instead of collapsing
# to "//".
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# Ratchet: 363,761 B measured on this branch 2026-08-08, rounded up to the
# next 1,000 B. Lower this value in the same commit as any deliberate
# compression of the file. See the header comment above before raising it -
# raising it to accommodate un-triaged growth defeats the purpose of this
# gate.
THRESHOLD_BYTES=364000

TARGET_FILE="$REPO_DIR/content/commands/ds-implement-ticket.md"

if [ ! -f "$TARGET_FILE" ]; then
  echo "check-command-file-budget.sh: missing file: $TARGET_FILE" >&2
  exit 1
fi

file_bytes="$(wc -c < "$TARGET_FILE" | tr -d '[:space:]')"

if [ "$file_bytes" -le "$THRESHOLD_BYTES" ]; then
  headroom=$(( THRESHOLD_BYTES - file_bytes ))
  echo "command file budget check: OK"
  echo "  ds-implement-ticket.md: $file_bytes B"
  echo "  threshold:              $THRESHOLD_BYTES B"
  echo "  headroom:               $headroom B"
  exit 0
fi

overage=$(( file_bytes - THRESHOLD_BYTES ))
echo "command file budget check: OVER BUDGET" >&2
echo "  ds-implement-ticket.md: $file_bytes B" >&2
echo "  threshold:              $THRESHOLD_BYTES B" >&2
echo "  overage:                $overage B" >&2
echo "" >&2
echo "content/commands/ds-implement-ticket.md grew past its budget." >&2
echo "Trim content or, if the growth is deliberate and justified, raise" >&2
echo "THRESHOLD_BYTES in scripts/check-command-file-budget.sh in the same PR." >&2
exit 1
