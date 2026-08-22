#!/bin/bash
# Remove the scheduled DinoStack worktree-reap launchd agent.
set -euo pipefail

LABEL="com.spacedinosaurs.dinostack-worktree-reap"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
RUNROOT="$HOME/.dinostack-worktree-reap"
UID_NUM="$(id -u)"

launchctl bootout "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || \
  launchctl unload "$PLIST_DEST" >/dev/null 2>&1 || true

if [[ -f "$PLIST_DEST" ]]; then
  rm -f "$PLIST_DEST"
  echo "Removed $PLIST_DEST and unloaded the agent."
else
  echo "No plist at $PLIST_DEST - nothing to unload."
fi

echo
echo "The run root (copied tool, logs, config) is left in place:"
echo "    $RUNROOT"
echo "Delete it too with:  rm -rf \"$RUNROOT\""
