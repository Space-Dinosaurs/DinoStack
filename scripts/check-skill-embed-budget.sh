#!/usr/bin/env bash
# Purpose: Two-sided guard on the generated .claude/skills/dinostack/
#          SKILL.md - the artifact Claude Code injects verbatim into context
#          when the /dinostack skill is invoked, post-DS-143
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
#            - CEILING: intended as a safety boundary, not a tidiness
#              budget, but its own arithmetic does not currently anchor it
#              to the one injection-verified data point it claims to
#              protect (DS-45 finding - see the CEILING constant's own
#              comment below for the full provenance and the gap it
#              documents). Do not treat a future CEILING bump as routine
#              housekeeping regardless: raising it without a new swept
#              injection measurement re-opens the exact risk this gate
#              exists to close.
#
# Public API: bash scripts/check-skill-embed-budget.sh
#             Exits 0 when the embed-completeness check passes AND
#             FLOOR <= size <= CEILING. Exits 1 otherwise, or when a
#             required input is missing.
#
# Upstream deps: .claude/skills/dinostack/SKILL.md (built by
#                .claude/build.sh; this script does not rebuild it - it
#                measures whatever is currently on disk, matching how
#                check-adapter-sync and the runtime skill loader both treat
#                the file as the artifact of record); content/sections/
#                [0-9][0-9]-*.md and content/rules/*.md (excluding
#                module-manifest.md) for the embed-completeness check;
#                scripts/lib/budget-gate.sh (shared repo-dir resolution and
#                byte measurement - the two-sided floor/ceiling report
#                below stays here, since it does not fit the OK/OVER-BUDGET
#                shape budget_report shares with the other two gates).
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

# BASH_SOURCE is unset under zsh - fall back to $0 so SCRIPT_DIR resolves
# correctly under both interpreters instead of collapsing to "//".
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib/budget-gate.sh
source "$SCRIPT_DIR/lib/budget-gate.sh"
REPO_DIR="$(budget_repo_dir "$SCRIPT_DIR")"

SKILL_FILE="$REPO_DIR/.claude/skills/dinostack/SKILL.md"

# Floor: catches a regression to a pointer-only skill (the embed step
# silently breaking and SKILL.md no longer inlining the methodology body).
# 100,000 B is far below any realistic embedded size and far above what a
# pointer-only skill would ever measure.
FLOOR=100000

