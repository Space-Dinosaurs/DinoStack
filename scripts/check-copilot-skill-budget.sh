#!/usr/bin/env bash
# Purpose: Budget/completeness guard on the generated
#          .github/skills/dinostack/SKILL.md - the artifact VS Code
#          Copilot's native Agent Skills primitive injects verbatim into
#          context when it description-matches the `dinostack` skill
#          against a prompt (DS-186, trigger-loaded methodology, mirroring
#          the DS-143 pattern already shipped for
#          .claude/skills/dinostack/SKILL.md via
#          scripts/check-skill-embed-budget.sh - this script is that
#          gate's Copilot sibling, modeled on it directly). Four failure
#          classes:
#            - EMBED INCOMPLETE: a whole content/sections/*.md or
#              content/rules/*.md source file silently dropped from
#              .copilot/build.sh's assembly. Can land inside the FLOOR
#              band undetected by size alone. Also covers an outright
#              add/remove of a source file via pinned
#              EXPECTED_SECTION_COUNT/EXPECTED_RULES_COUNT constants (see
#              their own comment below for why a pinned count, not a
#              re-derived one, is required).
#            - FLOOR: catches a regression to a pointer-only skill body
#              (.copilot/build.sh's embed step silently breaking and no
#              longer inlining the methodology body into SKILL.md). Would
#              otherwise be invisible - a pointer-only skill still builds
#              and still passes adapter-sync.
#            - STUB CEILING: catches the inverse regression - the full
#              methodology body accidentally re-embedded into
#              .github/copilot-instructions.md instead of staying in the
#              trigger-loaded skill, defeating the whole point of DS-186
#              (Copilot loads copilot-instructions.md unconditionally in
#              every session).
#            - No hard per-PR delta limit on the skill body: run
#              `bash scripts/gate-provenance.sh
#              .github/skills/dinostack/SKILL.md` before changing this -
#              it classifies DERIVED (D1: the adapter-sync.yml
#              regenerate-then-assert-clean pathspec covers .github/skills),
#              so this gate carries only the informational
#              scripts/lib/budget-gate.sh burn line, same rationale as
#              check-skill-embed-budget.sh's own DERIVED classification.
#
# Public API: bash scripts/check-copilot-skill-budget.sh
#             Exits 0 when the embed-completeness check passes, the stub
#             ceiling holds, AND FLOOR <= skill size. Exits 1 otherwise, or
#             when a required input is missing.
#
# Upstream deps: .github/skills/dinostack/SKILL.md and
#                .github/copilot-instructions.md (both built by
#                .copilot/build.sh; this script does not rebuild them - it
#                measures whatever is currently on disk, matching how
#                adapter-sync and the runtime skill loader both treat the
#                files as the artifacts of record); content/sections/
#                [0-9][0-9]-*.md and content/rules/*.md (excluding
#                module-manifest.md) for the embed-completeness check;
#                scripts/lib/budget-gate.sh (shared repo-dir resolution,
#                byte measurement, and budget_burn_line for the
#                informational line printed on every exit path below).
#
# Downstream consumers: .github/workflows/copilot-skill-budget.yml
#                        (advisory-only - deliberately NOT added to the
#                        `main` ruleset's required-checks list, matching
#                        scripts/check-command-file-budget.sh's precedent;
#                        its checkout step needs `fetch-depth: 0` so the
#                        burn line can resolve `origin/main`, or the git
#                        axis silently degrades to its SKIPPED variant on
#                        every CI run).
#
# Failure modes: embed incomplete (a source file dropped from assembly, or
#                a file count mismatch against EXPECTED_SECTION_COUNT/
#                EXPECTED_RULES_COUNT) -> exit 1 with a distinct "embed
#                incomplete" message, checked before the FLOOR/stub-ceiling
#                checks. Below FLOOR -> exit 1, message frames this as an
#                embed regression, not a healthy shrink. Above STUB_CEILING
#                (the stub copilot-instructions.md grew far past what a
#                pointer stub should ever measure) -> exit 1, message
#                frames this as a re-embed regression. Missing input file
#                -> exit 1. The burn line (on the skill body, vs
#                origin/main) is computed once before the FLOOR check and
#                printed on the FLOOR/OK exit paths - unresolvable git/base
#                renders a "burn: SKIPPED (...)" line rather than omitting
#                it entirely; never a failure. Read-only; no side effects.
#
# Detection boundary: the heading-completeness check below proves each
# source file's own top-level heading is PRESENT somewhere in the built
# skill body - it is a presence check, not a completeness digest, so
# partial corruption or truncation of a section's BODY (heading intact,
# content gutted or duplicated) is only caught if it pushes total bytes
# outside FLOOR..CEILING or below the stub ceiling on the wrong file.
#
# Compatible with both bash and zsh invocation of the containing shell.
# Avoid the variable names `status` and `path` anywhere in this file -
# both are special/read-only in zsh.

