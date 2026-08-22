#!/bin/bash
#
# Purpose: One-time installer for the scheduled DinoStack worktree-reap
#          report (macOS launchd). Run ON YOUR MAC from the repo:
#          `bash install.sh`. This job NEVER removes anything - it runs
#          `ds-cleanup-worktrees --multi-repo --report --json`
#          (structurally read-only) against every repo the operator's
#          ~/.agentic/cleanup-worktrees.json already names, and pushes a
#          worst-repos summary via macOS notification + Telegram. It exists
#          to catch machine-wide worktree accumulation between whatever
#          nudges already fire inside individual sessions (see README
#          "Retirement condition").
#
# Public API: none (not sourced or imported; run standalone as `bash
#             install.sh`).
#
# Upstream deps: python3 (required); gh (optional, for a launchd-safe PATH);
#                bin/ds-cleanup-worktrees + bin/tests/worktree_model.py from
#                this repo checkout (copied into the run root, original
#                relative layout preserved - load-bearing, see run.sh);
#                run.sh and com.spacedinosaurs.dinostack-worktree-reap.plist.template
#                (this directory); ~/.agentic/cleanup-worktrees.json (read,
#                never invented - the installer refuses to proceed if it's
#                missing/empty and the operator declines to scaffold it);
#                launchctl (bootstrap/load the LaunchAgent).
#
# Downstream consumers: a human running it manually, once per machine (and
#                        again after any local change to
#                        bin/ds-cleanup-worktrees/worktree_model.py, since the
#                        deployed copy is a install-time snapshot - see
#                        README's "Trade-off" note).
#
# Failure modes: to avoid macOS privacy protection (TCC) on ~/Documents, the
#                job does NOT run from the repo - this installer copies the
#                two files it needs into ~/.dinostack-worktree-reap/bin/, and
#                the launchd job runs entirely from there. No Full Disk
#                Access required, and no target repo's own files are ever
#                copied (this tool is read-only against real repo paths -
#                unlike the pr-review package, which does copy its own
#                PROJECT_DIR). Refuses to install the LaunchAgent against a
#                missing/unreadable/empty cleanup-worktrees.json - fails loud
#                rather than scheduling a job with nothing to sweep.
#
# Performance: one-time setup cost (a few file copies, a config write, a
#              launchctl bootstrap call); negligible.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNROOT="$HOME/.dinostack-worktree-reap"     # non-protected location
BIN_DIR="$RUNROOT/bin"
TESTS_DIR="$BIN_DIR/tests"
LOG_DIR="$RUNROOT/logs"

LABEL="com.spacedinosaurs.dinostack-worktree-reap"
TEMPLATE="$SCRIPT_DIR/com.spacedinosaurs.dinostack-worktree-reap.plist.template"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
RUN_SH="$RUNROOT/run.sh"
CONFIG="$RUNROOT/config.env"
LAUNCHD_LOG="$LOG_DIR/launchd.log"
CLEANUP_CONFIG="$HOME/.agentic/cleanup-worktrees.json"

echo "==> DinoStack worktree-reap scheduler installer (report-only, no Full Disk Access)"
echo "    repo     : $REPO_ROOT"
echo "    run root : $RUNROOT"

# --- Resolve required binaries ---------------------------------------------
PYTHON_BIN="$(command -v python3 || true)"
[[ -z "$PYTHON_BIN" ]] && { echo "ERROR: 'python3' not found on PATH." >&2; exit 1; }
echo "    python3  : $PYTHON_BIN"

# --- Build a robust PATH (launchd has a minimal one) -----------------------
declare -a DIRS=()
[[ -n "$PYTHON_BIN" ]] && DIRS+=("$(dirname "$PYTHON_BIN")")
GH_BIN="$(command -v gh || true)"
[[ -n "$GH_BIN" ]] && DIRS+=("$(dirname "$GH_BIN")")
DIRS+=("/opt/homebrew/bin" "/usr/local/bin" "$HOME/.local/bin" "/usr/bin" "/bin" "/usr/sbin" "/sbin")
EXTRA_PATH=""
for d in "${DIRS[@]}"; do
  [[ -d "$d" ]] || continue
  case ":$EXTRA_PATH:" in
    *":$d:"*) ;;
    *) EXTRA_PATH="${EXTRA_PATH:+$EXTRA_PATH:}$d" ;;
  esac
done
echo "    PATH     : $EXTRA_PATH"

# --- Lay out the run root ---------------------------------------------------
mkdir -p "$RUNROOT" "$LOG_DIR" "$TESTS_DIR"

# Copy EXACTLY the two files ds-cleanup-worktrees needs, preserving the
# relative bin/ + bin/tests/ layout - the tool resolves its own location
# (Path(__file__).resolve().parent) and imports worktree_model from
# "<that dir>/tests", so the layout is load-bearing, not cosmetic.
cp "$REPO_ROOT/bin/ds-cleanup-worktrees"        "$BIN_DIR/ds-cleanup-worktrees"
cp "$REPO_ROOT/bin/tests/worktree_model.py"     "$TESTS_DIR/worktree_model.py"
chmod +x "$BIN_DIR/ds-cleanup-worktrees"
echo "==> copied bin/ds-cleanup-worktrees + bin/tests/worktree_model.py into $BIN_DIR"

cp "$SCRIPT_DIR/run.sh" "$RUN_SH"
chmod +x "$RUN_SH"

