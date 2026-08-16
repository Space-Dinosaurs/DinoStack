#!/usr/bin/env bash
# Purpose: Claude Code SessionStart wrapper for the deferred-wrap feature. It
#          composes SEVEN concerns into a single fail-open SessionStart hook:
#          (a) the "newer version available" notice (delegated to the existing
#          version-check wrapper); (b) a one-line auth-failed notice when the
#          daemon previously could not authenticate; (c) a one-time migration of
#          deferred-wrap artifacts from the old top-level .agentic/ layout to the
#          new .agentic/wrap/ subdirectory; (d) the self-healing
#          `.agentic/wrap/claude-host` sentinel write (MAJOR-B) plus a guarded,
#          detached launch of the deferred-wrap daemon; (e) a hooks-snapshot
#          staleness nudge (DS-54, hooks/lib/hooks-staleness-core.sh) when the
#          methodology checkout has never been snapshotted, is half-migrated
#          across adapters, or has moved since the last snapshot sync;
#          (f) a deferred-work open-count nudge (bin/ds-defer count) for the
#          Follow-up Ticket Creation Discipline's sink
#          (.agentic/deferred-work.jsonl); and (g) a worktree-accumulation
#          nudge (bin/ds-reap-worktrees --count-only) when the current
#          project's non-root worktree count is at or above a small
#          threshold - REPORT ONLY, this call site never removes a worktree.
#          It is the FIRST and only SessionStart registration install.sh
#          makes; the version-check script is no longer wired directly - it
#          is invoked from here.
# Public API: bash hooks/session-start-wrap.sh
#             (reads the SessionStart JSON payload on stdin, extracts `cwd`;
#              writes a single JSON object to stdout; always exits 0.)
# Upstream deps: hooks/session-start-version-check.sh (version notice),
#                hooks/lib/hooks-staleness-core.sh (hooks-snapshot staleness
#                  nudge),
#                hooks/lib/repo-root.sh (resolve_agentic_root - anchors every
#                  .agentic/ read/write below to the repo root instead of the
#                  raw payload cwd; empty output on resolution failure and
#                  every guarded block SKIPS its write rather than falling
#                  back to $cwd),
#                jq OR a grep/sed fallback (extract `cwd` from stdin),
#                node + hooks/wrap-daemon.js (detached daemon launch),
#                .agentic/config.json (`deferred_wrap_daemon` toggle),
#                AGENTIC_WRAP_DAEMON env var (loop-guard),
#                hooks/lib/wrap-marker.js (wrapLockProvablyStaleLegacy - migration),
#                hooks/lib/repo-dir-fallback.sh (resolve_ae_repo_dir_with_fallback -
#                  locates bin/ds-defer for the deferred-work nudge and
#                  bin/ds-reap-worktrees for the worktree-accumulation nudge;
#                  tries scripts/lib/repo-dir.sh first, falls back to reading
#                  $HOME/.agentic/agentic-engineering-config.json via python3
#                  and validating with git when that lib is absent, e.g. the
#                  deployed hooks-snapshot layout),
#                bin/ds-defer (deferred-work open-count query for the nudge;
#                  optional - a missing/unresolvable binary just yields an
#                  empty message piece via the `command -v ds-defer` fallback),
#                bin/ds-reap-worktrees (worktree-count query for the nudge,
#                  invoked --count-only; optional - a missing/
#                  unresolvable binary just yields an empty message piece via
#                  the `command -v ds-reap-worktrees` fallback), python3
#                  (bin/ds-reap-worktrees is a Python CLI).
# Downstream consumers: Claude Code SessionStart hook, wired via
#                       ~/.claude/settings.json by .claude/install.sh.
# Failure modes: ALWAYS exits 0 (fail-open). A missing field, missing jq,
#                missing config, or a daemon-launch error never blocks the
#                session. The sentinel write is create-if-absent and swallows
#                every fs error. The migration block is fully || true-guarded
#                (set -euo pipefail safe) and never blocks the session. The
#                staleness nudge (hooks-staleness-core.sh) is itself fail-open
#                and always exits 0; a missing script or any internal error
#                just yields an empty message piece. The deferred-work nudge
#                is likewise fail-open: an unresolvable bin/ds-defer, a
#                nonzero exit, or non-numeric output all degrade silently to
#                an empty message piece (`2>/dev/null || true`), never a
#                blocked session. The worktree-accumulation nudge is likewise
#                fail-open: an unresolvable bin/ds-reap-worktrees, a nonzero
#                exit, unparsable summary output, or a non-git `cwd` all
#                degrade silently to an empty message piece, never a blocked
#                session - and this call site NEVER removes a worktree
#                regardless of the count (report-only; removal remains
#                operator-invoked via `/ds-cleanup-worktrees` or a bare
#                `ds-reap-worktrees` with no --dry-run).
#                There is NO stale-sweep (CRITICAL-A): this script never
#                promotes a marker, it only relocates old-layout artifacts once
#                per project, self-heals the sentinel, and conditionally launches
#                the daemon.
# Performance: one subshell to the version-check core (sub-10ms read path, no
#              blocking network), one defensive stdin parse, a migration sweep
#              (fast: mv only needed when old-path files exist), one subshell
#              to the staleness core (a handful of file checks, fail-open), one
#              `bin/ds-defer count` subprocess for the deferred-work nudge (a
#              single-file JSONL read, no network - runs on EVERY session
#              start for EVERY project, not just when the sink is non-empty),
#              one `bin/ds-reap-worktrees --count-only` subprocess for the
#              worktree-accumulation nudge - a SINGLE `git worktree list
#              --porcelain` call, no network, no per-entry `git status`/
#              `git ls-remote`/`git merge-base`/`gh` calls of any kind (round-2
#              Skeptic Major 4/5 correction: the FIRST-round implementation
#              used `--dry-run --no-gh`, which still ran full per-entry
#              evaluation including `git ls-remote` - measured 14.94s against
#              this repo's live 38-worktree checkout on 2026-08-11, the exact
#              opposite of "no network" this section previously claimed.
#              `--count-only` measured 55ms against the same checkout at 37
#              worktrees on 2026-08-11 via `time python3 bin/ds-reap-worktrees
#              --repo <repo> --count-only` - see bin/ds-reap-worktrees's own
#              `--count-only` flag description for the mechanism), runs on
#              EVERY session start for EVERY project, same cadence as the
#              deferred-work nudge, and at most one detached daemon spawn
#              that the hook never waits on.

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

