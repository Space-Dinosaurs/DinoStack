#!/usr/bin/env bash
# Purpose: Three-axis guard on the generated Gemini adapter's DS-184
#          trigger-loaded skill, modeled on scripts/check-skill-embed-
#          budget.sh (the equivalent gate for .claude/skills/dinostack/
#          SKILL.md) with one addition specific to this adapter's shape:
#          a stub-ceiling check on .gemini/GEMINI.md, since DS-184's whole
#          point is that GEMINI.md stops carrying the methodology body -
#          nothing else here would catch a silent re-embed of the full
#          body back into GEMINI.md.
#            - SKILL FLOOR: catches a regression to a pointer-only skill
#              body (the write step in .gemini/build.sh silently breaking
#              and .gemini/skills/dinostack/SKILL.md no longer inlining
#              the methodology content).
#            - SKILL EMBED INCOMPLETE: a whole content/sections/*.md or
#              content/rules/*.md source file silently dropped from
#              assembly. Can land inside the floor..ceiling byte band
#              undetected by size alone - checked via each source file's
#              own top-level heading, plus pinned
#              EXPECTED_SECTION_COUNT/EXPECTED_RULES_COUNT constants (see
#              their own comment below for why a pinned count, not a
#              re-derived one, is required).
#            - SKILL CEILING: an upper bound on the skill body - a
#              headroom boundary against known-good measurements, not a
#              swept safety guarantee, since no swept injection sweep has
#              been run for the Gemini adapter specifically (the DS-45
#              procedure at docs/skill-embed-injection-sweep.md, and its
#              2026-09-03 result, target the Claude harness only).
#            - STUB CEILING: .gemini/GEMINI.md must stay a small stub. A
#              re-embed of the full body back into GEMINI.md (accidental
#              revert of the DS-184 split) would otherwise pass every
#              other check here silently, since nothing else on this repo
#              measures GEMINI.md at all.
#
# Public API: bash scripts/check-gemini-skill-budget.sh
#             Exits 0 when the skill embed-completeness check passes,
#             SKILL_FLOOR <= skill size <= SKILL_CEILING, AND
#             stub size <= STUB_CEILING. Exits 1 otherwise, or when a
#             required input is missing. Per DS-182's provenance rule
#             (scripts/gate-provenance.sh classifies both target files
#             DERIVED - the write is manifest-declared in .gemini/
#             build.sh's own header), this gate carries only an
#             informational budget_burn_line on the skill axis, no hard
#             per-PR DELTA_LIMIT_BYTES.
#
# Upstream deps: .gemini/skills/dinostack/SKILL.md and .gemini/GEMINI.md
#                (both built by .gemini/build.sh; this script does not
#                rebuild them - it measures whatever is currently on disk,
#                matching how check-adapter-sync and the runtime skill
#                loader both treat the files as the artifacts of record);
#                content/sections/[0-9][0-9]-*.md and content/rules/*.md
#                (excluding module-manifest.md) for the skill embed-
#                completeness check; scripts/lib/budget-gate.sh (shared
#                repo-dir resolution, byte measurement, and
#                budget_burn_line for the informational line on the skill
#                axis).
#
# Downstream consumers: .github/workflows/gemini-skill-budget.yml (its own
#                        workflow file, per DS-184's instruction not to add
#                        a job to resident-budget.yml - a sibling unit is
#                        adding its own gate to a shared workflow file in
#                        the same round; needs fetch-depth: 0 so the burn
#                        line can resolve origin/main, matching the
#                        precedent in check-skill-embed-budget.sh's own
#                        Downstream consumers note).
#
# Failure modes: embed incomplete (a source file dropped from assembly, or
#                a file count mismatch against EXPECTED_SECTION_COUNT/
#                EXPECTED_RULES_COUNT) -> exit 1 with a distinct message,
#                checked before the floor/ceiling bound checks below.
#                Below SKILL_FLOOR -> exit 1, framed as an embed
#                regression, not a healthy shrink. Above SKILL_CEILING ->
#                exit 1. Above STUB_CEILING -> exit 1, framed as a
#                DS-184 regression (the split re-collapsing). Missing
#                input file -> exit 1. The burn line is computed once,
#                after the embed-completeness check, and printed on the
#                three skill-axis exit paths (OK, below floor, above
#                ceiling) - unresolvable git/base renders a "burn: SKIPPED
#                (...)" line rather than omitting it; never a failure,
#                never blocks the floor/ceiling result. Read-only; no side
#                effects on the repo.
#
# Detection boundary: the heading-completeness check proves each source
# file's own top-level heading is PRESENT somewhere in the built skill
# output - a presence check, not a completeness digest, so partial
# corruption or truncation of a section's BODY (heading intact, content
# gutted or duplicated) is only caught if it pushes total bytes outside
# SKILL_FLOOR..SKILL_CEILING.
#
# Compatible with both bash and zsh invocation of the containing shell; CI
# always invokes it as `bash scripts/check-gemini-skill-budget.sh`, but a
# contributor, reviewer, or this file's own regression test may invoke it
# as `zsh scripts/check-gemini-skill-budget.sh` and it must behave
# identically. Avoid the variable names `status` and `path` anywhere in
# this file - both are special/read-only in zsh.

