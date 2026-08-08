#!/usr/bin/env bash
# Purpose: Two-sided guard on the generated .claude/skills/agentic-engineering/
#          SKILL.md - the artifact Claude Code injects verbatim into context
#          when the /agentic-engineering skill is invoked, post-DS-143
#          (trigger-loaded methodology). Three failure classes:
#            - EMBED INCOMPLETE: a whole content/sections/*.md or
#              content/rules/*.md source file silently dropped from
#              assembly (a bad exclusion pattern, a broken loop, etc.). This
#              can land well inside the FLOOR..CEILING byte band undetected
#              by size alone - verified live: excluding
#              content/rules/code-standards.md from the embed loop rebuilds
#              a SKILL.md that still measures inside the band and exits 0
#              without this check. Also covers an outright add/remove of a
#              source file via pinned EXPECTED_SECTION_COUNT/
#              EXPECTED_RULES_COUNT constants (see their own comment below
#              for why a pinned count, not a re-derived one, is required).
#            - FLOOR: catches a regression to a pointer-only skill body (the
#              embed step in .claude/build.sh silently breaking and no
#              longer inlining METHODOLOGY.md/conventions.md/code-standards.md
#              into SKILL.md). Would otherwise be invisible - a pointer-only
#              skill still builds, still passes adapter-sync, and only fails
#              at runtime when an agent needs content that never loaded.
#            - CEILING: a safety boundary, not tidiness. Claude Code was
#              empirically confirmed to inject a 127,107-byte SKILL.md body
#              verbatim with no truncation, but that is ONE size point, not
#              a swept boundary - nobody has confirmed where truncation
#              starts. CEILING keeps the payload inside the verified-safe
#              range. Do not treat a future CEILING bump as routine
#              housekeeping: raising it without a new swept data point
#              re-opens the exact risk this gate exists to close.
#
# Public API: bash scripts/check-skill-embed-budget.sh
#             Exits 0 when the embed-completeness check passes AND
#             FLOOR <= size <= CEILING. Exits 1 otherwise, or when a
#             required input is missing.
#
# Upstream deps: .claude/skills/agentic-engineering/SKILL.md (built by
#                .claude/build.sh; this script does not rebuild it - it
#                measures whatever is currently on disk, matching how
#                check-adapter-sync and the runtime skill loader both treat
#                the file as the artifact of record); content/sections/
#                [0-9][0-9]-*.md and content/rules/*.md (excluding
#                module-manifest.md) for the embed-completeness check.
#
# Downstream consumers: .github/workflows/resident-budget.yml.
#
# Failure modes: embed incomplete (a source file dropped from assembly, or
#                a file count mismatch against EXPECTED_SECTION_COUNT/
#                EXPECTED_RULES_COUNT) -> exit 1 with a distinct "embed
#                incomplete" message, checked before the FLOOR/CEILING bound
#                check below. Below FLOOR -> exit 1, message explicitly
#                frames this as an embed regression, not a healthy shrink -
#                a passing skill body should never get anywhere near
#                100,000 B smaller by accident. Above CEILING -> exit 1,
#                message reiterates the single-data-point caveat and warns
#                against a routine bump. Missing input file -> exit 1.
#                Read-only; no side effects on the repo.
#
# Detection boundary: the heading-completeness check below proves each
# source file's own top-level heading is PRESENT somewhere in the built
# output - it is a presence check, not a completeness digest, so partial
# corruption or truncation of a section's BODY (heading intact, content
# gutted or duplicated) is only caught if it pushes total bytes outside
# FLOOR..CEILING.
#
# Compatible with both bash and zsh invocation of the containing shell; CI
# always invokes it as `bash scripts/check-skill-embed-budget.sh`, but a
# contributor, reviewer, or this file's own regression test may invoke it
# as `zsh scripts/check-skill-embed-budget.sh` and it must behave
# identically. Avoid the variable names `status` and `path` anywhere in
# this file - both are special/read-only in zsh.

set -euo pipefail

# BASH_SOURCE is unset under zsh - fall back to $0 so REPO_DIR resolves
# correctly under both interpreters instead of collapsing to "//".
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

SKILL_FILE="$REPO_DIR/.claude/skills/agentic-engineering/SKILL.md"

# Floor: catches a regression to a pointer-only skill (the embed step
# silently breaking and SKILL.md no longer inlining the methodology body).
# 100,000 B is far below any realistic embedded size and far above what a
# pointer-only skill would ever measure.
FLOOR=100000

