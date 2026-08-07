#!/usr/bin/env bash
# Purpose: Guard against unbounded growth of the "resident set" - the small
#          pointer table that stays loaded in every Claude Code session via
#          the @-import of content/templates/claude-managed-content.md into
#          ~/.claude/CLAUDE.md, regardless of whether that project's task
#          needs the full methodology.
#
#          As of DS-143, METHODOLOGY.md, content/rules/conventions.md, and
#          content/rules/code-standards.md are NOT part of this measurement.
#          They are no longer always-loaded: they load on skill invocation
#          (trigger-loaded via the SKILL.md embed), not on every session.
#          Growth of THAT content is governed by a sibling gate,
#          scripts/check-skill-embed-budget.sh - if you are looking for a
#          budget on the methodology body itself, that is the script you
#          want, not this one.
#
#          This script sums the byte size of
#          content/templates/claude-managed-content.md and fails if it
#          exceeds THRESHOLD. THRESHOLD is a ratchet: when a compression PR
#          shrinks the resident set, lower THRESHOLD in the same PR so
#          growth cannot silently claw the savings back. Raising THRESHOLD
#          should be rare and deliberate - it is a decision to permanently
#          tax every session in every project with more always-loaded
#          context.
#
# Public API: bash scripts/check-resident-budget.sh
#             Exits 0 when total bytes <= THRESHOLD. Exits 1 when over
#             budget, when the input file is missing, or when the
#             plausibility floor fires (see Failure modes below).
#
# Upstream deps: content/templates/claude-managed-content.md.
#
# Downstream consumers: .github/workflows/resident-budget.yml.
#
# Failure modes: over budget -> exit 1 with a breakdown naming the file and
#                the numbers. Missing input file -> exit 1. File emptied or
#                implausibly small (< MIN_PLAUSIBLE_BYTES) -> exit 1 with a
#                message that explicitly distinguishes a vanished/corrupted
#                file from a budget overage. Read-only; no side effects on
#                the repo.
#
# Compatible with both bash and zsh invocation of the containing shell; CI
# always invokes it as `bash scripts/check-resident-budget.sh`, but a
# contributor, reviewer, or this file's own regression test may invoke it
# as `zsh scripts/check-resident-budget.sh` and it must behave identically.

set -euo pipefail

# BASH_SOURCE is unset under zsh. CI always invokes this script as `bash
# scripts/check-resident-budget.sh` (see resident-budget.yml), but a
# contributor or reviewer may run it under zsh locally - fall back to $0 so
# REPO_DIR resolves correctly under both interpreters instead of collapsing
# to "//".
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# Ratchet: content/templates/claude-managed-content.md measured 1,705 B on
# this branch 2026-08-06 (DS-143, redefining this gate after the @-import
# removal - #581 lineage). THRESHOLD is set to roughly 2x that measurement
# (3,410 B) to give headroom for the pointer table to grow a few more lines
# before this gate fires, while still catching runaway growth early. Lower
# this value in the same commit as any deliberate compression of the
# managed-content file. See the header comment above before raising it.
THRESHOLD=3410

# Plausibility floor: if claude-managed-content.md were ever emptied or
# truncated (a bad merge, an accidental overwrite), managed_content_bytes
# would be near-zero and the check would PASS with a huge false headroom.
# This floor is deliberately far below any realistic content size for this
# file - it exists to catch "the file vanished or is empty," not to police
# normal size fluctuation.
MIN_PLAUSIBLE_BYTES=200

MANAGED_CONTENT_FILE="$REPO_DIR/content/templates/claude-managed-content.md"

if [ ! -f "$MANAGED_CONTENT_FILE" ]; then
  echo "check-resident-budget.sh: missing file: $MANAGED_CONTENT_FILE" >&2
  exit 1
fi

managed_content_bytes="$(wc -c < "$MANAGED_CONTENT_FILE" | tr -d '[:space:]')"

if [ "$managed_content_bytes" -lt "$MIN_PLAUSIBLE_BYTES" ]; then
  echo "check-resident-budget.sh: FILE FAILURE, not a budget problem." >&2
  echo "  content/templates/claude-managed-content.md is only" >&2
  echo "  $managed_content_bytes B, below the $MIN_PLAUSIBLE_BYTES B" >&2
  echo "  plausibility floor. This means the file was emptied, truncated," >&2
  echo "  or corrupted - it does NOT mean the resident set is under" >&2
  echo "  budget. Investigate content/templates/claude-managed-content.md" >&2
  echo "  directly; do not raise THRESHOLD or lower this floor to make" >&2
  echo "  this pass." >&2
  exit 1
fi

total="$managed_content_bytes"

if [ "$total" -le "$THRESHOLD" ]; then
  headroom=$(( THRESHOLD - total ))
  echo "resident budget check: OK"
  echo "  content/templates/claude-managed-content.md: $managed_content_bytes B"
  echo "  total:     $total B"
  echo "  threshold: $THRESHOLD B"
  echo "  headroom:  $headroom B"
  exit 0
fi

overage=$(( total - THRESHOLD ))
echo "resident budget check: OVER BUDGET" >&2
echo "  content/templates/claude-managed-content.md: $managed_content_bytes B" >&2
echo "  total:     $total B" >&2
echo "  threshold: $THRESHOLD B" >&2
echo "  overage:   $overage B" >&2
echo "" >&2
echo "The always-loaded resident set (the pointer table in" >&2
echo "content/templates/claude-managed-content.md) grew past its budget." >&2
echo "Trim content or, if the growth is deliberate and justified, raise" >&2
echo "THRESHOLD in scripts/check-resident-budget.sh in the same PR." >&2
exit 1
