#!/usr/bin/env bash
# Purpose: Build the Claude Code adapter outputs from canonical content/.
# Public API: invoked as `bash .claude/build.sh`; idempotent.
#             Optional tier filter: `bash .claude/build.sh minimal|medium|full`.
#             Default: builds all 3 tiers.
#
# Upstream deps: content/commands/, content/references[-<tier>]/, content/sections/,
#               content/SKILL[-<tier>].md, content/project-scaffolding.yml,
#               content/templates/, scripts/build-methodology.sh,
#               scripts/lib/tier-filter.py, python3,
#               .claude/skills/agentic-engineering/SKILL.frontmatter.yaml
#               .claude/skills/agentic-engineering-<tier>/SKILL.frontmatter.yaml
#
# Downstream consumers:
#   .claude/commands/                                  (shared, all tiers)
#   .claude/skills/agentic-engineering/                (full tier)
#   .claude/skills/agentic-engineering-medium/         (medium tier)
#   .claude/skills/agentic-engineering-minimal/        (minimal tier)
#
# Failure modes: exits non-zero on missing inputs, broken hardlinks, or assembly script failure.
# Performance: standard.

set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
COMMANDS_DST="$REPO_DIR/.claude/commands"
SCRIPTS="$REPO_DIR/scripts"

PREREQ='> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.'

# Portable inode helper (macOS uses -f, Linux uses -c)
get_inode() {
  if stat -c %i /dev/null >/dev/null 2>&1; then
    stat -c %i "$1"
  else
    stat -f %i "$1"
  fi
}

# Hardlink if not already linked to source
hardlink_if_changed() {
  local src="$1" dst="$2"
  if [[ -e "$dst" ]] && [[ "$(get_inode "$src")" == "$(get_inode "$dst")" ]]; then
    return 0
  fi
  rm -f "$dst"
  ln "$src" "$dst"
}

