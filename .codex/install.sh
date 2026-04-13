#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

SKILL_SRC="$REPO_DIR/.codex/skill"
SKILL_DST="$HOME/.agents/skills/agentic-engineering"
OLD_SKILL_DST="$HOME/.codex/skills/agentic-engineering"

AGENTS_SRC="$REPO_DIR/.codex/AGENTS.md"
AGENTS_DST="$HOME/.codex/AGENTS.md"

# ---------------------------------------------------------------------------
# Run build to ensure artifacts are up to date
# ---------------------------------------------------------------------------

echo "Running build..."
bash "$REPO_DIR/.codex/build.sh"

# ---------------------------------------------------------------------------
# Clean up old (incorrect) skill symlink at ~/.codex/skills/agentic-engineering/
# The correct path per Codex docs is ~/.agents/skills/<name>/, not ~/.codex/skills/.
# ---------------------------------------------------------------------------

if [[ -L "$OLD_SKILL_DST" ]]; then
  old_target="$(readlink "$OLD_SKILL_DST")"
  if [[ "$old_target" == "$SKILL_SRC" ]]; then
    rm "$OLD_SKILL_DST"
    echo "  - Removed stale symlink at $OLD_SKILL_DST (was pointing to $SKILL_SRC)"
  else
    echo "  ! $OLD_SKILL_DST points to $old_target (not ours - leaving it)"
  fi
elif [[ -e "$OLD_SKILL_DST" ]]; then
  echo "  ! Real file/directory at $OLD_SKILL_DST - not removing (manual cleanup may be needed)"
fi

# ---------------------------------------------------------------------------
# Symlink the agentic-engineering skill into ~/.agents/skills/
# Per Codex docs: user-scope skills load from $HOME/.agents/skills/<name>/SKILL.md
# ---------------------------------------------------------------------------

echo "Linking skill: agentic-engineering..."

mkdir -p "$(dirname "$SKILL_DST")"

if [[ -L "$SKILL_DST" ]]; then
  current_target="$(readlink "$SKILL_DST")"
  if [[ "$current_target" == "$SKILL_SRC" ]]; then
    echo "  = agentic-engineering (already linked)"
  else
    echo "  ! agentic-engineering (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$SKILL_DST" ]]; then
  echo "  ! agentic-engineering (real file/directory exists at destination - skipping)"
else
  ln -s "$SKILL_SRC" "$SKILL_DST"
  echo "  + agentic-engineering skill linked to $SKILL_DST"
fi

# ---------------------------------------------------------------------------
# Symlink ~/.codex/AGENTS.md to .codex/AGENTS.md
# Per Codex docs: global scope loads ~/.codex/AGENTS.md
# ---------------------------------------------------------------------------

echo "Linking global AGENTS.md..."

mkdir -p "$HOME/.codex"

if [[ -L "$AGENTS_DST" ]]; then
  current_target="$(readlink "$AGENTS_DST")"
  if [[ "$current_target" == "$AGENTS_SRC" ]]; then
    echo "  = ~/.codex/AGENTS.md (already linked)"
  else
    echo "  ! ~/.codex/AGENTS.md (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$AGENTS_DST" ]]; then
  BACKUP="$AGENTS_DST.backup-$(date +%Y%m%d%H%M%S)"
  echo ""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "  WARNING: ~/.codex/AGENTS.md already exists and is NOT a symlink."
  echo "  Backing it up to: $BACKUP"
  echo "  The existing file will be REPLACED with the agentic-engineering symlink."
  echo "  To restore: cp \"$BACKUP\" \"$AGENTS_DST\""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo ""
  mv "$AGENTS_DST" "$BACKUP"
  ln -s "$AGENTS_SRC" "$AGENTS_DST"
  echo "  + ~/.codex/AGENTS.md linked (backup saved to $BACKUP)"
else
  ln -s "$AGENTS_SRC" "$AGENTS_DST"
  echo "  + ~/.codex/AGENTS.md linked to $AGENTS_SRC"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Install complete."
echo ""
echo "What was installed:"
echo "  ~/.agents/skills/agentic-engineering  -> $SKILL_SRC"
echo "    Contains: SKILL.md (trigger + methodology summary)"
echo "              references/ (skeptic-protocol, subagent-protocol, agent-team, design-goals)"
echo ""
echo "  ~/.codex/AGENTS.md  -> $AGENTS_SRC"
echo "    Contains: Full agentic engineering methodology (loaded globally by Codex)"
echo ""
echo "What is available in the repo:"
echo "  .codex/AGENTS.md       - Source for the global ~/.codex/AGENTS.md symlink"
echo "  .codex/references/     - Local copies of reference docs"
echo "  .codex/commands/       - Command prompt templates (manual invocation)"
echo ""
echo "IMPORTANT - coexistence note:"
echo "  This install writes to ~/.agents/skills/ and ~/.codex/AGENTS.md."
echo "  It does NOT modify ~/.codex/config.toml or other Codex config files."
echo "  Safe to run alongside the Claude Code adapter."
echo ""
echo "Next steps:"
echo "  1. Open Codex in a project that uses this methodology."
echo "  2. The agentic-engineering skill will trigger automatically for software development tasks."
echo "  3. ~/.codex/AGENTS.md loads the full methodology globally in every Codex session."
echo "  4. The project's AGENTS.md (if present) loads additional project-specific rules."
echo "  5. For command templates, see .codex/commands/ and paste them into your session."
echo "  6. See .codex/README.md for known limitations and usage notes."
