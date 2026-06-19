#!/usr/bin/env bash
# Purpose: Claude Code SessionStart wrapper for the deferred-wrap feature. It
#          composes FOUR concerns into a single fail-open SessionStart hook:
#          (a) the "newer version available" notice (delegated to the existing
#          version-check wrapper); (b) a one-line auth-failed notice when the
#          daemon previously could not authenticate; (c) a one-time migration of
#          deferred-wrap artifacts from the old top-level .agentic/ layout to the
#          new .agentic/wrap/ subdirectory; and (d) the self-healing
#          `.agentic/wrap/claude-host` sentinel write (MAJOR-B) plus a guarded,
#          detached launch of the deferred-wrap daemon. It is the FIRST and only
#          SessionStart registration install.sh makes; the version-check script
#          is no longer wired directly - it is invoked from here.
# Public API: bash hooks/sessionstart.d/010-session-start-wrap.sh
#             (reads the SessionStart JSON payload on stdin, extracts `cwd`;
#              writes a single JSON object to stdout; always exits 0.)
# Upstream deps: $HOOKS_ROOT/session-start-version-check.sh (version notice),
#                jq OR a grep/sed fallback (extract `cwd` from stdin),
#                node + $HOOKS_ROOT/wrap-daemon.js (detached daemon launch),
#                .agentic/config.json (`deferred_wrap_daemon` toggle),
#                AGENTIC_WRAP_DAEMON env var (loop-guard),
#                $HOOKS_ROOT/lib/wrap-marker.js (wrapLockProvablyStaleLegacy - migration).
# Downstream consumers: Claude Code SessionStart hook, wired via
#                       ~/.claude/settings.json by .claude/install.sh.
# Failure modes: ALWAYS exits 0 (fail-open). A missing field, missing jq,
#                missing config, or a daemon-launch error never blocks the
#                session. The sentinel write is create-if-absent and swallows
#                every fs error. The migration block is fully || true-guarded
#                (set -euo pipefail safe) and never blocks the session.
#                There is NO stale-sweep (CRITICAL-A): this script never
#                promotes a marker, it only relocates old-layout artifacts once
#                per project, self-heals the sentinel, and conditionally launches
#                the daemon.
# Performance: one subshell to the version-check core (sub-10ms read path, no
#              blocking network), one defensive stdin parse, a migration sweep
#              (fast: mv only needed when old-path files exist), and at most one
#              detached daemon spawn that the hook never waits on.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Capture the SessionStart payload from stdin (we need `cwd`) ---
# The version-check wrapper discards stdin; here we must read it. Never block:
# if no payload arrives, `payload` is empty and `cwd` falls back to PWD.
payload=""
payload="$(cat 2>/dev/null || true)"

# --- Extract `cwd` defensively: jq when present, else a grep/sed fallback ---
extract_cwd() {
  local json="$1"
  local val=""
  if [[ -z "$json" ]]; then
    return 0
  fi
  if command -v jq >/dev/null 2>&1; then
    val="$(printf '%s' "$json" | jq -r '.cwd // empty' 2>/dev/null || true)"
  fi
  if [[ -z "$val" ]]; then
    # Fallback: first "cwd": "..." occurrence. Tolerates surrounding whitespace.
    val="$(printf '%s' "$json" \
      | grep -o '"cwd"[[:space:]]*:[[:space:]]*"[^"]*"' \
      | head -n1 \
      | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/' 2>/dev/null || true)"
  fi
  printf '%s' "$val"
}

cwd="$(extract_cwd "$payload")"
# Fall back to the process working directory when the payload omits cwd.
if [[ -z "$cwd" ]]; then
  cwd="${PWD:-.}"
fi

# --- (a) Version-update notice: reuse the existing version-check wrapper ---
# It emits a JSON object; we want only its `systemMessage` text. Re-feed the
# original payload on stdin (it drains and ignores it). Fail-open to empty.
version_msg=""
VERSION_CHECK="$HOOKS_ROOT/session-start-version-check.sh"
if [[ -f "$VERSION_CHECK" ]]; then
  version_json="$(printf '%s' "$payload" | bash "$VERSION_CHECK" 2>/dev/null || true)"
  if [[ -n "$version_json" ]]; then
    version_msg="$(printf '%s' "$version_json" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('systemMessage', '') or '')
