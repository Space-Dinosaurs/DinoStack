#!/usr/bin/env bash
# Purpose: Two-sided guard on the generated .kimi/skills/dinostack/SKILL.md -
#          the artifact the `dinostack` skill injects on trigger under the
#          DS-185 Kimi trigger-load design (mirroring DS-143's
#          .claude/skills/dinostack/SKILL.md equivalent) - plus a
#          single-sided ceiling-only guard on the always-resident
#          .kimi/AGENTS.md stub that DS-185 shrank to a lean activation
#          pointer. Four failure classes:
#            - SKILL.md EMBED INCOMPLETE: a whole content/sections/*.md or
#              content/rules/*.md source file silently dropped from
#              assembly (a bad exclusion pattern, a broken loop, etc.),
#              detected via pinned EXPECTED_SECTION_COUNT/
#              EXPECTED_RULES_COUNT constants plus a per-file top-level
#              heading presence check, same mechanism as
#              check-skill-embed-budget.sh (Claude's equivalent gate).
#            - SKILL.md FLOOR: catches a regression to a pointer-only skill
#              body (.kimi/build.sh's embed step silently breaking and no
#              longer inlining METHODOLOGY.md/the two rules files into
#              SKILL.md).
#            - SKILL.md CEILING: an informational safety boundary, NOT a
#              verified-safe injection size - no swept injection
#              measurement has been run against the Kimi harness (unlike
#              Claude's docs/skill-embed-injection-sweep.md procedure,
#              DS-45). Set at ~10% headroom over the measured size at gate
#              creation (139,277 B -> 153,205 B). Do not cite this CEILING
#              as verified-safe; raise it only alongside evidence, and say
#              so explicitly in the PR that raises it - same discipline as
#              check-skill-embed-budget.sh's CEILING.
#            - AGENTS.md STUB CEILING: catches an accidental re-embed of
#              the methodology body back into the always-resident
#              .kimi/AGENTS.md file (the exact regression DS-185 exists to
#              prevent). Ceiling-only, no floor - a lean stub legitimately
#              has no minimum size.
#
# Public API: bash scripts/check-kimi-skill-embed-budget.sh
#             Exits 0 when the SKILL.md embed-completeness check passes,
#             FLOOR <= SKILL.md size <= CEILING, AND AGENTS.md size <=
#             AGENTS_CEILING. Exits 1 otherwise, or when a required input
#             is missing.
#
# Upstream deps: .kimi/skills/dinostack/SKILL.md and .kimi/AGENTS.md (both
#                built by .kimi/build.sh; this script does not rebuild
#                them - it measures whatever is currently on disk, matching
#                how check-adapter-sync and the runtime skill loader both
#                treat these files as the artifacts of record);
#                content/sections/[0-9][0-9]-*.md and content/rules/*.md
#                (excluding module-manifest.md) for the embed-completeness
#                check; scripts/lib/budget-gate.sh (shared repo-dir
#                resolution, byte measurement, and budget_burn_line - both
#                .kimi/skills/dinostack/SKILL.md and .kimi/AGENTS.md
#                classify as DERIVED per scripts/gate-provenance.sh, so
#                this gate uses the informational burn line only, never a
#                hard per-PR DELTA_LIMIT_BYTES).
#
# Downstream consumers: .github/workflows/kimi-skill-budget.yml (its
#                        checkout needs fetch-depth: 0 so the burn lines
#                        can resolve origin/main - a default shallow
#                        checkout would leave that ref unreachable and both
#                        lines would render their SKIPPED variant on every
#                        CI run). Advisory only - not added to the `main`
#                        branch ruleset's required-checks list, matching
#                        check-command-file-budget.sh's precedent.
#
# Failure modes: SKILL.md embed incomplete (a source file dropped from
#                assembly, or a file count mismatch against
#                EXPECTED_SECTION_COUNT/EXPECTED_RULES_COUNT) -> exit 1.
#                SKILL.md below FLOOR or above CEILING -> exit 1. AGENTS.md
#                above AGENTS_CEILING -> exit 1. Missing input file -> exit
#                1. Both burn lines are computed once, printed on every
#                exit path for their respective file, and never affect the
#                exit code - unresolvable git/base renders a "burn: SKIPPED
#                (...)" line rather than omitting it. Read-only; no side
#                effects on the repo.
#
# Compatible with both bash and zsh invocation, per the same discipline as
# check-skill-embed-budget.sh. Avoid the variable names `status` and
# `path` anywhere in this file - both are special/read-only in zsh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib/budget-gate.sh
source "$SCRIPT_DIR/lib/budget-gate.sh"
REPO_DIR="$(budget_repo_dir "$SCRIPT_DIR")"