# Ceiling: 139,160 B (DS-45 correction to this comment - the value itself
# is unchanged). What this constant actually is: 126,509 B, a local build
# measurement of .claude/skills/dinostack/SKILL.md taken on the DS-143
# branch on 2026-08-07 (commit baf0b011bd61f055e6ec685663a1f6e24b8834ce),
# times 1.1 for headroom. 126,509 x 1.1 = 139,159.9, which was written up
# as "rounded down" to 139,160 in the original comment - that description
# was itself wrong; 139,160 is the nearest-integer rounding, not a
# round-down, and the true round-down would be 139,159. Immaterial by one
# byte, but stated accurately here since the previous text asserted the
# wrong operation.
#
# What this constant is NOT: it is not derived from, or swept relative to,
# the separate 127,107-byte figure this file's own header and failure
# messages cite as the harness's empirically-confirmed verbatim-injection
# point. That figure's provenance is not traceable through git history -
# `git log --all -S "127107"` and `-S "127,107"` return only the commits
# that introduced the prose asserting it (baf0b011, part of DS-143/PR
# #599), never a measurement commit naming which build, which session, or
# which harness version produced it; this is a statement about what git
# history contains, not a claim that no record exists anywhere (a
# gitignored planning doc is, by construction, outside what any git-log
# search could ever find either way). The two figures were plainly
# related in the authoring commit's own framing - c1d7c90c's message
# states CEILING as "~1.1x the measured build at authoring time" in one
# paragraph, and separately, in the next paragraph, that "the harness was
# empirically verified to inject the full SKILL.md body verbatim at
# ~127 KB" - but the arithmetic that actually produced 139,160 traces
# only to the 126,509 B build-size snapshot, never to 127,107. So CEILING
# is 1.1x that build-size snapshot (126,509 B, itself only 598 B below
# the injection-confirmed figure) - not 1.1x, or any swept multiple of,
# the injection-verified figure itself. CEILING (139,160 B) ends up
# roughly 12,053 B above the injection-confirmed point (127,107 B).
#
# What is actually on record, checked 2026-08-18: the largest recorded
# intact injection is 130,015 B (DS-146: canaries present at head and
# tail, no truncation, no performance warning - see
# .agentic/learnings.md KNW-20260811-004 and
# docs/skill-embed-injection-sweep.md). The live payload on main now
# measures 138,990 B. The region above 130,015 B - including the gap
# up to CEILING - is unmeasured. CEILING currently functions as a size
# ratchet with slack, not as evidence the current payload has been
# confirmed safe to inject.
#
# This does not weaken the existing guidance - it strengthens the case for
# it. Do not raise CEILING as routine housekeeping when content grows: only
# raise it alongside a new swept confirmation that a larger body still
# loads untruncated in the live harness, and say so explicitly in the PR
# that raises it. A reusable procedure for producing that swept
# confirmation is documented at
# docs/skill-embed-injection-sweep.md (DS-45) - use it rather
# than reconstructing an ad hoc measurement.
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
  local dir="$1" pattern="$2" exclude="$3" expected_count="$4" label="$5" constant_name="$6"
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
    echo "  If so, bump $constant_name above in the same commit that adds the" >&2
    echo "  file. If not, an extra file landed under $dir unexpectedly -" >&2
    echo "  investigate before bumping the count." >&2
    exit 1
  fi
  if [ "$file_count" -lt "$expected_count" ]; then
    echo "check-skill-embed-budget.sh: embed incomplete" >&2
    echo "  $label file count mismatch: expected $expected_count, found $file_count" >&2
    echo "  a $label source file went missing from $dir. This is the deleted-" >&2
    echo "  file case the pinned $constant_name constant exists to catch (see" >&2
    echo "  its comment above) - restore the missing file. Do NOT lower the" >&2
    echo "  expected count to make this pass unless the removal was" >&2
    echo "  deliberate." >&2
    exit 1
  fi
  while IFS= read -r f; do
    heading="$(grep -m1 '^## ' "$f" || true)"
    if [ -z "$heading" ]; then
      echo "check-skill-embed-budget.sh: embed incomplete" >&2
      echo "  $f has no top-level '## ' heading to check against" >&2
      echo "  every embedded $label source file needs its own distinct" >&2
      echo "  top-level '## Heading' line for this check to verify its" >&2
      echo "  presence in the built SKILL.md - add one (e.g. a '# ' opener" >&2
      echo "  demoted to '## ', or a missing heading added outright)." >&2
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
_check_embedded_set "$REPO_DIR/content/sections" '[0-9][0-9]-*.md' '' "$EXPECTED_SECTION_COUNT" 'section' 'EXPECTED_SECTION_COUNT'
_check_embedded_set "$REPO_DIR/content/rules" '*.md' 'module-manifest.md' "$EXPECTED_RULES_COUNT" 'rules' 'EXPECTED_RULES_COUNT'

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

skill_bytes="$(budget_file_bytes "$SKILL_FILE")"

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
  echo "  CEILING is intended as a safety boundary, not a tidiness budget," >&2
  echo "  but it is NOT derived from the one injection-verified figure this" >&2
  echo "  file cites (127,107 B) - see the CEILING constant's own comment" >&2
  echo "  above for the full DS-45 provenance correction. Do not raise" >&2
  echo "  CEILING as routine housekeeping - only raise it alongside a new" >&2
  echo "  swept confirmation that the larger body still loads untruncated" >&2
  echo "  in the live harness (procedure:" >&2
  echo "  docs/skill-embed-injection-sweep.md), and say so" >&2
  echo "  explicitly in the PR that raises it. Otherwise, trim content." >&2
  exit 1
fi

echo "skill embed budget check: OK"
echo "  SKILL.md: $skill_bytes B"
echo "  floor:    $FLOOR B"
echo "  ceiling:  $CEILING B"
echo "  headroom to ceiling: $(( CEILING - skill_bytes )) B"
exit 0
