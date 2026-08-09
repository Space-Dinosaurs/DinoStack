#!/usr/bin/env bash
# Purpose: Guard against unbounded growth of the "resident set" - the
#          content every Claude Code session pays for on every project,
#          regardless of whether that project's task needs it. Post-DS-143
#          (trigger-loaded methodology), ~/.claude/CLAUDE.md no longer
#          @-imports METHODOLOGY.md, conventions.md, or code-standards.md -
#          those now ship inside the generated skill body and load only on
#          skill invocation (see scripts/check-skill-embed-budget.sh for the
#          budget on THAT payload). The only content still resident in every
#          session is the Skill Loading table that .claude/install.sh writes
#          into the managed-by-dinostack block, single-sourced from
#          content/templates/claude-managed-content.md.
#
#          That file's own manifest HTML comment is NOT part of the resident
#          payload - it documents the file, it is never written into any
#          session's CLAUDE.md. Measuring the whole file (manifest included)
#          was tried and is wrong: the manifest is the majority of the file's
#          bytes, so a THRESHOLD sized off the whole file lets the real
#          payload balloon while the gate stays green, and a naive
#          plausibility floor never fires on the realistic regression (delete
#          the table, keep the manifest - file size barely changes). This
#          script measures only the body AFTER the closing `-->` of the
#          manifest comment.
#
# Public API: bash scripts/check-resident-budget.sh
#             Exits 0 when body bytes <= THRESHOLD. Exits 1 when over
#             budget, when the input file is missing, or when the
#             plausibility floor fires (see Failure modes below).
#
# Upstream deps: content/templates/claude-managed-content.md; python3 (used
#                for a deterministic byte-offset search of the manifest
#                comment terminator); scripts/lib/budget-gate.sh (shared
#                repo-dir resolution, byte measurement, and OK/OVER-BUDGET
#                report shape - see that file for the two sibling gates it
#                also backs).
#
# Downstream consumers: .github/workflows/resident-budget.yml.
#
# Failure modes: over budget -> exit 1 with byte count, threshold, and
#                overage printed. Body below MIN_PLAUSIBLE_BODY_BYTES -> exit
#                1 with a message that distinguishes "file gutted/manifest
#                left behind" from "budget overage" (these are different
#                classes of defect and get different remediation). Missing
#                comment terminator (`-->`) -> exit 1, since that means the
#                file no longer has the expected manifest/body split at all.
#                Missing input file -> exit 1. Read-only; no side effects on
#                the repo.
#
# Compatible with both bash and zsh invocation of the containing shell; CI
# always invokes it as `bash scripts/check-resident-budget.sh`, but a
# contributor, reviewer, or this file's own regression test may invoke it
# as `zsh scripts/check-resident-budget.sh` and it must behave identically.

set -euo pipefail

# BASH_SOURCE is unset under zsh. CI always invokes this script as `bash
# scripts/check-resident-budget.sh` (see resident-budget.yml), but a
# contributor or reviewer may run it under zsh locally - fall back to $0 so
# SCRIPT_DIR resolves correctly under both interpreters instead of
# collapsing to "//".
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib/budget-gate.sh
source "$SCRIPT_DIR/lib/budget-gate.sh"
REPO_DIR="$(budget_repo_dir "$SCRIPT_DIR")"

# Ratchet: 401 B measured for the post-manifest body on this branch
# 2026-08-07 (DS-143 - the Skill Loading table is the sole remaining
# resident payload after the trigger-loaded methodology change) + roughly
# 50% headroom on a fixed 7-line table. Lower this value in the same commit
# as any deliberate shrink of the resident table. See the header comment
# above before raising it.
THRESHOLD=600

# Plausibility floor: if the manifest comment ever swallows the whole file
# (e.g. someone deletes the Skill Loading table but leaves the manifest),
# body_bytes would be near-zero and the check would PASS with false
# headroom. 100 B is comfortably below the real ~400 B payload but far above
# "empty" - it can only fire on a gutted file, never on correct content.
MIN_PLAUSIBLE_BODY_BYTES=100

MANAGED_CONTENT_FILE="$REPO_DIR/content/templates/claude-managed-content.md"

if [ ! -f "$MANAGED_CONTENT_FILE" ]; then
  echo "check-resident-budget.sh: missing file: $MANAGED_CONTENT_FILE" >&2
  exit 1
fi

file_bytes="$(budget_file_bytes "$MANAGED_CONTENT_FILE")"

# Locate the byte offset of the manifest comment's closing "-->" and measure
# only what follows it. Using python3 for a single deterministic byte-offset
# search rather than shell string ops, which do not reliably handle
# multi-line HTML comments across bash/zsh.
comment_end_offset="$(python3 -c "
import sys
data = open(sys.argv[1], 'rb').read()
idx = data.find(b'-->')
if idx == -1:
    sys.exit(1)
sys.stdout.write(str(idx + 3))
" "$MANAGED_CONTENT_FILE")" || comment_end_offset=""

if [ -z "$comment_end_offset" ]; then
  echo "check-resident-budget.sh: could not find manifest comment terminator" >&2
  echo "  ('-->') in $MANAGED_CONTENT_FILE. Expected a leading HTML comment" >&2
  echo "  manifest followed by the resident body; the file's shape has" >&2
  echo "  changed and this script's measurement no longer applies." >&2
  exit 1
fi

body_bytes=$(( file_bytes - comment_end_offset ))

if [ "$body_bytes" -lt "$MIN_PLAUSIBLE_BODY_BYTES" ]; then
  echo "check-resident-budget.sh: BODY FAILURE, not a budget problem." >&2
  echo "  The measured post-manifest body is only $body_bytes B," >&2
  echo "  below the $MIN_PLAUSIBLE_BODY_BYTES B plausibility floor." >&2
  echo "  This means the resident content has been gutted (or the manifest" >&2
  echo "  comment now swallows the whole file) - it does NOT mean the" >&2
  echo "  resident set is under budget. Investigate" >&2
  echo "  content/templates/claude-managed-content.md directly; do not" >&2
  echo "  raise THRESHOLD or lower this floor to make this pass." >&2
  exit 1
fi

remediation="The always-loaded resident set grew past its budget.
Trim content or, if the growth is deliberate and justified, raise
THRESHOLD in scripts/check-resident-budget.sh in the same PR."

budget_report \
  "resident budget check" \
  "claude-managed-content.md (body only)" \
  "$body_bytes" \
  "$THRESHOLD" \
  "$remediation" \
  "file total (incl. manifest):           $file_bytes B"
