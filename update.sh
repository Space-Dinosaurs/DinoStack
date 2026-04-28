#!/usr/bin/env bash
set -euo pipefail

# update.sh — minimal launcher for the Node.js updater.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Node check — everything else is handled by the JS script
if ! command -v node >/dev/null 2>&1; then
  echo "error: 'node' not found on PATH — required by the update script." >&2
  exit 1
fi

exec node "$REPO_DIR/scripts/update.js" "$REPO_DIR" "$@"
