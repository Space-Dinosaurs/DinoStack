#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Uninstalls the DinoStack Codex adapter by removing only symlinks,
#          hook config, flags, legacy prompt links that point back to this
#          checkout, and its own marker-owned degrade-path companion file,
#          while restoring user backups where the installer made one.
#
# Public API:
#   bash .codex/uninstall.sh
#
# Upstream deps: bash 3.2+, python3, readlink, rm, rmdir, mktemp; optionally
#   scripts/lib/hooks-snapshot.sh for snapshot-aware hook cleanup.
#
# Downstream consumers: developers removing or refreshing the Codex adapter.
#
# Failure modes: skips real user files and symlinks not owned by this
#   checkout; the AGENTS.degraded.md companion is removed only when it
#   carries this checkout's own AGENTS_DEGRADED_MARKER first line, else
#   left in place as genuine user data; missing marker files prevent
#   automatic config flag removal; backup restore uses the newest matching
#   backup if present.
#
# Performance: local filesystem operations only; normally completes in <1 s.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SKILLS_SRC="$REPO_DIR/.codex/skills"
SKILLS_DST="$HOME/.agents/skills"
LEGACY_SKILL_SRC="$REPO_DIR/.codex/skill"
SKILL_NAMES=(dinostack brief wrap implement-ticket)

AGENTS_SRC="$REPO_DIR/.codex/AGENTS.md"
AGENTS_DST="$HOME/.codex/AGENTS.md"
# DS-183 round 5 (M1 fix): moved from $REPO_DIR/.codex/AGENTS.degraded.md
# (gitignored, deleted by a routine `git clean`) into the Codex config
# directory itself, alongside AGENTS_DST. See install.sh's matching comment.
AGENTS_DEGRADED="$HOME/.codex/AGENTS.degraded.md"
# DS-183 round 6 (M1 fix): $AGENTS_DEGRADED is a user-owned config path, so
# a real file found there is only ours to remove when it carries this
# marker as its first line - same mechanism, and same marker string, as
# install.sh's AGENTS_DEGRADED_MARKER. A real file without it is genuine
# user data and is left alone.
AGENTS_DEGRADED_MARKER="<!-- dinostack:codex-degrade-generated -->"

NAMED_AGENTS_SRC="$REPO_DIR/.codex/agents"
NAMED_AGENTS_DST="$HOME/.codex/agents"

HOOKS_SRC="$REPO_DIR/.codex/config/hooks.json"
LEGACY_HOOKS_SRC="$REPO_DIR/.codex/hooks.json"
LEGACY_HOOKS_SRC2="$REPO_DIR/.codex/config/hooks.json"
HOOKS_DST="$HOME/.codex/hooks.json"

CONFIG_FILE="$HOME/.codex/config.toml"
HOOKS_FLAG_MARKER="$HOME/.codex/.agentic-eng-added-codex-hooks-flag"
LEGACY_PROMPTS_OLD_SRC_PREFIX="$HOME/dinostack/.codex/prompts"
LEGACY_PROMPTS_DST="$HOME/.codex/prompts"

canonicalize_path() {
  python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"
}

SNAPSHOT_HOOKS_SRC=""
if [[ -f "$REPO_DIR/scripts/lib/hooks-snapshot.sh" ]]; then
  # shellcheck source=scripts/lib/hooks-snapshot.sh
  if . "$REPO_DIR/scripts/lib/hooks-snapshot.sh" 2>/dev/null; then
    SNAPSHOT_DIR="$(hooks_snapshot_dir "$REPO_DIR" 2>/dev/null || true)"
    if [[ -n "$SNAPSHOT_DIR" ]]; then
      SNAPSHOT_HOOKS_SRC="$SNAPSHOT_DIR/.codex/config/hooks.json"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Remove the four native skill symlinks from ~/.agents/skills/
# ---------------------------------------------------------------------------

echo "Removing native skills..."

for skill_name in "${SKILL_NAMES[@]}"; do
  skill_src="$SKILLS_SRC/$skill_name"
  skill_dst="$SKILLS_DST/$skill_name"
  if [[ -L "$skill_dst" ]]; then
    current_target="$(readlink "$skill_dst")"
    if [[ "$current_target" == "$skill_src" || \
          ( "$skill_name" == "dinostack" && "$current_target" == "$LEGACY_SKILL_SRC" ) ]]; then
      rm "$skill_dst"
      echo "  - $skill_name skill symlink removed from $skill_dst"
    else
      echo "  = $skill_dst (points to $current_target - not ours, skipping)"
    fi
  elif [[ -e "$skill_dst" ]]; then
    echo "  = $skill_dst (real file/directory - not removing)"
  else
    echo "  = $skill_dst (not found - nothing to do)"
  fi