SKILL_FILE="$REPO_DIR/.kimi/skills/dinostack/SKILL.md"
AGENTS_FILE="$REPO_DIR/.kimi/AGENTS.md"

# SKILL.md floor: catches a regression to a pointer-only skill body. Well
# below any realistic embedded size (139,277 B measured at gate creation)
# and well above what a pointer-only body (frontmatter + lean
# content/SKILL.md, no embedded methodology) would ever measure (~9,000 B).
SKILL_FLOOR=100000

# SKILL.md ceiling: informational safety boundary, NOT a verified-safe
# injection size for the Kimi harness - see the header comment above.
# 153,205 B = ceil(139,277 B measured at gate creation * 1.1).
SKILL_CEILING=153205

# AGENTS.md stub ceiling: catches an accidental re-embed of the
# methodology body. 1,462 B measured at gate creation; a re-embedded body
# would measure well over 100,000 B, so 8,000 B leaves generous room for
# the stub to grow (more command examples, a longer activation note, etc.)
# while still catching any re-embed by a wide margin.
AGENTS_CEILING=8000

# EXPECTED_SECTION_COUNT / EXPECTED_RULES_COUNT: pinned counts, ratcheted
# the same way check-skill-embed-budget.sh's equivalents are - update the
# same commit that adds, removes, or renumbers a
# content/sections/[0-9][0-9]-*.md file, or adds/removes a
# content/rules/*.md file other than module-manifest.md.
EXPECTED_SECTION_COUNT=12
EXPECTED_RULES_COUNT=2

if [ ! -f "$SKILL_FILE" ]; then
  echo "check-kimi-skill-embed-budget.sh: missing file: $SKILL_FILE" >&2
  echo "  Run .kimi/build.sh to regenerate it, then re-run this check." >&2
  exit 1
fi

if [ ! -f "$AGENTS_FILE" ]; then
  echo "check-kimi-skill-embed-budget.sh: missing file: $AGENTS_FILE" >&2
  echo "  Run .kimi/build.sh to regenerate it, then re-run this check." >&2
  exit 1
fi