# Ceiling: 126,509 B measured for .claude/skills/agentic-engineering/SKILL.md
# on this branch 2026-08-07 (DS-143), + roughly 10% headroom, rounded down.
# This is a SAFETY BOUNDARY, not a tidiness budget: Claude Code was
# empirically confirmed to inject a 127,107-byte SKILL.md body verbatim with
# no truncation, but that is ONE data point, not a swept boundary - nobody
# has confirmed where truncation actually begins. CEILING keeps the payload
# inside the verified-safe range around that single confirmed point. Do not
# raise this value as routine housekeeping when content grows - only raise
# it alongside a new swept confirmation that a larger body still loads
# untruncated, and say so explicitly in the PR that raises it.
CEILING=139160

# EXPECTED_SECTION_COUNT / EXPECTED_RULES_COUNT: pinned counts, ratcheted the
# same way FLOOR/CEILING/THRESHOLD are elsewhere in this repo (see
# scripts/check-resident-budget.sh). Update the same commit that adds,
# removes, or renumbers a content/sections/[0-9][0-9]-*.md file, or
# adds/removes a content/rules/*.md file other than module-manifest.md
# (excluded from the embed by .claude/build.sh, and from this count).
#
# Deliberately a fixed constant, NOT derived from the working tree at check
# time (e.g. re-running the same find/glob build-methodology.sh or
# .claude/build.sh themselves use): deriving the expected count from the
# working tree makes the expected side and the actual side move together,
# so an outright file deletion removes it from both what is expected AND
# what is checked - the loss becomes invisible. A pinned constant closes
# that tautology.
EXPECTED_SECTION_COUNT=12
EXPECTED_RULES_COUNT=2

if [ ! -f "$SKILL_FILE" ]; then
  echo "check-skill-embed-budget.sh: missing file: $SKILL_FILE" >&2
  echo "  Run .claude/build.sh to regenerate it, then re-run this check." >&2
  exit 1
fi

# Embed-completeness check (distinct from the FLOOR/CEILING bound check
# below): a whole embedded source file can go missing from assembly and
# still land inside the FLOOR..CEILING byte band, where the two-sided bound
# check alone cannot see it. A single arbitrary head/tail phrase pair cannot
# detect a dropped file in the middle of either set, so this checks a
# phrase from EVERY file in both sets - each file's own first top-level
# heading, derived dynamically so a renamed file is covered automatically
# without maintaining a hardcoded phrase list here. Shared between the two
# sets (content/sections/[0-9][0-9]-*.md and content/rules/*.md, excluding
# module-manifest.md) via one function to avoid duplicating this logic
# twice.
_check_embedded_set() {
  local dir="$1" pattern="$2" exclude="$3" expected_count="$4" label="$5"
  local files file_count f heading
  if [ -n "$exclude" ]; then
    files="$(LC_ALL=C find "$dir" -maxdepth 1 -type f -name "$pattern" ! -name "$exclude" | LC_ALL=C sort)"
  else
    files="$(LC_ALL=C find "$dir" -maxdepth 1 -type f -name "$pattern" | LC_ALL=C sort)"
  fi
  if [ -z "$files" ]; then
    echo "check-skill-embed-budget.sh: no $label files found in $dir" >&2
    exit 1
  fi
  file_count="$(wc -l <<< "$files" | tr -d '[:space:]')"
  if [ "$file_count" -gt "$expected_count" ]; then
    echo "check-skill-embed-budget.sh: embed incomplete" >&2
    echo "  $label file count mismatch: expected $expected_count, found $file_count" >&2
    echo "  a new $label source file was added - this is likely intentional." >&2
    echo "  If so, bump EXPECTED_SECTION_COUNT or EXPECTED_RULES_COUNT above" >&2
    echo "  in the same commit that adds the file. If not, an extra file" >&2
    echo "  landed under $dir unexpectedly - investigate before bumping the" >&2
    echo "  count." >&2
    exit 1
  fi
  if [ "$file_count" -lt "$expected_count" ]; then
    echo "check-skill-embed-budget.sh: embed incomplete" >&2
    echo "  $label file count mismatch: expected $expected_count, found $file_count" >&2
    echo "  a $label source file went missing from $dir. This is the deleted-" >&2
    echo "  file case the pinned EXPECTED_SECTION_COUNT/EXPECTED_RULES_COUNT" >&2
    echo "  constants exist to catch (see their comment above) - restore the" >&2
    echo "  missing file. Do NOT lower the expected count to make this pass" >&2
    echo "  unless the removal was deliberate." >&2
    exit 1
  fi
  while IFS= read -r f; do
    heading="$(grep -m1 '^## ' "$f" || true)"
    if [ -z "$heading" ]; then
      echo "check-skill-embed-budget.sh: embed incomplete" >&2
      echo "  $f has no top-level '## ' heading to check against" >&2
      exit 1
    fi
    if ! grep -qxF "$heading" "$SKILL_FILE"; then
      echo "check-skill-embed-budget.sh: embed incomplete" >&2
      echo "  missing $label heading from $(basename "$f"): $heading" >&2
      echo "  this file is not present in the built SKILL.md - assembly" >&2
      echo "  silently dropped a whole embedded file, which the FLOOR/CEILING" >&2
      echo "  byte band alone cannot detect." >&2
      exit 1
    fi
    # Accumulate into the global ALL_HEADINGS list (deliberately not `local`
    # here) so the caller can assert every checked heading is unique across
    # BOTH sets after both invocations return - see that check below.
    ALL_HEADINGS="$ALL_HEADINGS$heading
"
  done <<< "$files"
}