done

# Also clean up old (incorrect) symlinks at ~/.codex/skills/ if present
for skill_name in "${SKILL_NAMES[@]}"; do
  old_skill_dst="$HOME/.codex/skills/$skill_name"
  skill_src="$SKILLS_SRC/$skill_name"
  if [[ -L "$old_skill_dst" ]]; then
    old_target="$(readlink "$old_skill_dst")"
    if [[ "$old_target" == "$skill_src" || \
          ( "$skill_name" == "dinostack" && "$old_target" == "$LEGACY_SKILL_SRC" ) ]]; then
      rm "$old_skill_dst"
      echo "  - Removed stale legacy symlink at $old_skill_dst"
    fi
  fi
done

# ---------------------------------------------------------------------------
# Remove ~/.codex/AGENTS.md symlink and restore backup if one exists
# ---------------------------------------------------------------------------

echo "Removing global AGENTS.md..."

if [[ -L "$AGENTS_DST" ]]; then
  current_target="$(readlink "$AGENTS_DST")"
  if [[ "$current_target" == "$AGENTS_SRC" || "$current_target" == "$AGENTS_DEGRADED" ]]; then
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
# Remove the degrade-path companion file (DS-183 round 2, M3 fix; relocated
# round 5, M1 fix; marker-gated round 6, M1 fix). This file lives at
# $HOME/.codex/AGENTS.degraded.md, a sibling of $AGENTS_DST, so it survives
# outside the $AGENTS_DST symlink-removal block above and would otherwise
# never be cleaned up. $AGENTS_DEGRADED is now a user-owned config path, so
# a real file found there is recognized as ours - and removed outright,
# with its own backup restored if one exists - only when it carries
# AGENTS_DEGRADED_MARKER on its first line; a real file without the marker
# is genuine user data and is left in place untouched.
# ---------------------------------------------------------------------------

if [[ -f "$AGENTS_DEGRADED" && ! -L "$AGENTS_DEGRADED" ]]; then
  first_line="$(head -1 "$AGENTS_DEGRADED" 2>/dev/null || true)"
  if [[ "$first_line" == "$AGENTS_DEGRADED_MARKER" ]]; then
    rm "$AGENTS_DEGRADED"
    echo "  - $HOME/.codex/AGENTS.degraded.md (dinostack degrade-path artifact) removed"

    # Restore the most recent backup if one exists (round 6 M1 fix - the
    # three sibling symlink-removal blocks in this script all restore their
    # own backup; this block previously did not).
    latest_backup="$(ls -t "${AGENTS_DEGRADED}.backup-"* 2>/dev/null | head -1 || true)"
    if [[ -n "$latest_backup" ]]; then
      mv "$latest_backup" "$AGENTS_DEGRADED"
      echo "  + Restored backup: $latest_backup -> $AGENTS_DEGRADED"
    fi
  else
    echo "  = $HOME/.codex/AGENTS.degraded.md (real file, no dinostack marker - not removing)"
  fi
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
  current_target_canonical="$(canonicalize_path "$current_target")"
  hooks_src_canonical="$(canonicalize_path "$HOOKS_SRC")"
  legacy_hooks_src_canonical="$(canonicalize_path "$LEGACY_HOOKS_SRC")"
  legacy_hooks_src2_canonical="$(canonicalize_path "$LEGACY_HOOKS_SRC2")"
  snapshot_hooks_src_canonical=""
  if [[ -n "$SNAPSHOT_HOOKS_SRC" ]]; then
    snapshot_hooks_src_canonical="$(canonicalize_path "$SNAPSHOT_HOOKS_SRC")"
  fi
  if [[ "$current_target_canonical" == "$hooks_src_canonical" || \
        "$current_target_canonical" == "$legacy_hooks_src_canonical" || \
        "$current_target_canonical" == "$legacy_hooks_src2_canonical" || \
        ( -n "$snapshot_hooks_src_canonical" && "$current_target_canonical" == "$snapshot_hooks_src_canonical" ) ]]; then
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
  hooks_dst_target_canonical=""
  if [[ -n "$hooks_dst_target" ]]; then
    hooks_dst_target_canonical="$(canonicalize_path "$hooks_dst_target")"
  fi
  hooks_src_canonical="$(canonicalize_path "$HOOKS_SRC")"
  legacy_hooks_src_canonical="$(canonicalize_path "$LEGACY_HOOKS_SRC")"
  legacy_hooks_src2_canonical="$(canonicalize_path "$LEGACY_HOOKS_SRC2")"
  snapshot_hooks_src_canonical=""
  if [[ -n "$SNAPSHOT_HOOKS_SRC" ]]; then
    snapshot_hooks_src_canonical="$(canonicalize_path "$SNAPSHOT_HOOKS_SRC")"
  fi
  if [[ -f "$CONFIG_FILE" ]] \
     && grep -qE '^[[:space:]]*codex_hooks[[:space:]]*=[[:space:]]*true' "$CONFIG_FILE" 2>/dev/null \
     && [[ "$hooks_dst_target_canonical" == "$hooks_src_canonical" || \
           "$hooks_dst_target_canonical" == "$legacy_hooks_src_canonical" || \
           "$hooks_dst_target_canonical" == "$legacy_hooks_src2_canonical" || \
           ( -n "$snapshot_hooks_src_canonical" && "$hooks_dst_target_canonical" == "$snapshot_hooks_src_canonical" ) ]]; then
    echo "  ! Marker file missing; leaving codex_hooks flag in config.toml. Remove manually if desired."
  else
    echo "  = No install marker found - codex_hooks flag was not added by this installer"
  fi