set -euo pipefail

# BASH_SOURCE is unset under zsh - fall back to $0 so SCRIPT_DIR resolves
# correctly under both interpreters instead of collapsing to "//".
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib/budget-gate.sh
source "$SCRIPT_DIR/lib/budget-gate.sh"
REPO_DIR="$(budget_repo_dir "$SCRIPT_DIR")"

SKILL_FILE="$REPO_DIR/.gemini/skills/dinostack/SKILL.md"
STUB_FILE="$REPO_DIR/.gemini/GEMINI.md"

# Floor: catches a regression to a pointer-only skill (the write step in
# .gemini/build.sh silently breaking and SKILL.md no longer inlining the
# methodology body). 100,000 B is far below any realistic embedded size
# and far above what a pointer-only skill would ever measure - same
# rationale and same value as scripts/check-skill-embed-budget.sh's FLOOR.
SKILL_FLOOR=100000

# Ceiling: 145,000 B, matching scripts/check-skill-embed-budget.sh's
# CEILING for the Claude adapter's equivalent embed. The Gemini skill body
# assembles the identical content/sections/*.md + content/rules/{code-
# standards,conventions}.md set (see .gemini/build.sh Step 1) through a
# different header/footer wrapper, so the two artifacts' sizes track each
# other closely but are not byte-identical. No swept injection-safety
# measurement has been run for the Gemini adapter specifically (the
# procedure at docs/skill-embed-injection-sweep.md targets the Claude
# harness, and the 2026-09-03 sweep result documented in Claude's
# check-skill-embed-budget.sh CEILING comment applies only to that
# harness) - treat this CEILING as a headroom boundary against known-good
# measurements at authoring time, not a verified-safe injection size.
#
# DS-204 (unit B): SKILL.md's embed flipped from the full corpus to the
# minimal corpus (a generated "Deferred at this corpus" pointer block
# replaces deferred content; the full text is still reachable at the
# unfiltered SKILL.full.md sibling). Measured default size moved from
# 135,787 B (full corpus) to 121,600 B (minimal corpus, current default);
# neither figure is a swept injection-safety measurement - both are
# authoring-time headroom checks against the same unswept CEILING above.
SKILL_CEILING=145000

# Stub ceiling: .gemini/GEMINI.md must stay a small pointer. 10,000 B is
# generously above the ~2,100 B stub .gemini/build.sh currently produces,
# while far below any plausible size if the full methodology body were
# accidentally re-embedded into GEMINI.md (that body alone measures over
# 130,000 B) - the DS-184 regression this axis exists to catch.
STUB_CEILING=10000

