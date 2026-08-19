#!/usr/bin/env bash
# Purpose: Budget guard for Codex's trigger-loaded methodology (DS-183),
#          modeled directly on scripts/check-skill-embed-budget.sh's
#          three-axis shape but retargeted at the Codex artifacts, which
#          split content differently than Claude Code's single embedded
#          SKILL.md:
#            - METHODOLOGY_FILE embed-completeness + FLOOR + burn line:
#              .codex/skills/dinostack/METHODOLOGY.md is the artifact that
#              actually carries the assembled content/sections/*.md body
#              (built independently by scripts/codex-skills.py build(),
#              which itself calls scripts/build-methodology.sh - see that
#              script's own header). It does NOT embed content/rules/*.md
#              text the way Claude's SKILL.md does; those two rule files
#              are reachable only via the adjacent `rules -> ../../../
#              content/rules` symlink, never inlined as prose. So the
#              embed-completeness check below verifies SECTIONS by heading
#              presence inside METHODOLOGY.md (same technique as the Claude
#              gate) and verifies RULES by symlink resolution + file-count
#              match against content/rules/*.md (excluding
#              module-manifest.md) instead - there is no rules prose inside
#              METHODOLOGY.md to grep for.
#            - AGENTS_FILE stub ceiling: .codex/AGENTS.md is generated as a
#              minimal always-resident stub (runtime binding preamble,
#              activation-preflight pointer, skill-load-on-trigger
#              instruction) by .codex/build.sh - it must never regress to
#              re-embedding the full methodology body inline. This is a
#              ceiling-only check (ABOVE it means an accidental re-embed);
#              there is no meaningful floor for a hand-authored stub the
#              way there is for a generated embed, so none is checked here.
#
# Public API: bash scripts/check-codex-skill-budget.sh
#             Exits 0 when the embed-completeness check passes AND
#             METHODOLOGY_FILE bytes >= METHODOLOGY_FLOOR AND
#             AGENTS_FILE bytes <= AGENTS_STUB_CEILING. Exits 1 otherwise,
#             or when a required input is missing.
#
# Upstream deps: .codex/skills/dinostack/METHODOLOGY.md and .codex/
#                skills/dinostack/rules (built by .codex/build.sh via
#                scripts/codex-skills.py build()); .codex/AGENTS.md (built
#                by .codex/build.sh); content/sections/[0-9][0-9]-*.md and
#                content/rules/*.md (excluding module-manifest.md) for the
#                embed-completeness check; scripts/lib/budget-gate.sh
#                (shared repo-dir resolution, byte measurement, and
#                budget_burn_line for the informational line printed after
#                the METHODOLOGY_FILE FLOOR check).
#
# Downstream consumers: .github/workflows/codex-skill-budget.yml (its
#                        checkout step needs `fetch-depth: 0` so the burn
#                        line can resolve `origin/main` - a default
#                        shallow checkout would leave that ref unreachable
#                        and the line would render its SKIPPED variant on
#                        every CI run). Advisory only - deliberately not
#                        added to the `main` ruleset's required-checks list
#                        (matches check-command-file-budget.sh's
#                        precedent), but the job itself is not
#                        continue-on-error: it fails like any other check
#                        on overage.
#
# Failure modes: embed incomplete (a content/sections/*.md file dropped
#                from METHODOLOGY.md assembly, a section/rules file count
#                mismatch against EXPECTED_SECTION_COUNT/
#                EXPECTED_RULES_COUNT, or the rules symlink missing/broken)
#                -> exit 1, checked before either byte-bound check. Below
#                METHODOLOGY_FLOOR -> exit 1, framed as an embed
#                regression (pointer-only skill), not a healthy shrink.
#                Above AGENTS_STUB_CEILING -> exit 1, framed as an
#                accidental re-embed of the full body into the stub.
#                Missing input file -> exit 1. The burn line for
#                METHODOLOGY_FILE is computed once, after the embed-
#                completeness check, and printed on both the FLOOR-OK and
#                BELOW-FLOOR paths; unresolvable git/base renders a "burn:
#                SKIPPED (...)" line rather than omitting it. Read-only; no
#                side effects on the repo.
#
# Detection boundary: the heading-completeness check proves each section
# file's own top-level heading is PRESENT somewhere in the built
# METHODOLOGY.md - a presence check, not a completeness digest, so partial
# corruption or truncation of a section's BODY (heading intact, content
# gutted or duplicated) is only caught if it pushes total bytes below
# METHODOLOGY_FLOOR. The rules check proves the symlink resolves and the
# file count matches - it cannot detect a rules file's own content being
# corrupted, since content/rules/*.md is read through the same symlink
# content/rules/*.md itself is served from (there is no separate copy to
# diverge). It also cannot detect an ABSOLUTIZED symlink (one whose target
# is an absolute path into a specific machine's checkout instead of the
# tracked relative `../../../content/rules` form) - `find -L` and `grep`
# both resolve and read through an absolutized symlink exactly as they do a
# correctly relative one, so this check's rules-reachable pass gives no
# signal either way on that class of defect. scripts/check-symlinks-relative.sh
# (wired separately in .github/workflows/adapter-sync.yml) is the gate that
# actually catches it - see DS-96/DS-104 in AGENTS.md.
#
# Compatible with both bash and zsh invocation of the containing shell; CI
# always invokes it as `bash scripts/check-codex-skill-budget.sh`, but a
# contributor, reviewer, or this file's own regression test may invoke it
# as `zsh scripts/check-codex-skill-budget.sh` and it must behave
# identically. Avoid the variable names `status` and `path` anywhere in
# this file - both are special/read-only in zsh.

