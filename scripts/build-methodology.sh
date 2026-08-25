#!/usr/bin/env bash
# Purpose: Deterministically assemble the methodology body from content/sections/
#          numbered files into a single stream on stdout, filtered by an
#          active "corpus" tier (minimal/medium/full - DS-204) via
#          scripts/lib/corpus-filter.py. Callers redirect to adapter-specific
#          destination files (e.g. .claude/skills/agentic-engineering/METHODOLOGY.md).
#
# Public API: bash scripts/build-methodology.sh [--output <destination>]
#             [--list-files] [--corpus minimal|medium|full]
#             [--full-text-name <basename>]
#             With no option, writes the assembled full-corpus body to
#             stdout. With --list-files, emits the section basenames one per
#             line - the single-source file-set glob for downstream consumers
#             such as the methodology drift check; --list-files is corpus-
#             agnostic and MUST NOT be combined with --corpus/--full-text-name
#             (exits 2 if it is). --corpus selects the active tier; resolution
#             order is the flag, then the AE_CORPUS environment variable,
#             then "full". --full-text-name names the file a generated
#             "Deferred at this corpus" pointer block tells the reader to open
#             for the full text (default METHODOLOGY.md); it is passed
#             through verbatim to corpus-filter.py and has no effect unless
#             some section defers content at the active corpus.
#
# Upstream deps: regular depth-one content/sections/[0-9][0-9]-*.md files selected
#                with find, then byte-order sorted; bash and coreutils;
#                scripts/lib/corpus-filter.py (python3) for the per-file
#                corpus-marker filter pass.
#
# Downstream consumers: .claude/build.sh, .hermes/build.sh, scripts/check-methodology-drift.sh
#                       (via --list-files), .codex/build.sh, and .cursor/build.sh.
#                       All current adapter build.sh callers invoke this with
#                       no --corpus flag and no AE_CORPUS set, so they always
#                       get the full-corpus assembly - byte-identical to the
#                       pre-DS-204 output as long as every corpus:begin block
#                       in content/sections/ includes "full" in its list.
#
# Failure modes: exits non-zero if no section files match the glob (catches
#                accidental deletion or a misnamed renumber), if an atomic
#                output write fails, if --corpus/AE_CORPUS resolves to a value
#                outside {minimal, medium, full}, if --list-files is combined
#                with --corpus/--full-text-name, or if corpus-filter.py exits
#                non-zero on any section file (malformed markers - the
#                offending file:line is on stderr, unchanged from the
#                subprocess). Idempotent; read-only against sections.
#
# Performance: O(total size of section files); one corpus-filter.py subprocess
#              per section file, plus a single concatenation pass.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECTIONS_DIR="$REPO_DIR/content/sections"
CORPUS_FILTER="$REPO_DIR/scripts/lib/corpus-filter.py"

OUTPUT=""
LIST_FILES=0
CORPUS=""
CORPUS_SET=0
FULL_TEXT_NAME="METHODOLOGY.md"
FULL_TEXT_NAME_SET=0

usage() {
  echo "usage: build-methodology.sh [--output <destination>] [--list-files] [--corpus minimal|medium|full] [--full-text-name <basename>]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      if [[ $# -lt 2 || -z "$2" ]]; then
        usage
        exit 2
      fi
      OUTPUT="$2"
      shift 2
      ;;
    --list-files)
      LIST_FILES=1
      shift
      ;;
    --corpus)
      if [[ $# -lt 2 || -z "$2" ]]; then
        usage
        exit 2
      fi
      CORPUS="$2"
      CORPUS_SET=1
      shift 2
      ;;
    --full-text-name)
      if [[ $# -lt 2 || -z "$2" ]]; then
        usage
        exit 2
      fi
      FULL_TEXT_NAME="$2"
      FULL_TEXT_NAME_SET=1
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ "$LIST_FILES" -eq 1 && ( "$CORPUS_SET" -eq 1 || "$FULL_TEXT_NAME_SET" -eq 1 ) ]]; then
  echo "build-methodology.sh: --list-files lists source files and is corpus-agnostic; do not combine with --corpus/--full-text-name" >&2
  exit 2
fi

# LC_ALL=C ensures byte-order sort independent of locale.
files="$(LC_ALL=C find "$SECTIONS_DIR" -maxdepth 1 -type f -name '[0-9][0-9]-*.md' | LC_ALL=C sort)"

if [ -z "$files" ]; then
  echo "build-methodology.sh: no section files found in $SECTIONS_DIR" >&2
  exit 1
fi

if [[ "$LIST_FILES" -eq 1 ]]; then
  for f in $files; do
    basename "$f"
  done
  exit 0
fi

# --- Corpus resolution: flag > AE_CORPUS env > full.
if [[ "$CORPUS_SET" -eq 1 ]]; then
  RESOLVED_CORPUS="$CORPUS"
elif [[ -n "${AE_CORPUS:-}" ]]; then
  RESOLVED_CORPUS="$AE_CORPUS"
else
  RESOLVED_CORPUS="full"
fi

case "$RESOLVED_CORPUS" in
  minimal|medium|full) ;;
  *)
    echo "build-methodology.sh: invalid corpus '$RESOLVED_CORPUS' (expected minimal, medium, or full)" >&2
    exit 2
    ;;
esac

assemble() {
  local first=1
  local f
  while IFS= read -r f; do
    if [[ "$first" -eq 1 ]]; then
      first=0
    else
      echo
    fi
    python3 "$CORPUS_FILTER" \
      --corpus "$RESOLVED_CORPUS" \
      --source-name "$(basename "$f")" \
      --full-text-name "$FULL_TEXT_NAME" \
      < "$f"
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