except Exception:
    print('')
" 2>/dev/null || true)"
  fi
fi

# --- (b) One-time migration: relocate old-layout artifacts to .agentic/wrap/ ---
# Runs BEFORE the .claude-host self-heal and daemon launch so no lock is held yet.
# Every command is || true-guarded (set -euo pipefail safety; a failure must never
# abort the SessionStart hook or skip the daemon launch).
# ACCEPTED cross-version window: if an OLD-code session and a NEW-code session run
# concurrently during an in-place upgrade, they may use different lock paths
# (.agentic/wrap.lock vs .agentic/wrap/lock). This race is bounded to a transient
# recency-label discrepancy in context.md (a convenience label, not committed work).
# It self-heals on the next clean SessionStart once both sessions use new-code.
# No "lost-update" of committed work occurs; the window is accepted and documented.
{
  wd="$cwd/.agentic"
  STALE_MS=1800000  # 30 * 60 * 1000 ms - matches daemon default reclaim window

  # Ensure destination directories exist (idempotent).
  mkdir -p "$wd/wrap" "$wd/wrap/heartbeats" 2>/dev/null || true

  # --- Simple file/dir relocation (OLD -> NEW, idempotent via [ ! -e NEW ]) ---
  [ -e "$wd/.last-wrap"              ] && [ ! -e "$wd/wrap/last-wrap"             ] && mv "$wd/.last-wrap"              "$wd/wrap/last-wrap"              || true
  [ -e "$wd/wrap-daemon.pid"         ] && [ ! -e "$wd/wrap/daemon.pid"            ] && mv "$wd/wrap-daemon.pid"         "$wd/wrap/daemon.pid"             || true
  [ -e "$wd/wrap-daemon.log"         ] && [ ! -e "$wd/wrap/daemon.log"            ] && mv "$wd/wrap-daemon.log"         "$wd/wrap/daemon.log"             || true
  [ -e "$wd/wrap-daemon.log.1"       ] && [ ! -e "$wd/wrap/daemon.log.1"          ] && mv "$wd/wrap-daemon.log.1"       "$wd/wrap/daemon.log.1"           || true
  [ -e "$wd/wrap-daemon-auth-failed" ] && [ ! -e "$wd/wrap/daemon-auth-failed"    ] && mv "$wd/wrap-daemon-auth-failed" "$wd/wrap/daemon-auth-failed"     || true
  [ -e "$wd/.stop-deferred-activity.jsonl" ] && [ ! -e "$wd/wrap/deferred-activity.jsonl" ] && mv "$wd/.stop-deferred-activity.jsonl" "$wd/wrap/deferred-activity.jsonl" || true
  [ -e "$wd/.claude-host"                  ] && [ ! -e "$wd/wrap/claude-host"              ] && mv "$wd/.claude-host"                  "$wd/wrap/claude-host"              || true

  # --- Marker relocation: wrap-pending-<sid>.json -> wrap/pending-<sid>.json ---
  # Strip the "wrap-" prefix from the basename when moving into the new directory.
  for old_marker in "$wd"/wrap-pending-*.json; do
    [ -e "$old_marker" ] || continue
    b="$(basename "$old_marker")"
    new_marker="$wd/wrap/${b#wrap-}"
    [ ! -e "$new_marker" ] && mv "$old_marker" "$new_marker" || true
  done

  # --- Heartbeat relocation: .heartbeats/<sid> -> wrap/heartbeats/<sid> ---
  if [ -d "$wd/.heartbeats" ]; then
    for hb in "$wd/.heartbeats/"*; do
      [ -e "$hb" ] || continue
      mv "$hb" "$wd/wrap/heartbeats/$(basename "$hb")" 2>/dev/null || true
    done
    rmdir "$wd/.heartbeats" 2>/dev/null || true
  fi

  # --- Lock relocation: only when PROVABLY stale (never yanks a live lock) ---
  # Uses wrapLockProvablyStaleLegacy from the lib (exit 0 = stale = move; else KEEP).
  # Fail-open: any node error is treated as KEEP (|| true).
  if [ -e "$wd/wrap.lock" ] && [ ! -e "$wd/wrap/lock" ]; then
    if node -e 'try{const l=require(process.argv[1]); process.exit(l.wrapLockProvablyStaleLegacy(process.argv[2], Number(process.argv[3]))?0:1)}catch(_){process.exit(1)}' "$HOOKS_ROOT/lib/wrap-marker.js" "$cwd" "$STALE_MS" 2>/dev/null; then
      mv "$wd/wrap.lock" "$wd/wrap/lock" || true
    fi
  fi

  # --- Drain-temp sweep: remove orphaned rename-drain temps from any path ---
  # NEW path (post-migration):
  rm -f "$wd/wrap/deferred-activity.jsonl.draining."* 2>/dev/null || true
  # OLD path (one-time, for sessions that crashed mid-drain before migration):
  rm -f "$wd/.stop-deferred-activity.jsonl.draining."* 2>/dev/null || true
} || true

