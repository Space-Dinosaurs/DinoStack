#!/bin/bash
#
# Purpose: Runner for the scheduled DinoStack worktree-reap report. Invoked
#          by launchd, once daily. Runs the deep, machine-readable
#          `ds-cleanup-worktrees --multi-repo --report --json` tier against
#          every repo named in ~/.agentic/cleanup-worktrees.json, summarizes
#          the worst ~5 repos by non-root worktree count, and notifies via a
#          best-effort macOS banner plus a Telegram push. STRUCTURALLY
#          READ-ONLY: never invokes a sweep, `--archive-unproven`, or any
#          removal-capable flag - `--report` cannot remove anything under any
#          combination of flags (see content/commands/ds-cleanup-worktrees.md).
#
# Public API: none (not sourced or imported; invoked as a standalone script
#             by launchd or manually via `bash run.sh`).
#
# Upstream deps: config.env (DS_CLEANUP_BIN, PYTHON_BIN, LOG_DIR, EXTRA_PATH,
#                optional MAX_REPOS - written by install.sh, MAX_REPOS is
#                hand-added by an operator who wants repo discovery bounded);
#                optional telegram.env
#                (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID - same variable names
#                as dinostack-pr-review's telegram.env, copy or symlink it);
#                $DS_CLEANUP_BIN, itself a two-file copy of
#                bin/ds-cleanup-worktrees + bin/tests/worktree_model.py
#                deployed by install.sh in their original relative layout
#                (bin/ + bin/tests/) - that layout is load-bearing, since the
#                tool imports worktree_model relative to its own resolved
#                location; ~/.agentic/cleanup-worktrees.json (read by
#                ds-cleanup-worktrees itself, not by this script directly);
#                osascript (best-effort, macOS only); curl (Telegram push).
#
# Downstream consumers: the launchd job installed by install.sh
#                        (com.spacedinosaurs.dinostack-worktree-reap); a
#                        human running it manually to test the pipeline.
#
# Failure modes: rc is a tri-state, not boolean - ds-cleanup-worktrees itself
#                uses rc=1 for "some repos in a scanned root had per-repo
#                errors, but the rows that DID resolve are still populated
#                and trustworthy" (same contract Unit B's hook applies to
#                this tool), so rc=1 with non-empty, parseable rows proceeds
#                to the worst-repos summary with an added one-line note,
#                rather than being treated as total failure. Only rc values
#                outside {0,1}, an empty RAW file, or unparseable/rows-empty
#                JSON send the distinct failure alert (never silence) and
#                skip the summary - stale summary state is never notified as
#                if it were current. Every run is logged to
#                logs/run-<timestamp>.log regardless of outcome.
#                Telegram/osascript failures are swallowed (best-effort,
#                never fail the run over a notification channel).
#
# Performance: dominated by ds-cleanup-worktrees' own deep-tier cost (a full
#              per-entry evaluation per repo, network calls unless --no-gh);
#              this script's own overhead is negligible (JSON parse + string
#              formatting).
#
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # = ~/.dinostack-worktree-reap

