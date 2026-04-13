#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SKILL_SRC="$REPO_DIR/.codex/skill"
SKILL_DST="$HOME/.agents/skills/agentic-engineering"
OLD_SKILL_DST="$HOME/.codex/skills/agentic-engineering"

AGENTS_SRC="$REPO_DIR/.codex/AGENTS.md"
AGENTS_DST="$HOME/.codex/AGENTS.md"

NAMED_AGENTS_SRC="$REPO_DIR/.codex/agents"
NAMED_AGENTS_DST="$HOME/.codex/agents"

HOOKS_SRC="$REPO_DIR/.codex/hooks.json"
HOOKS_DST="$HOME/.codex/hooks.json"

CONFIG_FILE="$HOME/.codex/config.toml"
HOOKS_FLAG_MARKER="$HOME/.codex/.agentic-eng-added-codex-hooks-flag"
LEGACY_PROMPTS_BUILD="$REPO_DIR/.codex/prompts"
LEGACY_PROMPTS_DST="$HOME/.codex/prompts"

# ---------------------------------------------------------------------------
# Remove the agentic-engineering skill symlink from ~/.agents/skills/
# ---------------------------------------------------------------------------

echo "Removing skill: agentic-engineering..."

if [[ -L "$SKILL_DST" ]]; then
  current_target="$(readlink "$SKILL_DST")"
  if [[ "$current_target" == "$SKILL_SRC" ]]; then
    rm "$SKILL_DST"
    echo "  - agentic-engineering skill symlink removed from $SKILL_DST"
  else
    echo "  = $SKILL_DST (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$SKILL_DST" ]]; then
  echo "  = $SKILL_DST (real file/directory - not removing)"
else
  echo "  = $SKILL_DST (not found - nothing to do)"
fi

# Also clean up old (incorrect) symlink at ~/.codex/skills/ if present
if [[ -L "$OLD_SKILL_DST" ]]; then
  old_target="$(readlink "$OLD_SKILL_DST")"
  if [[ "$old_target" == "$SKILL_SRC" ]]; then
    rm "$OLD_SKILL_DST"
    echo "  - Removed stale legacy symlink at $OLD_SKILL_DST"
  fi
fi

# ---------------------------------------------------------------------------
# Remove ~/.codex/AGENTS.md symlink and restore backup if one exists
# ---------------------------------------------------------------------------

echo "Removing global AGENTS.md..."

if [[ -L "$AGENTS_DST" ]]; then
  current_target="$(readlink "$AGENTS_DST")"
  if [[ "$current_target" == "$AGENTS_SRC" ]]; then
    rm "$AGENTS_DST"
    echo "  - ~/.codex/AGENTS.md symlink removed"

    # Restore the most recent backup if one exists
    latest_backup="$(ls -t "${AGENTS_DST}.backup-"* 2>/dev/null | head -1 || true)"
    if [[ -n "$latest_backup" ]]; then
      mv "$latest_backup" "$AGENTS_DST"
      echo "  + Restored backup: $latest_backup -> ~/.codex/AGENTS.md"
    fi
  else
    echo "  = ~/.codex/AGENTS.md (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$AGENTS_DST" ]]; then
  echo "  = ~/.codex/AGENTS.md (real file - not removing)"
else
  echo "  = ~/.codex/AGENTS.md (not found - nothing to do)"
fi

# ---------------------------------------------------------------------------
# Remove ~/.codex/agents/ symlink and restore backup if one exists
# ---------------------------------------------------------------------------

echo "Removing named agents directory..."

if [[ -L "$NAMED_AGENTS_DST" ]]; then
  current_target="$(readlink "$NAMED_AGENTS_DST")"
  if [[ "$current_target" == "$NAMED_AGENTS_SRC" ]]; then
    rm "$NAMED_AGENTS_DST"
    echo "  - ~/.codex/agents/ symlink removed"

    # Restore the most recent backup if one exists
    latest_backup="$(ls -td "${NAMED_AGENTS_DST}.backup-"* 2>/dev/null | head -1 || true)"
    if [[ -n "$latest_backup" ]]; then
      mv "$latest_backup" "$NAMED_AGENTS_DST"
      echo "  + Restored backup: $latest_backup -> ~/.codex/agents/"
    fi
  else
    echo "  = ~/.codex/agents/ (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$NAMED_AGENTS_DST" ]]; then
  echo "  = ~/.codex/agents/ (real directory - not removing)"
else
  echo "  = ~/.codex/agents/ (not found - nothing to do)"
fi

# ---------------------------------------------------------------------------
# Remove ~/.codex/hooks.json symlink and restore backup if one exists
# ---------------------------------------------------------------------------

echo "Removing hooks.json..."

if [[ -L "$HOOKS_DST" ]]; then
  current_target="$(readlink "$HOOKS_DST")"
  if [[ "$current_target" == "$HOOKS_SRC" ]]; then
    rm "$HOOKS_DST"
    echo "  - ~/.codex/hooks.json symlink removed"

    # Restore the most recent backup if one exists
    latest_backup="$(ls -t "${HOOKS_DST}.backup-"* 2>/dev/null | head -1 || true)"
    if [[ -n "$latest_backup" ]]; then
      mv "$latest_backup" "$HOOKS_DST"
      echo "  + Restored backup: $latest_backup -> ~/.codex/hooks.json"
    fi
  else
    echo "  = ~/.codex/hooks.json (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$HOOKS_DST" ]]; then
  echo "  = ~/.codex/hooks.json (real file - not removing)"