fi

# ---------------------------------------------------------------------------
# Remove legacy ~/.codex/prompts/ symlinks from older adapter versions
# ---------------------------------------------------------------------------

echo "Removing legacy custom prompt symlinks..."

if [[ -d "$LEGACY_PROMPTS_DST" ]]; then
  removed_count=0
  for link_dst in "$LEGACY_PROMPTS_DST/"*.md; do
    [ -L "$link_dst" ] || continue
    current_target="$(readlink "$link_dst")"
    case "$current_target" in
      "$LEGACY_PROMPTS_OLD_SRC_PREFIX"/*.md)
        rm "$link_dst"
        echo "  - Removed legacy prompt symlink: $(basename "$link_dst")"
        removed_count=$((removed_count + 1))

        latest_backup="$(ls -t "${link_dst}.backup-"* 2>/dev/null | head -1 || true)"
        if [[ -n "$latest_backup" ]]; then
          mv "$latest_backup" "$link_dst"
          echo "    + Restored backup: $(basename "$latest_backup")"
        fi
        ;;
    esac
  done
  if [[ $removed_count -eq 0 ]]; then
    echo "  = No legacy prompt symlinks found"
  fi
else
  echo "  = ~/.codex/prompts/ not found - nothing to do"
fi

# ---------------------------------------------------------------------------
# Remove ~/.local/bin/agentic-* and ds-* symlinks
# ---------------------------------------------------------------------------

echo "Removing bin symlinks from ~/.local/bin..."

BIN_DST="$HOME/.local/bin"

if [[ ! -d "$BIN_DST" ]]; then
  echo "  [skip] ~/.local/bin not found"
else
  _found_any=false
  for dst_file in "$BIN_DST"/agentic-* "$BIN_DST"/ds-*; do
    [[ -e "$dst_file" || -L "$dst_file" ]] || continue
    _found_any=true
    name="$(basename "$dst_file")"

    if [[ -L "$dst_file" ]]; then
      current_target="$(readlink "$dst_file")"
      if [[ "$current_target" == "$REPO_DIR/bin/"* ]]; then
        rm "$dst_file"
        echo "  - $name removed"
      else
        echo "  = $name (points to $current_target - not ours, skipping)"
      fi
    else
      echo "  = $name (real file - not removing)"
    fi
  done
  if [[ "$_found_any" == false ]]; then
    echo "  = no agentic-*/ds-* entries found in ~/.local/bin"
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Uninstall complete."
echo ""
echo "Note: The following files were NOT removed (they are part of the repo, not installed):"
echo "  .codex/skills/         - stays in the repo (four generated native skills)"
echo "  .codex/AGENTS.md       - stays in the repo"
echo "  .codex/agents/         - stays in the repo (generated TOML files)"
echo "  .codex/config/hooks.json - stays in the repo"
echo "  .codex/hooks/          - stays in the repo (hook scripts)"
echo "  .codex/references/     - stays in the repo"
echo "  .codex/commands/       - stays in the repo"
echo ""
echo "If you want to remove the full repo, delete ~/DinoStack/ manually."
