#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

SKILL_SRC="$REPO_DIR/.codex/skill"
SKILL_DST="$HOME/.agents/skills/agentic-engineering"
OLD_SKILL_DST="$HOME/.codex/skills/agentic-engineering"

AGENTS_SRC="$REPO_DIR/.codex/AGENTS.md"
AGENTS_DST="$HOME/.codex/AGENTS.md"

NAMED_AGENTS_SRC="$REPO_DIR/.codex/agents"
NAMED_AGENTS_DST="$HOME/.codex/agents"

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
# Symlink ~/.codex/agents/ to .codex/agents/ (named agent TOML files)
# Per Codex docs: personal named agents load from ~/.codex/agents/<name>.toml
# ---------------------------------------------------------------------------

echo "Linking named agents directory..."

mkdir -p "$(dirname "$NAMED_AGENTS_DST")"

if [[ -L "$NAMED_AGENTS_DST" ]]; then
  current_target="$(readlink "$NAMED_AGENTS_DST")"
  if [[ "$current_target" == "$NAMED_AGENTS_SRC" ]]; then
    echo "  = ~/.codex/agents/ (already linked)"
  else
    echo "  ! ~/.codex/agents/ (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$NAMED_AGENTS_DST" ]]; then
  BACKUP="${NAMED_AGENTS_DST}.backup-$(date +%Y%m%d%H%M%S)"
  echo ""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "  WARNING: ~/.codex/agents/ already exists and is NOT a symlink."
  echo "  Backing it up to: $BACKUP"
  echo "  The existing directory will be REPLACED with the agentic-engineering symlink."
  echo "  To restore: mv \"$BACKUP\" \"$NAMED_AGENTS_DST\""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo ""
  mv "$NAMED_AGENTS_DST" "$BACKUP"
  ln -s "$NAMED_AGENTS_SRC" "$NAMED_AGENTS_DST"
  echo "  + ~/.codex/agents/ linked (backup saved to $BACKUP)"
else
  ln -s "$NAMED_AGENTS_SRC" "$NAMED_AGENTS_DST"
  echo "  + ~/.codex/agents/ linked to $NAMED_AGENTS_SRC"
fi

HOOKS_SRC="$REPO_DIR/.codex/hooks.json"
HOOKS_DST="$HOME/.codex/hooks.json"

CONFIG_FILE="$HOME/.codex/config.toml"

# ---------------------------------------------------------------------------
# Symlink ~/.codex/hooks.json to .codex/hooks.json
# Codex discovers hooks.json next to config layers; ~/.codex/hooks.json is
# the user-scope location that applies globally.
# ---------------------------------------------------------------------------

echo "Linking hooks.json..."

if [[ -L "$HOOKS_DST" ]]; then
  current_target="$(readlink "$HOOKS_DST")"
  if [[ "$current_target" == "$HOOKS_SRC" ]]; then
    echo "  = ~/.codex/hooks.json (already linked)"
  else
    echo "  ! ~/.codex/hooks.json (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$HOOKS_DST" ]]; then
  BACKUP="$HOOKS_DST.backup-$(date +%Y%m%d%H%M%S)"
  echo ""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "  WARNING: ~/.codex/hooks.json already exists and is NOT a symlink."
  echo "  Backing it up to: $BACKUP"
  echo "  The existing file will be REPLACED with the agentic-engineering symlink."
  echo "  To restore: cp \"$BACKUP\" \"$HOOKS_DST\""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo ""
  mv "$HOOKS_DST" "$BACKUP"
  ln -s "$HOOKS_SRC" "$HOOKS_DST"
  echo "  + ~/.codex/hooks.json linked (backup saved to $BACKUP)"
else
  ln -s "$HOOKS_SRC" "$HOOKS_DST"
  echo "  + ~/.codex/hooks.json linked to $HOOKS_SRC"
fi

# ---------------------------------------------------------------------------
# Enable codex_hooks feature flag in ~/.codex/config.toml
# The hooks system requires [features] codex_hooks = true.
# We add the flag only if missing and preserve all existing content.
# If the config file does not exist, we create it with only this flag.
# ---------------------------------------------------------------------------

echo "Checking codex_hooks feature flag in config.toml..."

ADDED_CODEX_HOOKS_FLAG=0

