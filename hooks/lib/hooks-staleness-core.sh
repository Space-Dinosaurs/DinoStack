#!/usr/bin/env bash
# Purpose: Adapter-neutral core for the "hooks snapshot needs attention"
#          SessionStart nudge (DS-54). Resolves the agentic-engineering clone
#          dir the same way version-check-core.sh does, then classifies the
#          methodology checkout's hook-snapshot state into one of four states
#          and prints at most one line describing it. Never touches the
#          filesystem beyond reads.
# Public API: bash hooks/lib/hooks-staleness-core.sh
#             (no args; prints ONE line to stdout when the snapshot state is
#              half_applied, never_migrated, or stale_but_stable; prints
#              nothing when current. Always exits 0.)
# Upstream deps: scripts/lib/repo-dir.sh (resolve_repo_dir; optional - a
#                inline $HOME/DinoStack fallback applies if the lib is
#                absent), scripts/lib/hooks-snapshot.sh (hooks_snapshot_dir,
#                compute_hooks_source_hash, hooks_config_points_at_snapshot -
#                required; the script stays silent if this lib is missing),
#                python3 (JSON read, realpath), grep. All fail-open.
# Downstream consumers: hooks/session-start-wrap.sh (composes this script's
#                       stdout into its systemMessage alongside the version
#                       notice and the auth-failed notice).
# Failure modes: always exits 0 (fail-open). Unresolvable repo_dir, a missing
#                scripts/lib/hooks-snapshot.sh, or any read/parse error is
#                treated as "nothing to report" - silent, not an error.
#                State priority (first match wins):
#                  half_applied     - snapshot + meta exist AND at least one
#                                      present in-scope adapter config still
#                                      points its hook command at the
#                                      checkout instead of the snapshot.
#                  never_migrated   - the snapshot dir or its
#                                      .snapshot-meta.json is absent.
#                  stale_but_stable - every checked config points at the
#                                      snapshot, but the live hook source
#                                      hash no longer matches
#                                      meta.source_hash.
#                  current          - none of the above; silent.
#                The stored source_hash key is read via a python .get()
#                default, so a missing key degrades to "current" (silent)
#                rather than a false-positive nudge.
# Performance: a handful of file existence checks, one python3 realpath call
#              for the Codex symlink, and (only when neither guard state
#              fired) one re-walk of the live hook source tree to hash it -
#              sub-50ms on a warm filesystem cache.

set -euo pipefail

_HSC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_REPO_DIR_LIB="$_HSC_DIR/../../scripts/lib/repo-dir.sh"
_HOOKS_SNAPSHOT_LIB="$_HSC_DIR/../../scripts/lib/hooks-snapshot.sh"

# --- Resolve the clone dir via the shared lib (with inline fallback) ---
ae_repo_dir=""
if [[ -f "$_REPO_DIR_LIB" ]]; then
  # shellcheck source=../../scripts/lib/repo-dir.sh
  source "$_REPO_DIR_LIB"
  resolve_repo_dir --quiet || true
  ae_repo_dir="$AE_REPO_DIR"
else
  ae_repo_dir="$HOME/DinoStack"
fi

# Nothing meaningful to report if the repo isn't resolvable or the snapshot
# lib is missing (e.g. an older/partial checkout mid-upgrade).
if [[ -z "$ae_repo_dir" ]] || [[ ! -d "$ae_repo_dir" ]] || [[ ! -f "$_HOOKS_SNAPSHOT_LIB" ]]; then
  exit 0
fi

# shellcheck source=../../scripts/lib/hooks-snapshot.sh
source "$_HOOKS_SNAPSHOT_LIB" || exit 0

snapshot_dir="$(hooks_snapshot_dir "$ae_repo_dir" 2>/dev/null || true)"
meta_file="${snapshot_dir:+$snapshot_dir/.snapshot-meta.json}"

# --- never_migrated: snapshot dir or its metadata is absent ---
if [[ -z "$snapshot_dir" ]] || [[ ! -d "$snapshot_dir" ]] || [[ -z "$meta_file" ]] || [[ ! -f "$meta_file" ]]; then
  echo "agentic-engineering: hooks are not yet snapshotted - a bare 'git pull' can silently change a live session's hook behavior. Run install.sh to enable the session-stable hooks snapshot."
  exit 0
fi

# --- half_applied: some present in-scope adapter config still points at the checkout ---
_half_applied=false

# Claude Code: ~/.claude/settings.json (json), SessionStart hook.
_claude_settings="$HOME/.claude/settings.json"
if [[ -f "$_claude_settings" ]] && grep -q "session-start-wrap.sh" "$_claude_settings" 2>/dev/null; then
  if ! hooks_config_points_at_snapshot "$_claude_settings" json "session-start-wrap.sh"; then
    _half_applied=true
  fi
fi

# Gemini CLI: ~/.gemini/settings.json (json), BeforeAgent risk-reminder hook.
_gemini_settings="$HOME/.gemini/settings.json"
if [[ "$_half_applied" == "false" ]] && [[ -f "$_gemini_settings" ]] && grep -q "risk-reminder.sh" "$_gemini_settings" 2>/dev/null; then
  if ! hooks_config_points_at_snapshot "$_gemini_settings" json "risk-reminder.sh"; then
    _half_applied=true
  fi
fi

# Kimi CLI: ~/.kimi/config.toml (toml), SessionStart hook.
_kimi_config="$HOME/.kimi/config.toml"
if [[ "$_half_applied" == "false" ]] && [[ -f "$_kimi_config" ]] && grep -q "session-start.sh" "$_kimi_config" 2>/dev/null; then
  if ! hooks_config_points_at_snapshot "$_kimi_config" toml "session-start.sh"; then
    _half_applied=true
  fi
fi

# Codex: ~/.codex/hooks.json is a symlink, not a json/toml command string -
# resolve its target directly instead of going through
# hooks_config_points_at_snapshot (which only understands json/toml bodies).
_codex_hooks_json="$HOME/.codex/hooks.json"
if [[ "$_half_applied" == "false" ]] && [[ -L "$_codex_hooks_json" ]]; then
  _codex_target="$(python3 -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$_codex_hooks_json" 2>/dev/null || true)"
  case "$_codex_target" in
    */hooks-snapshot/*) : ;;
    *) _half_applied=true ;;
  esac
fi

if [[ "$_half_applied" == "true" ]]; then
  echo "agentic-engineering: hooks snapshot is partially applied - one or more adapters still point at the checkout. Re-run install.sh for the affected adapter(s)."
  exit 0
fi

# --- stale_but_stable: every checked config points at the snapshot, but the
#     live hook source has moved on since the snapshot was written ---
_meta_hash="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('source_hash', ''))
except Exception:
    print('')
" "$meta_file" 2>/dev/null || echo "")"

if [[ -n "$_meta_hash" ]]; then
  _live_hash="$(compute_hooks_source_hash \
    "$ae_repo_dir/hooks" \
    "$ae_repo_dir/.codex/config/hooks.json" \
    "$ae_repo_dir/.codex/hooks" \
    "$ae_repo_dir/.gemini/hooks" \
    "$ae_repo_dir/.kimi/hooks" 2>/dev/null || echo "")"

  if [[ -n "$_live_hash" ]] && [[ "$_live_hash" != "$_meta_hash" ]]; then
    echo "agentic-engineering: hook scripts changed since the last snapshot sync. Run install.sh (or /pull-and-install) to refresh the live session's hooks."
  fi
fi

# --- current: nothing printed ---
exit 0
