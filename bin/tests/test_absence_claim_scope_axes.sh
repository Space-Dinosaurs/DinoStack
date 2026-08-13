#!/usr/bin/env bash
# Purpose: Pin the three scope axes named by the "Skeptic absence-or-critical
#          findings require conductor verification before action" rule in
#          content/sections/02-delegation.md, so a future compression back to
#          a single axis (the exact drift observed mid-ticket on DS-114, where
#          "case variants and paraphrases" silently vanished with no gate
#          objecting) fails loudly instead of passing every existing check.
#
#          Each axis closes a distinct motivating failure and is asserted
#          INDIVIDUALLY, with its own failure message naming which axis is
#          missing and why it exists - a single combined assertion would tell
#          a future reader only that "something" broke, not which axis to
#          restore:
#            - "the pattern"    - covers a token-scoped or case-sensitive grep
#                                 that misses a semantic variant of the term
#                                 being searched for.
#            - "the file set"   - covers a search confined to one file (or too
#                                 few files) that misses a restatement of the
#                                 same rule living elsewhere in the tree.
#            - "any closed list" - covers an enumerated vocabulary certified
#                                 complete when a legitimate value is missing
#                                 from it; no amount of widening the pattern or
#                                 the file set answers a completeness question
#                                 about a closed list. This axis is no longer
#                                 method-less (DS-113): the clause now names
#                                 the method (derive the population
#                                 independently and diff against the list) and
#                                 points at a worked example, both pinned below.
#
#          A second gate confirms the pre-existing freshness half of the same
#          rule (the reason the rule exists in the first place - stale git
#          state producing a false absence claim) has not been silently
#          dropped alongside a future edit to the scope-axis clause.
#
# Public API: none (executable test). Run with:
#             bash bin/tests/test_absence_claim_scope_axes.sh
#
# Upstream deps: bash 3.2+, grep. Read-only - asserts against the tracked
#                canonical source file, writes nothing.
#
# Downstream consumers: the `bin-sh-tests` CI job (.github/workflows/bin-tests.yml,
#                        `files=(bin/tests/test_*.sh)`), which glob-discovers
#                        this file - no separate CI wiring needed.
#
# Failure modes: this file runs `set -uo pipefail` WITHOUT -e (matching its
#                sibling bin/tests/test_loop_state_site_coverage.sh), so the
#                exit code is derived from the FAIL counter, never from the
#                last command's status. Every verdict below routes through
#                _pass/_fail so a real miss cannot silently report "0 failed".
#
# Performance: < 1 s wall time (a handful of `grep -c` passes, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR" || exit 1

FILE=content/sections/02-delegation.md

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

echo "--- absence-claim scope axes (content/sections/02-delegation.md) ---"

# Axis 1: the pattern (token/case narrowness).
if grep -qF 'broaden the pattern' "$FILE"; then
  _pass "axis 'the pattern' present"
else
  _fail "AXIS MISSING: 'the pattern' not found in $FILE - this axis covers a token-scoped or case-sensitive grep that misses a semantic variant of the term being searched for. Restore it; do not compress the remedy clause back to a single axis."
fi

# Axis 2: the file set (search confined to too few files).
if grep -qF 'the file set' "$FILE"; then
  _pass "axis 'the file set' present"
else
  _fail "AXIS MISSING: 'the file set' not found in $FILE - this axis covers a search confined to one file (or too few files) that misses a restatement of the same rule living elsewhere in the tree. Restore it; do not compress the remedy clause back to a single axis."
fi

# Axis 3: any closed list (enumeration completeness).
if grep -qF 'any closed list' "$FILE"; then
  _pass "axis 'any closed list' present"
else
  _fail "AXIS MISSING: 'any closed list' not found in $FILE - this axis covers an enumerated vocabulary certified complete when a legitimate value is missing from it; no amount of widening the pattern or the file set answers a completeness question about a closed list. Restore it; do not compress the remedy clause back to a single axis."
fi

# Freshness half: confirm the pre-existing rule this clause extends is still
# present, byte-for-byte on its closing sentence, and was not dropped or
# rewritten alongside a future edit to the scope-axis clause.
if grep -qF 'is not a substitute for verifying falsifiable claims before acting on them.' "$FILE"; then
  _pass "freshness half present (closing sentence intact)"
else
  _fail "FRESHNESS HALF MISSING: the closing sentence of the pre-existing freshness rule ('...is not a substitute for verifying falsifiable claims before acting on them.') was not found in $FILE. That half addresses stale git state producing a false absence claim and must survive any edit to the adjacent scope-axis clause."
