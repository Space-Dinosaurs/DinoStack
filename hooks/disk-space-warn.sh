#!/usr/bin/env bash
# Purpose: Warn the session, at most once per 30 minutes machine-wide, when
#          the volume holding the project has less free space than
#          AE_DISK_WARN_FREE_GB, so an unattended run notices before the disk
#          fills. The warning names the two cleanup tools by absolute path.
#          Catch: on 2026-10-29 `skc-oauth-*` temp dirs filled the disk at
#          about 8 GB/day with no session noticing.
#          Retire when Claude Code ships its own low-disk warning, or when
#          ~/.agentic/disk-warn.log shows no fire in 90 days.
# Public API: bash hooks/disk-space-warn.sh (no args, never reads stdin).
#             Env: AE_DISK_WARN_FREE_GB, whole GiB, default 50; 0 turns the
#             hook off; anything that is not 0 or 1-6 digits without a
#             leading zero is treated as 50. CLAUDE_PROJECT_DIR (else $PWD)
#             selects the volume.
#             Prints nothing unless it fires; then prints one PostToolUse
#             hookSpecificOutput.additionalContext JSON object and appends a
#             line to ~/.agentic/disk-warn.log.
# Upstream deps: find, touch, df -Pk, awk, python3 (JSON encoding, fire path
#                only), lib/repo-dir-fallback.sh (fire path only).
# Downstream consumers: .claude/install.sh (PostToolUse "*" hook, guarded
#                       `test -f ... && bash ... || exit 0` form),
#                       .claude/uninstall.sh, bin/ds-doctor
#                       MANAGED_HOOK_BASENAMES.
# Failure modes: always exits 0. The throttle stamp
#                (~/.agentic/disk-warn.stamp) is touched before df runs, so a
#                failing df, an unwritable HOME or a missing python3 stays
#                silent for the next 30 minutes rather than retrying on
#                every tool call.
# Performance: on the throttled path (every tool call but one per 30 min)
#              one bash and one find process.

_disk_space_warn() {
  local raw="${AE_DISK_WARN_FREE_GB:-50}" threshold=50
  if [[ "$raw" =~ ^(0|[1-9][0-9]{0,5})$ ]]; then
    threshold=$((10#$raw))
  fi
  [[ "$threshold" -eq 0 ]] && return 0

  local dir="$HOME/.agentic"
  local stamp="$dir/disk-warn.stamp"
  [[ -n "$(find "$stamp" -mmin -30 2>/dev/null)" ]] && return 0
  mkdir -p "$dir" 2>/dev/null || return 0
  touch "$stamp" 2>/dev/null || return 0

  local target="${CLAUDE_PROJECT_DIR:-$PWD}" tab=$'\t' row avail_kb volume
  row="$(df -Pk "$target" 2>/dev/null | awk 'NR == 2 { m = $6; for (i = 7; i <= NF; i++) m = m " " $i; print $4 "\t" m }')"
  avail_kb="${row%%"$tab"*}"
  volume="${row#*"$tab"}"
  [[ "$avail_kb" =~ ^[0-9]+$ ]] || return 0
  (( avail_kb < threshold * 1048576 )) || return 0

  local disk_tool="ds-disk" cleanup_tool="ds-cleanup-worktrees"
  # shellcheck source=lib/repo-dir-fallback.sh
  if source "$(dirname "${BASH_SOURCE[0]}")/lib/repo-dir-fallback.sh" 2>/dev/null; then
    resolve_ae_repo_dir_with_fallback >/dev/null 2>&1 || true
    [[ -x "$AE_REPO_DIR/bin/ds-disk" ]] && disk_tool="$AE_REPO_DIR/bin/ds-disk"
    [[ -x "$AE_REPO_DIR/bin/ds-cleanup-worktrees" ]] && cleanup_tool="$AE_REPO_DIR/bin/ds-cleanup-worktrees"
  fi

  local free_gib=$(( avail_kb / 1048576 ))
  local msg="Low disk space: ${free_gib} GiB free on ${volume} (warning threshold ${threshold} GiB, set by AE_DISK_WARN_FREE_GB). Tell the operator, then reclaim space: run \"${disk_tool}\" to see what it would delete, then \"${disk_tool}\" --sweep to delete aged temp directories, and \"${cleanup_tool}\" --dry-run --explain to list worktrees that can be removed. This warning repeats at most every 30 minutes."
  python3 -c 'import json, sys; print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": sys.argv[1]}}))' "$msg" 2>/dev/null || return 0
  printf '%s free_gib=%s threshold_gib=%s volume=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$free_gib" "$threshold" "$volume" >> "$dir/disk-warn.log" 2>/dev/null
  return 0
}

_disk_space_warn
exit 0