# --- Resolve the repo root ONCE, immediately after cwd is known ---
# Anchors every .agentic/ read/write below to the repo root instead of the
# raw payload cwd. On resolution failure resolved_root is an EMPTY STRING
# and every guarded block below SKIPS its .agentic/ write entirely - never
# falls back to $cwd, which would silently reproduce the bug this resolver
# exists to fix. See hooks/lib/repo-root.sh.
# shellcheck source=./lib/repo-root.sh
source "$SCRIPT_DIR/lib/repo-root.sh"
resolved_root="$(resolve_agentic_root "$cwd")"

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

# --- (a2) Hooks-snapshot staleness nudge (DS-54) ---
# Prints at most one line describing the methodology checkout's hook-snapshot
# state (half_applied / never_migrated / stale_but_stable), or nothing when
# current. Fully fail-open; a missing script or any internal error just
# leaves this piece empty.
staleness_msg=""
HOOKS_STALENESS_CORE="$SCRIPT_DIR/lib/hooks-staleness-core.sh"
if [[ -f "$HOOKS_STALENESS_CORE" ]]; then
  staleness_msg="$(bash "$HOOKS_STALENESS_CORE" 2>/dev/null || true)"
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
if [[ -n "$resolved_root" ]]; then
{
  wd="$resolved_root/.agentic"
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
    if node -e 'try{const l=require(process.argv[1]); process.exit(l.wrapLockProvablyStaleLegacy(process.argv[2], Number(process.argv[3]))?0:1)}catch(_){process.exit(1)}' "$SCRIPT_DIR/lib/wrap-marker.js" "$resolved_root" "$STALE_MS" 2>/dev/null; then
      mv "$wd/wrap.lock" "$wd/wrap/lock" || true
    fi
  fi

  # --- Drain-temp sweep: remove orphaned rename-drain temps from any path ---
  # NEW path (post-migration):
  rm -f "$wd/wrap/deferred-activity.jsonl.draining."* 2>/dev/null || true
  # OLD path (one-time, for sessions that crashed mid-drain before migration):
  rm -f "$wd/.stop-deferred-activity.jsonl.draining."* 2>/dev/null || true
} || true
fi

