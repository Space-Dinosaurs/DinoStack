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
# Upstream deps: .claude/build.sh (rebuilds SKILL.md from content/ sources).
#
# Downstream consumers: intended for a CI job wired by a later DS-143 unit
#                        (not this one - see the ticket note below).
#
# Failure modes: under FLOOR -> exit 1, most likely means the embed block in
#                .claude/build.sh regressed to a pointer-only SKILL.md or the
#                build truncated. Over CEILING -> exit 1, means the embedded
#                methodology grew past its safety boundary (see CEILING
#                rationale below) and needs compression or a deliberately
#                re-verified higher ceiling. Missing .claude/build.sh -> exit
#                1. Read-only against repo sources; writes only to the
#                generated .claude/skills/agentic-engineering/SKILL.md via
#                the build it invokes (the same file .claude/build.sh always
#                regenerates).
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