set -euo pipefail

# BASH_SOURCE is unset under zsh - fall back to $0 so SCRIPT_DIR resolves
# correctly under both interpreters instead of collapsing to "//".
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib/budget-gate.sh
source "$SCRIPT_DIR/lib/budget-gate.sh"
REPO_DIR="$(budget_repo_dir "$SCRIPT_DIR")"

METHODOLOGY_FILE="$REPO_DIR/.codex/skills/dinostack/METHODOLOGY.md"
RULES_LINK="$REPO_DIR/.codex/skills/dinostack/rules"
AGENTS_FILE="$REPO_DIR/.codex/AGENTS.md"

# Floor: catches a regression to a pointer-only skill body (the assembly
# step in scripts/codex-skills.py silently breaking and no longer inlining
# content/sections/*.md into METHODOLOGY.md). The live measured size is
# ~102,900 B (2026-08-19); 80,000 B is far below any realistic assembled
# size and far above what a pointer-only skill would ever measure.
METHODOLOGY_FLOOR=80000

# Ceiling on the always-resident AGENTS.md stub. The live measured size is
# ~5,000 B (2026-08-19, post-DS-183); 10,000 B leaves headroom for the stub
# to grow (new pointer text, a longer trigger-signal list) while still
# catching an accidental re-embed of the full methodology body, which
# measured 140,910 B pre-DS-183 - more than 14x this ceiling.
AGENTS_STUB_CEILING=10000

# EXPECTED_SECTION_COUNT / EXPECTED_RULES_COUNT: pinned counts, ratcheted
# the same way FLOOR/CEILING/THRESHOLD are elsewhere in this repo (see
# scripts/check-resident-budget.sh and scripts/check-skill-embed-budget.sh,
# whose own EXPECTED_SECTION_COUNT/EXPECTED_RULES_COUNT this mirrors).
# Update the same commit that adds, removes, or renumbers a
# content/sections/[0-9][0-9]-*.md file, or adds/removes a
# content/rules/*.md file other than module-manifest.md.
#
# Deliberately a fixed constant, NOT derived from the working tree at check
# time: deriving the expected count from the working tree makes the
# expected side and the actual side move together, so an outright file
# deletion removes it from both what is expected AND what is checked - the
# loss becomes invisible. A pinned constant closes that tautology.
EXPECTED_SECTION_COUNT=12
EXPECTED_RULES_COUNT=2

