#!/usr/bin/env bash
# WorktreeRemove hook for a multi-repo workspace; pairs with worktree-create.sh.
# Installed by /ds-init-project; see content/references/subagent-protocol.md
# §Multi-repo workspace. stdin: hook JSON with `worktree_path`. Removal is
# delegated to ds-retire-carrier; exit 0 only when it retired the worktree.
set -euo pipefail

die() { echo "worktree-remove: ERROR: $*" >&2; exit 1; }

WT="$(python3 -c 'import json, sys; v = json.load(sys.stdin).get("worktree_path"); print(v if isinstance(v, str) else "")' 2>/dev/null)" \
  || die "could not parse hook input JSON"
[ -n "$WT" ] || die "hook input has no 'worktree_path' field"

if [ ! -e "$WT" ]; then
  echo "worktree-remove: $WT already gone" >&2
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WS="${CLAUDE_PROJECT_DIR:-$SCRIPT_DIR/../..}"
WS="$(cd "$WS" && pwd -P)" || die "workspace root not found: $WS"
ROOT="$WS/.worktrees"

WT="$(cd "$WT" && pwd -P)" || die "cannot resolve $WT"
case "$WT" in
  "$ROOT"/*/*) ;;
  *) die "refusing $WT: not under $ROOT/<repo>/<name>" ;;
esac
REL="${WT#"$ROOT"/}"
[[ "$REL" == */* && "${REL#*/}" != */* ]] || die "refusing $WT: not exactly $ROOT/<repo>/<name>"

cd "$WS"

RETIRE="$(command -v ds-retire-carrier 2>/dev/null || true)"
if [ -z "$RETIRE" ]; then
  AE_BOOT="$(python3 -c 'import json, os; print(json.load(open(os.path.expanduser("~/.agentic/agentic-engineering-config.json"))).get("repo_dir", ""))' 2>/dev/null || true)"
  LIB="${AE_BOOT:-$HOME/DinoStack}/scripts/lib/repo-dir.sh"
  if [ -f "$LIB" ]; then
    # shellcheck source=/dev/null
    . "$LIB"
    if resolve_repo_dir --quiet && [ -x "$AE_REPO_DIR/bin/ds-retire-carrier" ]; then
      RETIRE="$AE_REPO_DIR/bin/ds-retire-carrier"
    fi
  fi
fi
[ -n "$RETIRE" ] || die "ds-retire-carrier not found on PATH or in the DinoStack checkout; keeping $WT"

rc=0
"$RETIRE" --owner worktree-remove-hook "$WT" >&2 || rc=$?
[ "$rc" -eq 0 ] || die "ds-retire-carrier exited $rc; keeping $WT (see its hold record)"
exit 0
