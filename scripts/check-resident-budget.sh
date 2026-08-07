#!/usr/bin/env bash
# Purpose: Guard against unbounded growth of the "resident set" - the small
#          Skill Loading table that .claude/install.sh writes verbatim into
#          the managed-by-agentic-engineering block of ~/.claude/CLAUDE.md,
#          on every project, regardless of whether that project's task
#          needs the full methodology.
#
#          content/templates/claude-managed-content.md is the canonical
#          source of that table, but the installer does not read this file
#          today - it still carries the table text inline (a sibling unit
#          of DS-143 wires the installer to read this file instead; until
#          that lands, this gate bounds a copy that is not yet coupled to
#          what ships). The file opens with a manifest HTML comment
#          (Purpose/Public API/etc, delimited by <!-- ... -->) that never
#          ships to CLAUDE.md - only the body after the comment does. This
#          script measures that shipped body only, not the whole file: a
#          measurement that included the manifest comment could pass with
#          the entire table deleted, because the comment alone is larger
#          than the table. If the manifest comment is absent (removed or
#          reformatted), the whole file is treated as the body rather than
#          failing on an "empty" match - the split is best-effort, not a
#          hard requirement that the manifest exist.
#
#          A byte-count bound alone cannot detect content loss disguised as
#          same-size filler, so this script also asserts a stable,
#          content-bearing phrase from the table itself
#          (STABLE_CONTENT_PHRASE below) is present in the measured body.
#
#          As of this unit, .claude/install.sh still emits three separate
#          @-import lines (METHODOLOGY.md, content/rules/conventions.md,
#          content/rules/code-standards.md) into the managed block in
#          addition to this table - see .claude/install.sh around the
#          managed_content assembly. DS-143's plan is to remove those
#          @-imports and make that content trigger-loaded instead (via the
#          SKILL.md embed, budgeted separately by
#          scripts/check-skill-embed-budget.sh), but that removal has NOT
#          landed as of this commit - it is pending a sibling unit, not
#          accomplished fact.
#
#          This script sums the byte size of the shipped body of
#          content/templates/claude-managed-content.md and fails if it
#          exceeds THRESHOLD. THRESHOLD is a ratchet: when a compression PR
#          shrinks the resident set, lower THRESHOLD in the same PR so
#          growth cannot silently claw the savings back. Raising THRESHOLD
#          should be rare and deliberate - it is a decision to permanently
#          tax every session in every project with more always-loaded
#          context.
#
# Public API: bash scripts/check-resident-budget.sh
#             Exits 0 when body bytes <= THRESHOLD and the content
#             assertion passes. Exits 1 when over budget, when the input
#             file is missing, when the plausibility floor fires, or when
#             the content assertion fails (see Failure modes below).
#
# Upstream deps: content/templates/claude-managed-content.md.
#
# Downstream consumers: .github/workflows/resident-budget.yml.
#
# Failure modes: over budget -> exit 1 with a breakdown naming the file and
#                the numbers. Missing input file -> exit 1. Shipped body
#                emptied or implausibly small (< MIN_PLAUSIBLE_BYTES) -> exit
#                1 with a message that explicitly distinguishes a
#                vanished/gutted body from a budget overage - this catches
#                the "delete the table, keep the manifest comment"
#                regression that a whole-file measurement would miss.
#                Content assertion failure (STABLE_CONTENT_PHRASE absent
#                from the body) -> exit 1 with a distinct "table content
#                missing" message - this catches same-size content
#                replacement that a byte-count bound alone cannot see.
#                Read-only; no side effects on the repo.
#
# Compatible with both bash and zsh invocation of the containing shell; CI
# always invokes it as `bash scripts/check-resident-budget.sh`, but a
# contributor, reviewer, or this file's own regression test may invoke it
# as `zsh scripts/check-resident-budget.sh` and it must behave identically.

set -euo pipefail

# BASH_SOURCE is unset under zsh. CI always invokes this script as `bash
# scripts/check-resident-budget.sh` (see resident-budget.yml), but a
# contributor or reviewer may run it under zsh locally - fall back to $0 so
# REPO_DIR resolves correctly under both interpreters instead of collapsing
# to "//".
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# Ratchet: the shipped body of content/templates/claude-managed-content.md
# (everything after the manifest comment's closing "-->") measured 401 B on
# this branch 2026-08-07 (DS-143 fix pass 1, correcting a plan defect that
# measured the whole file, including the 1,305 B manifest comment that
# never ships). THRESHOLD is set to roughly 1.5x that measurement (600 B)
# to give headroom for the table to grow a line or two before this gate
# fires, while still catching runaway growth early. Lower this value in
# the same commit as any deliberate compression of the shipped body.
# See the header comment above before raising it.
THRESHOLD=600