if [[ -f "$SCRIPT_DIR/config.env" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/config.env"
else
  echo "ERROR: $SCRIPT_DIR/config.env not found. Run install.sh from the repo first." >&2
  exit 1
fi

: "${DS_CLEANUP_BIN:?config.env is missing DS_CLEANUP_BIN - re-run install.sh}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG_DIR="${LOG_DIR:-$SCRIPT_DIR/logs}"

# Make python3 / gh discoverable under launchd's minimal environment.
if [[ -n "${EXTRA_PATH:-}" ]]; then
  export PATH="$EXTRA_PATH:$PATH"
fi

mkdir -p "$LOG_DIR"

TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/run-$TS.log"
RAW="$LOG_DIR/run-$TS.json"   # raw ds-cleanup-worktrees --json output

send_telegram() {
  local text="$1"
  local tg_env="$SCRIPT_DIR/telegram.env"
  [[ -f "$tg_env" ]] || return 0
  # shellcheck disable=SC1090
  source "$tg_env"
  [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]] || return 0
  # curl -sS does not echo the URL, so the token never lands in the log.
  curl -sS -m 25 -o /dev/null \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${text}" >>"$LOG" 2>&1 || true
}

{
  echo "=== DinoStack worktree-reap report run: $(date) ==="
  echo "ds-cleanup-worktrees: $DS_CLEANUP_BIN"
  echo "python3             : $PYTHON_BIN"
  echo "config              : ${HOME}/.agentic/cleanup-worktrees.json"
  echo "PATH                : $PATH"
  echo "----------------------------------------"

  # DEEP tier, JSON - MANDATORY: never a bare sweep, never --archive-unproven.
  # --report is structurally read-only; this invocation never mutates any
  # target repo. MAX_REPOS is optional (unset by default; hand-add to
  # config.env to bound discovery cost / exercise the `truncated` summary
  # line below).
  MAX_REPOS_ARGS=()
  if [[ -n "${MAX_REPOS:-}" ]]; then
    MAX_REPOS_ARGS=(--max-repos "$MAX_REPOS")
  fi
  "$PYTHON_BIN" "$DS_CLEANUP_BIN" --multi-repo --report --json "${MAX_REPOS_ARGS[@]+"${MAX_REPOS_ARGS[@]}"}" >"$RAW"
  rc=$?

  echo "----------------------------------------"
  echo "=== ds-cleanup-worktrees exit code: $rc ==="
} >>"$LOG" 2>&1

# rc is a tri-state: 0 (clean), 1 (some repos in a scanned root had
# per-repo errors, but rows still populated for the rest), or anything else
# (total failure). Only rc values outside {0,1}, an empty RAW file, or
# unparseable/rows-empty JSON count as a failed run.
RC_NOTE=""
if [[ "${rc:-2}" -ne 0 && "${rc:-2}" -ne 1 ]] || [[ ! -s "$RAW" ]]; then
  echo "run failed (rc=${rc:-?}) - skipping worst-repos summary; state may be stale" >>"$LOG"
  HINT="$(tail -5 "$LOG" 2>/dev/null | tr '\n' ' ' | cut -c1-300)"
  send_telegram "❌ DinoStack worktree-reap report FAILED (exit ${rc:-?}) - no summary this run.
${HINT}"
  # This branch is entered only on an already-detected failure (rc outside
  # {0,1}, or an empty RAW file even when rc=0) - always exit nonzero here so
  # launchd never records a FAILED-alerted run as a success.
  if [[ "${rc:-1}" -eq 0 ]]; then
    exit 1
  fi
  exit "$rc"
fi

if [[ "$rc" -eq 1 ]]; then
  # rc=1 only proceeds when the rows the tool DID emit are present and
  # parseable - an rc=1 run with empty/unparseable rows carries no usable
  # signal and is still a failed run.
  ROWS_COUNT="$("$PYTHON_BIN" - "$RAW" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    print("unparseable")
    sys.exit(0)
rows = data.get("rows")
print(len(rows) if isinstance(rows, list) else "unparseable")
PYEOF
)"
  if [[ "$ROWS_COUNT" == "unparseable" || "$ROWS_COUNT" -eq 0 ]]; then
    echo "run failed (rc=1, rows=$ROWS_COUNT) - skipping worst-repos summary; state may be stale" >>"$LOG"
    HINT="$(tail -5 "$LOG" 2>/dev/null | tr '\n' ' ' | cut -c1-300)"
    send_telegram "❌ DinoStack worktree-reap report FAILED (exit 1, unparseable/empty rows) - no summary this run.
${HINT}"
    exit 1
  fi
  RC_NOTE="(note: some repos had per-repo errors (rc=1))"
  echo "NOTE: ds-cleanup-worktrees exited 1 (per-repo errors) but rows are populated ($ROWS_COUNT row(s)) - proceeding with summary." >>"$LOG"
fi

# --- Build the worst-N-repos summary from the JSON --------------------------
# Sorted worst-first by non-root worktree count (top 5), independent of
# whichever tiebreak order the tool itself already applied.
SUMMARY="$("$PYTHON_BIN" - "$RAW" <<'PYEOF'
import json, sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except Exception as exc:
    print(f"(could not parse report JSON: {exc})")
    sys.exit(0)

rows = data.get("rows") or []
truncated = bool(data.get("truncated"))
rows = sorted(rows, key=lambda r: -(r.get("nonroot_worktrees") or 0))
top = rows[:5]

if not top:
    print("No repos discovered - check ~/.agentic/cleanup-worktrees.json.")
    sys.exit(0)

lines = []
for r in top:
    repo = r.get("repo", "?")
    count = r.get("nonroot_worktrees", "?")
    eligible = r.get("eligible")
    suffix = f" ({eligible} eligible to remove)" if eligible else ""
    lines.append(f"{count} worktree(s){suffix}  {repo}")

if truncated:
    lines.append("(list truncated by --max-repos)")

print("\n".join(lines))
PYEOF
)"

echo "worst-repos summary:" >>"$LOG"
echo "$SUMMARY" >>"$LOG"
if [[ -n "$RC_NOTE" ]]; then
  echo "$RC_NOTE" >>"$LOG"
fi

# (1) Local macOS banner - best-effort; macOS often suppresses launchd-posted
#     notifications, so this is a nicety, not the primary channel.
if command -v osascript >/dev/null 2>&1; then
  FIRST_LINE="$(echo "$SUMMARY" | head -1)"
  MSG_ESC="${FIRST_LINE//\"/\'}"
  osascript -e "display notification \"$MSG_ESC\" with title \"DinoStack worktree-reap\" sound name \"Glass\"" \
    >>"$LOG" 2>&1 || true
fi

# (2) Telegram push - reliable, reaches your phone.
TG_TEXT="🦕 DinoStack worktree-reap - worst repos:
${SUMMARY}"
if [[ -n "$RC_NOTE" ]]; then
  TG_TEXT="${TG_TEXT}
${RC_NOTE}"
fi
send_telegram "$TG_TEXT"
echo "notified: worst-repos summary sent" >>"$LOG"

# Keep the log directory tidy: drop runs older than 30 days.
find "$LOG_DIR" -name 'run-*.log'  -mtime +30 -delete 2>/dev/null || true
find "$LOG_DIR" -name 'run-*.json' -mtime +30 -delete 2>/dev/null || true

exit 0