# --- (b) Auth-failed notice: surface a one-liner when the daemon flagged it ---
auth_msg=""
if [[ -n "$resolved_root" ]] && [[ -f "$resolved_root/.agentic/wrap/daemon-auth-failed" ]]; then
  auth_msg="deferred-wrap daemon could not authenticate; run \`claude auth login\` (see .agentic/wrap/daemon-auth-failed)."
fi

# --- (c) Self-heal the .agentic/wrap/claude-host sentinel (MAJOR-B) ---
# UNCONDITIONAL: not suppressed by the AGENTIC_WRAP_DAEMON loop-guard. Writing a
# true fact is harmless; it only gates Step-0a staging (itself guard-suppressed).
# create-if-absent, fully fail-open. This is what activates the feature on
# existing installs without an install.sh re-run. Guarded on resolved_root:
# this is the single highest-volume litter producer in the repo when
# unguarded (unconditional mkdir -p at a drifted cwd).
if [[ -n "$resolved_root" ]]; then
{
  mkdir -p "$resolved_root/.agentic/wrap" 2>/dev/null || true
  if [[ ! -f "$resolved_root/.agentic/wrap/claude-host" ]]; then
    : > "$resolved_root/.agentic/wrap/claude-host" 2>/dev/null || true
  fi
} || true
fi