if [ ! -f "$METHODOLOGY_FILE" ]; then
  echo "check-codex-skill-budget.sh: missing file: $METHODOLOGY_FILE" >&2
  echo "  Run .codex/build.sh to regenerate it, then re-run this check." >&2
  exit 1
fi

if [ ! -f "$AGENTS_FILE" ]; then
  echo "check-codex-skill-budget.sh: missing file: $AGENTS_FILE" >&2
  echo "  Run .codex/build.sh to regenerate it, then re-run this check." >&2
  exit 1
fi

# Section embed-completeness check: each content/sections/[0-9][0-9]-*.md
# file's own top-level heading must be present somewhere in the built
# METHODOLOGY.md, and the file count must match EXPECTED_SECTION_COUNT
# exactly. DS-183 round 2 (M6 fix): this was previously a 47-line near-
# verbatim reimplementation of check-skill-embed-budget.sh's own
# _check_embedded_set - now calls the shared
# scripts/lib/budget-gate.sh:budget_check_embedded_set instead. Output
# wording differs from check-skill-embed-budget.sh's own calls (this script
# was never bound to that script's exact wording the way the M6 finding
# required for check-skill-embed-budget.sh itself), but the duplicate-
# heading check below still needs ALL_SECTION_HEADINGS accumulated by the
# shared function.
ALL_SECTION_HEADINGS=""
_check_section_headings() {
  budget_check_embedded_set "check-codex-skill-budget.sh" "$REPO_DIR/content/sections" \
    '[0-9][0-9]-*.md' '' "$EXPECTED_SECTION_COUNT" 'section' 'EXPECTED_SECTION_COUNT' \
    "$METHODOLOGY_FILE" ALL_SECTION_HEADINGS 'METHODOLOGY.md' 'METHODOLOGY_FLOOR'

  local duplicate_headings
  duplicate_headings="$(printf '%s' "$ALL_SECTION_HEADINGS" | LC_ALL=C sort | LC_ALL=C uniq -d)"
  if [ -n "$duplicate_headings" ]; then
    echo "check-codex-skill-budget.sh: embed incomplete" >&2
    echo "  duplicate top-level heading(s) shared across section files - the" >&2
    echo "  presence check above cannot distinguish per-file completeness when" >&2
    echo "  a heading repeats:" >&2
    printf '%s\n' "$duplicate_headings" | while IFS= read -r dup; do
      [ -n "$dup" ] && echo "    $dup" >&2
    done
    exit 1
  fi
}

# Rules reachability check: METHODOLOGY.md does not embed content/rules/*.md
# as text (unlike Claude's SKILL.md), so completeness here means the
# rules/ symlink resolves to a real directory and contains exactly
# EXPECTED_RULES_COUNT files matching content/rules/*.md (excluding
# module-manifest.md), not a text-presence check.
_check_rules_reachable() {
  local dir="$REPO_DIR/content/rules"
  local source_files source_count linked_files linked_count
  source_files="$(LC_ALL=C find "$dir" -maxdepth 1 -type f -name '*.md' ! -name 'module-manifest.md' | LC_ALL=C sort)"
  source_count="$(wc -l <<< "$source_files" | tr -d '[:space:]')"
  if [ "$source_count" -ne "$EXPECTED_RULES_COUNT" ]; then
    echo "check-codex-skill-budget.sh: embed incomplete" >&2
    echo "  rules file count mismatch: expected $EXPECTED_RULES_COUNT, found $source_count" >&2
    echo "  a content/rules/*.md file (other than module-manifest.md) was" >&2
    echo "  added or removed - if intentional, bump EXPECTED_RULES_COUNT above" >&2
    echo "  in the same commit. If not, investigate before bumping the count." >&2
    exit 1
  fi
  if [ ! -e "$RULES_LINK" ]; then
    echo "check-codex-skill-budget.sh: embed incomplete" >&2
    echo "  $RULES_LINK does not exist - the dinostack skill's rules" >&2
    echo "  resource is unreachable. Run .codex/build.sh to regenerate it." >&2
    exit 1
  fi
  linked_files="$(LC_ALL=C find -L "$RULES_LINK" -maxdepth 1 -type f -name '*.md' ! -name 'module-manifest.md' | LC_ALL=C sort)"
  linked_count="$(wc -l <<< "$linked_files" | tr -d '[:space:]')"
  if [ "$linked_count" -ne "$EXPECTED_RULES_COUNT" ]; then
    echo "check-codex-skill-budget.sh: embed incomplete" >&2
    echo "  $RULES_LINK resolves but contains $linked_count rules file(s)," >&2
    echo "  expected $EXPECTED_RULES_COUNT - the resource link is stale or broken." >&2
    exit 1
  fi
}