if [[ -f "$CONFIG_FILE" ]]; then
  if grep -qE '^[[:space:]]*codex_hooks[[:space:]]*=[[:space:]]*true' "$CONFIG_FILE" 2>/dev/null; then
    echo "  = codex_hooks already enabled in $CONFIG_FILE"
  elif grep -qE '^[[:space:]]*codex_hooks[[:space:]]*=' "$CONFIG_FILE" 2>/dev/null; then
    echo ""
    echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "  WARNING: codex_hooks is present in $CONFIG_FILE but is NOT set to true."
    echo "  Hooks will not fire until you manually set it to:"
    echo "    codex_hooks = true"
    echo "  in the [features] section of $CONFIG_FILE"
    echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo ""
  else
    # File exists, flag is missing. Add it safely.
    # Check if [features] section exists
    if grep -q "^\[features\]" "$CONFIG_FILE" 2>/dev/null; then
      # [features] section exists - insert the flag after the FIRST match only
      # Use a temp file to avoid in-place issues
      TMPFILE="$(mktemp)"
      awk 'BEGIN{done=0} /^\[features\]/ && !done {print; print "codex_hooks = true"; done=1; next} 1' "$CONFIG_FILE" > "$TMPFILE"
      mv "$TMPFILE" "$CONFIG_FILE"
      echo "  + Added codex_hooks = true to existing [features] section in $CONFIG_FILE"
      ADDED_CODEX_HOOKS_FLAG=1
    else
      # No [features] section - append it
      printf '\n[features]\ncodex_hooks = true\n' >> "$CONFIG_FILE"
      echo "  + Appended [features] section with codex_hooks = true to $CONFIG_FILE"
      ADDED_CODEX_HOOKS_FLAG=1
    fi
  fi
else
  # Config file does not exist - create it with only the feature flag
  mkdir -p "$(dirname "$CONFIG_FILE")"
  printf '[features]\ncodex_hooks = true\n' > "$CONFIG_FILE"
  echo "  + Created $CONFIG_FILE with [features] codex_hooks = true"
  ADDED_CODEX_HOOKS_FLAG=1
fi

# Write a marker file so uninstall.sh knows to remove the flag
HOOKS_FLAG_MARKER="$HOME/.codex/.agentic-eng-added-codex-hooks-flag"
if [[ $ADDED_CODEX_HOOKS_FLAG -eq 1 ]]; then
  touch "$HOOKS_FLAG_MARKER"
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
echo "  ~/.codex/agents/  -> $NAMED_AGENTS_SRC"
echo "    Contains: Named agent TOML files (engineer, architect, debugger, investigator,"
echo "              qa-engineer, security-auditor, orchestration-planner, skeptic,"
echo "              adr-drift-detector, adr-generator)"
echo ""
echo "  ~/.codex/hooks.json  -> $HOOKS_SRC"
echo "    Contains: UserPromptSubmit (risk reminder) and Stop (context save) hooks"
echo "    Requires: [features] codex_hooks = true in ~/.codex/config.toml (added automatically)"
echo ""
echo "What is available in the repo:"
echo "  .codex/AGENTS.md       - Source for the global ~/.codex/AGENTS.md symlink"
echo "  .codex/agents/         - Generated named agent TOML files (source: content/agents/*.md)"
echo "  .codex/hooks.json      - Hooks configuration (UserPromptSubmit + Stop)"
echo "  .codex/hooks/          - Hook scripts (risk-reminder.sh, stop-context-codex.js)"
echo "  .codex/commands/       - Source command templates (hardlinks from content/commands/)"
echo "  .codex/references/     - Local copies of reference docs"
echo ""
echo "IMPORTANT - coexistence note:"
echo "  This install writes to ~/.agents/skills/, ~/.codex/AGENTS.md,"
echo "  ~/.codex/agents/, ~/.codex/hooks.json, and"
echo "  may have added codex_hooks = true to ~/.codex/config.toml."
echo "  Safe to run alongside the Claude Code adapter."
echo ""
echo "Next steps:"
echo "  1. Open Codex in a project that uses this methodology."
echo "  2. The agentic-engineering skill will trigger automatically for software development tasks."
echo "  3. ~/.codex/AGENTS.md loads the full methodology globally in every Codex session."
echo "  4. The project's AGENTS.md (if present) loads additional project-specific rules."
echo "  5. Risk reminder hook fires automatically before each prompt."
echo "  6. Session context saved to ~/.codex/projects/[hash]/context.md on Stop."
echo "  7. Command templates live in .codex/commands/ for manual use when needed."
echo "  8. See .codex/README.md for full documentation."
