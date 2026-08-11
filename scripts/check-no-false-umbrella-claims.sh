#!/usr/bin/env bash
# Purpose: Fail on prose asserting the SHAPE of a claim that has been false,
#          in some paraphrase, three separate times (round 1/2/3 of
#          fix/shipped-gitignore-umbrella-gaps) since /ds-init-project Step 9
#          was inverted from a hand-copied, targeted `.gitignore` denylist to
#          a default-deny `.agentic/*` umbrella delegated to `ds-migrate
#          apply` (content/project-scaffolding.yml). Three independent manual
#          sweeps each found sites the next round found - a fourth manual
#          sweep is not a fix. This is a literal-shape RE-INTRODUCTION
#          guard, not a semantic one: it blocks the known-false wordings
#          (and close paraphrases of them) from silently returning via a
#          revert or a stale copy-paste. It is NOT exhaustive against novel
#          paraphrases of the same false claim - a fresh wording that
#          doesn't match one of the patterns below will still pass this
#          gate. Do not widen it chasing every possible paraphrase; that
#          produces false positives instead. An honest narrow gate beats an
#          overclaiming one.
#
# What it catches (the FIVE live sites found in round 4, generalized to a
# pattern rather than five literal strings, so a close paraphrase is caught
# too; widened in round 5 after four more same-meaning paraphrases survived
# the round-4 patterns unscathed - "the scoped .gitignore block from Step 9",
# "Step 9's own gitignore block", "a targeted gitignore denylist block", and
# "a targeted DENYLIST" - none of which matched because the round-4 patterns
# required adjacent words ("own block", "targeted denylist") rather than
# allowing intervening words, and matched only lowercase "denylist"):
#   1. "targeted .gitignore block" / "targeted `.gitignore` block" / "scoped
#      .gitignore block" (with or without intervening words, e.g. "the
#      scoped .gitignore block from Step 9") - Step 9 no longer produces one;
#      it delegates to a default-deny umbrella.
#   2. "targeted denylist" / "targeted ... denylist block" (any case,
#      allowing intervening words, e.g. "a targeted gitignore denylist
#      block" or "a targeted DENYLIST") - same stale shape, describing
#      Step 9's CURRENT gitignore output rather than its pre-inversion
#      history.
#   3. "Step 9's own block" / "this Step's own block" / "Step 9's own
#      gitignore block" (allowing intervening words between "own" and
#      "block") - a self-reference to a hand-copied enumeration block inside
#      Step 9 that no longer exists.
#   4. The specific dangling forward/backward-references introduced and
#      caught in round 4: "`.agentic/.activated` line above" (no such line
#      exists) and "see the drift test below" (no such test exists in that
#      file).
#
# Public API: bash scripts/check-no-false-umbrella-claims.sh
#             Exits 0 if clean, 1 if any forbidden phrase is found outside an
#             allow-listed line.
#
# Allow-listing a legitimate occurrence: append `<!-- false-umbrella-claim-ok
# -->` to the same line (e.g. a historical/explanatory sentence that
# correctly describes the PRE-inversion shape as history, not as Step 9's
# current behavior). Use sparingly and only after confirming the sentence is
# true.
#
# Upstream deps: grep -E (POSIX extended regex, portable across the
#                GNU/BSD grep this repo's CI and local dev machines run).
#
# Downstream consumers: .github/workflows/no-false-umbrella-claims.yml
#                        (wired as its own job).
#
# Failure modes: a forbidden phrase found in content/, bin/, docs/, or
#                README.md and not allow-listed on that line -> exit 1,
#                listing every offending file:line.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Extended-regex alternation, one pattern per finding shape above. Kept as
# separate `-e` clauses (not one giant alternation) so a future addition is a
# one-line diff and the failure message below can name which shape matched.
# Case-sensitivity per pattern: most patterns below are matched with `grep
# -i` (case-insensitive) since round 5 found an uppercase "DENYLIST"
# paraphrase the round-4 lowercase-only pattern missed, and there is no
# legitimate reason for "targeted"/"scoped"/"denylist"/"block" to appear
# case-varied in prose describing this specific stale claim. The two
# dangling-reference patterns stay literal (no case variance expected in
# those specific phrases) but are run through the same `-i` pass for
# uniformity - reviewed for false positives below.
PATTERNS=(
  'targeted[^.]{0,2}\.?gitignore[^.]{0,2}block'
  'scoped[^.]{0,2}\.?gitignore[^.]{0,2}block'
  'targeted[[:space:]].{0,25}denylist'
  "Step 9['’]?s own.{0,25}block"
  "this Step['’]?s own.{0,25}block"
  '\.activated. line above'
  'see the drift test below'
)

SCAN_PATHS=(content bin docs README.md AGENTS.md CONTRIBUTING.md hooks scripts)

# A typo'd or later-removed scan path makes `grep -r` scan nothing for it,
# silently - the gate would stay green having asserted less than it claims.
# Hard-fail up front instead of letting that pass unnoticed.
for scan_path in "${SCAN_PATHS[@]}"; do
  if [ ! -e "$scan_path" ]; then
    echo "ERROR: SCAN_PATHS entry '$scan_path' does not exist - fix the path" >&2
    exit 1
  fi
done

fail=0
for pattern in "${PATTERNS[@]}"; do
  # -I: skip binary files. -n: line numbers. -i: case-insensitive (see note
  # above - round 5 widened from case-sensitive after an uppercase
  # "DENYLIST" paraphrase was found).
  matches="$(grep -rnI -i -E "$pattern" "${SCAN_PATHS[@]}" 2>/dev/null | grep -v -- '<!-- false-umbrella-claim-ok -->' || true)"
  # Exclude this script's own pattern definitions, and its regression test's
  # deliberate mutation fixtures, from matching themselves.
  matches="$(echo "$matches" | grep -v -e '^scripts/check-no-false-umbrella-claims.sh:' -e '^bin/tests/test_check_no_false_umbrella_claims.sh:' || true)"
  if [ -n "$matches" ]; then
    echo "::error::check-no-false-umbrella-claims: forbidden phrase pattern matched: $pattern" >&2
    echo "$matches" >&2
    fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  echo "One or more files assert a stale claim about /ds-init-project Step 9's" >&2
  echo ".gitignore output (a hand-copied targeted block/denylist, a specific" >&2
  echo "'Step 9's own block' location, or a dangling cross-reference to a line" >&2
  echo "or test that does not exist). Step 9 delegates to a default-deny" >&2
  echo "'.agentic/*' umbrella via 'ds-migrate apply' as of round 3 - see" >&2
  echo "content/project-scaffolding.yml. Fix the prose (prefer deletion over a" >&2
  echo "narrowed rewrite - see root MEMORY.md), or allow-list a genuinely" >&2
  echo "historical/explanatory sentence with a trailing" >&2
  echo "'<!-- false-umbrella-claim-ok -->' marker on the same line." >&2
  exit 1
fi

echo "OK: no false umbrella-claim phrases found."
exit 0