_check_section_headings
_check_rules_reachable

methodology_bytes="$(budget_file_bytes "$METHODOLOGY_FILE")"
agents_bytes="$(budget_file_bytes "$AGENTS_FILE")"

# Informational burn line (git-based, vs the resolved base ref) for the
# generated METHODOLOGY.md artifact - never affects the exit code, always
# renders a line (a "burn: SKIPPED (...)" line, never silently omitted,
# when git or a base ref is unavailable). No burn line for AGENTS_FILE:
# only one axis was requested for the stub (the ceiling below).
burn_line="$(budget_burn_line "$REPO_DIR" "$METHODOLOGY_FILE" "$METHODOLOGY_FLOOR" "$methodology_bytes")"

if [ "$methodology_bytes" -lt "$METHODOLOGY_FLOOR" ]; then
  echo "check-codex-skill-budget.sh: BELOW METHODOLOGY FLOOR - embed" >&2
  echo "  regression, not a healthy shrink." >&2
  echo "  $METHODOLOGY_FILE measured only $methodology_bytes B," >&2
  echo "  below the $METHODOLOGY_FLOOR B floor." >&2
  echo "  This almost certainly means the assembly step in" >&2
  echo "  scripts/codex-skills.py broke and METHODOLOGY.md regressed to a" >&2
  echo "  pointer-only body. Investigate the build step directly; do not" >&2
  echo "  lower METHODOLOGY_FLOOR to make this pass." >&2
  echo "  $burn_line" >&2
  exit 1
fi

if [ "$agents_bytes" -gt "$AGENTS_STUB_CEILING" ]; then
  overage=$(( agents_bytes - AGENTS_STUB_CEILING ))
  echo "check-codex-skill-budget.sh: ABOVE AGENTS STUB CEILING." >&2
  echo "  $AGENTS_FILE measured $agents_bytes B," >&2
  echo "  above the $AGENTS_STUB_CEILING B ceiling ($overage B over)." >&2
  echo "  This almost certainly means the full methodology body was" >&2
  echo "  re-embedded into .codex/AGENTS.md (a DS-183 regression) instead of" >&2
  echo "  staying in .codex/skills/dinostack/METHODOLOGY.md, which loads on" >&2
  echo "  trigger via the dinostack skill. Investigate .codex/build.sh" >&2
  echo "  directly; do not raise AGENTS_STUB_CEILING to make this pass." >&2
  exit 1
fi

echo "codex skill budget check: OK"
echo "  METHODOLOGY.md: $methodology_bytes B"
echo "  methodology floor: $METHODOLOGY_FLOOR B"
echo "  $burn_line"
echo "  headroom to methodology floor: $(( methodology_bytes - METHODOLOGY_FLOOR )) B"
echo "  AGENTS.md (stub): $agents_bytes B"
echo "  stub ceiling: $AGENTS_STUB_CEILING B"
echo "  headroom to stub ceiling: $(( AGENTS_STUB_CEILING - agents_bytes )) B"
exit 0
