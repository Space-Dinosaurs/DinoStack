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
#                threshold, and overage printed. Build failure -> exit 1
#                when build-methodology.sh output is implausibly small
#                (< MIN_PLAUSIBLE_METHODOLOGY_BYTES), with a message that
#                explicitly distinguishes a broken build from a budget
#                overage. Missing input file -> exit 1. Read-only; no side
#                effects on the repo.
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

# BASH_SOURCE is unset under zsh (this script is invoked as `zsh
# scripts/check-resident-budget.sh` by some CI/local paths, even though it
# is written for bash) - fall back to $0 so REPO_DIR resolves correctly
# under both interpreters instead of collapsing to "//".
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# Ratchet: 123,938 measured on origin/main 2026-07-31 + 1,000 B headroom.
# Lower this value in the same commit as any deliberate compression of the
# resident set. See the header comment above before raising it.
THRESHOLD=124938

# Plausibility floor: if build-methodology.sh ever exits 0 while emitting
# nothing or a truncated stream, methodology_bytes would be near-zero and
# the check would PASS with tens of KB of false headroom. This floor is
# deliberately far below any realistic post-compression target - this repo
# has an active compression programme aiming for ~66,400 B and an
# aspiration of 60,000 B for METHODOLOGY.md alone, so the floor must never
# be able to fire on correct, successful compression work. 10,000 B is
# roughly an order of magnitude below that floor: it can only mean the
# build produced garbage or nothing, never that compression "went well".
MIN_PLAUSIBLE_METHODOLOGY_BYTES=10000

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

if [ "$methodology_bytes" -lt "$MIN_PLAUSIBLE_METHODOLOGY_BYTES" ]; then
  echo "check-resident-budget.sh: BUILD FAILURE, not a budget problem." >&2
  echo "  build-methodology.sh produced only $methodology_bytes B of output," >&2
  echo "  below the $MIN_PLAUSIBLE_METHODOLOGY_BYTES B plausibility floor." >&2
  echo "  This means the build is broken or emitted truncated/empty output -" >&2
  echo "  it does NOT mean the resident set is under budget. Investigate" >&2
  echo "  scripts/build-methodology.sh directly; do not raise THRESHOLD or" >&2
  echo "  lower this floor to make this pass." >&2
  exit 1
fi

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