# Build one tier's skill directory.
# Args: $1 = tier (minimal|medium|full)
build_tier() {
  local tier="$1"
  local suffix=""
  local skill_src_name="SKILL-full.md"
  local refs_src_dir="$CONTENT/references"
  local sections_dir_arg=""
  local skill_dst

  case "$tier" in
    minimal)
      suffix="-minimal"
      skill_src_name="SKILL-minimal.md"
      refs_src_dir="$CONTENT/references-minimal"
      sections_dir_arg="minimal"
      ;;
    medium)
      suffix="-medium"
      skill_src_name="SKILL-medium.md"
      refs_src_dir="$CONTENT/references-medium"
      sections_dir_arg="medium"
      ;;
    full)
      suffix=""
      skill_src_name="SKILL-full.md"
      refs_src_dir="$CONTENT/references"
      sections_dir_arg="full"
      ;;
  esac
  skill_dst="$REPO_DIR/.claude/skills/agentic-engineering${suffix}"
  mkdir -p "$skill_dst"

  # METHODOLOGY.md: assemble sections for this tier
  bash "$SCRIPTS/build-methodology.sh" "$sections_dir_arg" > "$skill_dst/METHODOLOGY.md"
  # SKILL.md: frontmatter + body. Each tier has its own frontmatter.
  local frontmatter="$skill_dst/SKILL.frontmatter.yaml"
  local skill_body="$CONTENT/$skill_src_name"
  if [[ ! -f "$frontmatter" ]]; then
    echo "build.sh: missing $frontmatter" >&2
    exit 1
  fi
  if [[ ! -f "$skill_body" ]]; then
    echo "build.sh: missing $skill_body" >&2
    exit 1
  fi
  {
    cat "$frontmatter"
    echo
    # Strip leading HTML comment block (manifest header) if present
    perl -0pe 's/\A<!--.*?-->\n\n?//s' "$skill_body"
  } > "$skill_dst/SKILL.md"

  # rules/: hardlink from content/rules/ for full tier only
  if [[ "$tier" == "full" ]]; then
    mkdir -p "$skill_dst/rules"
    for src in "$CONTENT/rules/"*.md; do
      [[ -f "$src" ]] || continue
      local name dst
      name="$(basename "$src")"
      dst="$skill_dst/rules/$name"
      hardlink_if_changed "$src" "$dst"
    done
  fi

  # references/: hardlink from tier-appropriate references/
  mkdir -p "$skill_dst/references"
  if [[ -d "$refs_src_dir" ]]; then
    for src in "$refs_src_dir"/*.md; do
      [[ -f "$src" ]] || continue
      local name dst
      name="$(basename "$src")"
      dst="$skill_dst/references/$name"
      hardlink_if_changed "$src" "$dst"
    done
  fi

  # project-scaffolding.yml: hardlink from content/
  if [[ -f "$CONTENT/project-scaffolding.yml" ]]; then
    hardlink_if_changed "$CONTENT/project-scaffolding.yml" "$skill_dst/project-scaffolding.yml"
  fi

  # templates/: hardlink .agentic seed files (full tier only)
  if [[ "$tier" == "full" && -d "$CONTENT/templates/.agentic" ]]; then
    mkdir -p "$skill_dst/templates/.agentic"
    for tmpl_name in config.json learnings.md; do
      local TMPL_SRC="$CONTENT/templates/.agentic/$tmpl_name"
      local TMPL_DST="$skill_dst/templates/.agentic/$tmpl_name"
      if [[ -f "$TMPL_SRC" ]]; then
        hardlink_if_changed "$TMPL_SRC" "$TMPL_DST"
      fi
    done
  fi

  echo "  + built tier=$tier -> ${skill_dst#$REPO_DIR/}"
}

# Tier filter (CLI arg) or build all
TIER_FILTER="${1:-all}"
case "$TIER_FILTER" in
  all|minimal|medium|full) ;;
  *)
    echo "build.sh: invalid filter '$TIER_FILTER' (expected all|minimal|medium|full)" >&2
    exit 2
    ;;
esac

echo "Claude adapter build: tiers=$TIER_FILTER"

# Commands (shared, all tiers) — prepend prerequisite blockquote.
# The implement-ticket-body.md source is a tier-annotated input to
# scripts/build-commands.sh and is NOT a generated command body. Exclude it
# from the adapter copy so the adapter's commands dir contains only the
# router and the three tier-specific bodies.
mkdir -p "$COMMANDS_DST"
for src in "$CONTENT/commands/"*.md; do
  [[ -f "$src" ]] || continue
  name="$(basename "$src")"
  case "$name" in
    implement-ticket-body.md) continue ;;  # source for scripts/build-commands.sh
  esac
  { echo "$PREREQ"; echo; cat "$src"; } > "$COMMANDS_DST/$name"
done

# Agents: hardlink each tier's agent sources into .claude/agents[-<tier>]/
# (commands stay shared, agents are tier-specific)
for tier in full medium minimal; do
  src_dir="$CONTENT/agents"
  dst_dir="$REPO_DIR/.claude/agents"
  case "$tier" in
    medium)
      src_dir="$CONTENT/agents-medium"
      dst_dir="$REPO_DIR/.claude/agents-medium"
      ;;
    minimal)
      src_dir="$CONTENT/agents-minimal"
      dst_dir="$REPO_DIR/.claude/agents-minimal"
      ;;
  esac
  if [[ ! -d "$src_dir" ]]; then
    if [[ "$TIER_FILTER" == "all" || "$TIER_FILTER" == "$tier" ]]; then
      echo "  ! tier=$tier source missing: $src_dir (skipping)"
    fi
    continue
  fi
  mkdir -p "$dst_dir"
  for src in "$src_dir"/*.md; do
    [[ -f "$src" ]] || continue
    name="$(basename "$src")"
    hardlink_if_changed "$src" "$dst_dir/$name"
  done
  echo "  + linked $tier agents -> ${dst_dir#$REPO_DIR/}"
done

# Build tier skill directories
if [[ "$TIER_FILTER" == "all" ]]; then
  build_tier full
  build_tier medium
  build_tier minimal
else
  build_tier "$TIER_FILTER"
fi

echo "Claude adapter build complete."