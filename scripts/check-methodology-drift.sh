#!/usr/bin/env bash
# Purpose: Verify that the assembled methodology body matches the committed
#          baseline hash. Used as a CI gate to catch unintended drift between
#          content/sections/ source files and the documented baseline. The
#          baseline is updated in the same commit that intentionally changes
#          methodology content.
#
# Public API: bash scripts/check-methodology-drift.sh
#             Exits 0 on match, 1 on mismatch or missing baseline file.
#
# Upstream deps: scripts/build-methodology.sh; sha256sum (or shasum -a 256);
#                scripts/.methodology-baseline.sha256.
#
# Downstream consumers: .github/workflows/methodology-drift.yml.
#
# Failure modes: missing baseline file -> exit 1 with instructions; hash
#                mismatch -> exit 1 with current/expected hashes printed.
#                Read-only; no side effects on the repo.
#
# Performance: O(total size of section files); one assembly + one hash.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASELINE_FILE="$REPO_DIR/scripts/.methodology-baseline.sha256"

if [ ! -f "$BASELINE_FILE" ]; then
  echo "check-methodology-drift.sh: baseline file missing: $BASELINE_FILE" >&2
  echo "  To establish a baseline:" >&2
  echo "    bash scripts/build-methodology.sh | shasum -a 256 | awk '{print \$1}' > $BASELINE_FILE" >&2
  exit 1
fi

expected="$(cat "$BASELINE_FILE" | tr -d '[:space:]')"

# Prefer sha256sum (Linux/CI) when available; fall back to shasum -a 256 (macOS).
if command -v sha256sum >/dev/null 2>&1; then
  current="$(bash "$REPO_DIR/scripts/build-methodology.sh" | sha256sum | awk '{print $1}')"
else
  current="$(bash "$REPO_DIR/scripts/build-methodology.sh" | shasum -a 256 | awk '{print $1}')"
fi

if [ "$current" = "$expected" ]; then
  echo "methodology drift check: OK ($current)"
  exit 0
fi

echo "methodology drift check: MISMATCH" >&2
echo "  expected: $expected" >&2
echo "  current:  $current" >&2
echo "" >&2
echo "If this drift is intentional, regenerate the baseline:" >&2
echo "  bash scripts/build-methodology.sh | shasum -a 256 | awk '{print \$1}' > $BASELINE_FILE" >&2
echo "and include the updated baseline in the same commit." >&2
exit 1
