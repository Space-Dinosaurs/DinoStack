#!/usr/bin/env bash
# Purpose: CI ratchet against the assembled methodology "resident set" -
#          the byte total an agent must hold in context to operate under
#          the methodology (assembled body + the two force-loaded rule
#          files). Fails if the resident set regrows past the ratchet
#          established at DS-68 (methodology compression), preventing
#          silent re-bloat after detail was relocated to
#          content/references/.
#
# Public API: bash scripts/check-resident-budget.sh
#             Exits 0 when total <= THRESHOLD, printing total and
#             threshold. Exits 1 with a relocation hint otherwise.
#             Optional env override RESIDENT_BUDGET_OVERRIDE replaces
#             THRESHOLD for local testing of the failure path only -
#             never set in CI.
#
# Upstream deps: scripts/build-methodology.sh; content/rules/code-standards.md;
#                content/rules/conventions.md; wc.
#
# Downstream consumers: .github/workflows/resident-budget.yml.
#
# Failure modes: total > threshold -> exit 1 with the overage and a
#                relocation/raise-the-ratchet hint. Read-only; no side
#                effects on the repo.
#
# Performance: O(total size of section + rule files); one assembly pass
#              plus three byte counts.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# THRESHOLD derivation: 87,323 bytes measured actual resident set at the
# DS-68 (methodology compression) merge, plus 1,000 bytes of headroom.
THRESHOLD=88323

if [ -n "${RESIDENT_BUDGET_OVERRIDE:-}" ]; then
  THRESHOLD="$RESIDENT_BUDGET_OVERRIDE"
fi

methodology_bytes="$(bash "$REPO_DIR/scripts/build-methodology.sh" | wc -c)"
code_standards_bytes="$(wc -c < "$REPO_DIR/content/rules/code-standards.md")"
conventions_bytes="$(wc -c < "$REPO_DIR/content/rules/conventions.md")"

total=$(( methodology_bytes + code_standards_bytes + conventions_bytes ))

if [ "$total" -le "$THRESHOLD" ]; then
  echo "resident budget check: OK ($total <= $THRESHOLD)"
  exit 0
fi

echo "resident budget check: FAIL" >&2
echo "  resident set grew to $total bytes, ratchet is $THRESHOLD" >&2
echo "  - relocate detail to content/references/ per DS-68, or" >&2
echo "  - consciously raise the ratchet in scripts/check-resident-budget.sh" >&2
exit 1
