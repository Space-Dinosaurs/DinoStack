#!/bin/bash
#
# Purpose: Read-only preflight/health-check for the scheduled DinoStack
#          worktree-reap report. Confirms the LaunchAgent is loaded, the
#          repo-discovery config is non-empty, and the last run (if any)
#          happened recently. Posts NOTHING, removes NOTHING, runs no
#          report. Usage (on your Mac): `bash verify.sh`.
#
# Public API: none (not sourced or imported; run standalone as `bash
#             verify.sh`).
#
# Upstream deps: python3 (config JSON parse); launchctl (plist load check);
#                ~/.dinostack-worktree-reap (run root - copied tool, logs,
#                config, deployed by install.sh); ~/Library/LaunchAgents
#                plist; ~/.agentic/cleanup-worktrees.json.
#
# Downstream consumers: a human confirming the install is healthy, at any
#                        time; the README's "Test immediately" section.
#
# Failure modes: exits 1 via `fail()` on the first unmet precondition (run
#                root missing, copied tool missing, config missing/empty,
#                plist missing, launchd job not loaded) - never silently
#                partial. A stale (>48h) last-run log is a WARN, not a
#                failure - the job may simply not have fired yet on a fresh
#                install.
#
# Performance: a handful of file-existence checks plus one launchctl call;
#              negligible.
#
# Usage (on your Mac):  bash verify.sh
set -u

LABEL="com.spacedinosaurs.dinostack-worktree-reap"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
RUNROOT="$HOME/.dinostack-worktree-reap"
LOG_DIR="$RUNROOT/logs"
CLEANUP_CONFIG="$HOME/.agentic/cleanup-worktrees.json"
UID_NUM="$(id -u)"

mkdir -p "$LOG_DIR" 2>/dev/null
LOG="$LOG_DIR/verify-$(date +%Y%m%d-%H%M%S).log"
if [[ -w "$LOG_DIR" ]]; then
  exec > >(tee "$LOG") 2>&1
fi

echo "=== verify: $(date) ==="
fail() { echo "FAIL: $1"; echo "=== verify FAILED ==="; exit 1; }

echo "-- run root --"
if [[ -d "$RUNROOT" ]]; then
  echo "run root: $RUNROOT (present)"
else
  fail "run root $RUNROOT not found - run install.sh first"
fi

echo
echo "-- copied tool --"
DS_CLEANUP="$RUNROOT/bin/ds-cleanup-worktrees"
WORKTREE_MODEL="$RUNROOT/bin/tests/worktree_model.py"
[[ -f "$DS_CLEANUP" ]] || fail "$DS_CLEANUP missing - run install.sh"
[[ -f "$WORKTREE_MODEL" ]] || fail "$WORKTREE_MODEL missing - run install.sh"
echo "ds-cleanup-worktrees: present"
echo "worktree_model.py   : present"

echo
echo "-- repo-discovery config --"
if [[ ! -f "$CLEANUP_CONFIG" ]]; then
  fail "$CLEANUP_CONFIG not found - run 'ds-cleanup-worktrees --init-config' or install.sh"
fi
EMPTY="$(python3 - "$CLEANUP_CONFIG" <<'PYEOF' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    print("unreadable")
    sys.exit(0)
roots = data.get("roots") or []
repos = data.get("repos") or []
print("empty" if not roots and not repos else "nonempty")
PYEOF
)"
[[ "$EMPTY" == "nonempty" ]] || fail "$CLEANUP_CONFIG has zero roots and zero repos (or is unreadable: $EMPTY)"
echo "config: $CLEANUP_CONFIG (non-empty)"

echo
echo "-- launchd agent --"
if [[ -f "$PLIST_DEST" ]]; then
  echo "plist: $PLIST_DEST (present)"
else
  fail "plist $PLIST_DEST not found - run install.sh"
fi
if launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1; then
  echo "launchd: loaded (gui/$UID_NUM/$LABEL)"
else
  fail "launchd job gui/$UID_NUM/$LABEL is not loaded - run install.sh"
fi

echo
echo "-- last run --"
LAST_LOG="$(ls -t "$LOG_DIR"/run-*.log 2>/dev/null | head -1)"
if [[ -z "$LAST_LOG" ]]; then
  echo "WARN: no run-*.log found yet - the job hasn't fired. Trigger one with:"
  echo "      launchctl kickstart -k \"gui/$UID_NUM/$LABEL\""
else
  AGE_HOURS=$(( ( $(date +%s) - $(stat -f %m "$LAST_LOG" 2>/dev/null || stat -c %Y "$LAST_LOG") ) / 3600 ))
  echo "last run: $LAST_LOG (${AGE_HOURS}h ago)"
  if [[ "$AGE_HOURS" -gt 48 ]]; then
    echo "WARN: last run is over 48h old for a daily job - check launchd status and the log."
  fi
fi

echo
echo "=== verify OK ==="