# Plausibility floor: if the shipped body were ever gutted (the table
# deleted while the manifest comment remains, or the file truncated to
# just the comment), body_bytes would be near-zero and a whole-file
# measurement would still PASS on the strength of the comment alone. This
# floor is set to roughly a quarter of the live measured body (100 B) -
# comfortably below any realistic table content, but high enough to catch
# "manifest survives, payload gone."
MIN_PLAUSIBLE_BYTES=100

# Content assertion: a byte-count bound cannot tell real table content
# apart from same-size filler. This phrase is the skill-invocation cell of
# the Skill Loading table itself - content-bearing, not incidental
# formatting (not "##", not a table pipe) - and must survive any edit that
# keeps the table doing its job.
STABLE_CONTENT_PHRASE='/agentic-engineering'

MANAGED_CONTENT_FILE="$REPO_DIR/content/templates/claude-managed-content.md"

if [ ! -f "$MANAGED_CONTENT_FILE" ]; then
  echo "check-resident-budget.sh: missing file: $MANAGED_CONTENT_FILE" >&2
  exit 1
fi

# Measure only the shipped body - everything after the manifest comment's
# closing "-->", when a manifest comment is present. Split on the first
# occurrence of "-->" via awk's record separator and take the second
# record; write it to a temp file rather than a shell variable so trailing
# newlines are preserved exactly (a $(...) capture would strip them and
# shift the byte count). If no "-->" is found, treat the whole file as the
# body rather than failing on an empty match - the manifest comment is a
# convention, not a structural requirement of the shipped content.
body_file="$(mktemp)"
trap 'rm -f "$body_file"' EXIT

if grep -q -- '-->' "$MANAGED_CONTENT_FILE"; then
  awk 'BEGIN{RS="-->"} NR==2{printf "%s", $0; exit}' "$MANAGED_CONTENT_FILE" > "$body_file"
else
  cat "$MANAGED_CONTENT_FILE" > "$body_file"
fi

body_bytes="$(wc -c < "$body_file" | tr -d '[:space:]')"

if [ "$body_bytes" -lt "$MIN_PLAUSIBLE_BYTES" ]; then
  echo "check-resident-budget.sh: FILE FAILURE, not a budget problem." >&2
  echo "  The shipped body of" >&2
  echo "  content/templates/claude-managed-content.md (everything after the" >&2
  echo "  manifest comment's closing '-->', or the whole file if no" >&2
  echo "  manifest comment is present) is only $body_bytes B, below" >&2
  echo "  the $MIN_PLAUSIBLE_BYTES B plausibility floor. This means the" >&2
  echo "  table was emptied or truncated - it does NOT mean the resident" >&2
  echo "  set is under budget. Investigate" >&2
  echo "  content/templates/claude-managed-content.md directly; do not" >&2
  echo "  raise THRESHOLD or lower this floor to make this pass." >&2
  exit 1
fi

if ! grep -qF -- "$STABLE_CONTENT_PHRASE" "$body_file"; then
  echo "check-resident-budget.sh: TABLE CONTENT MISSING, not a budget problem." >&2
  echo "  The shipped body of" >&2
  echo "  content/templates/claude-managed-content.md is $body_bytes B (within" >&2
  echo "  bounds) but does not contain the expected phrase" >&2
  echo "  '$STABLE_CONTENT_PHRASE'. A byte-count bound alone cannot tell real" >&2
  echo "  table content apart from same-size filler - this means the Skill" >&2
  echo "  Loading table's content was replaced or corrupted, not just" >&2
  echo "  resized. Investigate content/templates/claude-managed-content.md" >&2
  echo "  directly." >&2
  exit 1
fi

total="$body_bytes"

if [ "$total" -le "$THRESHOLD" ]; then
  headroom=$(( THRESHOLD - total ))
  echo "resident budget check: OK"
  echo "  content/templates/claude-managed-content.md (shipped body): $body_bytes B"
  echo "  total:     $total B"
  echo "  threshold: $THRESHOLD B"
  echo "  headroom:  $headroom B"
  exit 0
fi

overage=$(( total - THRESHOLD ))
echo "resident budget check: OVER BUDGET" >&2
echo "  content/templates/claude-managed-content.md (shipped body): $body_bytes B" >&2
echo "  total:     $total B" >&2
echo "  threshold: $THRESHOLD B" >&2
echo "  overage:   $overage B" >&2
echo "" >&2
echo "The always-loaded resident set (the Skill Loading table's shipped" >&2
echo "body in content/templates/claude-managed-content.md) grew past its" >&2
echo "budget. Trim content or, if the growth is deliberate and justified," >&2
echo "raise THRESHOLD in scripts/check-resident-budget.sh in the same PR." >&2
exit 1
