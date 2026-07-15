#!/usr/bin/env bash
# Purpose: Shared dormant-stub renderer. Single source of the stub body used by
#          every adapter's dormant artifact, so the 11 build.sh scripts and the
#          11 install.sh scripts don't each carry their own copy.
#
# Public API (source this file, then call):
#   ae_stub_body [tier_file_path]
#       Prints the rendered stub body to stdout. Strips the leading HTML comment
#       header from content/sections/00-dormant-stub.md and substitutes the
#       {{TIER_FILE}} token. When tier_file_path is omitted/empty, the token
#       renders as a relative pointer so the stub still reads sensibly at build
#       time (before an install path is known).
#
#   ae_stub_bytes [tier_file_path]
#       Prints the byte length of the rendered body (budget check helper).
#
# Upstream deps: content/sections/00-dormant-stub.md; perl; bash; coreutils.
# Downstream consumers: adapter install.sh dormant paths (render at install time
#                       with the resolved absolute tier path), scripts/check-stub-budget.sh.
# Failure modes: exits non-zero (via caller) if the source file is missing.
# Performance: one perl pass; negligible.

# Resolve repo root from this lib's location (scripts/lib/stub.sh -> repo).
_AE_STUB_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_AE_STUB_SRC="$(cd "$_AE_STUB_LIB_DIR/../.." && pwd)/content/sections/00-dormant-stub.md"

ae_stub_body() {
  local tier_file="${1:-}"
  if [[ ! -f "$_AE_STUB_SRC" ]]; then
    echo "stub.sh: missing source: $_AE_STUB_SRC" >&2
    return 1
  fi
  # Default pointer when no absolute path is known at render time.
  local token="${tier_file:-the resolved-tier methodology file (see /ds status)}"
  # Strip the leading comment header (everything before the first `## ` heading),
  # then substitute the {{TIER_FILE}} token. AE_STUB_TOKEN is passed via env so
  # perl treats it as literal data — no shell interpolation into the regex.
  AE_STUB_TOKEN="$token" perl -0pe 's/\A.*?(?=^## )//ms' "$_AE_STUB_SRC" \
    | AE_STUB_TOKEN="$token" perl -pe 's/\{\{TIER_FILE\}\}/$ENV{AE_STUB_TOKEN}/g'
}

ae_stub_bytes() {
  ae_stub_body "${1:-}" | wc -c | tr -d ' '
}

# ae_install_stub_file <dest> <tier_file_path>
#   Dormant path for the symlink-class adapters (codex/kimi/gemini): replace the
#   full-file symlink (or any existing target) at <dest> with a rendered stub
#   FILE, so the harness loads only the near-zero stub until activated. Removes a
#   prior symlink first (never writes through it). Prints a one-line status.
ae_install_stub_file() {
  local dest="$1" tier_file="${2:-}"
  # Remove a stale symlink outright (never write through it); back up a real file.
  if [[ -L "$dest" ]]; then
    rm -f "$dest"
  elif [[ -e "$dest" ]]; then
    local backup
    backup="$dest.backup-$(date +%Y%m%d%H%M%S)"
    mv "$dest" "$backup"
    echo "  (backed up existing $dest -> $backup)"
  fi
  mkdir -p "$(dirname "$dest")"
  if ! ae_stub_body "$tier_file" > "$dest"; then
    echo "  ! failed to render dormant stub to $dest" >&2
    return 1
  fi
  echo "  + $dest (dormant stub)"
}

# ae_is_stub_file <path>
#   Returns 0 iff <path> is a REAL file (not a symlink) that we wrote as a dormant
#   stub, identified by the stable heading. Used by uninstall.sh to remove an
#   installed stub without clobbering a user's own real file at the same path.
ae_is_stub_file() {
  local path="$1"
  [[ -f "$path" && ! -L "$path" ]] || return 1
  grep -q "^## agentic-engineering (dormant)$" "$path" 2>/dev/null
}