else
  echo "  = ~/.codex/hooks.json (not found - nothing to do)"
fi

# ---------------------------------------------------------------------------
# Remove codex_hooks feature flag from ~/.codex/config.toml if we added it
# ---------------------------------------------------------------------------

echo "Removing codex_hooks feature flag..."

if [[ -f "$HOOKS_FLAG_MARKER" ]]; then
  if [[ -f "$CONFIG_FILE" ]]; then
    if grep -q "codex_hooks" "$CONFIG_FILE" 2>/dev/null; then
      # Remove the codex_hooks line from config.toml (match indented or spaced variants too)
      TMPFILE="$(mktemp)"
      grep -vE '^[[:space:]]*codex_hooks[[:space:]]*=' "$CONFIG_FILE" > "$TMPFILE"
      # Also remove [features] section if it is now empty (only whitespace/comments remain)
      # Simple approach: remove [features] line if the next non-blank/non-comment line is
      # another [section] or EOF. Use python3 for reliability.
      python3 - "$TMPFILE" <<'PYEOF'
import sys, re

with open(sys.argv[1]) as f:
    lines = f.readlines()

out = []
i = 0
while i < len(lines):
    line = lines[i]
    # Detect an empty [features] section: [features] followed by only blank/comment lines
    # before the next section or EOF
    if re.match(r'^\[features\]\s*$', line):
        # Look ahead to see if all remaining lines in this section are blank/comment
        j = i + 1
        while j < len(lines) and (lines[j].strip() == '' or lines[j].strip().startswith('#')):
            j += 1
        if j >= len(lines) or lines[j].startswith('['):
            # The [features] section is now empty - skip the header and blanks
            i = j
            # Also strip the trailing blank line that was before this section
            while out and out[-1].strip() == '':
                out.pop()
            continue
    out.append(line)
    i += 1

with open(sys.argv[1], 'w') as f:
    f.writelines(out)
PYEOF
      mv "$TMPFILE" "$CONFIG_FILE"
      echo "  - Removed codex_hooks flag from $CONFIG_FILE"
    else
      echo "  = codex_hooks not found in $CONFIG_FILE (already removed)"
    fi
  else
    echo "  = $CONFIG_FILE not found - nothing to remove"
  fi
  rm "$HOOKS_FLAG_MARKER"
  echo "  - Removed install marker"
else
  # Marker is absent. Check if config.toml still has the flag AND hooks.json points to our repo.
  # If both are true the user may have lost the marker; warn but do NOT remove the flag.
  hooks_dst_target=""
  if [[ -L "$HOOKS_DST" ]]; then
    hooks_dst_target="$(readlink "$HOOKS_DST")"
  fi
  if [[ -f "$CONFIG_FILE" ]] \
     && grep -qE '^[[:space:]]*codex_hooks[[:space:]]*=[[:space:]]*true' "$CONFIG_FILE" 2>/dev/null \
     && [[ "$hooks_dst_target" == "$HOOKS_SRC" ]]; then
    echo "  ! Marker file missing; leaving codex_hooks flag in config.toml. Remove manually if desired."
  else
    echo "  = No install marker found - codex_hooks flag was not added by this installer"
  fi
fi

# ---------------------------------------------------------------------------
# Remove legacy ~/.codex/prompts/ symlinks from older adapter versions
# ---------------------------------------------------------------------------

echo "Removing legacy custom prompt symlinks..."

if [[ -d "$LEGACY_PROMPTS_DST" ]] && [[ -d "$LEGACY_PROMPTS_BUILD" ]]; then
  removed_count=0
  for built in "$LEGACY_PROMPTS_BUILD/"*.md; do
    [ -f "$built" ] || continue
    bname="$(basename "$built")"
    link_dst="$LEGACY_PROMPTS_DST/$bname"

    if [[ -L "$link_dst" ]]; then
      current_target="$(readlink "$link_dst")"
      if [[ "$current_target" == "$built" ]]; then
        rm "$link_dst"
        echo "  - Removed legacy prompt symlink: $bname"
        removed_count=$((removed_count + 1))

        latest_backup="$(ls -t "${link_dst}.backup-"* 2>/dev/null | head -1 || true)"
        if [[ -n "$latest_backup" ]]; then
          mv "$latest_backup" "$link_dst"
          echo "    + Restored backup: $(basename "$latest_backup")"
        fi
      fi
    fi
  done
  if [[ $removed_count -eq 0 ]]; then
    echo "  = No legacy prompt symlinks found"
  fi
elif [[ ! -d "$LEGACY_PROMPTS_DST" ]]; then
  echo "  = ~/.codex/prompts/ not found - nothing to do"
else
  echo "  = No local legacy prompt build directory found - nothing to do"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Uninstall complete."
echo ""
echo "Note: The following files were NOT removed (they are part of the repo, not installed):"
echo "  .codex/AGENTS.md       - stays in the repo"
echo "  .codex/agents/         - stays in the repo (generated TOML files)"
echo "  .codex/hooks.json      - stays in the repo"
echo "  .codex/hooks/          - stays in the repo (hook scripts)"
echo "  .codex/references/     - stays in the repo"
echo "  .codex/commands/       - stays in the repo"
echo ""
echo "If you want to remove the full repo, delete ~/agentic-engineering/ manually."