# EXPECTED_SECTION_COUNT / EXPECTED_RULES_COUNT: pinned counts, ratcheted
# the same way scripts/check-skill-embed-budget.sh's own identically-named
# constants are (see that file's comment for the full rationale on why a
# pinned constant, not one re-derived from the working tree, is required
# to catch an outright file deletion). Update the same commit that adds,
# removes, or renumbers a content/sections/[0-9][0-9]-*.md file, or
# adds/removes a content/rules/*.md file other than module-manifest.md.
EXPECTED_SECTION_COUNT=12
EXPECTED_RULES_COUNT=2

if [ ! -f "$SKILL_FILE" ]; then
  echo "check-gemini-skill-budget.sh: missing file: $SKILL_FILE" >&2
  echo "  Run .gemini/build.sh to regenerate it, then re-run this check." >&2
  exit 1
fi

if [ ! -f "$STUB_FILE" ]; then
  echo "check-gemini-skill-budget.sh: missing file: $STUB_FILE" >&2
  echo "  Run .gemini/build.sh to regenerate it, then re-run this check." >&2
  exit 1
fi

# Embed-completeness check (distinct from the SKILL_FLOOR/SKILL_CEILING
# bound check below): a whole embedded source file can go missing from
# assembly and still land inside the floor..ceiling byte band, where the
# two-sided bound check alone cannot see it. Checks a phrase from EVERY
# file in both sets - each file's own first top-level heading, derived
# dynamically so a renamed file is covered automatically without
# maintaining a hardcoded phrase list here. Shared between the two sets
# (content/sections/[0-9][0-9]-*.md and content/rules/*.md, excluding
# module-manifest.md) via one function to avoid duplicating this logic
# twice - same shape as scripts/check-skill-embed-budget.sh's
# _check_embedded_set.
_check_embedded_set() {
  local dir="$1" pattern="$2" exclude="$3" expected_count="$4" label="$5" constant_name="$6"
  local files file_count f heading
  if [ -n "$exclude" ]; then
    files="$(LC_ALL=C find "$dir" -maxdepth 1 -type f -name "$pattern" ! -name "$exclude" | LC_ALL=C sort)"
  else
    files="$(LC_ALL=C find "$dir" -maxdepth 1 -type f -name "$pattern" | LC_ALL=C sort)"
  fi
  if [ -z "$files" ]; then
    echo "check-gemini-skill-budget.sh: no $label files found in $dir" >&2
    exit 1
  fi
  file_count="$(wc -l <<< "$files" | tr -d '[:space:]')"
  if [ "$file_count" -gt "$expected_count" ]; then
    echo "check-gemini-skill-budget.sh: embed incomplete" >&2
    echo "  $label file count mismatch: expected $expected_count, found $file_count" >&2
    echo "  a new $label source file was added - this is likely intentional." >&2
    echo "  If so, bump $constant_name above in the same commit that adds the" >&2
    echo "  file. If not, an extra file landed under $dir unexpectedly -" >&2
    echo "  investigate before bumping the count." >&2
    exit 1
  fi
  if [ "$file_count" -lt "$expected_count" ]; then
    echo "check-gemini-skill-budget.sh: embed incomplete" >&2
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
      echo "check-gemini-skill-budget.sh: embed incomplete" >&2
      echo "  $f has no top-level '## ' heading to check against" >&2
      echo "  every embedded $label source file needs its own distinct" >&2
      echo "  top-level '## Heading' line for this check to verify its" >&2
      echo "  presence in the built SKILL.md - add one (e.g. a '# ' opener" >&2
      echo "  demoted to '## ', or a missing heading added outright)." >&2
      exit 1
    fi
    if ! grep -qxF "$heading" "$SKILL_FILE"; then
      echo "check-gemini-skill-budget.sh: embed incomplete" >&2
      echo "  missing $label heading from $(basename "$f"): $heading" >&2
      echo "  this file is not present in the built SKILL.md - assembly" >&2
      echo "  silently dropped a whole embedded file, which the floor/ceiling" >&2
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
  echo "check-gemini-skill-budget.sh: embed incomplete" >&2
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
stub_bytes="$(budget_file_bytes "$STUB_FILE")"

# Informational burn line (git-based, vs the resolved base ref) on the
# skill axis only - never affects the exit code, always renders a line (a
# "burn: SKIPPED (...)" line, never silently omitted, when git or a base
# ref is unavailable). No delta axis on either file, deliberately: both
# are GENERATED artifacts whose size on any given branch reflects upstream
# content/** churn as much as this PR's own diff (see
# scripts/gate-provenance.sh's DERIVED classification and
# scripts/check-skill-embed-budget.sh's identical rationale).
burn_line="$(budget_burn_line "$REPO_DIR" "$SKILL_FILE" "$SKILL_CEILING" "$skill_bytes")"

if [ "$skill_bytes" -lt "$SKILL_FLOOR" ]; then
  echo "check-gemini-skill-budget.sh: SKILL BELOW FLOOR - embed regression," >&2
  echo "  not a healthy shrink." >&2
  echo "  $SKILL_FILE measured only $skill_bytes B," >&2
  echo "  below the $SKILL_FLOOR B floor." >&2
  echo "  This almost certainly means the skill-write step in" >&2
  echo "  .gemini/build.sh broke and SKILL.md regressed to a pointer-only" >&2
  echo "  body that no longer inlines the methodology content. Investigate" >&2
  echo "  the build step directly; do not lower SKILL_FLOOR to make this" >&2
  echo "  pass." >&2
  echo "  $burn_line" >&2
  exit 1
fi

if [ "$skill_bytes" -gt "$SKILL_CEILING" ]; then
  overage=$(( skill_bytes - SKILL_CEILING ))
  echo "check-gemini-skill-budget.sh: SKILL ABOVE CEILING." >&2
  echo "  $SKILL_FILE measured $skill_bytes B," >&2
  echo "  above the $SKILL_CEILING B ceiling ($overage B over)." >&2
  echo "" >&2
  echo "  SKILL_CEILING is a headroom boundary against known-good" >&2
  echo "  measurements, not a swept injection-safety guarantee - no sweep" >&2
  echo "  has been run for the Gemini adapter specifically. Do not raise" >&2
  echo "  SKILL_CEILING as routine housekeeping when content grows; trim" >&2
  echo "  content instead, or raise it deliberately with justification in" >&2
  echo "  the PR that does so." >&2
  echo "  $burn_line" >&2
  exit 1
fi

if [ "$stub_bytes" -gt "$STUB_CEILING" ]; then
  echo "check-gemini-skill-budget.sh: STUB ABOVE CEILING - DS-184 regression." >&2
  echo "  $STUB_FILE measured $stub_bytes B," >&2
  echo "  above the $STUB_CEILING B stub ceiling." >&2
  echo "" >&2
  echo "  GEMINI.md is supposed to stay a small always-loaded stub pointing" >&2
  echo "  at the trigger-loaded dinostack skill (DS-184) - the full" >&2
  echo "  methodology body belongs in .gemini/skills/dinostack/SKILL.md" >&2
  echo "  instead. This measurement suggests the split has silently" >&2
  echo "  re-collapsed (the full body got re-embedded into GEMINI.md)." >&2
  echo "  Investigate .gemini/build.sh's Step 1; do not raise STUB_CEILING" >&2
  echo "  to make this pass." >&2
  exit 1
fi

echo "gemini skill budget check: OK"
echo "  SKILL.md:      $skill_bytes B"
echo "  skill floor:   $SKILL_FLOOR B"
echo "  skill ceiling: $SKILL_CEILING B"
echo "  $burn_line"
echo "  headroom to skill ceiling: $(( SKILL_CEILING - skill_bytes )) B"
echo "  GEMINI.md stub: $stub_bytes B"
echo "  stub ceiling:   $STUB_CEILING B"
echo "  headroom to stub ceiling: $(( STUB_CEILING - stub_bytes )) B"
exit 0
