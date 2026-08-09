#!/usr/bin/env bash
# Purpose: Mechanically enforce, on EVERY future commit rather than once at
#          review time, that per-ticket loop-state keying stays complete:
#            Gate C  - every file mentioning the loop-state path is accounted
#                      for in one of the three buckets (EDITED / ALLOWLIST /
#                      DEFERRED), failing in BOTH directions.
#            Gate W1 - every surviving path-literal line that performs an
#                      OPERATION on loop state names $LOOP_KEY.
#            Gate W2 - no PROSE-PHRASED loop-state write site survives
#                      unrepointed (the class that let the Phase 10a CI-loop
#                      writes through review, because they carry the referent
#                      but no path literal).
#            Gate W3 - the six Phase 7 referent-free write sites, which contain
#                      ZERO occurrences of "loop-state" and are invisible to
#                      both a path grep and a referent grep, name a keyed path.
#
#          FLOOR DESIGN - READ BEFORE TOUCHING A THRESHOLD.
#          A floor must be placed on a quantity the change does NOT reduce.
#          An earlier revision of this work floored on L1 (the count of bare
#          `.agentic/loop-state.json` literals) at >= 40. L1 is the exact
#          quantity per-ticket keying reduces - measured 66 before, ~12 after -
#          so a CORRECT implementation would fail this suite, this suite is a
#          required check, and the cheapest green would be to lower the floor,
#          deleting the anti-vacuity property the gate exists for. L1 is
#          therefore NOT floored here. The floors below sit on:
#            - L2, the REFERENT count, which repointing leaves stable or grows
#              (it swaps a filename and keeps the referent);
#            - a POSITIVE $LOOP_KEY floor, a count the change INCREASES - this
#              is the load-bearing one, because it is what makes blanket
#              exemption-marking unable to buy a green;
#            - a per-stage floor on EVERY post-filter, because a floor on a
#              stage-1 pattern says nothing about a vacuous stage-2 filter;
#            - a CAP on exemption markers, because appending `loop-key: legacy`
#              to every flagged line otherwise makes W1 fully green with zero
#              repointing.
#          If a floor fires, that is the signal. Do not retune it to get green.
#
#          PATTERN HAZARD: `git grep -E` does NOT support `\b`. Measured,
#          'to loop-state\b' matches 0 lines where 'to loop-state' matches 2.
#          A `\b` pattern is silently vacuous. NO PATTERN HERE USES `\b`.
#
#          BARE-GREP HAZARD: a bare `git grep` must never terminate an `&&`
#          chain or stand as a verdict - it asserts nothing on a hit and FAILS
#          when it finds nothing, so a clean document breaks the build and a
#          stale one passes. Every grep here writes to a file whose emptiness
#          is then tested, and every verdict routes through _pass/_fail.
#
# Public API: none (executable test). Run with:
#             bash bin/tests/test_loop_state_site_coverage.sh
#
# Upstream deps: bash 3.2+, git, grep. Read-only - runs `git grep` against the
#                working tree and writes only to a mktemp dir.
#
#                Gate C's left-hand lens is `git grep -l`, which sees TRACKED
#                files only. A newly created file must be `git add`-ed before
#                Gate C can account for it; an unstaged new file surfaces as a
#                "listed but no longer matching" failure.
#
# Downstream consumers: the `bin-sh-tests` CI job, which glob-discovers
#                       bin/tests/test_*.sh - no CI wiring needed.
#
# Failure modes: this file runs `set -uo pipefail` WITHOUT -e (matching its
#                sibling suites), so the exit code is derived from the FAIL
#                counter, never from the last command's status. A gate ending
#                in a bare `[ ... ]` would have its verdict DISCARDED and the
#                suite would print "0 failed" on a real miss - hence _pass and
#                _fail on every path.
#
# MAINTENANCE OBLIGATION (deliberate, stated so nobody reverse-engineers it):
#                because Gate C's accounted list lives in this file and this
#                file is a required check, that list is a PERMANENT repo-wide
#                invariant. Any future commit adding a `.agentic/loop-state.json`
#                mention anywhere under the seven scoped paths will fail here
#                until the list below is hand-edited. Whoever adds the mention
#                owns updating the list - the failure message says so. That is
#                the accepted cost of making the gate enforced rather than
#                one-shot. If the cost proves unacceptable, the correct change
#                is to scope Gate C to a one-shot pre-merge step, NOT to loosen
#                the list.
#
# Performance: < 3 s wall time (a dozen `git grep` passes, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR" || exit 1

