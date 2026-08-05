#!/usr/bin/env bash
# Purpose: Static regression tripwire for DS-135 - guards against the
#          reintroduction of the O(n^2) accumulate-in-loop pattern that was
#          used to build `body_content` in `.gemini/build.sh` and
#          `.codex/build.sh`. The fix replaced a per-line string
#          concatenation loop (quadratic in the number of body lines) with a
#          single `"${body_lines[*]}"` IFS join (linear). This test is
#          deliberately static rather than timing-based: the `bin-sh-tests`
#          CI job runs under `timeout-minutes: 5` with only 3-63 seconds of
#          measured headroom, and `.codex/build.sh` alone takes roughly 31s
#          to run, so a wall-clock timing assertion here would risk killing
#          the entire job with no diagnostic on a slow runner.
#
# Public API: ./bin/tests/test_no_quadratic_body_join.sh
#             Exits 0 (PASS) when neither build script contains the
#             quadratic accumulate-in-loop pattern; exits 1 (FAIL) and
#             prints which file(s) still contain it otherwise.
#
# Upstream deps: bash, grep. No network, no external state.
#
# Downstream consumers: developer running locally before commit; CI
#                        (bin-sh-tests.yml auto-discovers bin/tests/test_*.sh).
#
# Failure modes: `.gemini/build.sh` or `.codex/build.sh` reintroduces the
#                `body_content="$body_content` concatenation pattern -> FAIL
#                naming the offending file(s).
set -euo pipefail

FAIL=0
for f in .gemini/build.sh .codex/build.sh; do
  if grep -n 'body_content="\$body_content' "$f" >/dev/null 2>&1; then
    echo "FAIL: $f contains the O(n^2) accumulate-in-loop pattern" >&2
    FAIL=1
  fi
done
[[ $FAIL -eq 0 ]] && echo "PASS: no quadratic accumulate-in-loop pattern found."
exit $FAIL