# Embed-completeness check: a whole embedded source file can go missing
# from assembly and still land inside the FLOOR..CEILING byte band, where
# the two-sided bound check alone cannot see it. Checks a phrase from
# EVERY file in both sets - each file's own first top-level heading,
# derived dynamically so a renamed file is covered automatically. Same
# mechanism as check-skill-embed-budget.sh's _check_embedded_set.
_check_embedded_set() {
  local dir="$1" pattern="$2" exclude="$3" expected_count="$4" label="$5" constant_name="$6"
  local files file_count f heading
  if [ -n "$exclude" ]; then
    files="$(LC_ALL=C find "$dir" -maxdepth 1 -type f -name "$pattern" ! -name "$exclude" | LC_ALL=C sort)"
  else
    files="$(LC_ALL=C find "$dir" -maxdepth 1 -type f -name "$pattern" | LC_ALL=C sort)"
  fi
  if [ -z "$files" ]; then
    echo "check-kimi-skill-embed-budget.sh: no $label files found in $dir" >&2
    exit 1
  fi
  file_count="$(wc -l <<< "$files" | tr -d '[:space:]')"
  if [ "$file_count" -gt "$expected_count" ]; then
    echo "check-kimi-skill-embed-budget.sh: embed incomplete" >&2
    echo "  $label file count mismatch: expected $expected_count, found $file_count" >&2
    echo "  a new $label source file was added - this is likely intentional." >&2
    echo "  If so, bump $constant_name above in the same commit that adds the" >&2
    echo "  file. If not, an extra file landed under $dir unexpectedly -" >&2
    echo "  investigate before bumping the count." >&2
    exit 1
  fi
  if [ "$file_count" -lt "$expected_count" ]; then
    echo "check-kimi-skill-embed-budget.sh: embed incomplete" >&2
    echo "  $label file count mismatch: expected $expected_count, found $file_count" >&2
    echo "  a $label source file went missing from $dir. This is the deleted-" >&2
    echo "  file case the pinned $constant_name constant exists to catch - restore" >&2
    echo "  the missing file. Do NOT lower the expected count to make this pass" >&2
    echo "  unless the removal was deliberate." >&2
    exit 1
  fi
  while IFS= read -r f; do
    heading="$(grep -m1 '^## ' "$f" || true)"
    if [ -z "$heading" ]; then
      echo "check-kimi-skill-embed-budget.sh: embed incomplete" >&2
      echo "  $f has no top-level '## ' heading to check against" >&2
      echo "  every embedded $label source file needs its own distinct" >&2
      echo "  top-level '## Heading' line for this check to verify its" >&2
      echo "  presence in the built SKILL.md - add one." >&2
      exit 1
    fi
    if ! grep -qxF "$heading" "$SKILL_FILE"; then
      echo "check-kimi-skill-embed-budget.sh: embed incomplete" >&2
      echo "  missing $label heading from $(basename "$f"): $heading" >&2
      echo "  this file is not present in the built SKILL.md - assembly" >&2
      echo "  silently dropped a whole embedded file, which the FLOOR/CEILING" >&2
      echo "  byte band alone cannot detect." >&2
      exit 1
    fi
    ALL_HEADINGS="$ALL_HEADINGS$heading
"
  done <<< "$files"
}

ALL_HEADINGS=""
_check_embedded_set "$REPO_DIR/content/sections" '[0-9][0-9]-*.md' '' "$EXPECTED_SECTION_COUNT" 'section' 'EXPECTED_SECTION_COUNT'
_check_embedded_set "$REPO_DIR/content/rules" '*.md' 'module-manifest.md' "$EXPECTED_RULES_COUNT" 'rules' 'EXPECTED_RULES_COUNT'

# Duplicate-heading guard: see check-skill-embed-budget.sh's identical
# comment - a presence check alone cannot tell which file it matched if
# two source files share the same first top-level heading.
duplicate_headings="$(printf '%s' "$ALL_HEADINGS" | LC_ALL=C sort | LC_ALL=C uniq -d)"
if [ -n "$duplicate_headings" ]; then
  echo "check-kimi-skill-embed-budget.sh: embed incomplete" >&2
  echo "  duplicate top-level heading(s) shared across source files:" >&2
  printf '%s\n' "$duplicate_headings" | while IFS= read -r dup; do
    [ -n "$dup" ] && echo "    $dup" >&2
  done
  echo "  give the affected file(s) a distinct top-level heading." >&2
  exit 1
fi

skill_bytes="$(budget_file_bytes "$SKILL_FILE")"
agents_bytes="$(budget_file_bytes "$AGENTS_FILE")"

