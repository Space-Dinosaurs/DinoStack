#!/usr/bin/env bash
# Purpose: Guard against unbounded growth or catastrophic shrinkage of the
#          embedded methodology payload inside the generated Claude Code
#          skill file - .claude/skills/agentic-engineering/SKILL.md. DS-143
#          moved the resident methodology out of always-loaded @-imports and
#          into this file's "Embedded Resident Content" section, so it now
#          loads on skill invocation instead. That relocation left the
#          embedded payload (~126 KB) with no growth gate of its own; this
#          script is that gate, sibling to scripts/check-resident-budget.sh
#          (which now measures a much smaller pointer table instead).
#
# Public API: bash scripts/check-skill-embed-budget.sh
#             Exits 0 when FLOOR <= measured bytes <= CEILING. Exits 1 when
#             either bound is crossed, or when a required input is missing.
#
# Upstream deps: .claude/build.sh (rebuilds SKILL.md from content/ sources,
#                see its own side-effects below); content/sections/[0-9][0-9]-*.md
#                (section-heading completeness check); content/rules/conventions.md
#                (tail-phrase completeness check).
#
# Downstream consumers: intended for a CI job wired by a later DS-143 unit
#                        (not this one - see the ticket note below).
#
# Failure modes: embed incomplete (a whole section or rules file silently
#                dropped from assembly, landing inside the FLOOR..CEILING
#                dead zone where the byte band alone can't see it) -> exit 1
#                with a distinct "embed incomplete" message, separate from
#                and checked before the bound violations below. Under FLOOR
#                -> exit 1, most likely means the embed block in
#                .claude/build.sh regressed to a pointer-only SKILL.md or the
#                build truncated. Over CEILING -> exit 1, means the embedded
#                methodology grew past its safety boundary (see CEILING
#                rationale below) and needs compression or a deliberately
#                re-verified higher ceiling. Missing .claude/build.sh -> exit
#                1. A failing `.claude/build.sh` propagates the build's own
#                exit code via `set -e` rather than this script's own exit 1
#                - e.g. a build that dies with exit 7 makes this script exit
#                7, not 1; this is correct and CI-safe (any nonzero fails the
#                job) but is a distinct, undocumented-elsewhere code path.
#                NOT read-only: this script invokes a full adapter build
#                (`bash .claude/build.sh`), which writes
#                .claude/skills/agentic-engineering/{SKILL.md,METHODOLOGY.md},
#                re-links its references/, project-scaffolding.yml, and
#                templates/.agentic/* hardlinks, rewrites every
#                .claude/commands/*.md, and DELETES any .claude/commands/*.md
#                whose content/commands/ source no longer exists. A
#                contributor running this "budget check" on a branch that
#                renamed or removed a command will see those files deleted
#                from their tree (git-recoverable, and the same prune
#                .claude/build.sh always performs - not a novel side effect
#                of this script, but a real one worth knowing about before
#                running it).
#
# Performance: not a `stat` - runs a full adapter build (`bash
#              .claude/build.sh`, which itself invokes
#              scripts/build-methodology.sh) plus a fixed-size loop over the
#              12 content/sections/*.md files, on every invocation. Expect
#              build-script latency (sub-second on a warm checkout), not
#              filesystem-metadata latency; this is surprising for something
#              named check-*-budget.sh and worth calling out explicitly.
#
# Note: SKILL.md is measured by running .claude/build.sh fresh, NOT by
#       statting whatever happens to be on disk - a PR that edits content/
#       sources without rebuilding adapters would otherwise be measured
#       against a stale artifact and could slip a regression past this gate.
#
# Compatible with both bash and zsh invocation of the containing shell; a
# contributor, reviewer, or this file's own regression test may invoke it as
# `zsh scripts/check-skill-embed-budget.sh` and it must behave identically.
# Avoid the variable names `status` and `path` anywhere in this file - both
# are special/read-only in zsh and have silently broken sibling scripts here
# before.

set -euo pipefail

# BASH_SOURCE is unset under zsh. Fall back to $0 so REPO_DIR resolves
# correctly under both interpreters instead of collapsing to "//".
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

BUILD_SCRIPT="$REPO_DIR/.claude/build.sh"
SKILL_MD="$REPO_DIR/.claude/skills/agentic-engineering/SKILL.md"

# FLOOR: catches a regression to a pointer-only SKILL.md (it was ~6 KB
# before the DS-143 embed) and catastrophic build truncation. There is no
# realistic path to a correct, fully-embedded SKILL.md landing anywhere
# near this value.
FLOOR=100000

# CEILING: this is NOT a tidiness limit - it is a safety boundary. The
# harness was empirically verified to inject an entire SKILL.md body
# verbatim, with no truncation, at a measured size of approximately 127 KB.
# That is a SINGLE data point, not a swept boundary - nobody has confirmed
# where (or whether) the harness starts truncating or dropping content
# above it. CEILING is set at roughly 1.1x the measured size at the time
# this script was authored, giving limited headroom while staying inside
# the region that has actually been observed to work.
#
# Ratchet discipline, same as scripts/check-resident-budget.sh: CEILING
# ratchets DOWN when compression work shrinks the embedded payload - lower
# it in the same commit as any deliberate compression. Raising CEILING is
# NOT a simple constant bump: a contributor who wants more headroom must
# first re-run a scale probe confirming the harness still delivers the
# whole file verbatim at (or near) the new target size, then set CEILING
# from that fresh measurement - never from a stale prior figure and never
# reflexively.
CEILING=139160

