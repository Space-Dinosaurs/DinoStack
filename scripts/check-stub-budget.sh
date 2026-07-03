#!/usr/bin/env bash
# Purpose: CI gate — the rendered dormant stub body must stay <= 2048 bytes.
#          The stub ships into every adapter at rest; a bloated stub defeats the
#          whole point of dormancy (near-zero cost when methodology is off).
#
# Public API: bash scripts/check-stub-budget.sh
#             Exit 0 when the rendered body is within budget; exit 1 otherwise.
#
# Upstream deps: scripts/lib/stub.sh; content/sections/00-dormant-stub.md.
# Downstream consumers: CI (adapter-sync.yml / mega-PR final gate), build-all.sh.
# Failure modes: exit 1 on over-budget or missing source.
# Performance: single render; negligible.

set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/stub.sh
. "$REPO_DIR/scripts/lib/stub.sh"

BUDGET=2048
# Measure the worst case: a long absolute install path substituted for the token.
sample_path="/Users/example/.claude/skills/agentic-engineering-minimal/METHODOLOGY.md"
bytes="$(ae_stub_bytes "$sample_path")"

if [ "$bytes" -le "$BUDGET" ]; then
  echo "stub-budget check: OK ($bytes <= $BUDGET bytes)"
  exit 0
fi

echo "stub-budget check: FAIL ($bytes > $BUDGET bytes)" >&2
echo "  Trim content/sections/00-dormant-stub.md to fit the budget." >&2
exit 1
