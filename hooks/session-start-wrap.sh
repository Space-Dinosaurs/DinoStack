#!/usr/bin/env bash
# Purpose: Claude Code SessionStart wrapper for the deferred-wrap feature. It
#          composes THREE concerns into a single fail-open SessionStart hook:
#          (a) the "newer version available" notice (delegated to the existing
#          version-check wrapper); (b) a one-line auth-failed notice when the
#          daemon previously could not authenticate; and (c) the self-healing
#          `.agentic/.claude-host` sentinel write (MAJOR-B) plus a guarded,
#          detached launch of the deferred-wrap daemon. It is the FIRST and only
#          SessionStart registration install.sh makes; the version-check script
#          is no longer wired directly - it is invoked from here.
# Public API: bash hooks/session-start-wrap.sh
#             (reads the SessionStart JSON payload on stdin, extracts `cwd`;
#              writes a single JSON object to stdout; always exits 0.)
# Upstream deps: hooks/session-start-version-check.sh (version notice),
#                jq OR a grep/sed fallback (extract `cwd` from stdin),
#                node + hooks/wrap-daemon.js (detached daemon launch),
#                .agentic/config.json (`deferred_wrap_daemon` toggle),
#                AGENTIC_WRAP_DAEMON env var (loop-guard).
# Downstream consumers: Claude Code SessionStart hook, wired via
#                       ~/.claude/settings.json by .claude/install.sh.
# Failure modes: ALWAYS exits 0 (fail-open). A missing field, missing jq,
#                missing config, or a daemon-launch error never blocks the
#                session. The sentinel write is create-if-absent and swallows
#                every fs error. There is NO stale-sweep (CRITICAL-A): this
#                script never promotes a marker, it only self-heals the sentinel
#                and conditionally launches the daemon.
# Performance: one subshell to the version-check core (sub-10ms read path, no
#              blocking network), one defensive stdin parse, and at most one
#              detached daemon spawn that the hook never waits on.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
VERSION_CHECK="$SCRIPT_DIR/session-start-version-check.sh"
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

# --- (b) Auth-failed notice: surface a one-liner when the daemon flagged it ---
auth_msg=""
if [[ -f "$cwd/.agentic/wrap-daemon-auth-failed" ]]; then
  auth_msg="deferred-wrap daemon could not authenticate; run \`claude auth login\` (see .agentic/wrap-daemon-auth-failed)."
fi

# --- (c) Self-heal the .claude-host sentinel (MAJOR-B) ---
# UNCONDITIONAL: not suppressed by the AGENTIC_WRAP_DAEMON loop-guard. Writing a
# true fact is harmless; it only gates Step-0a staging (itself guard-suppressed).
# create-if-absent, fully fail-open. This is what activates the feature on
# existing installs without an install.sh re-run.
{
  mkdir -p "$cwd/.agentic" 2>/dev/null || true
  if [[ ! -f "$cwd/.agentic/.claude-host" ]]; then
    : > "$cwd/.agentic/.claude-host" 2>/dev/null || true
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
  DAEMON="$SCRIPT_DIR/wrap-daemon.js"
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
