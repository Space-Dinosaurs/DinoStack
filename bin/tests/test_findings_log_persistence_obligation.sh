#!/usr/bin/env bash
# Purpose: Pin three properties of the findings_log data-loss fix (the
#          "Phase 12's status:'complete' write used to be a full-file
#          overwrite that silently destroyed findings_log" defect and its
#          repair) that no existing gate mechanically enforces:
#            1. Phase 12's `findings_log` persistence paragraph is stated as
#               a NORMATIVE, read-modify-write requirement covering every
#               other `loop_state` field - not merely a description of what
#               the current implementation happens to do.
#            2. Step 2's `findings_log` update is framed as a durable
#               RECORD (log every finding, every severity, including
#               all-Minor/sign-off rounds) - not a loop-continuation
#               scratchpad that could be safely thrown away.
#            3. No instruction anywhere in content/ licenses DELETING or
#               otherwise clearing a keyed loop-state file's findings_log as
#               part of normal Phase 12 completion - the exact license this
#               fix removed ("Set to status:'complete' or deleted after the
#               PR is opened").
#
#          Each assertion below is something a grep can honestly prove -
#          presence/absence of an identifier, phrase, or negated pattern -
#          not a restatement of the prose. Per this repo's regression-test
#          obligation, every assertion below has a paired reddening mutation
#          demonstrated at review time (see the PR/commit that introduced
#          this file for the exact `sed`/`python3` mutation and its FAIL
#          output); this file only encodes the resulting pass/fail check.
#
# Public API: none (executable test). Run with:
#             bash bin/tests/test_findings_log_persistence_obligation.sh
#
# Upstream deps: bash 3.2+, grep. Read-only - asserts against the tracked
#                canonical source files, writes nothing.
#
# Downstream consumers: the `bin-sh-tests` CI job (.github/workflows/bin-tests.yml,
#                        `files=(bin/tests/test_*.sh)`), which glob-discovers
#                        this file - no separate CI wiring needed. Also run
#                        by `bash scripts/check-local.sh` via its
#                        `list_bin_sh_tests` glob-discovery helper.
#
# Failure modes: this file runs `set -uo pipefail` WITHOUT -e (matching its
#                siblings bin/tests/test_wrap_knowledge_commit.sh and
#                bin/tests/test_loop_state_site_coverage.sh), so the exit
#                code is derived from the FAIL counter, never from the last
#                command's status. Every verdict routes through _pass/_fail
#                so a real miss cannot silently report "0 failed".
#
# Performance: < 1 s wall time (a handful of grep passes, no network).
#
# Retirement: this suite pins PROSE, not runtime behavior - it would have
#             caught the exact regression it was written against (a stale
#             review, doc edit, or slide-deck restatement silently
#             reintroducing the "status:'complete' or deleted" data-loss
#             license, or softening Phase 12's read-modify-write MUST back
#             to a bare description) before it reached a merged PR. It
#             retires only if Phase 12's `findings_log` persistence becomes
#             mechanically enforced at write time (e.g. a hook or script
#             that rejects a non-read-modify-write `loop_state` write) so
#             this prose pin becomes redundant with a stronger runtime
#             check, or if Phase 12's completion write is redesigned away
#             from the `status: "complete"` shape this suite keys on. Absent
#             either, this is a permanent floor - the underlying failure
#             (silent prose drift with no other gate watching it) does not
#             go away on its own.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR" || exit 1

IMPLEMENT_TICKET=content/commands/ds-implement-ticket.md

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

echo "--- findings_log persistence obligation ---"

# 1a. Phase 12's persistence paragraph must exist, and must be phrased as a
#     normative MUST covering "every other" loop_state field - not a bare
#     description. Mutation that reddens this: rewording "MUST be
#     read-modify-write, preserving every other `loop_state` field" down to
#     something like "is read-modify-write" (removes the normative MUST and
#     the every-other-field scope) makes this grep fail.
if grep -qF 'MUST be read-modify-write, preserving every other `loop_state` field' "$IMPLEMENT_TICKET"; then
  _pass "Phase 12 persistence paragraph states the read-modify-write requirement normatively (MUST), scoped to every other loop_state field"
else
  _fail "Phase 12 persistence paragraph no longer states the read-modify-write requirement as a normative MUST covering every other loop_state field - $IMPLEMENT_TICKET may have regressed to a descriptive-only claim, which a future implementation change could silently violate."