fi

# Axis 3 method (DS-113 item 5): closed-list broadening now names a method,
# not just the axis. A membership grep against the list's own current
# members can only confirm what is already there - it can never surface the
# one legitimate value that is missing from it.
if grep -qF 'deriving its members independently and diffing against it' "$FILE"; then
  _pass "closed-list method present (item 5)"
else
  _fail "METHOD MISSING: 'deriving its members independently and diffing against it' not found in $FILE - item 5 requires the closed-list axis to name a method, not just the axis. A membership grep against the list's own current members can only confirm them; it cannot answer a completeness question about the list, which is exactly the DS-98 failure mode this method exists to prevent."
fi

# Worked-example pointer (dangling-pointer guard): the clause's pointer and
# the target heading it points at must both be live, or the pointer rots
# silently the next time either file is edited.
if grep -qF '§Absence-claim scope axes' "$FILE"; then
  _pass "worked-example pointer present in $FILE"
else
  _fail "POINTER MISSING: '§Absence-claim scope axes' not found in $FILE - the closed-list method needs a worked example pointer, or the method reads as unmotivated prose."
fi

if grep -qF '## Absence-claim scope axes' content/references/delegation-detail.md; then
  _pass "worked-example heading present in content/references/delegation-detail.md"
else
  _fail "HEADING MISSING: '## Absence-claim scope axes' not found in content/references/delegation-detail.md - the pointer in $FILE now dangles; restore the target section or update the pointer."
fi

# Manifest-completeness guard (DS-169 round-2): every "## " section heading in
# delegation-detail.md must be covered by the header "Contains:" list, so a
# future section addition without a manifest update fails loudly. The exact
# drift this guards: db8a6703 added "## Capability-unavailability scope axes"
# with no manifest entry, and only a4595255 (post-Skeptic) added it - the
# sibling heading-presence pin above could not catch that because it only
# names the one heading it guards. A completeness check is the only shape
# that catches an arbitrary new section. The manifest is a prose summary (a
# wrapped, semicolon-delimited paragraph), not a 1:1 index - e.g. the
# "Open Questions and Deferred Defaults" heading maps to the entry "Open
# Questions / Deferred Defaults bucketing rules" - so the comparison is
# word-level: every significant word (length > 3) of each heading must appear
# in the normalized Contains text. A heading whose title words appear NOWHERE
# in the list is an omitted section, exactly the db8a6703 class.
DETAIL_REF=content/references/delegation-detail.md
CONTAINS_TEXT="$(awk '/Contains:/{f=1} /^Public API:/{f=0} f' "$DETAIL_REF")"
norm_manifest="$(printf '%s' "$CONTAINS_TEXT" | tr '[:upper:]' '[:lower:]' | tr '\n' ' ' | sed -E 's/[^a-z0-9]+/ /g')"

# Explicit pin for the DS-169 section (mirrors the sibling heading pin above,
# but on the manifest side): the entry that a4595255 added must stay live.
if printf '%s' "$CONTAINS_TEXT" | grep -qF 'Capability-unavailability scope axes'; then
  _pass "manifest entry for '## Capability-unavailability scope axes' present in Contains list"
else
  _fail "MANIFEST MISSING: 'Capability-unavailability scope axes' not found in the Contains: header list of $DETAIL_REF - a section was added without a manifest entry. Add it to the 'Contains:' list, matching the sibling 'Absence-claim scope axes' entry style."
fi

while IFS= read -r heading; do
  h="${heading#\#\# }"
  norm_h="$(printf '%s' "$h" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/ /g')"
  # Documented exclusion: "Follow-up Ticket Creation Discipline" predates the
  # Contains list and deliberately has no entry there; it is not a section
  # added without a manifest update, so it is the one heading the guard skips.
  if [ "$norm_h" = "follow up ticket creation discipline" ]; then
    _pass "heading '$h' is the documented Contains-list exclusion"
    continue
  fi
  missing=""
  for w in $norm_h; do
    [ "${#w}" -le 3 ] && continue
    case " $norm_manifest " in
      *" $w "*) ;;
      *) missing="$missing $w" ;;
    esac
  done
  if [ -z "$missing" ]; then
    _pass "heading '$h' covered by Contains list"
  else
    _fail "MANIFEST MISSING '$h': its significant words [$missing] appear nowhere in the Contains: header list of $DETAIL_REF - a section was added without a manifest entry. Add it to the 'Contains:' list, matching the sibling 'Absence-claim scope axes' entry style."
  fi
done < <(grep '^## ' "$DETAIL_REF")

echo
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
