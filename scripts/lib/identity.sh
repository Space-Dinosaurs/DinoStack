# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Purpose: Shared developer-identity setup helper sourced by every adapter
#          installer; prompts for / resolves a GitHub handle and records it
#          via the ds-identity binary.
#
# Public API:
#   AE_IDENTITY_SCOPE        - identity scope for installer writes: global
#                              (default) or profile.
#   _ae_identity_bind_config_dir <dir> <redirected>
#                            - bind the selected harness config dir and infer
#                              profile scope for redirected installs unless the
#                              caller explicitly set AE_IDENTITY_SCOPE.
#   ae_confirm <prompt>       - TTY-safe y/N prompt; returns 0 for y/Y, 1 otherwise.
#   _ae_setup_identity        - 7-branch identity resolution (no-identity flag,
#                               missing binary, existing identity, --identity flag,
#                               non-TTY, gh auto-detect, manual prompt).
#   AE_IDENTITY_FLAG          - default var (empty string); callers may set before sourcing.
#   AE_NO_IDENTITY            - default var ("false"); callers may set before sourcing.
#
# Upstream dependencies:
#   ds-identity binary (on PATH), gh (optional, for auto-detect),
#   /dev/tty (optional, for interactive prompts).
#
# Downstream consumers:
#   .claude/install.sh, .codex/install.sh, .cursor/install.sh,
#   .gemini/install.sh, .hermes/install.sh, .kimi/install.sh,
#   .omp/install.sh, .openclaw/install.sh, .opencode/install.sh,
#   .pi/install.sh
#
# Failure modes:
#   Never aborts the caller - every ds-identity call captures rc;
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
# Scope for identity writes during install. Default "global" preserves legacy
# single-global behavior. Redirected installers infer profile scope unless the
# caller explicitly selected a scope.
if [[ -n "${AE_IDENTITY_SCOPE+x}" ]]; then
  AE_IDENTITY_SCOPE_EXPLICIT=true
else
  AE_IDENTITY_SCOPE=global
  AE_IDENTITY_SCOPE_EXPLICIT=false
fi

_ae_identity_bind_config_dir() {
  local config_dir="$1"
  local redirected="${2:-false}"
  AE_CONFIG_DIR="$config_dir"
  if [[ "$AE_IDENTITY_SCOPE_EXPLICIT" != "true" && "$redirected" == "true" ]]; then
    AE_IDENTITY_SCOPE=profile
  fi
}

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

_ae_identity_show_command() {
  if [[ "$AE_IDENTITY_SCOPE" == "profile" && -n "${AE_CONFIG_DIR:-}" ]]; then
    printf "ds-identity show --scope profile --profile-dir "
    printf "%q" "$AE_CONFIG_DIR"
  else
    printf "ds-identity show --scope effective"
  fi
}

_ae_identity_confirm_command() {
  if [[ "$AE_IDENTITY_SCOPE" == "profile" && -n "${AE_CONFIG_DIR:-}" ]]; then
    printf "ds-identity confirm --scope profile --profile-dir "
    printf "%q" "$AE_CONFIG_DIR"
  else
    printf "ds-identity confirm --scope global"
  fi
}

_ae_identity_guidance() {
  echo "  Inspect identity: $(_ae_identity_show_command)"
  echo "  Confirm provisional identity: $(_ae_identity_confirm_command)"
}

