#!/usr/bin/env bash
# Purpose: Adapter-neutral core for the "newer version available" SessionStart
#          notice. Resolves the agentic-engineering clone dir, reads a small
#          cache of how far the local clone is behind upstream, and prints a
#          single generic update notice to stdout when behind. Kicks off a
#          detached, TTL-throttled background refresh that runs `git fetch` and
#          recomputes the behind-count without ever blocking the caller.
# Public API: bash hooks/lib/version-check-core.sh
#             (no args; prints the notice to stdout when behind_count > 0,
#              otherwise prints nothing. Always exits 0.)
# Upstream deps: ~/.agentic/agentic-engineering-config.json (optional; repo_dir),
#                ~/.agentic/version-check-cache.json (optional cache),
#                git, python3 (cache parse + atomic JSON write). All optional;
#                any missing piece is handled fail-open.
# Downstream consumers: hooks/session-start-version-check.sh (Claude Code wrapper),
#                       .kimi/hooks/session-start.sh (Kimi, prints to stderr).
# Failure modes: always exits 0 (fail-open). No cache, offline, non-git dir,
#                missing python3/git, or malformed cache => prints nothing,
#                still exits 0. Detached refresh redirects all of
#                stdin/stdout/stderr so the parent returns immediately; a failed
#                fetch leaves the prior cache untouched. Cache writes are atomic
#                (tmp file + mv) so a torn read just fails open on the next run.
# Performance: read path is a single file read + one python3 parse (sub-10ms,
#              no network). The network (git fetch) only ever runs in a detached
#              background process, so the caller never waits on it.

set -euo pipefail

# Time-to-live for the cached behind-count, in seconds. Detached refresh only
# runs when the cache is older than this, so many rapid sessions do not each
# spawn a `git fetch`. ~6 hours: freshness lags by at most one TTL window, which
# is acceptable for a passive update nudge.
VERSION_CHECK_TTL_SECONDS=21600

AE_CONFIG="$HOME/.agentic/agentic-engineering-config.json"
CACHE_FILE="$HOME/.agentic/version-check-cache.json"

# --- Resolve the clone dir (same resolver as /update-agentic-engineering Step 0) ---
ae_repo_dir=""
if [[ -f "$AE_CONFIG" ]]; then
  ae_repo_dir="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$AE_CONFIG" 2>/dev/null || echo "")"
fi
if [[ -z "$ae_repo_dir" ]] || ! git -C "$ae_repo_dir" rev-parse --git-dir >/dev/null 2>&1; then
  ae_repo_dir="$HOME/agentic-engineering"
fi

# --- Maybe kick off a detached refresh (TTL-throttled) ---
# Reads the cache timestamp; if absent or older than the TTL, launches a fully
# detached process that fetches and rewrites the cache atomically. All three
# standard fds are redirected so the parent (and Claude Code's hook runner)
# never waits on an inherited pipe. This is the single most important detail:
# without the redirects the SessionStart hook would block on git fetch.
maybe_refresh() {
  local now last_fetch=0 age
  now="$(date +%s 2>/dev/null || echo 0)"

  if [[ -f "$CACHE_FILE" ]]; then
    last_fetch="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(int(json.load(f).get('last_fetch_epoch', 0)))
except Exception:
    print(0)
" "$CACHE_FILE" 2>/dev/null || echo 0)"
  fi

  # Make fail-open structural: never let a non-numeric timestamp reach the
  # arithmetic below (set -u plus a bad value would abort the hook). Mirrors the
  # read-path guard on behind_count.
  [[ "$last_fetch" =~ ^[0-9]+$ ]] || last_fetch=0

  age=$(( now - last_fetch ))
  # Refresh when there is no usable timestamp, the clock looks off, or the cache
  # has aged past the TTL.
  if [[ "$last_fetch" -gt 0 && "$age" -lt "$VERSION_CHECK_TTL_SECONDS" && "$age" -ge 0 ]]; then
    return 0
  fi

  # Detached, fully-redirected background refresh. nohup + & + all-fds-redirected
  # so the caller returns immediately and never blocks on git fetch.
  nohup bash -c '
    repo="$1"
    cache="$2"
    git -C "$repo" fetch --quiet origin >/dev/null 2>&1 || exit 0
    behind="$(git -C "$repo" rev-list --count HEAD..@{u} 2>/dev/null || echo "")"
    case "$behind" in
      ""|*[!0-9]*) exit 0 ;;
    esac
    now="$(date +%s 2>/dev/null || echo 0)"
    tmp="${cache}.tmp.$$"
    if printf "{\"behind_count\": %s, \"last_fetch_epoch\": %s}\n" "$behind" "$now" > "$tmp" 2>/dev/null; then
      mv -f "$tmp" "$cache" 2>/dev/null || rm -f "$tmp" 2>/dev/null
    fi
  ' _ "$ae_repo_dir" "$CACHE_FILE" </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
}

# --- Read path: print the notice iff cached behind_count > 0 ---
behind_count="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(int(json.load(f).get('behind_count', 0)))
except Exception:
    print(0)
" "$CACHE_FILE" 2>/dev/null || echo 0)"

# Ensure the cache dir exists so the detached refresh can write into it.
mkdir -p "$HOME/.agentic" >/dev/null 2>&1 || true

maybe_refresh

if [[ "$behind_count" =~ ^[0-9]+$ ]] && [[ "$behind_count" -gt 0 ]]; then
  echo "⚠️ agentic-engineering: newer version available. Update with /update-agentic-engineering (in session) or ${ae_repo_dir}/update.sh (shell)."
fi

exit 0
