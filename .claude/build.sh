#!/usr/bin/env bash
# Purpose: Build the Claude Code adapter outputs from canonical content/.
# Public API: invoked as `bash .claude/build.sh`; idempotent.
# Upstream deps: content/commands/, content/references/, content/rules/, content/sections/,
#               content/SKILL.md, content/project-scaffolding.yml, content/templates/,
#               content/output-styles/, scripts/build-methodology.sh,
#               .claude/skills/dinostack/SKILL.frontmatter.yaml,
#               .claude/commands.frontmatter/ (optional per-command frontmatter sidecars).
# Downstream consumers: .claude/commands/, .claude/skills/dinostack/{SKILL.md,METHODOLOGY.md,references/,
#                       project-scaffolding.yml,templates/,output-styles/}.
# Failure modes: exits non-zero on missing inputs, broken hardlinks, or assembly script failure.
# Side-effects: removes stale .claude/commands/*.md files whose basename no longer matches any
#               content/commands/*.md source (e.g. after a command rename or deletion upstream).
#               Also embeds METHODOLOGY.md and content/rules/*.md (except module-manifest.md)
#               verbatim into the generated SKILL.md body under an "Embedded Resident Content"
#               section, so the full methodology loads on skill invocation without relying on
#               ~/.claude/CLAUDE.md's @-import lines.
# Performance: standard.

set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
COMMANDS_DST="$REPO_DIR/.claude/commands"
SKILL_DST="$REPO_DIR/.claude/skills/dinostack"
REFS_DST="$SKILL_DST/references"

PREREQ='> **Prerequisite:** If the /dinostack skill has not been loaded in this session, invoke it first before proceeding.'

# Portable inode helper (macOS uses -f, Linux uses -c)
get_inode() {
  if stat -c %i /dev/null >/dev/null 2>&1; then
    stat -c %i "$1"
  else
    stat -f %i "$1"
  fi
}

# Methodology: assemble content/sections/*.md into a single METHODOLOGY.md.
mkdir -p "$SKILL_DST"
bash "$REPO_DIR/scripts/build-methodology.sh" > "$SKILL_DST/METHODOLOGY.md"

# SKILL.md: assemble from adapter-private frontmatter + canonical content/SKILL.md body.
# content/SKILL.md may begin with an HTML comment manifest block (<!-- ... -->); strip it
# before concatenating so the assembled output matches the expected adapter SKILL.md format.
FRONTMATTER="$SKILL_DST/SKILL.frontmatter.yaml"
if [[ ! -f "$FRONTMATTER" ]]; then
  echo "build.sh: missing $FRONTMATTER" >&2
  exit 1
fi
if [[ ! -f "$CONTENT/SKILL.md" ]]; then
  echo "build.sh: missing $CONTENT/SKILL.md" >&2
  exit 1
fi
{
  cat "$FRONTMATTER"
  echo
  # Strip leading HTML comment block (manifest header) if present, then emit body.
  perl -0pe 's/\A<!--.*?-->\n\n?//s' "$CONTENT/SKILL.md"
} > "$SKILL_DST/SKILL.md"

# Embed resident content directly into SKILL.md so it loads on skill invocation
# instead of via the three @-import lines in ~/.claude/CLAUDE.md. This lets the
# imports be dropped from ~/.claude/CLAUDE.md (a separate unit) without losing
# always-on access to METHODOLOGY.md and the two rules files - Claude Code injects
# the full SKILL.md body verbatim when the skill is invoked.
{
  echo ""
  echo "## Embedded Resident Content"
  echo ""
  echo "### METHODOLOGY.md"
  echo ""
  cat "$SKILL_DST/METHODOLOGY.md"
  echo ""
  for f in "$CONTENT/rules/"*.md; do
    name=$(basename "$f")
    [[ "$name" == "module-manifest.md" ]] && continue
    echo "### rules/${name}"
    echo ""
    cat "$f"
    echo ""
  done
  echo ""
  echo "## Note for this Claude Code build"
  echo ""
  echo "The rules and methodology files named above under 'Rules (read these files)'"
  echo "(METHODOLOGY.md, rules/code-standards.md, rules/conventions.md) are embedded"
  echo "verbatim above under 'Embedded Resident Content' - they are already in context now that this skill has been invoked. Do not issue a separate Read for them."
} >> "$SKILL_DST/SKILL.md"