FILE=content/commands/ds-implement-ticket.md

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Count matching LINES for a pattern, tolerating the zero-match exit status.
# `git grep -c` prints `<path>:<n>`; with no match it prints nothing and exits 1.
_count() { # _count <extra-git-grep-flags...> -- pattern
  local out
  out="$(git grep "$@" -- "$FILE" 2>/dev/null | cut -d: -f2)"
  [ -n "$out" ] || out=0
  printf '%s' "$out"
}

# Pool matching lines across the extracted-content split of $FILE. Gates W1,
# W2, and W3 scan for loop-state referents that used to live entirely inside
# content/commands/ds-implement-ticket.md but the progressive-disclosure
# split has been relocating phase bodies (batch-mode.md, open-goal-loop.md,
# orchestration-units.md, qa-loop-state.md, handoff-evaluation.md) into
# content/references/**. A gate body scanning `-- "$FILE"` alone goes blind
# to a loop-state referent line the moment its phase is extracted. This
# helper pools all six paths so W1/W2/W3 stay complete across the split.
# L2 / LOOP_KEY / MARKERS deliberately do NOT use this helper - see FLOOR
# DESIGN above; widening those floors would collapse per-file floors into a
# global sum, which bin/tests/test_tasks_jsonl_fold.sh forbids.
#
# ZSH HAZARD (see bin/tests/test_tasks_jsonl_fold.sh:64-68 for the sibling
# incident): a bash `for f in $FILES` on an unquoted word-split variable
# iterates correctly under bash but NOT under zsh, which does not
# word-split unquoted parameter expansions - the loop body then runs once
# on the whole multi-line string as a single (nonexistent) "path", `git
# grep` returns rc=1 for it, and `|| true` on the OUTER call swallows the
# failure, silently producing an EMPTY pooled file that gate bodies then
# read as "no hits" - a vacuous pass, not a loud failure. The heredoc `while
# read` loop below is immune: `read` always splits on IFS-delimited input
# lines regardless of shell, under both bash and zsh.
#
# Five of the six paths below do not exist yet on most branches - that is
# fine and deliberate: `git grep ... -- <missing path>` returns rc=1 with no
# output, so `|| true` makes every partial-merge state safe.
_pool_loop_state_files() { # $1=outfile, rest = git grep flags/pattern
  local outfile="$1"; shift
  : > "$outfile"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    git grep "$@" -- "$f" >> "$outfile" 2>/dev/null || true
  done <<'FILESPEC'
content/commands/ds-implement-ticket.md
content/references/batch-mode.md
content/references/open-goal-loop.md
content/references/orchestration-units.md
content/references/qa-loop-state.md
content/references/handoff-evaluation.md
FILESPEC
}

# ---------------------------------------------------------------------------
# Non-vacuity floors and the marker cap.
# ---------------------------------------------------------------------------
echo "--- floors and caps ---"

# L2 (referent) is floored because repointing does NOT reduce it. L1 is
# deliberately NOT floored - see FLOOR DESIGN in the manifest above.
L2="$(_count -ciE 'loop.?state')"
if [ "${L2:-0}" -ge 60 ]; then
  _pass "L2 floor: $L2 referent lines (>= 60)"
else
  _fail "FLOOR FAIL: L2=$L2 (<60) - the referent pattern is vacuous. Do NOT lower this floor; find out why the referent disappeared."
