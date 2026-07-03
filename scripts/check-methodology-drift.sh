#!/usr/bin/env bash
# Purpose: Verify that the assembled methodology body matches the committed
#          baseline hash for EACH tier (full / medium / minimal). Used as a CI
#          gate to catch unintended drift between content/sections/ source
#          files and the documented baselines. The baselines are updated in
#          the same commit that intentionally changes methodology content.
#
# Public API: bash scripts/check-methodology-drift.sh
#             Exits 0 on all-match, 1 on any mismatch or missing baseline file.
#
# Upstream deps: scripts/build-methodology.sh; sha256sum (or shasum -a 256);
#                python3; scripts/lib/tier-filter.py (via build-methodology.sh);
#                scripts/.methodology-baseline.sha256.
#
# Downstream consumers: .github/workflows/methodology-drift.yml.
#
# Failure modes: missing baseline file -> exit 1 with instructions; hash
#                mismatch -> exit 1 with current/expected hashes printed.
#                Read-only; no side effects on the repo.
#
# Performance: 3 O(total size) assembles + 3 hashes, one per tier.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASELINE_FILE="$REPO_DIR/scripts/.methodology-baseline.sha256"

if [ ! -f "$BASELINE_FILE" ]; then
	echo "check-methodology-drift.sh: baseline file missing: $BASELINE_FILE" >&2
	echo "  To establish a baseline:" >&2
	echo "    for tier in full medium minimal; do" >&2
	echo "      hash=\$(bash $REPO_DIR/scripts/build-methodology.sh \"\$tier\" | shasum -a 256 | awk '{print \$1}')" >&2
	echo "      echo \"\$hash  \$tier\"" >&2
	echo "    done > $BASELINE_FILE" >&2
	exit 1
fi

# Pick hash binary portably: sha256sum (Linux/CI) preferred, shasum (macOS) fallback.
if command -v sha256sum >/dev/null 2>&1; then
	hash_cmd() { sha256sum | awk '{print $1}'; }
else
	hash_cmd() { shasum -a 256 | awk '{print $1}'; }
fi

fail=0
expected_full="$(awk '$2=="full"{print $1}' "$BASELINE_FILE")"
expected_medium="$(awk '$2=="medium"{print $1}' "$BASELINE_FILE")"
expected_minimal="$(awk '$2=="minimal"{print $1}' "$BASELINE_FILE")"

check_one() {
	local tier="$1" expected="$2" current
	current="$(bash "$REPO_DIR/scripts/build-methodology.sh" "$tier" | hash_cmd)"
	if [ "$current" = "$expected" ]; then
		echo "methodology drift check: $tier OK ($current)"
		return 0
	fi
	echo "methodology drift check: $tier MISMATCH" >&2
	echo "  expected: $expected" >&2
	echo "  current:  $current" >&2
	return 1
}

if ! check_one full "$expected_full"; then fail=1; fi
if [ -n "$expected_medium" ] && ! check_one medium "$expected_medium"; then fail=1; fi
if [ -n "$expected_minimal" ] && ! check_one minimal "$expected_minimal"; then fail=1; fi

if [ "$fail" -ne 0 ]; then
	echo "" >&2
	echo "If this drift is intentional, regenerate the baseline:" >&2
	echo "  for tier in full medium minimal; do" >&2
	echo "    hash=\$(bash $REPO_DIR/scripts/build-methodology.sh \"\$tier\" | shasum -a 256 | awk '{print \$1}')" >&2
	echo "    echo \"\$hash  \$tier\"" >&2
	echo "  done > $BASELINE_FILE" >&2
	echo "and include the updated baseline in the same commit." >&2
	exit 1
fi

exit 0
