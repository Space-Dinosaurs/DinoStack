# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Purpose: Shared developer-identity setup helper sourced by every adapter
#          installer; prompts for / resolves a GitHub handle and records it
#          via the agentic-identity binary.
#
# Public API:
#   ae_confirm <prompt>       - TTY-safe y/N prompt; returns 0 for y/Y, 1 otherwise.
#   _ae_setup_identity        - 7-branch identity resolution (no-identity flag,
#                               missing binary, existing identity, --identity flag,
#                               non-TTY, gh auto-detect, manual prompt).
#   AE_IDENTITY_FLAG          - default var (empty string); callers may set before sourcing.
#   AE_NO_IDENTITY            - default var ("false"); callers may set before sourcing.
#
# Upstream dependencies:
#   agentic-identity binary (on PATH), gh (optional, for auto-detect),
#   /dev/tty (optional, for interactive prompts).
#
# Downstream consumers:
#   .claude/install.sh, .codex/install.sh, .cursor/install.sh,
#   .gemini/install.sh, .hermes/install.sh, .kimi/install.sh,
#   .omp/install.sh, .opencode/install.sh, .pi/install.sh
#
# Failure modes:
#   Never aborts the caller - every agentic-identity call captures rc;
#   missing binary / no TTY / unset handle all degrade to a printed skip
#   message. Safe to source under set -euo pipefail (no top-level side
#   effects beyond function defs + ${VAR:-default} assignments).
#
# Performance:
#   One optional `gh api user` network call only on the interactive
#   auto-detect path; otherwise local-only.
# ---------------------------------------------------------------------------

AE_IDENTITY_FLAG="${AE_IDENTITY_FLAG:-}"
AE_NO_IDENTITY="${AE_NO_IDENTITY:-false}"

# ---------------------------------------------------------------------------
# ae_confirm: TTY-safe yes/no prompt for optional installs.
#
# When /dev/tty is available (interactive or curl|bash in a real terminal),
# prompts the user exactly as a bare `read -p` would. When /dev/tty is not
# available (headless/piped/CI), defaults to "no" and returns 1 without
# aborting under set -e.
#
# Usage: if ae_confirm "  Install foo? [y/N] "; then ...
# ---------------------------------------------------------------------------
ae_confirm() {
  local prompt="$1"
  local reply=""
  if [[ -r /dev/tty ]]; then
    read -p "$prompt" -n 1 -r reply </dev/tty || reply=""
    echo
  fi
  [[ "$reply" =~ ^[Yy]$ ]]
}

_ae_setup_identity() {
  # Branch 1: --no-identity flag
  if [[ "$AE_NO_IDENTITY" == "true" ]]; then
    echo "  - identity setup skipped (--no-identity)"
    return
  fi

  # Branch 2: agentic-identity not on PATH
  if ! command -v agentic-identity &>/dev/null; then
    echo "  ! agentic-identity not found on PATH - set later with 'agentic-identity init <handle>'"
    return
  fi

  # Branch 3: detect existing identity
  local show_out
  show_out="$(agentic-identity show --scope effective 2>/dev/null)" || show_out=""
  local existing_handle
  existing_handle="$(echo "$show_out" | grep '^developer_id:' | awk '{print $2}')"
  if [[ -n "$existing_handle" ]]; then
    if echo "$show_out" | grep -q 'provisional:'; then
      echo "  = identity already set to '$existing_handle' (provisional - run 'agentic-identity confirm' to lock it in)"
    else
      echo "  = identity already set to '$existing_handle' (confirmed)"
    fi
    return
  fi

  # Branch 4: --identity=<handle> flag set (explicit intent, use --force)
  if [[ -n "$AE_IDENTITY_FLAG" ]]; then
    local rc=0
    agentic-identity init "$AE_IDENTITY_FLAG" --force >/dev/null 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then
      echo "  + identity set to '$AE_IDENTITY_FLAG' via --identity flag"
    else
      echo "  ! identity init failed for '$AE_IDENTITY_FLAG' (invalid handle?) - set manually with 'agentic-identity init <handle>'"
    fi
    return
  fi

  # Branch 5: non-TTY
  if [[ ! -r /dev/tty ]]; then
    echo "  - non-interactive install: skipped identity setup (run 'agentic-identity auto' or 'agentic-identity init <handle>')"
    return
  fi

  # Branch 6: interactive + gh present and authenticated
  local gh_login=""
  if command -v gh &>/dev/null; then
    gh_login="$(gh api user --jq .login 2>/dev/null | tr '[:upper:]' '[:lower:]')" || gh_login=""
  fi

  if [[ -n "$gh_login" ]] && echo "$gh_login" | grep -qE '^[a-z0-9._-]{1,64}$'; then
    echo "  Detected GitHub handle: $gh_login"
    if ae_confirm "  Set developer identity to '$gh_login'? [y/N] "; then
      local rc=0
      agentic-identity init "$gh_login" >/dev/null 2>&1 || rc=$?
      if [[ "$rc" -eq 0 ]]; then
        echo "  + identity set to '$gh_login' (confirmed)"
      elif [[ "$rc" -eq 2 ]]; then
        echo "  = identity already set (use 'agentic-identity init $gh_login --force' to change)"
      else
        echo "  ! identity init failed - set manually with 'agentic-identity init <handle>'"
      fi
    else
      echo "  - identity setup skipped (run 'agentic-identity init <handle>' later)"
    fi
    return
  fi

  # Branch 7: gh absent or unauthenticated - prompt manually
  echo "  Developer identity links telemetry to your handle across sessions."
  local typed_handle=""
  read -r -p "  GitHub handle [skip]: " typed_handle </dev/tty || typed_handle=""
  typed_handle="$(echo "$typed_handle" | xargs | tr '[:upper:]' '[:lower:]')"
  if [[ -z "$typed_handle" ]]; then
    echo "  - identity setup skipped (run 'agentic-identity init <handle>' later)"
    return
  fi
  if ! echo "$typed_handle" | grep -qE '^[a-z0-9._-]{1,64}$'; then
    echo "  ! '$typed_handle' is not a valid handle (must match ^[a-z0-9._-]{1,64}\$) - skipping"
    return
  fi
  local rc=0
  agentic-identity init "$typed_handle" >/dev/null 2>&1 || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    echo "  + identity set to '$typed_handle' (confirmed)"
  elif [[ "$rc" -eq 2 ]]; then
    echo "  = identity already set (use 'agentic-identity init $typed_handle --force' to change)"
  else
    echo "  ! identity init failed - set manually with 'agentic-identity init <handle>'"
  fi
}
