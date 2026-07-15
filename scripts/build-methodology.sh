#!/usr/bin/env bash
# Purpose: Deterministically assemble the methodology body from the SINGLE
#          `content/sections/` source tree, filtering per tier at build time
#          via scripts/lib/tier-filter.py. Elides manual tier copies.
#
# Public API:
#   bash scripts/build-methodology.sh                    # default tier=full
#   bash scripts/build-methodology.sh minimal             # minimal sections
#   bash scripts/build-methodology.sh medium              # medium sections
#   bash scripts/build-methodology.sh full                # full sections (default)
#
# Tier resolution:
#   $1 if set and matches minimal|medium|full; else env AE_TIER; else "full".
#
# Single source of truth: `content/sections/[0-9][0-9]-*.md`. Each file uses
# inline marker blocks (<!-- tiers: ... --> / <!-- tier:begin ... -->) to
# control which tiers see which content. Files matching no tier for the
# requested build are skipped entirely.
#
# Upstream deps: content/sections/*.md; bash; coreutils; find; sort;
#                python3; scripts/lib/tier-filter.py.
#
# Downstream consumers: .claude/build.sh, .hermes/build.sh,
#                       scripts/check-methodology-drift.sh.
#
# Failure modes: exits non-zero if no section files match the glob, the tier
#                argument is invalid, or the filter rejects a section file
#                (unknown tier, unbalanced/unknown marker).
#
# Performance: O(total size of section files); single pass per file.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECTIONS_DIR="$REPO_DIR/content/sections"
FILTER="$REPO_DIR/scripts/lib/tier-filter.py"

# Tier resolution: positional arg -> env -> default "full"
TIER="${1:-${AE_TIER:-full}}"
case "$TIER" in
minimal | medium | full) ;;
*)
	echo "build-methodology.sh: invalid tier '$TIER' (expected minimal|medium|full)" >&2
	exit 2
	;;
esac

if [ ! -d "$SECTIONS_DIR" ]; then
	echo "build-methodology.sh: sections dir missing: $SECTIONS_DIR" >&2
	exit 3
fi

if [ ! -x "$FILTER" ]; then
	echo "build-methodology.sh: filter not executable: $FILTER" >&2
	exit 4
fi

# LC_ALL=C ensures byte-order sort independent of locale.
# `00-*` is reserved for non-methodology single-sources (e.g. the dormant stub,
# rendered per-adapter at install time via scripts/lib/stub.sh) — exclude it so
# it never leaks into the assembled METHODOLOGY.md. Sections start at 01.
files="$(LC_ALL=C find "$SECTIONS_DIR" -maxdepth 1 -type f -name '[0-9][0-9]-*.md' ! -name '00-*' | LC_ALL=C sort)"

if [ -z "$files" ]; then
	echo "build-methodology.sh: no section files found in $SECTIONS_DIR" >&2
	exit 1
fi

first=1
while IFS= read -r f; do
	if [ "$first" -eq 1 ]; then
		first=0
	else
		# Single blank line between files
		echo
	fi
	python3 "$FILTER" "$TIER" <"$f"
done <<<"$files"