fi

# POSITIVE floor: the change must ADD keyed references. This is what makes
# blanket exemption-marking (see the cap below) unable to buy a green.
KEYED="$(_count -c 'LOOP_KEY')"
if [ "${KEYED:-0}" -ge 30 ]; then
  _pass "LOOP_KEY floor: $KEYED keyed references (>= 30)"
else
  _fail "FLOOR FAIL: only ${KEYED:-0} LOOP_KEY references (<30) - repointing did not happen. Repoint the sites; do NOT lower this floor."
fi

# MARKER CAP. Appending `loop-key: legacy` to every flagged line makes W1
# green with zero repointing. The cap makes blanket marking fail loudly.
# Raise it only with a named reason per line.
MARKERS="$(_count -c 'loop-key: ')"
if [ "${MARKERS:-0}" -le 15 ]; then
  _pass "marker cap: $MARKERS exemption markers (<= 15)"
else
  _fail "CAP FAIL: ${MARKERS} exemption markers (>15) - markers are silencing gates, not documenting exceptions. Repoint the sites instead."
fi

# ---------------------------------------------------------------------------
# Gate W1: every path-literal OPERATION line names $LOOP_KEY.
# ---------------------------------------------------------------------------
echo "--- Gate W1: path-literal operation sites ---"

# STAGE FLOOR on the verb post-filter, measured over the L2 (REFERENT) set,
# NOT over the L1 path-literal set. Flooring it on the verb-matching subset of
# L1 would be the same defect the manifest forbids: that subset is BY
# DEFINITION the operation lines not yet repointed, so it falls toward zero as
# the work completes, and its diagnostic ("post-filter is vacuous") would push
# an honest engineer to "fix" the pattern and silently disarm W1. L2 does not
# shrink under repointing, so the floor is safe in both directions.
#
# POOLED across the six extracted-content paths - see _pool_loop_state_files
# above. This is a gate BODY input, not the L2 floor itself (L2 stays scoped
# to $FILE only).
_pool_loop_state_files "$TMP/w1a" -niE 'loop.?state'
W1_STAGE2="$(grep -Eci 'overwrit|write|read|delete|rm -f|jq |atomic|set .?status' "$TMP/w1a" 2>/dev/null || true)"
[ -n "$W1_STAGE2" ] || W1_STAGE2=0
if [ "$W1_STAGE2" -ge 40 ]; then
  _pass "W1 stage floor: verb filter matched $W1_STAGE2 lines over the L2 set (>= 40)"
else
  _fail "FLOOR FAIL: W1 verb filter matched $W1_STAGE2 over the L2 set (<40) - post-filter is vacuous. Fix the pattern, do NOT lower the floor."
fi

# GATE BODY runs over L1 - only the FLOOR moved. W1's job is to prove every
# SURVIVING path literal on an operation line names $LOOP_KEY, and that
# question is only meaningful over lines that carry the literal. POOLED
# across the six extracted-content paths.
_pool_loop_state_files "$TMP/w1raw" -nE 'loop-state\.json'
grep -Ei 'overwrit|write|read|delete|rm -f|jq |atomic|set .?status' "$TMP/w1raw" 2>/dev/null \
  | grep -v 'LOOP_KEY' \
  | grep -v 'loop-key: legacy' > "$TMP/w1" 2>/dev/null || true
if [ -s "$TMP/w1" ]; then
  _fail "W1 FAIL - unrepointed path-literal operation site(s):"
  cat "$TMP/w1" >&2
else
  _pass "W1: no unrepointed path-literal operation site"
fi

# ---------------------------------------------------------------------------
# Gate W2: no PROSE-PHRASED write site survives.
# The gate whose absence let the Phase 10a CI-loop writes through review.
# ---------------------------------------------------------------------------
echo "--- Gate W2: prose-phrased sites ---"