# --- (d) Launch the deferred-wrap daemon detached (toggle true, not guarded) ---
# Gate 1: never spawn a daemon from inside a daemon-driven headless run.
# Gate 2: only when `deferred_wrap_daemon` is true in the project config.
# Mirrors the version-check-core.sh detached fire-and-forget pattern.
daemon_enabled() {
  [[ -n "$resolved_root" ]] || return 1
  local config="$resolved_root/.agentic/config.json"
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
    # redundant launch is a cheap no-op. Deliberately passes the raw $cwd,
    # not $resolved_root: wrap-daemon.js resolves internally via
    # hooks/lib/repo-root.js (resolveAgenticCwd) at every .agentic/ access.
    nohup node "$DAEMON" "$cwd" </dev/null >/dev/null 2>&1 &
    disown 2>/dev/null || true
  fi
fi

# --- Compose + emit a single JSON object ---
# Join every non-empty message piece (version notice, auth-failed notice,
# hooks-snapshot staleness nudge) with a blank line. When all pieces are
# empty, emit a bare suppressOutput object. AGENTIC_QUIET=1 suppresses the
# user-facing message but still satisfies the SessionStart JSON contract.
combined=""
if [[ "${AGENTIC_QUIET:-}" != "1" ]]; then
  # --- Deferred-work open-count nudge (4th contributor). Resolved via
  # hooks/lib/repo-dir-fallback.sh's resolve_ae_repo_dir_with_fallback
  # (shared with hooks/lib/version-check-core.sh; tries scripts/lib/
  # repo-dir.sh's resolve_repo_dir first, falls back inline when that lib
  # is absent) rather than trusting PATH - ~/.local/bin (where install.sh
  # symlinks ds-defer) is not reliably on the PATH a GUI-launched harness
  # inherits, and grepping hooks/ turns up zero existing "command -v ds-*"
  # call sites to imitate. This hook runs from the hooks-snapshot dir in
  # production (~/.agentic/hooks-snapshot/DinoStack-<hash>/hooks/), which
  # sync_hooks_snapshot (scripts/lib/hooks-snapshot.sh) copies `hooks/`
  # wholesale plus bin/ds-identity and, conditionally, .codex/config/hooks.json,
  # .codex/hooks, .gemini/hooks, and .kimi/hooks - NOT the rest of `bin/`,
  # and NOT `scripts/` at all - so
  # both $SCRIPT_DIR/../scripts/lib/repo-dir.sh AND
  # $SCRIPT_DIR/../bin/ds-defer are absent in the deployed layout. The
  # repo-dir-fallback.sh inline branch is therefore what actually resolves
  # AE_REPO_DIR in production, not a rare degraded path; the DS_DEFER_BIN
  # existence check right below is what handles ds-defer itself being
  # absent from the snapshot (falls through to the `command -v ds-defer`
  # branch). ---
  defer_msg=""
  # shellcheck source=./lib/repo-dir-fallback.sh
  source "$SCRIPT_DIR/lib/repo-dir-fallback.sh"
  resolve_ae_repo_dir_with_fallback
  if [[ -n "${AE_REPO_DIR:-}" ]] && [[ -x "$AE_REPO_DIR/bin/ds-defer" ]]; then
    DS_DEFER_BIN="$AE_REPO_DIR/bin/ds-defer"
  fi
  if [[ -z "${DS_DEFER_BIN:-}" ]] && command -v ds-defer >/dev/null 2>&1; then
    DS_DEFER_BIN="$(command -v ds-defer)"
  fi
  if [[ -n "${DS_DEFER_BIN:-}" ]]; then
    defer_count="$("$DS_DEFER_BIN" count --repo "$cwd" --status open 2>/dev/null || true)"
    if [[ "$defer_count" =~ ^[0-9]+$ ]] && [[ "$defer_count" -gt 0 ]]; then
      defer_msg="${defer_count} deferred-work item(s) pending in this project - see .agentic/deferred-work.jsonl or run \`ds-defer list --repo .\`."
    fi
  fi

  # --- Worktree-accumulation nudge (5th contributor). Report-only - this
  # SessionStart call site NEVER removes anything, per the worktree-reaper
  # ticket's explicit requirement (passive triggers report; only an
  # explicit invocation of ds-reap-worktrees or /ds-cleanup-worktrees
  # removes). Resolved the same way as ds-defer above: AE_REPO_DIR (already
  # resolved by resolve_ae_repo_dir_with_fallback for the defer nudge)
  # first, PATH fallback second - the deployed hooks-snapshot layout does
  # NOT include the rest of bin/, so DS_REAP_BIN is very commonly absent
  # there and this nudge silently degrades to empty, same as ds-defer's own
  # `command -v ds-defer` fallback comment explains above.
  worktree_msg=""
  WORKTREE_NUDGE_THRESHOLD=5
  if [[ -n "${AE_REPO_DIR:-}" ]] && [[ -x "$AE_REPO_DIR/bin/ds-reap-worktrees" ]]; then
    DS_REAP_BIN="$AE_REPO_DIR/bin/ds-reap-worktrees"
  fi
  if [[ -z "${DS_REAP_BIN:-}" ]] && command -v ds-reap-worktrees >/dev/null 2>&1; then
    DS_REAP_BIN="$(command -v ds-reap-worktrees)"
  fi
  if [[ -n "${DS_REAP_BIN:-}" ]]; then
    # `--count-only` (round-2 Skeptic Major 4): only the `entries=N` count
    # is needed here (N includes the main worktree, so the non-root count
    # is N-1) - zero network calls, zero per-entry `git` calls beyond the
    # single `git worktree list --porcelain` --count-only itself needs.
    # v1's `--dry-run --no-gh` full-mode invocation measured 14.94s against
    # the live checkout because --no-gh suppressed `gh` but NOT `git
    # ls-remote`, one network round-trip per entry - this call site never
    # needed anything beyond a count, so it never needed that cost.
    reap_summary="$(python3 "$DS_REAP_BIN" --repo "$cwd" --count-only 2>/dev/null || true)"
    if [[ "$reap_summary" =~ entries=([0-9]+) ]]; then
      total_entries="${BASH_REMATCH[1]}"
      nonroot_count=$((total_entries - 1))
      if [[ "$nonroot_count" -ge "$WORKTREE_NUDGE_THRESHOLD" ]]; then
        worktree_msg="${nonroot_count} non-root git worktrees in this project - consider running \`/ds-cleanup-worktrees\` (removes eligible worktrees by default; pass \`--dry-run --explain\` to \`ds-reap-worktrees\` first for a dry-run report)."
      fi
    fi
  fi

  parts=()
  [[ -n "$version_msg" ]] && parts+=("$version_msg")
  [[ -n "$auth_msg" ]] && parts+=("$auth_msg")
  [[ -n "$staleness_msg" ]] && parts+=("$staleness_msg")
  [[ -n "$defer_msg" ]] && parts+=("$defer_msg")
  [[ -n "$worktree_msg" ]] && parts+=("$worktree_msg")
  if [[ ${#parts[@]} -gt 0 ]]; then
    sep=""
    for part in "${parts[@]}"; do
      combined="${combined}${sep}${part}"
      sep=$'\n\n'
    done
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