set -euo pipefail

# BASH_SOURCE is unset under zsh - fall back to $0 so SCRIPT_DIR resolves
# correctly under both interpreters instead of collapsing to "//".
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib/budget-gate.sh
source "$SCRIPT_DIR/lib/budget-gate.sh"
REPO_DIR="$(budget_repo_dir "$SCRIPT_DIR")"

SKILL_FILE="$REPO_DIR/.github/skills/dinostack/SKILL.md"
STUB_FILE="$REPO_DIR/.github/copilot-instructions.md"

# Floor: catches a regression to a pointer-only skill (the embed step in
# .copilot/build.sh silently breaking and no longer inlining the
# methodology body into SKILL.md). 100,000 B is far below any realistic
# embedded size (live measured 135,521 B) and far above what a
# pointer-only skill would ever measure.
FLOOR=100000

# Stub ceiling: catches the accidental-re-embed regression on the OTHER
# file - copilot-instructions.md growing back toward a full methodology
# body instead of staying a stub pointer. 5,000 B is well above the live
# stub (669 B as of authoring) but far below anything resembling a
# partial or full re-embed.
STUB_CEILING=5000

# EXPECTED_SECTION_COUNT / EXPECTED_RULES_COUNT: pinned counts, same
# discipline as scripts/check-skill-embed-budget.sh's identical
# constants - see that file's comment for the full rationale (a
# working-tree-derived expected count makes deletion invisible to this
# check; a pinned constant closes that tautology). Update the same commit
# that adds, removes, or renumbers a content/sections/[0-9][0-9]-*.md
# file, or adds/removes a content/rules/*.md file other than
# module-manifest.md (excluded from the embed by .copilot/build.sh, and
# from this count).
EXPECTED_SECTION_COUNT=12
EXPECTED_RULES_COUNT=2

if [ ! -f "$SKILL_FILE" ]; then
  echo "check-copilot-skill-budget.sh: missing file: $SKILL_FILE" >&2
  echo "  Run .copilot/build.sh to regenerate it, then re-run this check." >&2
  exit 1
fi

if [ ! -f "$STUB_FILE" ]; then
  echo "check-copilot-skill-budget.sh: missing file: $STUB_FILE" >&2
  echo "  Run .copilot/build.sh to regenerate it, then re-run this check." >&2
  exit 1
fi