# POOLED across the six extracted-content paths - see _pool_loop_state_files
# above. This is a gate BODY input, not one of the L2/LOOP_KEY/MARKERS floors.
_pool_loop_state_files "$TMP/w2a" -niE 'to loop-state|write loop-state|in loop-state|loop-state file'
W2_STAGE1="$(grep -c . "$TMP/w2a" 2>/dev/null || true)"
[ -n "$W2_STAGE1" ] || W2_STAGE1=0
if [ "${W2_STAGE1:-0}" -ge 3 ]; then
  _pass "W2 stage floor: prose pattern matched $W2_STAGE1 lines (>= 3)"
else
  _fail "FLOOR FAIL: W2 prose pattern matched ${W2_STAGE1:-0} (<3) - pattern is vacuous. Fix the pattern, do NOT lower the floor."
fi

_pool_loop_state_files "$TMP/w2raw" -nEi 'to loop-state|write loop-state|in loop-state|loop-state file'
grep -v 'loop-state\.json' "$TMP/w2raw" 2>/dev/null \
  | grep -v 'LOOP_KEY' \
  | grep -v 'loop-key: prose' > "$TMP/w2" 2>/dev/null || true
if [ -s "$TMP/w2" ]; then
  _fail "W2 FAIL - prose-phrased loop-state site(s) not repointed:"
  cat "$TMP/w2" >&2
else
  _pass "W2: no unrepointed prose-phrased loop-state site"
fi

# ---------------------------------------------------------------------------
# Gate W3: Phase 7 referent-free writes.
# These six lines contain ZERO occurrences of "loop-state" and are invisible
# to both the path-literal and referent lenses. W3 pins the exact string
# `last_phase=quality_gate`, so a routine rewording silently disarms it - the
# stage floor below is what makes that rewording fail loudly instead.
# ---------------------------------------------------------------------------
echo "--- Gate W3: Phase 7 referent-free writes ---"

# POOLED across the six extracted-content paths - see _pool_loop_state_files
# above. This is a gate BODY input, not one of the L2/LOOP_KEY/MARKERS floors.
_pool_loop_state_files "$TMP/w3a" -nE 'write .?last_phase=quality_gate|Write .?last_phase=quality_gate'
W3_HITS="$(grep -c . "$TMP/w3a" 2>/dev/null || true)"
[ -n "$W3_HITS" ] || W3_HITS=0
if [ "${W3_HITS:-0}" -ge 6 ]; then
  _pass "W3 stage floor: matched $W3_HITS Phase 7 sites (>= 6)"
else
  _fail "FLOOR FAIL: W3 matched ${W3_HITS:-0} Phase 7 sites (<6) - pattern disarmed by a rewording. Fix the pattern, do NOT lower the floor."
fi

_pool_loop_state_files "$TMP/w3raw" -nE 'write .?last_phase=quality_gate|Write .?last_phase=quality_gate'
grep -v 'LOOP_KEY' "$TMP/w3raw" 2>/dev/null > "$TMP/w3" || true
if [ -s "$TMP/w3" ]; then
  _fail "W3 FAIL - Phase 7 write site(s) with no keyed path:"
  cat "$TMP/w3" >&2
else
  _pass "W3: all Phase 7 referent-free write sites name a keyed path"
fi

# ---------------------------------------------------------------------------
# Gate C: per-unit completeness.
#
# Fails in BOTH directions: an unaccounted matching file, AND a listed path
# that no longer matches. Do NOT "fix" the second direction by switching to a
# one-way `comm -13` - that direction is exactly what catches the set drifting
# under you (a file silently losing its last mention, or a new file not yet
# `git add`-ed).
#
# The list is the FLAT UNION of all three buckets, with no inline comments -
# a `#` suffix would not match a bare path and would break the comparison. The
# per-file bucket membership and rationale live in the unit's plan prose, not
# here; Gate C only checks that every matching file is accounted for SOMEWHERE.
# That is a known, accepted limit: Gate C passes identically whether a file
# sits in EDITED, ALLOWLIST or DEFERRED, so bucket assignment is a review
# obligation, not a mechanical one.
#
# The 87 further matching files across adapter directories are deliberately
# EXCLUDED from the scope paths: they are generated from content/, adapter
# parity is proven separately by `check-adapter-sync`, and including them would
# double-count every source hit N times. `.opencode/plugins` IS in scope
# because .opencode/plugins/session-context.ts is hand-authored and regenerated
# by no build script. docs/_archive/ is excluded - archived artifacts are frozen.
# ---------------------------------------------------------------------------
echo "--- Gate C: completeness ---"