fi

# 1b. The paragraph must also spell out the destructive counter-example
#     (an emit-only-status write) so the obligation is falsifiable, not just
#     asserted. Mutation: deleting the counter-example clause reddens this.
if grep -qF 'a write that emits only `{"status":"complete"}` violates this step and destroys the log' "$IMPLEMENT_TICKET"; then
  _pass "Phase 12 persistence paragraph names the specific violating write shape"
else
  _fail "Phase 12 persistence paragraph no longer names the specific violating write shape ({\"status\":\"complete\"} emit-only) - the obligation is no longer falsifiable against a concrete counter-example."
fi

# 2. Step 2's findings_log update must be framed as a durable record, not a
#    loop-continuation scratchpad. Mutation: reverting to the pre-fix
#    wording "Update `findings_log`:" with no durable-record parenthetical
#    reddens this.
if grep -qF 'Update `findings_log` (durable record - log every finding, every severity, including all-Minor/sign-off rounds)' "$IMPLEMENT_TICKET"; then
  _pass "Step 2 frames the findings_log update as a durable record covering every severity and all-Minor/sign-off rounds"
else
  _fail "Step 2 no longer frames the findings_log update as a durable record - $IMPLEMENT_TICKET may have regressed to treating findings_log as disposable loop-continuation state."
fi

# 3. No instruction anywhere in content/ may license deleting or clearing a
#    keyed loop-state file's findings_log as part of normal completion. This
#    is a negative sweep with a control probe: the control MUST match (a
#    real, intentional deletion instruction exists elsewhere in the file,
#    for the operator's own fresh-start prompt at Resume check), so a
#    silent-zero from a broken pattern is distinguishable from a genuinely
#    clean sweep. Mutation: restoring the removed slide-deck license text
#    ("Set to `status: \"complete\"` or deleted after the PR is opened.")
#    anywhere under content/ or docs/ reddens the swept assertion below.
CONTROL_HIT=$(grep -c "delete \*\*only\*\* \`.agentic/loop-state-\$LOOP_KEY.json\`" "$IMPLEMENT_TICKET" || true)
if [ "$CONTROL_HIT" -ge 1 ]; then
  _pass "control probe matched (operator fresh-start deletion instruction is present, confirming the sweep pattern is not silently vacuous)"
else
  _fail "control probe found 0 matches for the known operator fresh-start deletion instruction - the sweep pattern below cannot be trusted to detect a real hit, because it cannot be distinguished from an unrelated wording drift in the control instruction itself."
fi

# The pattern deliberately requires "or deleted/dropped/removed" to
# IMMEDIATELY follow the status:"complete" literal (with only optional
# whitespace, a trailing </code> tag, or a closing markdown backtick between
# them) - not merely to co-occur anywhere before the next period. A looser
# co-occurrence pattern (tried first while writing this test) false-positived
# on the fix's own correct replacement wording ("...preserved, never cleared
# or deleted"), because "never" and "deleted" both appear before the same
# sentence-ending period as "complete". Requiring immediate adjacency to "or"
# is what distinguishes the license from a negation of it. The closing-
# backtick alternative is required because the exact license this fix
# removed was phrased as inline markdown code (`` `status: "complete"` or
# deleted ``, content/references/cross-session-loop-resume.md:79 pre-fix) -
# a pattern covering only the HTML <code> form is blind to that shape.
LICENSE_PATTERN='status: "complete"(</code>|`)?[[:space:]]+(or|OR)[[:space:]]+(deleted|dropped|removed)'
LICENSE_HITS=$(grep -rlE "$LICENSE_PATTERN" content/ docs/*.md docs/slides/*.md README.md CONTRIBUTING.md 2>/dev/null | wc -l | tr -d ' ')
if [ "$LICENSE_HITS" -eq 0 ]; then
  _pass "no tracked prose licenses deleting/dropping/removing a loop-state file as an alternative to the status:complete write (count=0)"
else
  _fail "$LICENSE_HITS file(s) still license deleting/dropping/removing a loop-state file as an alternative to the status:complete write - the data-loss license this fix removed has resurfaced. Run: grep -rlE '$LICENSE_PATTERN' content/ docs/*.md docs/slides/*.md README.md CONTRIBUTING.md"
fi

echo ""
echo "$PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