# --- Write machine-specific config.env -------------------------------------
cat >"$CONFIG" <<EOF
# Generated by install.sh on $(date). Machine-specific - do not commit.
DS_CLEANUP_BIN="$BIN_DIR/ds-cleanup-worktrees"
PYTHON_BIN="$PYTHON_BIN"
LOG_DIR="$LOG_DIR"
EXTRA_PATH="$EXTRA_PATH"
EOF
echo "==> wrote $CONFIG"

# --- Repo discovery: reuse ~/.agentic/cleanup-worktrees.json, no duplicate --
# config surface. Offer to scaffold it via --init-config when absent - never
# silently invent a config, and never install the LaunchAgent against a
# config that would sweep nothing.
# TTY-safe yes/no prompt (mirrors scripts/lib/identity.sh's ae_confirm): a
# bare `read -p` aborts under `set -euo pipefail` with piped stdin (the
# `curl | bash` path). Reads /dev/tty directly; defaults to "no" (and never
# aborts) when no tty is available.
ae_confirm() {
  local prompt="$1"
  local reply=""
  if [[ -r /dev/tty ]]; then
    read -p "$prompt" -n 1 -r reply </dev/tty || reply=""
    echo
  fi
  [[ "$reply" =~ ^[Yy]$ ]]
}

if [[ ! -f "$CLEANUP_CONFIG" ]]; then
  echo
  echo "No $CLEANUP_CONFIG found - this is the same config --multi-repo already uses."
  if ae_confirm "Run 'ds-cleanup-worktrees --init-config' now to scaffold it? [y/N] "; then
    "$PYTHON_BIN" "$BIN_DIR/ds-cleanup-worktrees" --init-config || true
  else
    echo "    skipped - edit $CLEANUP_CONFIG by hand, or re-run install.sh."
  fi
fi

if [[ ! -f "$CLEANUP_CONFIG" ]]; then
  echo "ERROR: $CLEANUP_CONFIG still absent. Refusing to install the LaunchAgent -" >&2
  echo "       there is nothing for it to sweep. Create the config (see above), then re-run install.sh." >&2
  exit 1
fi

# Refuse to install against a config with zero roots AND zero repos - a
# structurally empty sweep target, same failure mode as a missing file.
ROOTS_AND_REPOS_EMPTY="$("$PYTHON_BIN" - "$CLEANUP_CONFIG" <<'PYEOF'
import json, sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except Exception as exc:
    print(f"unreadable: {exc}")
    sys.exit(0)
roots = data.get("roots") or []
repos = data.get("repos") or []
print("empty" if not roots and not repos else "nonempty")
PYEOF
)"
if [[ "$ROOTS_AND_REPOS_EMPTY" != "nonempty" ]]; then
  echo "ERROR: $CLEANUP_CONFIG has zero \"roots\" and zero \"repos\" entries" \
       "(or is unreadable: $ROOTS_AND_REPOS_EMPTY)." >&2
  echo "       Refusing to install the LaunchAgent - there is nothing for it to sweep." >&2
  echo "       Add at least one root/repo to $CLEANUP_CONFIG, then re-run install.sh." >&2
  exit 1
fi
echo "==> $CLEANUP_CONFIG has at least one root or repo - proceeding"

# --- Deploy the Telegram secrets template (never overwrite secrets) --------
TG_ENV="$RUNROOT/telegram.env"
if [[ ! -f "$TG_ENV" ]]; then
  cat >"$TG_ENV" <<'EOF'
# Telegram notifications for the worktree-reap report (git-ignored; keep private).
# Same variable names as dinostack-pr-review's telegram.env - copy or symlink
# that file here instead of re-running telegram-setup.sh:
#   cp ~/.dinostack-pr-review/telegram.env ~/.dinostack-worktree-reap/telegram.env
# or:
#   ln -s ~/.dinostack-pr-review/telegram.env ~/.dinostack-worktree-reap/telegram.env
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""
EOF
  chmod 600 "$TG_ENV"
  echo "==> created $TG_ENV (copy/symlink from dinostack-pr-review's telegram.env, or fill in by hand)"
else
  echo "==> kept existing $TG_ENV"
fi

# --- Render and install the launchd plist ----------------------------------
mkdir -p "$HOME/Library/LaunchAgents"
sed \
  -e "s|@LABEL@|$LABEL|g" \
  -e "s|@RUN_SH@|$RUN_SH|g" \
  -e "s|@PATH@|$EXTRA_PATH|g" \
  -e "s|@LAUNCHD_LOG@|$LAUNCHD_LOG|g" \
  "$TEMPLATE" >"$PLIST_DEST"
echo "==> wrote $PLIST_DEST"

UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || true
if launchctl bootstrap "gui/$UID_NUM" "$PLIST_DEST" 2>/dev/null; then
  launchctl enable "gui/$UID_NUM/$LABEL" 2>/dev/null || true
  echo "==> loaded via launchctl bootstrap"
else
  launchctl unload "$PLIST_DEST" >/dev/null 2>&1 || true
  launchctl load -w "$PLIST_DEST"
  echo "==> loaded via launchctl load"
fi

echo
echo "Done. Runs once daily (see the plist template for cadence), out of $RUNROOT."
echo "Report-only - never removes anything."
echo
echo "Trigger one now:"
echo "    launchctl kickstart -k \"gui/$UID_NUM/$LABEL\""
echo "Then watch the log:"
echo "    tail -f \"$LOG_DIR\"/run-*.log"
echo
echo "NOTE: after changing bin/ds-cleanup-worktrees or bin/tests/worktree_model.py"
echo "      in the repo, re-run this installer to resync the copies."