git grep -l 'loop-state\.json' \
    -- content hooks bin scripts docs README.md .opencode/plugins 2>/dev/null \
  | grep -v '^docs/_archive/' | sort > "$TMP/actual" || true

sort > "$TMP/accounted" <<'EOF'
hooks/lib/state-mark.js
hooks/stop-context.js
hooks/session-end-wrap.js
hooks/tests/test-state-mark.js
hooks/tests/test-state-mark-multikey.js
.opencode/plugins/session-context.ts
bin/ds-emit
bin/tests/test_agentic_emit_loop_key.sh
bin/tests/test_loop_key_derivation.sh
bin/tests/test_loop_state_site_coverage.sh
bin/tests/test_ticket_rework_ledger.sh
content/agents/learning-extractor.md
content/agents/learnings-agent.md
content/agents/wrap-ticket.md
content/commands/ds-implement-ticket.md
content/commands/ds-init-project.md
content/commands/ds-ticket-triage.md
content/commands/ds-wrap.md
content/references/conductor-operating-rules.md
content/references/cross-session-loop-resume.md
content/references/planning-artifacts.md
content/references/skeptic-protocol.md
content/references/subagent-protocol.md
content/references/trigger-catalog.md
content/sections/07-cross-session-loop-resume.md
docs/index.html
docs/secrets-and-permissions.md
docs/slides/cross-session-resume-slides.html
docs/slides/cross-session-resume-slides.md
docs/slides/how-it-works-slides.html
docs/slides/how-it-works-slides.md
docs/slides/planning-tier-slides.html
docs/slides/planning-tier-slides.md
docs/trigger-catalog.md
README.md
bin/tests/test_agentic_status.py
bin/tests/test_batch_state_timestamp_field.sh
content/references/delegation-detail.md
content/sections/02-delegation.md
docs/slides/worktree-lifecycle-slides.html
docs/slides/worktree-lifecycle-slides.md
hooks/tests/test-session-end-wrap-state-mark.js
hooks/tests/test-state-mark-legacy-active.js
hooks/tests/test-stop-context-cadence.js
hooks/tests/test-stop-context-session-log.js
content/sections/03-planning-artifacts.md
content/sections/09-events-log.md
docs/agentic-engineering-comparison.html
scripts/codex-skills.py
bin/tests/test_agentic_migrate.py
bin/tests/lib/git_fixture.py
EOF

diff "$TMP/actual" "$TMP/accounted" > "$TMP/gatec" 2>&1 || true
if [ -s "$TMP/gatec" ]; then
  _fail "GATE C FAIL - the loop-state file set has drifted from the accounted list."
  {
    echo "  '<' = matches but is NOT accounted for: add it to the list in $0."
    echo "  '>' = accounted for but no longer matches: it lost its last mention,"
    echo "        or it is a new file that has not been 'git add'-ed yet"
    echo "        (Gate C's left-hand lens is 'git grep -l', which sees tracked files only)."
    echo "  Whoever added or removed the mention owns updating that list."
    cat "$TMP/gatec"
  } >&2
else
  ACCOUNTED_N="$(grep -c . "$TMP/accounted" 2>/dev/null || true)"
  _pass "Gate C: every matching file accounted for ($ACCOUNTED_N expected)"
fi

echo
echo "Results: $PASS passed, $FAIL failed  (L2=$L2 LOOP_KEY=$KEYED markers=$MARKERS)"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
