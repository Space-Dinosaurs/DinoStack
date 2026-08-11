#!/usr/bin/env bash
# Purpose: Fail on prose asserting the SHAPE of a claim that has been false,
#          in some paraphrase, three separate times (round 1/2/3 of
#          fix/shipped-gitignore-umbrella-gaps) since /ds-init-project Step 9
#          was inverted from a hand-copied, targeted `.gitignore` denylist to
#          a default-deny `.agentic/*` umbrella delegated to `ds-migrate
#          apply` (content/project-scaffolding.yml). Three independent manual
#          sweeps each found sites the next round found - a fourth manual
#          sweep is not a fix; this makes the recurring claim shape
#          mechanically unrepresentable instead.
#
# What it catches (the FIVE live sites found in round 4, generalized to a
# pattern rather than five literal strings, so a close paraphrase is caught
# too):
#   1. "targeted .gitignore block" / "targeted `.gitignore` block" - Step 9
#      no longer produces one; it delegates to a default-deny umbrella.
#   2. "targeted denylist" - same stale shape, describing Step 9's CURRENT
#      gitignore output rather than its pre-inversion history.
#   3. "Step 9's own block" / "this Step's own block" - a self-reference to a
#      hand-copied enumeration block inside Step 9 that no longer exists.
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
# Downstream consumers: .github/workflows/no-planning-docs.yml sibling
#                        (wired as its own job - see
#                        .github/workflows/no-false-umbrella-claims.yml).
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
PATTERNS=(
  'targeted[^.]{0,2}\.?gitignore[^.]{0,2}block'
  'targeted denylist'
  "Step 9['’]?s own block"
  "this Step['’]?s own block"
  '\.activated. line above'
  'see the drift test below'
)

SCAN_PATHS=(content bin docs README.md)

fail=0
for pattern in "${PATTERNS[@]}"; do
  # -I: skip binary files. -n: line numbers. Case-sensitive by design (the
  # five known sites are all lowercase/mixed-case as written; loosen with -i
  # only if a future paraphrase needs it, after checking for new FPs).
  matches="$(grep -rnI -E "$pattern" "${SCAN_PATHS[@]}" 2>/dev/null | grep -v -- '<!-- false-umbrella-claim-ok -->' || true)"
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