ALL_HEADINGS=""
_check_embedded_set "$REPO_DIR/content/sections" '[0-9][0-9]-*.md' '' "$EXPECTED_SECTION_COUNT" 'section'
_check_embedded_set "$REPO_DIR/content/rules" '*.md' 'module-manifest.md' "$EXPECTED_RULES_COUNT" 'rules'

# Duplicate-heading guard: `grep -qxF "$heading" "$SKILL_FILE"` above matches
# presence ANYWHERE in the built output, not per-file. If two source files
# happened to share the same first top-level heading, dropping ONE of them
# would still find the OTHER's copy of that heading in the output and pass
# - the presence check alone cannot tell which file it matched. Asserting
# uniqueness up front closes this cheaply instead of relying on it staying
# true by chance.
duplicate_headings="$(printf '%s' "$ALL_HEADINGS" | LC_ALL=C sort | LC_ALL=C uniq -d)"
if [ -n "$duplicate_headings" ]; then
  echo "check-skill-embed-budget.sh: embed incomplete" >&2
  echo "  duplicate top-level heading(s) shared across source files - the" >&2
  echo "  presence check above cannot distinguish per-file completeness when" >&2
  echo "  a heading repeats, so it can silently pass with one copy dropped:" >&2
  printf '%s\n' "$duplicate_headings" | while IFS= read -r dup; do
    [ -n "$dup" ] && echo "    $dup" >&2
  done
  echo "  give the affected file(s) a distinct top-level heading." >&2
  exit 1
fi

skill_bytes="$(wc -c < "$SKILL_FILE" | tr -d '[:space:]')"

if [ "$skill_bytes" -lt "$FLOOR" ]; then
  echo "check-skill-embed-budget.sh: BELOW FLOOR - embed regression, not a" >&2
  echo "  healthy shrink." >&2
  echo "  $SKILL_FILE measured only $skill_bytes B," >&2
  echo "  below the $FLOOR B floor." >&2
  echo "  This almost certainly means the embed step in .claude/build.sh" >&2
  echo "  broke and SKILL.md regressed to a pointer-only body that no" >&2
  echo "  longer inlines the methodology content. Investigate the build" >&2
  echo "  step directly; do not lower FLOOR to make this pass." >&2
  exit 1
fi

if [ "$skill_bytes" -gt "$CEILING" ]; then
  overage=$(( skill_bytes - CEILING ))
  echo "check-skill-embed-budget.sh: ABOVE CEILING." >&2
  echo "  $SKILL_FILE measured $skill_bytes B," >&2
  echo "  above the $CEILING B ceiling ($overage B over)." >&2
  echo "" >&2
  echo "  CEILING is a safety boundary, not a tidiness budget: Claude Code" >&2
  echo "  was empirically confirmed to inject a 127,107-byte SKILL.md body" >&2
  echo "  verbatim with no truncation, but that is ONE data point, not a" >&2
  echo "  swept boundary. Do not raise CEILING as routine housekeeping -" >&2
  echo "  only raise it alongside a new swept confirmation that the larger" >&2
  echo "  body still loads untruncated in the live harness, and say so" >&2
  echo "  explicitly in the PR that raises it. Otherwise, trim content." >&2
  exit 1
fi

echo "skill embed budget check: OK"
echo "  SKILL.md: $skill_bytes B"
echo "  floor:    $FLOOR B"
echo "  ceiling:  $CEILING B"
echo "  headroom to ceiling: $(( CEILING - skill_bytes )) B"
exit 0
