#!/usr/bin/env bash
# Purpose: Guard against unbounded growth of the "resident set" - the
#          methodology content every Claude Code session loads via the
#          @-imports in ~/.claude/CLAUDE.md on every project, regardless of
#          whether that project's task needs it. The resident set is:
#            - the assembled METHODOLOGY.md (bash scripts/build-methodology.sh)
#            - content/rules/conventions.md
#            - content/rules/code-standards.md
#          This script sums their byte sizes and fails if the total exceeds
#          THRESHOLD. THRESHOLD is a ratchet: when a compression PR shrinks
#          the resident set, lower THRESHOLD in the same PR so growth cannot
#          silently claw the savings back. Raising THRESHOLD should be rare
#          and deliberate - it is a decision to permanently tax every session
#          in every project with more always-loaded context.
#
# Public API: bash scripts/check-resident-budget.sh
#             Exits 0 when total bytes <= THRESHOLD, 1 otherwise.
#
# Upstream deps: scripts/build-methodology.sh; content/rules/conventions.md;
#                content/rules/code-standards.md.
#
# Downstream consumers: .github/workflows/resident-budget.yml.
#
# Failure modes: over budget -> exit 1 with per-file breakdown, total,
#                threshold, and overage printed. Read-only; no side effects
#                on the repo.
#
# Note: METHODOLOGY.md is measured by running build-methodology.sh fresh,
#       NOT by statting the generated .claude/skills/agentic-engineering/
#       METHODOLOGY.md file - a PR that edits content/sections/** without
#       rebuilding adapters would otherwise be measured against a stale
#       artifact and could slip a regression past this gate.
#
# Compatible with both bash and zsh invocation of the containing shell;
# this script itself always runs under `bash scripts/check-resident-budget.sh`.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Ratchet: 123,938 measured on origin/main 2026-07-31 + 1,000 B headroom.
# Lower this value in the same commit as any deliberate compression of the
# resident set. See the header comment above before raising it.
THRESHOLD=124938

CONVENTIONS_FILE="$REPO_DIR/content/rules/conventions.md"
CODE_STANDARDS_FILE="$REPO_DIR/content/rules/code-standards.md"

if [ ! -f "$CONVENTIONS_FILE" ]; then
  echo "check-resident-budget.sh: missing file: $CONVENTIONS_FILE" >&2
  exit 1
fi
if [ ! -f "$CODE_STANDARDS_FILE" ]; then
  echo "check-resident-budget.sh: missing file: $CODE_STANDARDS_FILE" >&2
  exit 1
fi

methodology_bytes="$(bash "$REPO_DIR/scripts/build-methodology.sh" | wc -c | tr -d '[:space:]')"
conventions_bytes="$(wc -c < "$CONVENTIONS_FILE" | tr -d '[:space:]')"
code_standards_bytes="$(wc -c < "$CODE_STANDARDS_FILE" | tr -d '[:space:]')"

total=$(( methodology_bytes + conventions_bytes + code_standards_bytes ))

if [ "$total" -le "$THRESHOLD" ]; then
  headroom=$(( THRESHOLD - total ))
  echo "resident budget check: OK"
  echo "  METHODOLOGY.md (built):        $methodology_bytes B"
  echo "  content/rules/conventions.md:  $conventions_bytes B"
  echo "  content/rules/code-standards.md: $code_standards_bytes B"
  echo "  total:     $total B"
  echo "  threshold: $THRESHOLD B"
  echo "  headroom:  $headroom B"
  exit 0
fi

overage=$(( total - THRESHOLD ))
echo "resident budget check: OVER BUDGET" >&2
echo "  METHODOLOGY.md (built):        $methodology_bytes B" >&2
echo "  content/rules/conventions.md:  $conventions_bytes B" >&2
echo "  content/rules/code-standards.md: $code_standards_bytes B" >&2
echo "  total:     $total B" >&2
echo "  threshold: $THRESHOLD B" >&2
echo "  overage:   $overage B" >&2
echo "" >&2
echo "The always-loaded methodology resident set grew past its budget." >&2
echo "Trim content or, if the growth is deliberate and justified, raise" >&2
echo "THRESHOLD in scripts/check-resident-budget.sh in the same PR." >&2
exit 1