# SKILL.md's base-at-origin/main representation changes TYPE across DS-185
# (a 25 B symlink before, a real ~139,000 B generated file after) - a
# budget_delta between those two is a symlink-target-string-vs-real-content
# comparison, not a meaningful burn rate, and would render as an alarming
# "0 d to limit" on the very first CI run after merge (m5, DS-185 round 2).
# Detect that transition via the base ref's own git object mode (120000 =
# symlink) and render a distinct SKIPPED line instead of a misleading
# burn rate; once history moves past the transition commit, later runs use
# the normal budget_burn_line path with no special-casing needed.
_kimi_skill_base_was_symlink() {
  local repo_dir="$1" target_path="$2"
  local rel_path="$target_path"
  case "$target_path" in
    "$repo_dir"/*) rel_path="${target_path#"$repo_dir"/}" ;;
  esac
  local base_ref
  base_ref="$(budget_base_resolve "$repo_dir" 2>/dev/null)" || return 1
  local mode
  mode="$(git -C "$repo_dir" ls-tree "$base_ref" -- "$rel_path" 2>/dev/null | awk '{print $1}')"
  [ "$mode" = "120000" ]
}

if _kimi_skill_base_was_symlink "$REPO_DIR" "$SKILL_FILE"; then
  skill_burn_line="burn: SKIPPED (base was a symlink, not a comparable generated body)"
else
  skill_burn_line="$(budget_burn_line "$REPO_DIR" "$SKILL_FILE" "$SKILL_CEILING" "$skill_bytes")"
fi
agents_burn_line="$(budget_burn_line "$REPO_DIR" "$AGENTS_FILE" "$AGENTS_CEILING" "$agents_bytes")"

if [ "$skill_bytes" -lt "$SKILL_FLOOR" ]; then
  echo "check-kimi-skill-embed-budget.sh: SKILL.md BELOW FLOOR - embed regression," >&2
  echo "  not a healthy shrink." >&2
  echo "  $SKILL_FILE measured only $skill_bytes B," >&2
  echo "  below the $SKILL_FLOOR B floor." >&2
  echo "  This almost certainly means the embed step in .kimi/build.sh broke and" >&2
  echo "  SKILL.md regressed to a pointer-only body that no longer inlines the" >&2
  echo "  methodology content. Investigate the build step directly; do not lower" >&2
  echo "  SKILL_FLOOR to make this pass." >&2
  echo "  $skill_burn_line" >&2
  exit 1
fi

if [ "$skill_bytes" -gt "$SKILL_CEILING" ]; then
  overage=$(( skill_bytes - SKILL_CEILING ))
  echo "check-kimi-skill-embed-budget.sh: SKILL.md ABOVE CEILING." >&2
  echo "  $SKILL_FILE measured $skill_bytes B," >&2
  echo "  above the $SKILL_CEILING B ceiling ($overage B over)." >&2
  echo "" >&2
  echo "  SKILL_CEILING is informational, not a verified-safe injection size -" >&2
  echo "  no swept injection measurement has been run against the Kimi harness." >&2
  echo "  Do not raise it as routine housekeeping; if raising it, say so" >&2
  echo "  explicitly in the PR that raises it. Otherwise, trim content." >&2
  echo "  $skill_burn_line" >&2
  exit 1
fi

if [ "$agents_bytes" -gt "$AGENTS_CEILING" ]; then
  overage=$(( agents_bytes - AGENTS_CEILING ))
  echo "check-kimi-skill-embed-budget.sh: AGENTS.md ABOVE STUB CEILING." >&2
  echo "  $AGENTS_FILE measured $agents_bytes B," >&2
  echo "  above the $AGENTS_CEILING B stub ceiling ($overage B over)." >&2
  echo "" >&2
  echo "  This is the regression DS-185 exists to prevent: .kimi/AGENTS.md is" >&2
  echo "  loaded unconditionally on every Kimi session and must stay a lean" >&2
  echo "  activation stub - the methodology body belongs in the trigger-loaded" >&2
  echo "  .kimi/skills/dinostack/SKILL.md instead. Investigate .kimi/build.sh's" >&2
  echo "  AGENTS.md generation step, or .kimi/install.sh's link-health fallback" >&2
  echo "  (which deliberately appends the full body here ONLY when the skill" >&2
  echo "  body fails to build - if that fallback fired unexpectedly, resolve" >&2
  echo "  the underlying build failure it reported)." >&2
  echo "  $agents_burn_line" >&2
  exit 1
fi

echo "kimi skill embed budget check: OK"
echo "  SKILL.md:  $skill_bytes B"
echo "  floor:     $SKILL_FLOOR B"
echo "  ceiling:   $SKILL_CEILING B"
echo "  $skill_burn_line"
echo "  headroom to ceiling: $(( SKILL_CEILING - skill_bytes )) B"
echo "  AGENTS.md: $agents_bytes B"
echo "  stub ceiling: $AGENTS_CEILING B"
echo "  $agents_burn_line"
echo "  headroom to stub ceiling: $(( AGENTS_CEILING - agents_bytes )) B"
exit 0