# Embed-completeness check (distinct from the FLOOR/stub-ceiling checks
# below): a whole embedded source file can go missing from assembly and
# still land inside the FLOOR band, where the size-only checks alone
# cannot see it. Checks a phrase from EVERY file in both sets - each
# file's own first top-level heading, derived dynamically so a renamed
# file is covered automatically without maintaining a hardcoded phrase
# list here. Shared between the two sets (content/sections/[0-9][0-9]-*.md
# and content/rules/*.md, excluding module-manifest.md) via one function
# to avoid duplicating this logic twice.
_check_embedded_set() {
  local dir="$1" pattern="$2" exclude="$3" expected_count="$4" label="$5" constant_name="$6"
  local files file_count f heading
  if [ -n "$exclude" ]; then
    files="$(LC_ALL=C find "$dir" -maxdepth 1 -type f -name "$pattern" ! -name "$exclude" | LC_ALL=C sort)"
  else
    files="$(LC_ALL=C find "$dir" -maxdepth 1 -type f -name "$pattern" | LC_ALL=C sort)"
  fi
  if [ -z "$files" ]; then
    echo "check-copilot-skill-budget.sh: no $label files found in $dir" >&2
    exit 1
  fi
  file_count="$(wc -l <<< "$files" | tr -d '[:space:]')"
  if [ "$file_count" -gt "$expected_count" ]; then
    echo "check-copilot-skill-budget.sh: embed incomplete" >&2
    echo "  $label file count mismatch: expected $expected_count, found $file_count" >&2
    echo "  a new $label source file was added - this is likely intentional." >&2
    echo "  If so, bump $constant_name above in the same commit that adds the" >&2
    echo "  file. If not, an extra file landed under $dir unexpectedly -" >&2
    echo "  investigate before bumping the count." >&2
    exit 1
  fi
  if [ "$file_count" -lt "$expected_count" ]; then
    echo "check-copilot-skill-budget.sh: embed incomplete" >&2
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
      echo "check-copilot-skill-budget.sh: embed incomplete" >&2
      echo "  $f has no top-level '## ' heading to check against" >&2
      echo "  every embedded $label source file needs its own distinct" >&2
      echo "  top-level '## Heading' line for this check to verify its" >&2
      echo "  presence in the built SKILL.md - add one (e.g. a '# ' opener" >&2
      echo "  demoted to '## ', or a missing heading added outright)." >&2
      exit 1
    fi
    if ! grep -qxF "$heading" "$SKILL_FILE"; then
      echo "check-copilot-skill-budget.sh: embed incomplete" >&2
      echo "  missing $label heading from $(basename "$f"): $heading" >&2
      echo "  this file is not present in the built SKILL.md - assembly" >&2
      echo "  silently dropped a whole embedded file, which the FLOOR check" >&2
      echo "  alone cannot detect." >&2
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
  echo "check-copilot-skill-budget.sh: embed incomplete" >&2
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
# skill body - never affects the exit code, always renders a line (a
# "burn: SKIPPED (...)" line, never silently omitted, when git or a base
# ref is unavailable). No hard delta limit here: this is a DERIVED
# artifact per `bash scripts/gate-provenance.sh
# .github/skills/dinostack/SKILL.md` (D1), same rationale as
# check-skill-embed-budget.sh's identical DERIVED classification -
# scripts/lib/budget-gate.sh's own header explains the AUTHORED/DERIVED
# axis split.
burn_line="$(budget_burn_line "$REPO_DIR" "$SKILL_FILE" "" "$skill_bytes")"

if [ "$skill_bytes" -lt "$FLOOR" ]; then
  echo "check-copilot-skill-budget.sh: BELOW FLOOR - embed regression, not a" >&2
  echo "  healthy shrink." >&2
  echo "  $SKILL_FILE measured only $skill_bytes B," >&2
  echo "  below the $FLOOR B floor." >&2
  echo "  This almost certainly means the embed step in .copilot/build.sh" >&2
  echo "  broke and SKILL.md regressed to a pointer-only body that no" >&2
  echo "  longer inlines the methodology content. Investigate the build" >&2
  echo "  step directly; do not lower FLOOR to make this pass." >&2
  echo "  $burn_line" >&2
  exit 1
fi

if [ "$stub_bytes" -gt "$STUB_CEILING" ]; then
  overage=$(( stub_bytes - STUB_CEILING ))
  echo "check-copilot-skill-budget.sh: STUB ABOVE CEILING." >&2
  echo "  $STUB_FILE measured $stub_bytes B," >&2
  echo "  above the $STUB_CEILING B stub ceiling ($overage B over)." >&2
  echo "" >&2
  echo "  copilot-instructions.md is meant to stay a thin pointer at the" >&2
  echo "  trigger-loaded dinostack skill (DS-186) - this almost certainly" >&2
  echo "  means the methodology body got re-embedded into the always-loaded" >&2
  echo "  stub instead of staying in .github/skills/dinostack/SKILL.md," >&2
  echo "  defeating the whole point of the trigger-load move. Investigate" >&2
  echo "  the .copilot/build.sh Step 1 split; do not raise STUB_CEILING to" >&2
  echo "  make this pass." >&2
  exit 1
fi

echo "copilot skill budget check: OK"
echo "  SKILL.md: $skill_bytes B"
echo "  floor:    $FLOOR B"
echo "  stub:     $stub_bytes B (ceiling: $STUB_CEILING B)"
echo "  $burn_line"
echo "  headroom to floor: $(( skill_bytes - FLOOR )) B"
exit 0