if [ ! -f "$BUILD_SCRIPT" ]; then
  echo "check-skill-embed-budget.sh: missing file: $BUILD_SCRIPT" >&2
  exit 1
fi

bash "$BUILD_SCRIPT" >/dev/null

if [ ! -f "$SKILL_MD" ]; then
  echo "check-skill-embed-budget.sh: build did not produce $SKILL_MD" >&2
  exit 1
fi

# Embed-completeness check (distinct from the FLOOR/CEILING bound check
# below): a whole embedded file - one content/sections/*.md section, or the
# content/rules/conventions.md tail - can go missing from assembly and still
# land inside the FLOOR..CEILING byte band, where the two-sided bound check
# alone cannot see it (verified: dropping content/sections/04-risk-
# classification.md from assembly, or dropping content/rules/conventions.md
# from the .claude/build.sh embed loop, both still land inside the band and
# both must fail here instead). A single arbitrary head/tail phrase pair
# cannot detect a dropped *middle* section, so this checks a phrase from
# EVERY content/sections/*.md file, not just one - each section's own first
# top-level heading, derived dynamically so a renamed or newly added section
# is covered automatically without maintaining a hardcoded list here.
SECTIONS_DIR="$REPO_DIR/content/sections"
section_files="$(LC_ALL=C find "$SECTIONS_DIR" -maxdepth 1 -type f -name '[0-9][0-9]-*.md' | LC_ALL=C sort)"
if [ -z "$section_files" ]; then
  echo "check-skill-embed-budget.sh: no section files found in $SECTIONS_DIR" >&2
  exit 1
fi
while IFS= read -r section_file; do
  heading="$(grep -m1 '^## ' "$section_file" || true)"
  if [ -z "$heading" ]; then
    echo "check-skill-embed-budget.sh: embed incomplete" >&2
    echo "  $section_file has no top-level '## ' heading to check against" >&2
    exit 1
  fi
  if ! grep -qxF "$heading" "$SKILL_MD"; then
    echo "check-skill-embed-budget.sh: embed incomplete" >&2
    echo "  missing section heading from $(basename "$section_file"): $heading" >&2
    echo "  this section is not present in the built SKILL.md - assembly" >&2
    echo "  silently dropped a whole embedded file, which the FLOOR/CEILING" >&2
    echo "  byte band alone cannot detect." >&2
    exit 1
  fi
done <<< "$section_files"

# Tail-phrase check: content/rules/conventions.md sorts last (alphabetically)
# among the content/rules/*.md files .claude/build.sh embeds (module-
# manifest.md is deliberately excluded from the embed), so a stable phrase
# from its own last heading confirms the rules-file embed loop actually
# reached and completed its last file - catching a whole rules file
# silently dropped from the embed the same way the section-heading loop
# above catches a dropped section.
TAIL_PHRASE='## External Comment Discipline'
if ! grep -qxF "$TAIL_PHRASE" "$SKILL_MD"; then
  echo "check-skill-embed-budget.sh: embed incomplete" >&2
  echo "  missing tail phrase from content/rules/conventions.md: $TAIL_PHRASE" >&2
  echo "  this heading is not present in the built SKILL.md - the rules-file" >&2
  echo "  embed loop in .claude/build.sh did not complete." >&2
  exit 1
fi

skill_bytes="$(wc -c < "$SKILL_MD" | tr -d '[:space:]')"

if [ "$skill_bytes" -lt "$FLOOR" ]; then
  echo "skill embed budget check: UNDER FLOOR" >&2
  echo "  SKILL.md (built):  $skill_bytes B" >&2
  echo "  floor:             $FLOOR B" >&2
  echo "" >&2
  echo "The embedded methodology payload is implausibly small. This likely" >&2
  echo "means the embed block in .claude/build.sh regressed to a" >&2
  echo "pointer-only SKILL.md, or the build produced truncated output. It" >&2
  echo "does NOT mean the file is under budget - investigate .claude/build.sh" >&2
  echo "directly; do not lower FLOOR to make this pass." >&2
  exit 1
fi

if [ "$skill_bytes" -gt "$CEILING" ]; then
  overage=$(( skill_bytes - CEILING ))
  echo "skill embed budget check: OVER CEILING" >&2
  echo "  SKILL.md (built):  $skill_bytes B" >&2
  echo "  ceiling:           $CEILING B" >&2
  echo "  overage:           $overage B" >&2
  echo "" >&2
  echo "The embedded methodology payload grew past its safety ceiling. This" >&2
  echo "is not a tidiness limit - the harness has only been confirmed to" >&2
  echo "inject the full SKILL.md body verbatim near the current ceiling; a" >&2
  echo "single data point, not a swept boundary. Compress the embedded" >&2
  echo "content, or if growth is deliberate and justified, re-run a scale" >&2
  echo "probe at the new target size and set CEILING from that fresh" >&2
  echo "measurement in the same PR." >&2
  exit 1
fi

headroom=$(( CEILING - skill_bytes ))
echo "skill embed budget check: OK"
echo "  SKILL.md (built):  $skill_bytes B"
echo "  floor:             $FLOOR B"
echo "  ceiling:           $CEILING B"
echo "  headroom:          $headroom B"
exit 0
