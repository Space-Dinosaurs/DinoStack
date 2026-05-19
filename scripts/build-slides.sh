#!/usr/bin/env bash
# Purpose: Deterministically render every docs/slides/*-slides.md Marp deck to
#          its sibling *.html, normalizing Marpit's per-render random scope
#          tokens so output is byte-stable across machines and runs.
#
# Public API: bash scripts/build-slides.sh
#
# Upstream deps: docs/slides/*-slides.md (deck sources); scripts/package.json +
#                scripts/package-lock.json; npm; @marp-team/marp-cli@4.3.1
#                (EXACT pin, see scripts/package.json); bash; awk; coreutils
#                find+sort+mktemp+cmp.
#
# Downstream consumers: .github/workflows/slides-sync.yml (drift gate);
#                       content/commands/update-agentic-engineering.md slide
#                       step; contributors regenerating decks locally.
#
# Failure modes: exits non-zero on zero-glob (no decks found), marp render
#                failure, or missing render output. Idempotent and read-only
#                against the *.md sources (only *.html is written). A cold run
#                needs network for `npm ci`; warm runs are offline.
#
# Performance: cold run = `npm ci` plus ~15 sequential marp renders; marp
#              cold-start dominates. Warm runs skip install. No internal
#              timeout (CI supplies the job-level timeout).
#
# INVARIANT: Marpit always delimits data-marpit-scope-XXXXXXXX with a non-alnum
#            char; 8-char-exact search vs 4-char sNNN replacement cannot
#            self-re-match; all-15-deck 2x reproducibility gate + browser
#            spot-check detect any violation.

set -euo pipefail
export LC_ALL=C

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS_DIR="$REPO_DIR/scripts"
SLIDES_DIR="$REPO_DIR/docs/slides"

# Staleness-gated install: (re)install only when the bin is missing or the
# installed lockfile no longer matches the committed lockfile.
if [ ! -x "$SCRIPTS_DIR/node_modules/.bin/marp" ] \
  || ! cmp -s "$SCRIPTS_DIR/node_modules/.package-lock.json" "$SCRIPTS_DIR/package-lock.json"; then
  npm ci --prefix "$SCRIPTS_DIR" --no-audit --no-fund
fi

MARP="$SCRIPTS_DIR/node_modules/.bin/marp"

# Collect decks deterministically.
decks=()
while IFS= read -r deck; do
  decks+=("$deck")
done < <(find "$SLIDES_DIR" -maxdepth 1 -type f -name '*-slides.md' | LC_ALL=C sort)

if [ "${#decks[@]}" -eq 0 ]; then
  echo "build-slides: no docs/slides/*-slides.md decks found in $SLIDES_DIR" >&2
  exit 1
fi

for md in "${decks[@]}"; do
  html="${md%.md}.html"
  base="$(basename "$md")"

  tmp="$(mktemp "${TMPDIR:-/tmp}/build-slides.XXXXXX")"
  # shellcheck disable=SC2064
  trap "rm -f '$tmp'" EXIT

  if ! "$MARP" --no-stdin "$md" -o "$tmp"; then
    echo "build-slides: marp render failed for $base" >&2
    rm -f "$tmp"
    trap - EXIT
    exit 1
  fi

  if [ ! -s "$tmp" ]; then
    echo "build-slides: marp produced no output for $base" >&2
    rm -f "$tmp"
    trap - EXIT
    exit 1
  fi

  # Fresh awk process per file: map/n reset per deck by construction. Replace
  # each unique 8-char random scope token with a stable sNNN counter so output
  # is reproducible. Do NOT stream all decks through one awk - that would leak
  # the counter across files and make output order-dependent.
  awk '{
    line = $0
    while (match(line, /data-marpit-scope-[A-Za-z0-9]{8}/)) {
      tok = substr(line, RSTART, RLENGTH)
      if (!(tok in map)) { map[tok] = sprintf("data-marpit-scope-s%03d", ++n) }
      line = substr(line, 1, RSTART - 1) map[tok] substr(line, RSTART + RLENGTH)
    }
    print line
  }' "$tmp" > "$html"

  rm -f "$tmp"
  trap - EXIT

  echo "build-slides: rendered $base -> $(basename "$html")" >&2
done
