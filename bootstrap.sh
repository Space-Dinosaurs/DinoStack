#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Module Manifest
#
# Purpose: One-liner remote installer for agentic-engineering. Clones or
#          updates the repository from GitHub, delegates to .claude/install.sh
#          for adapter setup, and writes the resolved repo path to
#          ~/.agentic/agentic-engineering-config.json for use by update.sh and
#          the /update-agentic-engineering command.
#
# Public API:
#   curl -fsSL https://raw.githubusercontent.com/Space-Dinosaurs/DinoStack/main/bootstrap.sh | bash
#   curl -fsSL ... | bash -s -- --mode=opt-in
#   AE_DEST_DIR=/custom/path bash bootstrap.sh [--mode=opt-in|opt-out] [--profile=...]
#
# Upstream deps: git, python3 (required); node (optional, for update.sh TUI)
#
# Downstream consumers:
#   - End users installing agentic-engineering for the first time
#   - .claude/install.sh (delegated to after clone/update)
#   - ~/.agentic/agentic-engineering-config.json (written with repo_dir key)
#
# Failure modes:
#   Exit 0: success
#   Exit 1: preflight failure (missing git/python3, or unwritable AE_DEST_DIR parent)
#   Exit 2: clone/pull failure (both HTTPS and SSH failed, or dest exists but is
#            not a git repo)
#   Exit 3: .claude/install.sh delegation failure (non-zero exit from install.sh)
#   All failures print actionable messages to stderr naming what went wrong.
#   Config write failure (~/.agentic/) is non-fatal; warns and continues.
#
# Performance: Network-bound (git clone). Local operations are negligible.
# =============================================================================

# ---------------------------------------------------------------------------
# Capture working directory before any cd operations
# ---------------------------------------------------------------------------
BOOTSTRAP_PWD="$(pwd)"

# ---------------------------------------------------------------------------
# URL seams - real defaults; overridable for testing
# ---------------------------------------------------------------------------
HTTPS_URL="${AE_HTTPS_URL:-https://github.com/Space-Dinosaurs/DinoStack.git}"
SSH_URL="${AE_SSH_URL:-git@github.com:Space-Dinosaurs/DinoStack.git}"

# ---------------------------------------------------------------------------
# Destination directory resolution
# ---------------------------------------------------------------------------
AE_DEST_DIR="${AE_DEST_DIR:-$BOOTSTRAP_PWD/DinoStack}"

# Normalize to absolute path via python3 (required dep anyway)
AE_DEST_DIR="$(python3 -c "import os,sys;print(os.path.abspath(sys.argv[1]))" "$AE_DEST_DIR")"

# ---------------------------------------------------------------------------
# Preflight: required tools
# ---------------------------------------------------------------------------
MISSING=""
if ! command -v git >/dev/null 2>&1; then
  MISSING="$MISSING git"
fi
if ! command -v python3 >/dev/null 2>&1; then
  MISSING="$MISSING python3"
fi

if [ -n "$MISSING" ]; then
  echo "bootstrap.sh: missing required tools:$MISSING" >&2
  echo "Install the missing tools and re-run." >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "bootstrap.sh: warning: 'node' not found - update.sh TUI will not work (install Node.js later if needed)" >&2
fi

# ---------------------------------------------------------------------------
# Parent directory pre-creation
# ---------------------------------------------------------------------------
AE_PARENT="$(dirname "$AE_DEST_DIR")"
if ! mkdir -p "$AE_PARENT" 2>/dev/null; then
  echo "bootstrap.sh: cannot create parent directory '$AE_PARENT' - check write permissions" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Clone-or-update logic
# ---------------------------------------------------------------------------
if [ -d "$AE_DEST_DIR" ]; then
  if git -C "$AE_DEST_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    # Existing git repo: update path
    DIRTY="$(git -C "$AE_DEST_DIR" status --porcelain 2>/dev/null)"
    if [ -n "$DIRTY" ]; then
      echo "bootstrap.sh: warning: working tree at '$AE_DEST_DIR' has uncommitted changes - skipping pull:" >&2
      echo "$DIRTY" >&2
    else
      echo "Updating existing repo at $AE_DEST_DIR ..."
      if ! git -C "$AE_DEST_DIR" pull --ff-only; then
        echo "bootstrap.sh: 'git pull --ff-only' failed in '$AE_DEST_DIR'" >&2
        echo "Resolve the conflict manually (e.g. git -C \"$AE_DEST_DIR\" merge) and re-run." >&2
        exit 2
      fi
    fi
  else
    echo "bootstrap.sh: '$AE_DEST_DIR' exists but is not a git repository" >&2
    echo "Move or remove it, or set AE_DEST_DIR to a different path, then re-run." >&2
    exit 2
  fi
else
  # Fresh clone: HTTPS first, SSH fallback - set -e-safe via if/!
  echo "Cloning DinoStack to $AE_DEST_DIR ..."
  if ! git clone "$HTTPS_URL" "$AE_DEST_DIR"; then
    echo "HTTPS clone failed (repo may be private); trying SSH..." >&2
    if ! git clone "$SSH_URL" "$AE_DEST_DIR"; then
      echo "Both HTTPS and SSH clone failed. If the repo is private, ensure SSH access is configured (https://docs.github.com/en/authentication)." >&2
      exit 2
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Delegate to .claude/install.sh
# ---------------------------------------------------------------------------
INSTALL_SH="$AE_DEST_DIR/.claude/install.sh"
if [ ! -f "$INSTALL_SH" ]; then
  echo "bootstrap.sh: install script not found at '$INSTALL_SH'" >&2
  exit 3
fi

echo ""
if ! bash "$INSTALL_SH" "$@"; then
  echo "bootstrap.sh: install.sh exited with a non-zero status" >&2
  echo "Check the output above for details and re-run after fixing the issue." >&2
  exit 3
fi

# ---------------------------------------------------------------------------
# Write resolved repo path to ~/.agentic/agentic-engineering-config.json
# Additive (preserves all existing keys). Non-fatal on any failure.
# ---------------------------------------------------------------------------
if ! python3 - "$HOME/.agentic/agentic-engineering-config.json" "$AE_DEST_DIR" <<'PYEOF'
import json, sys, os
cfg, repo_dir = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(cfg), exist_ok=True)
data = {}
if os.path.exists(cfg):
    try:
        with open(cfg) as f: data = json.load(f)
    except Exception: data = {}
data["repo_dir"] = repo_dir
with open(cfg, "w") as f:
    json.dump(data, f, indent=2); f.write("\n")
PYEOF
then
  echo "bootstrap.sh: warning: failed to write repo_dir to ~/.agentic/agentic-engineering-config.json (non-fatal)" >&2
fi

# ---------------------------------------------------------------------------
# Success summary
# ---------------------------------------------------------------------------
echo ""
echo "agentic-engineering installed to: $AE_DEST_DIR"
echo "Update anytime via either:"
echo "  cd $AE_DEST_DIR && ./update.sh"
echo "  or the /update-agentic-engineering command inside Claude Code (location-aware)"
echo ""
# Remind about PATH if ~/.local/bin is not already on it
if ! echo ":$PATH:" | grep -q ":$HOME/.local/bin:"; then
  echo "NOTE: agentic binaries were linked to ~/.local/bin, which is not yet on your PATH."
  echo "Add to your shell profile (~/.zshrc or ~/.bashrc):"
  echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo "Then open a new shell or run: source ~/.zshrc"
fi