# --- (b) Auth-failed notice: surface a one-liner when the daemon flagged it ---
auth_msg=""
if [[ -f "$cwd/.agentic/wrap/daemon-auth-failed" ]]; then
  auth_msg="deferred-wrap daemon could not authenticate; run \`claude auth login\` (see .agentic/wrap/daemon-auth-failed)."
fi

# --- (c) Self-heal the .agentic/wrap/claude-host sentinel (MAJOR-B) ---
# UNCONDITIONAL: not suppressed by the AGENTIC_WRAP_DAEMON loop-guard. Writing a
# true fact is harmless; it only gates Step-0a staging (itself guard-suppressed).
# create-if-absent, fully fail-open. This is what activates the feature on
# existing installs without an install.sh re-run.
{
  mkdir -p "$cwd/.agentic/wrap" 2>/dev/null || true
  if [[ ! -f "$cwd/.agentic/wrap/claude-host" ]]; then
    : > "$cwd/.agentic/wrap/claude-host" 2>/dev/null || true
  fi
} || true

# --- (d) Launch the deferred-wrap daemon detached (toggle true, not guarded) ---
# Gate 1: never spawn a daemon from inside a daemon-driven headless run.
# Gate 2: only when `deferred_wrap_daemon` is true in the project config.
# Mirrors the version-check-core.sh detached fire-and-forget pattern.
daemon_enabled() {
  local config="$cwd/.agentic/config.json"
  [[ -f "$config" ]] || return 1
  python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        sys.exit(0 if json.load(f).get('deferred_wrap_daemon') is True else 1)
except Exception:
    sys.exit(1)
" "$config" 2>/dev/null
}

if [[ "${AGENTIC_WRAP_DAEMON:-}" != "1" ]] && daemon_enabled; then
  DAEMON="$HOOKS_ROOT/wrap-daemon.js"
  if [[ -f "$DAEMON" ]] && command -v node >/dev/null 2>&1; then
    # Detached, fully-redirected so the hook returns immediately and never
    # blocks on the daemon. The daemon owns its own singleton pid lock, so a
    # redundant launch is a cheap no-op.
    nohup node "$DAEMON" "$cwd" </dev/null >/dev/null 2>&1 &
    disown 2>/dev/null || true
  fi
fi

# --- Compose + emit a single JSON object ---
# Join the version notice and the auth-failed notice with a blank line. When
# both are empty, emit a bare suppressOutput object. AGENTIC_QUIET=1 suppresses
# the user-facing message but still satisfies the SessionStart JSON contract.
combined=""
if [[ "${AGENTIC_QUIET:-}" != "1" ]]; then
  if [[ -n "$version_msg" && -n "$auth_msg" ]]; then
    combined="$version_msg"$'\n\n'"$auth_msg"
  elif [[ -n "$version_msg" ]]; then
    combined="$version_msg"
  elif [[ -n "$auth_msg" ]]; then
    combined="$auth_msg"
  fi
fi

if [[ -n "$combined" ]]; then
  python3 -c "
import json, sys
print(json.dumps({'systemMessage': sys.argv[1], 'suppressOutput': True}))
" "$combined" 2>/dev/null || printf '{"suppressOutput": true}\n'
else
  printf '{"suppressOutput": true}\n'
fi

exit 0
