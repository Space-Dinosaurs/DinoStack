#!/usr/bin/env bash
# Purpose: Deterministically assemble the methodology body from content/sections/
#          numbered files into a single stream on stdout. Callers redirect to
#          adapter-specific destination files (e.g. .claude/skills/agentic-
#          engineering/METHODOLOGY.md).
#
# Public API: bash scripts/build-methodology.sh [--output <destination>]
#             With no option, writes the assembled body to stdout.
#
# Upstream deps: content/sections/[0-9][0-9]-*.md files; bash; coreutils sort+ls.
#
# Downstream consumers: .claude/build.sh, .hermes/build.sh, scripts/check-methodology-drift.sh,
#                       future .codex/build.sh, future .cursor/build.sh.
#
# Failure modes: exits non-zero if no section files match the glob (catches
#                accidental deletion or a misnamed renumber) or if an atomic
#                output write fails. Idempotent; read-only against sections.
#
# Performance: O(total size of section files); single concatenation pass.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECTIONS_DIR="$REPO_DIR/content/sections"
OUTPUT=""

if [[ $# -gt 0 ]]; then
  if [[ $# -ne 2 || "$1" != "--output" || -z "$2" ]]; then
    echo "usage: build-methodology.sh [--output <destination>]" >&2
    exit 2
  fi
  OUTPUT="$2"
fi

# LC_ALL=C ensures byte-order sort independent of locale.
files="$(LC_ALL=C find "$SECTIONS_DIR" -maxdepth 1 -type f -name '[0-9][0-9]-*.md' | LC_ALL=C sort)"

if [ -z "$files" ]; then
  echo "build-methodology.sh: no section files found in $SECTIONS_DIR" >&2
  exit 1
fi

assemble() {
  local first=1
  local f
  while IFS= read -r f; do
    if [[ "$first" -eq 1 ]]; then
      first=0
    else
      echo
    fi
    cat "$f"
  done <<< "$files"
}

if [[ -z "$OUTPUT" ]]; then
  assemble
  exit 0
fi

mkdir -p "$(dirname "$OUTPUT")"
temporary="$(mktemp "$(dirname "$OUTPUT")/.methodology.XXXXXX")"
cleanup() {
  rm -f "$temporary"
}
trap cleanup EXIT HUP INT TERM
assemble > "$temporary"
mv "$temporary" "$OUTPUT"
trap - EXIT HUP INT TERM