# Commands: prepend prerequisite blockquote. If an adapter-private frontmatter
# sidecar exists at .claude/commands.frontmatter/<name>.yaml, prepend it as a
# YAML frontmatter block before the prereq. Sidecars let a single command get
# a cheaper model on this adapter without touching the shared content/commands/
# source (other adapters consume that file verbatim or wrap it themselves).
FRONTMATTER_DIR="$REPO_DIR/.claude/commands.frontmatter"
declare -a generated_commands=()
for src in "$CONTENT/commands/"*.md; do
  name="$(basename "$src")"
  base="${name%.md}"
  sidecar="$FRONTMATTER_DIR/$base.yaml"
  generated_commands+=("$name")
  if [[ -f "$sidecar" ]]; then
    { echo "---"; cat "$sidecar"; echo "---"; echo; echo "$PREREQ"; echo; cat "$src"; } > "$COMMANDS_DST/$name"
  else
    { echo "$PREREQ"; echo; cat "$src"; } > "$COMMANDS_DST/$name"
  fi
done

# Remove stale command files (source was renamed or deleted upstream)
for existing in "$COMMANDS_DST"/*.md; do
  [ -f "$existing" ] || continue
  bname="$(basename "$existing")"
  found=0
  for gen in "${generated_commands[@]}"; do
    if [[ "$gen" == "$bname" ]]; then
      found=1
      break
    fi
  done
  if [[ $found -eq 0 ]]; then
    rm "$existing"
    echo "Removed stale command: $bname"
  fi
done

# References: hardlink from content/ so edits stay in sync across adapters
mkdir -p "$REFS_DST"
for src in "$CONTENT/references/"*.md; do
  name="$(basename "$src")"
  dst="$REFS_DST/$name"
  if [[ -e "$dst" ]] && [[ "$(get_inode "$src")" == "$(get_inode "$dst")" ]]; then
    continue
  fi
  rm -f "$dst"
  ln "$src" "$dst"
done

# project-scaffolding.yml: hardlink from content/ so it stays in sync
SCAFFOLDING_SRC="$CONTENT/project-scaffolding.yml"
SCAFFOLDING_DST="$SKILL_DST/project-scaffolding.yml"
if [[ -e "$SCAFFOLDING_DST" ]] && [[ "$(get_inode "$SCAFFOLDING_SRC")" == "$(get_inode "$SCAFFOLDING_DST")" ]]; then
  :
else
  rm -f "$SCAFFOLDING_DST"
  ln "$SCAFFOLDING_SRC" "$SCAFFOLDING_DST"
fi

# templates/: hardlink .agentic seed files (glob so new templates auto-propagate)
mkdir -p "$SKILL_DST/templates/.agentic"
for TMPL_SRC in "$CONTENT"/templates/.agentic/*; do
  [[ -f "$TMPL_SRC" ]] || continue
  tmpl_name="$(basename "$TMPL_SRC")"
  TMPL_DST="$SKILL_DST/templates/.agentic/$tmpl_name"
  if [[ -e "$TMPL_DST" ]] && [[ "$(get_inode "$TMPL_SRC")" == "$(get_inode "$TMPL_DST")" ]]; then
    :
  else
    rm -f "$TMPL_DST"
    ln "$TMPL_SRC" "$TMPL_DST"
  fi
done

# output-styles/: plain copy (not hardlink) from content/ - a leaf artifact
# with no downstream re-consumption inside .claude/skills/dinostack/, unlike
# content/rules/*.md, so a copy is correct and matches the pattern below
# rather than the hardlink pattern above.
mkdir -p "$SKILL_DST/output-styles"
cp "$CONTENT/output-styles/dinostack.md" "$SKILL_DST/output-styles/dinostack.md"

echo "Claude adapter build complete."