_ae_setup_identity() {
  # Scope-aware ds-identity args. For profile scope, pin the config dir
  # explicitly so detection does not rely on env propagation to the subprocess
  # (AE_CONFIG_DIR is set by the calling adapter install.sh before sourcing us).
  local ae_scope_args=(--scope "$AE_IDENTITY_SCOPE")
  if [[ "$AE_IDENTITY_SCOPE" == "profile" && -n "${AE_CONFIG_DIR:-}" ]]; then
    ae_scope_args+=(--profile-dir "$AE_CONFIG_DIR")
  fi

  # Branch 1: --no-identity flag
  if [[ "$AE_NO_IDENTITY" == "true" ]]; then
    echo "  - identity setup skipped (--no-identity)"
    return
  fi

  # Branch 2: ds-identity not on PATH
  if ! command -v ds-identity &>/dev/null; then
    echo "  ! ds-identity not found on PATH - set later with 'ds-identity init <handle>'"
    return
  fi

  # Branch 3: detect existing identity (global: effective incl. project fallback;
  # profile: this profile's own identity only). For profile scope, pin the
  # config dir explicitly (mirrors ae_scope_args) so detection works without
  # env propagation to the subprocess.
  local show_scope="$AE_IDENTITY_SCOPE"
  [[ "$show_scope" == "global" ]] && show_scope="effective"
  local show_args=(--scope "$show_scope")
  if [[ "$AE_IDENTITY_SCOPE" == "profile" && -n "${AE_CONFIG_DIR:-}" ]]; then
    show_args+=(--profile-dir "$AE_CONFIG_DIR")
  fi
  local show_out
  show_out="$(ds-identity show "${show_args[@]}" 2>/dev/null)" || show_out=""
  local existing_handle
  existing_handle="$(echo "$show_out" | grep '^developer_id:' | awk '{print $2}')" || existing_handle=""
  if [[ -n "$existing_handle" ]]; then
    if echo "$show_out" | grep -q 'provisional:'; then
      echo "  = identity already set to '$existing_handle' (provisional - run '$(_ae_identity_confirm_command)' to lock it in)"
    else
      echo "  = identity already set to '$existing_handle' (confirmed)"
    fi
    return
  fi

  # Branch 4: --identity=<handle> flag set (explicit intent, use --force)
  if [[ -n "$AE_IDENTITY_FLAG" ]]; then
    local rc=0
    ds-identity init "$AE_IDENTITY_FLAG" --force "${ae_scope_args[@]}" >/dev/null 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then
      echo "  + identity set to '$AE_IDENTITY_FLAG' via --identity flag"
    else
      echo "  ! identity init failed for '$AE_IDENTITY_FLAG' (invalid handle?) - set manually with 'ds-identity init <handle>'"
    fi
    return
  fi

  # Branch 5: non-TTY
  if [[ ! -r /dev/tty ]]; then
    echo "  - non-interactive install: skipped identity setup (run 'ds-identity auto' or 'ds-identity init <handle>')"
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
      ds-identity init "$gh_login" "${ae_scope_args[@]}" >/dev/null 2>&1 || rc=$?
      if [[ "$rc" -eq 0 ]]; then
        echo "  + identity set to '$gh_login' (confirmed)"
      elif [[ "$rc" -eq 2 ]]; then
        echo "  = identity already set (use 'ds-identity init $gh_login --force' to change)"
      else
        echo "  ! identity init failed - set manually with 'ds-identity init <handle>'"
      fi
    else
      echo "  - identity setup skipped (run 'ds-identity init <handle>' later)"
    fi
    return
  fi

  # Branch 7: gh absent or unauthenticated - prompt manually
  echo "  Developer identity links telemetry to your handle across sessions."
  local typed_handle=""
  local raw_handle=""
  read -r -p "  GitHub handle [skip]: " typed_handle </dev/tty || typed_handle=""
  raw_handle="$typed_handle"
  typed_handle="$(echo "$typed_handle" | xargs | tr '[:upper:]' '[:lower:]')" || typed_handle=""
  if [[ -z "$typed_handle" ]]; then
    if [[ -n "${raw_handle//[[:space:]]/}" ]]; then
      echo "  - typed handle could not be parsed, skipping identity setup (run 'ds-identity init <handle>' later)"
    else
      echo "  - identity setup skipped (run 'ds-identity init <handle>' later)"
    fi
    return
  fi
  if ! echo "$typed_handle" | grep -qE '^[a-z0-9._-]{1,64}$'; then
    echo "  ! '$typed_handle' is not a valid handle (must match ^[a-z0-9._-]{1,64}\$) - skipping"
    return
  fi
  local rc=0
  ds-identity init "$typed_handle" "${ae_scope_args[@]}" >/dev/null 2>&1 || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    echo "  + identity set to '$typed_handle' (confirmed)"
  elif [[ "$rc" -eq 2 ]]; then
    echo "  = identity already set (use 'ds-identity init $typed_handle --force' to change)"
  else
    echo "  ! identity init failed - set manually with 'ds-identity init <handle>'"
  fi
}
