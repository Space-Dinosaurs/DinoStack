#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Module Manifest
#
# Purpose: Non-interactive "install every adapter in one shot" launcher.
#          Discovers all adapter directories (dot-dirs containing install.sh),
#          runs each adapter's install.sh in sequence (.claude first), forwards
#          shared activation flags verbatim, and continues past failures.
#          The non-interactive counterpart to the TTY-only update.sh TUI.
#
# Public API:
#   ./install-all.sh [--mode=opt-in|opt-out] [--profile=relaxed|default|strict]
#                    [--identity=<handle>] [--no-identity] [-h|--help]
#
# Upstream deps: bash. Per-adapter install.sh scripts depend on python3 (and
#                node for the .claude update tooling) - see each adapter README.
#
# Downstream consumers: End users / CI wanting a scripted full install. Calls
#                       each <adapter>/install.sh.
#
# Failure modes:
#   Exit 0: every adapter install.sh exited 0.
#   Exit 1: one or more adapters failed (continue-on-error; failures collected
#           and reported in the final summary with their exit codes), OR no
#           adapters were discovered.
#
# Performance: Sequential. Dominated by the per-adapter install.sh work
#              (symlinks, python3 config writes, optional builds).
#
# Notes: Adapter discovery mirrors scripts/update.js discoverAdapters() and its
#        SKIP_DIRS set exactly. .claude runs first unconditionally so its
#        agentic-* binaries (incl. agentic-identity) are on PATH before other
#        adapters' identity steps run.
# =============================================================================

# ---------------------------------------------------------------------------
# Resolve repo dir from the script's own location (CWD-independent)
# ---------------------------------------------------------------------------
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Skip-list - mirrors SKIP_DIRS in scripts/update.js exactly.
# ---------------------------------------------------------------------------
SKIP_DIRS=(. .. .git .github .vscode .idea .cache .venv .mypy_cache .pytest_cache .ruff_cache)

is_skipped() {
  local candidate="$1"
  local skip
  for skip in "${SKIP_DIRS[@]}"; do
    [[ "$candidate" == "$skip" ]] && return 0
  done
  return 1
}

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
print_help() {
  cat <<'EOF'
Usage: install-all.sh [options]

Non-interactive installer that runs every adapter's install.sh in one shot.
Discovers all adapter directories (dot-dirs containing an install.sh), then
runs each in sequence with .claude first. This is the non-interactive
counterpart to the interactive ./update.sh TUI.

Adapter installs continue on error: a failure in one adapter does not abort
the rest. Failures are reported in a final summary, and the script exits
non-zero if any adapter failed.

Options:
  --mode=opt-in | --mode=opt-out        Activation mode (forwarded to each adapter)
  --profile=relaxed|default|strict      Risk profile (forwarded to each adapter)
  --identity=<handle>                   Set developer identity non-interactively
  --no-identity                         Skip the developer-identity prompt
  -h, --help                            Print this help and exit.

All non-flag arguments are forwarded verbatim to each adapter's install.sh.

Example:
  ./install-all.sh --mode=opt-out --profile=default --identity=octocat
EOF
}

# ---------------------------------------------------------------------------
# Argument handling: intercept -h/--help; forward everything else verbatim.
# ---------------------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    -h|--help)
      print_help
      exit 0
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Adapter discovery - mirrors discoverAdapters() in scripts/update.js:
#   - dot-directories at repo root containing an install.sh
#   - skipping SKIP_DIRS
#   - sorted case-insensitively
# ---------------------------------------------------------------------------
ADAPTERS=()
for entry in "$REPO_DIR"/.*; do
  [[ -d "$entry" ]] || continue
  name="$(basename "$entry")"
  is_skipped "$name" && continue
  [[ -f "$entry/install.sh" ]] || continue
  ADAPTERS+=("$name")
done

if [[ ${#ADAPTERS[@]} -eq 0 ]]; then
  echo "error: no adapters found in $REPO_DIR." >&2
  exit 1
fi

# Case-insensitive alphabetical sort (matches update.js localeCompare on
# lowercased names). Disable globbing around the unquoted array assignment so a
# glob metacharacter in a future adapter name can't be pathname-expanded.
set -f
IFS=$'\n' ADAPTERS=($(printf '%s\n' "${ADAPTERS[@]}" | sort -f))
unset IFS
set +f

# ---------------------------------------------------------------------------
# Ordering: .claude FIRST regardless of sort order.
# Rationale: the .claude installer wires the agentic-* CLI binaries (incl.
# agentic-identity) onto PATH via ~/.local/bin. scripts/lib/identity.sh calls
# agentic-identity, so .claude must run before other adapters' identity steps.
# ---------------------------------------------------------------------------
ORDERED=()
if [[ -f "$REPO_DIR/.claude/install.sh" ]]; then
  ORDERED+=(".claude")
fi
for name in "${ADAPTERS[@]}"; do
  [[ "$name" == ".claude" ]] && continue
  ORDERED+=("$name")
done

# ---------------------------------------------------------------------------
# Run each adapter's install.sh - continue on error, collect failures.
# Capture each exit with '|| rc=$?' so a failure does not trip set -e.
# ---------------------------------------------------------------------------
SUCCEEDED=()
FAILED=()
FAILED_CODES=()

# Guard the expansion explicitly: bash 3.2 (macOS default) errors on
# "${ORDERED[@]}" under `set -u` when the array is empty. ORDERED is provably
# non-empty here, but the +-form makes the invariant safe against refactors.
for name in "${ORDERED[@]+"${ORDERED[@]}"}"; do
  echo ""
  echo "==> $name"
  rc=0
  bash "$REPO_DIR/$name/install.sh" "$@" || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    SUCCEEDED+=("$name")
  else
    echo "  ! $name/install.sh failed (exit $rc)" >&2
    FAILED+=("$name")
    FAILED_CODES+=("$rc")
  fi
done

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
echo ""
echo "================================================================"
echo "install-all summary"
echo "================================================================"

if [[ ${#SUCCEEDED[@]} -gt 0 ]]; then
  echo "Succeeded (${#SUCCEEDED[@]}): ${SUCCEEDED[*]}"
else
  echo "Succeeded (0): none"
fi

if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "Failed (${#FAILED[@]}):"
  for i in "${!FAILED[@]}"; do
    echo "  - ${FAILED[$i]} (exit ${FAILED_CODES[$i]})"
  done
  echo ""
  echo "One or more adapters failed. Fix the failures above and re-run."
  exit 1
fi

echo ""
echo "All ${#SUCCEEDED[@]} adapter(s) installed successfully."
