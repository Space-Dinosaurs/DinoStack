#!/usr/bin/env bash
# Purpose: Two-sided guard on the generated .claude/skills/agentic-engineering/
#          SKILL.md - the artifact Claude Code injects verbatim into context
#          when the /agentic-engineering skill is invoked, post-DS-143
#          (trigger-loaded methodology). Two failure directions:
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
#             Exits 0 when FLOOR <= size <= CEILING. Exits 1 otherwise, or
#             when the input file is missing.
#
# Upstream deps: .claude/skills/agentic-engineering/SKILL.md (built by
#                .claude/build.sh; this script does not rebuild it - it
#                measures whatever is currently on disk, matching how
#                check-adapter-sync and the runtime skill loader both treat
#                the file as the artifact of record); scripts/lib/
#                budget-gate.sh (shared repo-dir resolution and byte
#                measurement - the two-sided floor/ceiling report below
#                stays here, since it does not fit the OK/OVER-BUDGET
#                shape budget_report shares with the other two gates).
#
# Downstream consumers: .github/workflows/resident-budget.yml.
#
# Failure modes: below FLOOR -> exit 1, message explicitly frames this as an
#                embed regression, not a healthy shrink - a passing skill
#                body should never get anywhere near 100,000 B smaller by
#                accident. Above CEILING -> exit 1, message reiterates the
#                single-data-point caveat and warns against a routine bump.
#                Missing input file -> exit 1. Read-only; no side effects on
#                the repo.
#
# Compatible with both bash and zsh invocation of the containing shell; CI
# always invokes it as `bash scripts/check-skill-embed-budget.sh`, but a
# contributor, reviewer, or this file's own regression test may invoke it
# as `zsh scripts/check-skill-embed-budget.sh` and it must behave
# identically.

set -euo pipefail

# BASH_SOURCE is unset under zsh - fall back to $0 so SCRIPT_DIR resolves
# correctly under both interpreters instead of collapsing to "//".
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib/budget-gate.sh
source "$SCRIPT_DIR/lib/budget-gate.sh"
REPO_DIR="$(budget_repo_dir "$SCRIPT_DIR")"

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

if [ ! -f "$SKILL_FILE" ]; then
  echo "check-skill-embed-budget.sh: missing file: $SKILL_FILE" >&2
  echo "  Run .claude/build.sh to regenerate it, then re-run this check." >&2
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
