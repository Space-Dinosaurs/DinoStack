#!/usr/bin/env bash
# Purpose: Regression test for the skill-reminder applicability filter added to
#          hooks/skill-auto-load-check.sh in DS-218 Unit 1 (round 3). The filter adds a
#          second, structurally-independent bounded stdin read (select() + a single
#          os.read syscall, never a buffered/looping read) that inspects the turn's
#          "prompt" field for a left-word-boundary keyword match, and suppresses the
#          banner only on a confident non-match. Two prior mechanisms failed on the
#          identical held-open-partial-payload shape: signal.alarm with no handler
#          (terminates the process, exit 142) and select()+sys.stdin.read(n) (the
#          buffered read still loops toward n bytes or EOF, so it hangs past the select
#          bound - reproduced hanging to an external 4s timeout kill with zero output).
#          Scenarios 5 and 6 are the regression coverage for exactly that failure shape.
# Public API: bash bin/tests/test_skill_reminder_applicability.sh
#             Exits 0 on all pass, 1 on any failure.
# Upstream deps: bash, python3, mkfifo, timeout (or a portable equivalent - GNU
#                coreutils' timeout is assumed present per the CI runner).
# Downstream consumers: developer running locally before commit; CI (bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
# Failure modes: any assertion failure prints the failing assertion (via fail()) and
#                the script exits 1 at the end. A temporary fake HOME sandboxes
#                ~/.claude/agentic-engineering.json; the real one is never touched.
#
# Named mutations (verified during implementation to actually redden their stated
# assertion - see the engineer's return summary for the measured output):
#   1. Revert the left-anchor to an unanchored substring match: reddens scenario 2
#      while scenario 1 stays green (the discriminating pair).
#   2. Over-tighten to whole-word-only matching (add a trailing \b): reddens scenario 3.
#   3. Change the unparseable / no-stdin fallback to fail-closed ("no_match" instead of
#      "unknown"): reddens scenario 4.
#   4. Replace os.read(fd, 65536) with sys.stdin.read(65536) / TextIOWrapper.read():
#      reddens scenario 5 - the mutant hangs on the held-open partial payload until an
#      external `timeout 4` kills it at rc=124, with no banner ever printed.
#   5. Remove the select() timeout entirely (block indefinitely on readability):
#      reddens scenario 6 the same way.
#   6. Remove the `or not prompt.strip()` guard (round 4 Major 1 fix), so an empty
#      or whitespace-only "prompt" string falls through to the pattern match on ''
#      instead of raising: reddens scenario 7.
#
# Named mutations, vocabulary-widening round (page|icon|button|menu|mockup|design|
# admin|screen|logo|render|api|endpoint|template|feature|fix|broken|revert|demo(s)):
#   7. Fold `\bdemos?\b` back into the bare left-anchor-only group (instead of its own
#      both-side-anchored alternative): reddens scenario 10, since "demon"/"democracy"/
#      "demolish" would then match the group's left-boundary-only "demo" prefix.
#   8. Remove any one of the 17 new bare-group words from the pattern: reddens that
#      word's case in scenario 8 (the loop asserts each word individually, so removing
#      one word only reddens its own assertion, not the whole scenario).
#
# Named mutations, DS-242 round (ticket IDs, worktree/conductor/reap(ing), border):
#   9.  Remove the ticket_pattern check entirely: reddens scenario 11's positive case
#       ("AUT-930" no longer fires).
#   10. Fold ticket_pattern into the IGNORECASE `pattern` instead of keeping it a
#       separate case-sensitive check: reddens scenario 11's negative case
#       (lowercase "ab-12" starts firing).
#   11. Remove `border` from the bare left-anchor-only group: reddens scenario 12.
#   12. Remove `\bworktrees?\b`, `\bconductors?\b`, or `\breap(?:ing)?\b` from the
#       both-side-anchored alternation: reddens that word's positive case in
#       scenario 13.
#   13. Widen one of the three both-side-anchored alternatives to an unanchored
#       (bare substring) match - each word has its OWN look-alike negative case in
#       scenario 13, since widening one word does not affect the other two's
#       negative cases:
#         - `\breap(?:ing)?\b` -> `\breap`: reddens "reapply" (shares the "reap"
#           prefix; right anchor is the one that was removed).
#         - `\bworktrees?\b` -> `worktrees?` (drop both anchors): reddens
#           "networktree", which contains "worktree" as a substring
#           (n-e-t-w-o-r-k-t-r-e-e) but is not itself the word "worktree".
#         - `\bconductors?\b` -> `conductors?` (drop both anchors): reddens
#           "semiconductor", which contains "conductor" as a substring but is not
#           itself the word "conductor".
#       Confirmed: widening only ONE word's anchor does not redden the OTHER two
#       words' negative cases (verified during implementation - see the
#       engineer's return summary).
#   14. Single-anchor removal (narrower than mutation 13's drop-both-anchors
#       form - the round-2 gap: mutation 13 never tested removing just ONE
#       side). Each has its own look-alike negative case, confirmed isolated
#       from the other two (removing one word's anchor does not redden a
#       different word's negative):
#         - `\bworktrees?\b` -> `\bworktrees?` (right anchor only removed):
#           reddens "worktreeing" (left-anchored prefix match, no right
#           boundary required after "worktree").
#         - `\bconductors?\b` -> `\bconductors?` (right anchor only removed):
#           reddens "conductorship" (same shape as "worktreeing").
#         - `\breap(?:ing)?\b` -> `reap(?:ing)?\b` (left anchor only removed):
#           reddens "misreap" (right-anchored suffix match, no left boundary
#           required before "reap").
#   15. Ticket pattern, boundary and cardinality mutations (round-2 gap - the
#       existing scenario 11 negative, "ab-12", only exercises the
#       IGNORECASE-vs-case-sensitive split, not these two axes):
#         - Remove both `\b` anchors from `ticket_pattern` entirely: reddens a
#           mid-token ID with no boundary before the letter run, e.g.
#           "xAUT-930" (the "x" is itself a word character immediately
#           preceding "AUT-930", so no boundary exists there under the
#           anchored pattern - unlike a space-preceded "AUT-930", which
#           already matches today regardless of anchors, since start-of-word
#           is itself a boundary).
#         - Widen `[A-Z]{2,6}` to `[A-Z]{1,6}`: reddens a one-letter-prefix ID,
#           e.g. "A-12".

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_DIR/hooks/skill-auto-load-check.sh"

PASS=0
FAIL=0

pass() { echo "PASS: $*"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $*" >&2; FAIL=$((FAIL + 1)); }

TMP_ROOT="$(mktemp -d)"
cleanup() { rm -rf "$TMP_ROOT"; }
trap cleanup EXIT

FAKE_HOME="$TMP_ROOT/home"
mkdir -p "$FAKE_HOME/.claude"
printf '{"skill_auto_load": true}\n' > "$FAKE_HOME/.claude/agentic-engineering.json"

run_with_prompt() {
  # $1 = prompt text; writes stdout/stderr/rc into globals for the caller to assert on.
  local prompt="$1"
  local payload
  payload="$(python3 -c "import json, sys; print(json.dumps({'prompt': sys.argv[1]}))" "$prompt")"
  RUN_OUT="$(printf '%s' "$payload" | HOME="$FAKE_HOME" bash "$HOOK" 2>"$TMP_ROOT/stderr.log")"
  RUN_RC=$?
  RUN_ERR="$(cat "$TMP_ROOT/stderr.log")"
}

# ---------------------------------------------------------------------------
# Scenario 1: clean positive control - a genuine-keyword prompt in a fresh
# invocation emits the banner.
# ---------------------------------------------------------------------------
run_with_prompt "please refactor this function and run tests"
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 1: genuine-keyword prompt emits the banner"
else
  fail "scenario 1: expected the banner, got stdout: $RUN_OUT"
fi
if [[ "$RUN_RC" -eq 0 && -z "$RUN_ERR" ]]; then
  pass "scenario 1: exit 0, empty stderr"
else
  fail "scenario 1: expected exit 0 and empty stderr, got rc=$RUN_RC stderr=$RUN_ERR"
fi

# ---------------------------------------------------------------------------
# Scenario 2: a prompt containing ONLY the 5 cited word-boundary false-positive
# traps (encode/credit/latest/airplane/digit), no genuine keyword, does not
# emit the banner.
# ---------------------------------------------------------------------------
run_with_prompt "please encode the video, check my credit report, book the latest airplane, what digit is this"
if [[ -z "$RUN_OUT" ]]; then
  pass "scenario 2: false-positive-trap-only prompt suppresses the banner"
else
  fail "scenario 2: expected empty stdout, got: $RUN_OUT"
fi
if [[ "$RUN_RC" -eq 0 && -z "$RUN_ERR" ]]; then
  pass "scenario 2: exit 0, empty stderr"
else
  fail "scenario 2: expected exit 0 and empty stderr, got rc=$RUN_RC stderr=$RUN_ERR"
fi

# ---------------------------------------------------------------------------
# Scenario 3: an accepted inflection false positive (test -> testimony) DOES
# emit the banner, confirming the documented left-anchor bias is real.
# ---------------------------------------------------------------------------
run_with_prompt "the witness gave a lengthy testimony in court today"
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 3: left-anchored inflection false positive (testimony) still emits the banner"
else
  fail "scenario 3: expected the banner, got stdout: $RUN_OUT"
fi

# ---------------------------------------------------------------------------
# Scenario 4: no stdin piped (legacy invocation shape) still emits the banner
# unconditionally (backward compat, matches the existing adapter tests).
# ---------------------------------------------------------------------------
NO_STDIN_OUT="$(HOME="$FAKE_HOME" bash "$HOOK" < /dev/null 2>"$TMP_ROOT/stderr-nostdin.log")"
NO_STDIN_RC=$?
NO_STDIN_ERR="$(cat "$TMP_ROOT/stderr-nostdin.log")"
if [[ "$NO_STDIN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 4: no-stdin legacy invocation still emits the banner unconditionally"
else
  fail "scenario 4: expected the banner with no stdin piped, got stdout: $NO_STDIN_OUT"
fi
if [[ "$NO_STDIN_RC" -eq 0 && -z "$NO_STDIN_ERR" ]]; then
  pass "scenario 4: exit 0, empty stderr"
else
  fail "scenario 4: expected exit 0 and empty stderr, got rc=$NO_STDIN_RC stderr=$NO_STDIN_ERR"
fi

# ---------------------------------------------------------------------------
# Scenario 5: a stdin producer opens a FIFO, sends a PARTIAL JSON payload, and
# holds the fd open without closing (5s hold). The script must not hang past
# the select() bound, and must still emit the banner (fail-open on truncated
# input). Bounded externally by `timeout 4` - if the mechanism regresses to a
# buffered read (mutation 4), this call is killed at rc=124 with zero output
# rather than completing near-instantly with the banner.
# ---------------------------------------------------------------------------
FIFO5="$TMP_ROOT/fifo5"
mkfifo "$FIFO5"
( exec 3>"$FIFO5"; printf '{"prompt":"please refactor' >&3; sleep 5; exec 3>&- ) &
WRITER5_PID=$!
START5=$(date +%s)
S5_OUT="$(HOME="$FAKE_HOME" timeout 4 bash "$HOOK" < "$FIFO5" 2>"$TMP_ROOT/stderr5.log")"
S5_RC=$?
END5=$(date +%s)
S5_ERR="$(cat "$TMP_ROOT/stderr5.log")"
S5_ELAPSED=$((END5 - START5))
wait "$WRITER5_PID" 2>/dev/null

if [[ "$S5_ELAPSED" -le 2 ]]; then
  pass "scenario 5: completes within ~2s despite the writer holding the fd open for 5s (elapsed=${S5_ELAPSED}s)"
else
  fail "scenario 5: expected completion within ~2s, elapsed=${S5_ELAPSED}s rc=$S5_RC stdout=$S5_OUT stderr=$S5_ERR"
fi
if [[ "$S5_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 5: fail-open on a truncated partial payload - banner still emitted"
else
  fail "scenario 5: expected the banner on a truncated partial payload, got rc=$S5_RC stdout=$S5_OUT stderr=$S5_ERR"
fi

# ---------------------------------------------------------------------------
# Scenario 6: a stdin producer opens a FIFO for writing but never sends any
# data and never closes it (5s hold, zero bytes). The script must not hang
# past the select() bound, and must still emit the banner.
# ---------------------------------------------------------------------------
FIFO6="$TMP_ROOT/fifo6"
mkfifo "$FIFO6"
( exec 3>"$FIFO6"; sleep 5; exec 3>&- ) &
WRITER6_PID=$!
START6=$(date +%s)
S6_OUT="$(HOME="$FAKE_HOME" timeout 4 bash "$HOOK" < "$FIFO6" 2>"$TMP_ROOT/stderr6.log")"
S6_RC=$?
END6=$(date +%s)
S6_ERR="$(cat "$TMP_ROOT/stderr6.log")"
S6_ELAPSED=$((END6 - START6))
wait "$WRITER6_PID" 2>/dev/null

if [[ "$S6_ELAPSED" -le 2 ]]; then
  pass "scenario 6: completes within ~2s despite an open fd with zero bytes written (elapsed=${S6_ELAPSED}s)"
else
  fail "scenario 6: expected completion within ~2s, elapsed=${S6_ELAPSED}s rc=$S6_RC stdout=$S6_OUT stderr=$S6_ERR"
fi
if [[ "$S6_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 6: fail-open on zero bytes with the fd held open - banner still emitted"
else
  fail "scenario 6: expected the banner with zero bytes written, got rc=$S6_RC stdout=$S6_OUT stderr=$S6_ERR"
fi

# ---------------------------------------------------------------------------
# Scenario 7: an empty or whitespace-only "prompt" string is the same
# evidentiary state as an absent prompt (scenario 4) - it must FIRE, never
# silently suppress (round 4 Major 1). Confirms both the empty-string and
# whitespace-only variants.
# ---------------------------------------------------------------------------
run_with_prompt ""
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 7: empty-string prompt fires the banner (fail-open, not silent suppression)"
else
  fail "scenario 7: expected the banner on an empty-string prompt, got stdout: $RUN_OUT"
fi
if [[ "$RUN_RC" -eq 0 && -z "$RUN_ERR" ]]; then
  pass "scenario 7: exit 0, empty stderr (empty-string prompt)"
else
  fail "scenario 7: expected exit 0 and empty stderr, got rc=$RUN_RC stderr=$RUN_ERR"
fi

run_with_prompt "   "
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 7: whitespace-only prompt fires the banner (fail-open, not silent suppression)"
else
  fail "scenario 7: expected the banner on a whitespace-only prompt, got stdout: $RUN_OUT"
fi
if [[ "$RUN_RC" -eq 0 && -z "$RUN_ERR" ]]; then
  pass "scenario 7: exit 0, empty stderr (whitespace-only prompt)"
else
  fail "scenario 7: expected exit 0 and empty stderr, got rc=$RUN_RC stderr=$RUN_ERR"
fi

# ---------------------------------------------------------------------------
# Combining-condition check: skill_auto_load=false suppresses the banner even
# on a prompt that would otherwise match.
# ---------------------------------------------------------------------------
FALSE_HOME="$TMP_ROOT/home-false"
mkdir -p "$FALSE_HOME/.claude"
printf '{"skill_auto_load": false}\n' > "$FALSE_HOME/.claude/agentic-engineering.json"
FALSE_OUT="$(printf '{"prompt":"please refactor this function"}' | HOME="$FALSE_HOME" bash "$HOOK" 2>"$TMP_ROOT/stderr-false.log")"
FALSE_ERR="$(cat "$TMP_ROOT/stderr-false.log")"
if [[ -z "$FALSE_OUT" && -z "$FALSE_ERR" ]]; then
  pass "combining condition: skill_auto_load=false suppresses the banner even on a matching prompt"
else
  fail "combining condition: expected silence when skill_auto_load=false, got stdout=$FALSE_OUT stderr=$FALSE_ERR"
fi

# ---------------------------------------------------------------------------
# Scenario 8: each of the 17 vocabulary-widening bare-group words, alone in a
# plain-English sentence with no other keyword present, fires the banner.
# ---------------------------------------------------------------------------
NEW_WORDS=(page icon button menu mockup design admin screen logo render api
           endpoint template feature fix broken revert)
for word in "${NEW_WORDS[@]}"; do
  run_with_prompt "can we talk about the ${word} on this thing"
  if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
    pass "scenario 8: word '$word' alone fires the banner"
  else
    fail "scenario 8: word '$word' alone expected the banner, got stdout: $RUN_OUT"
  fi
done

# ---------------------------------------------------------------------------
# Scenario 9: demo/demos, as their own both-side-anchored alternative, fire
# the banner.
# ---------------------------------------------------------------------------
run_with_prompt "we need a demo of this"
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 9: 'demo' fires the banner"
else
  fail "scenario 9: 'demo' expected the banner, got stdout: $RUN_OUT"
fi

run_with_prompt "send the demos over"
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 9: 'demos' fires the banner"
else
  fail "scenario 9: 'demos' expected the banner, got stdout: $RUN_OUT"
fi

# ---------------------------------------------------------------------------
# Scenario 10: a prompt containing only demon/democracy/demolish - words that
# share a "demo" prefix but are not demo/demos - and no other keyword, does
# NOT fire the banner. Confirms \bdemos?\b is both-side-anchored, not folded
# into the left-anchor-only bare group.
# ---------------------------------------------------------------------------
run_with_prompt "the demon threatened democracy so they had to demolish the tower"
if [[ -z "$RUN_OUT" ]]; then
  pass "scenario 10: demon/democracy/demolish-only prompt suppresses the banner"
else
  fail "scenario 10: expected empty stdout, got: $RUN_OUT"
fi

# ---------------------------------------------------------------------------
# Scenario 11: ticket IDs (case-sensitive [A-Z]{2,6}-\d{2,5}). The uppercase
# form fires the banner alone; the lowercase form does not (the main
# IGNORECASE pattern must not swallow it).
# ---------------------------------------------------------------------------
run_with_prompt "fold AUT-930 into the mix"
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 11: uppercase ticket ID (AUT-930) alone fires the banner"
else
  fail "scenario 11: expected the banner for AUT-930, got stdout: $RUN_OUT"
fi

run_with_prompt "ab-12 should not match"
if [[ -z "$RUN_OUT" ]]; then
  pass "scenario 11: lowercase ticket-ID-shaped text (ab-12) does not fire the banner"
else
  fail "scenario 11: expected empty stdout for ab-12, got: $RUN_OUT"
fi

# ---------------------------------------------------------------------------
# Scenario 12: `border`, left-anchored like the existing bare-word group,
# fires the banner alone.
# ---------------------------------------------------------------------------
run_with_prompt "just make the borders 1px"
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 12: 'border' (as 'borders') alone fires the banner"
else
  fail "scenario 12: expected the banner for 'borders', got stdout: $RUN_OUT"
fi

# ---------------------------------------------------------------------------
# Scenario 13: worktree/conductor/reap(ing), each both-side-anchored, fire the
# banner alone (including their plain plural/inflected forms measured in the
# corpora). Each word has its own negative-case look-alike that shares its
# substring but is not the word itself at a boundary: "reapply" (reap),
# "networktree" (worktree, contains "worktree" starting at its 4th letter -
# n-e-t-[w-o-r-k-t-r-e-e]), and "semiconductor" (conductor). None fire.
# ---------------------------------------------------------------------------
run_with_prompt "let's talk about worktrees"
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 13: 'worktrees' alone fires the banner"
else
  fail "scenario 13: expected the banner for 'worktrees', got stdout: $RUN_OUT"
fi

run_with_prompt "the conductor should delegate this"
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 13: 'conductor' alone fires the banner"
else
  fail "scenario 13: expected the banner for 'conductor', got stdout: $RUN_OUT"
fi

run_with_prompt "how does auto-reap work?"
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 13: 'reap' alone fires the banner"
else
  fail "scenario 13: expected the banner for 'reap', got stdout: $RUN_OUT"
fi

run_with_prompt "this auto reaping is separate"
if [[ "$RUN_OUT" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "scenario 13: 'reaping' alone fires the banner"
else
  fail "scenario 13: expected the banner for 'reaping', got stdout: $RUN_OUT"
fi

run_with_prompt "reapply the patch please"
if [[ -z "$RUN_OUT" ]]; then
  pass "scenario 13: 'reapply' does not fire the banner"
else
  fail "scenario 13: expected empty stdout for 'reapply', got: $RUN_OUT"
fi

run_with_prompt "the networktree diagram needs updating"
if [[ -z "$RUN_OUT" ]]; then
  pass "scenario 13: 'networktree' does not fire the banner"
else
  fail "scenario 13: expected empty stdout for 'networktree', got: $RUN_OUT"
fi

run_with_prompt "the semiconductor shortage is affecting production"
if [[ -z "$RUN_OUT" ]]; then
  pass "scenario 13: 'semiconductor' does not fire the banner"
else
  fail "scenario 13: expected empty stdout for 'semiconductor', got: $RUN_OUT"
fi

# ---------------------------------------------------------------------------
# Scenario 14: single-anchor look-alikes (mutation 14). Each shares a word's
# substring but only on the side whose anchor mutation 14 does NOT remove -
# "worktreeing" and "conductorship" both extend past their word's right
# boundary; "misreap" extends before "reap"'s left boundary. None fire today.
# ---------------------------------------------------------------------------
run_with_prompt "let's talk about worktreeing this branch"
if [[ -z "$RUN_OUT" ]]; then
  pass "scenario 14: 'worktreeing' does not fire the banner"
else
  fail "scenario 14: expected empty stdout for 'worktreeing', got: $RUN_OUT"
fi

run_with_prompt "his conductorship ended last year"
if [[ -z "$RUN_OUT" ]]; then
  pass "scenario 14: 'conductorship' does not fire the banner"
else
  fail "scenario 14: expected empty stdout for 'conductorship', got: $RUN_OUT"
fi

run_with_prompt "did we misreap that resource"
if [[ -z "$RUN_OUT" ]]; then
  pass "scenario 14: 'misreap' does not fire the banner"
else
  fail "scenario 14: expected empty stdout for 'misreap', got: $RUN_OUT"
fi

# ---------------------------------------------------------------------------
# Scenario 15: ticket-pattern boundary and cardinality look-alikes
# (mutation 15). "xAUT-930" is a mid-token ID with no boundary before the
# letter run (the "x" is a word character immediately abutting "AUT-930");
# "A-12" is a single-letter-prefix ID, below the {2,6} floor. Neither fires
# today.
# ---------------------------------------------------------------------------
run_with_prompt "check xAUT-930 for updates"
if [[ -z "$RUN_OUT" ]]; then
  pass "scenario 15: mid-token ID 'xAUT-930' does not fire the banner"
else
  fail "scenario 15: expected empty stdout for 'xAUT-930', got: $RUN_OUT"
fi

run_with_prompt "look at A-12 sometime"
if [[ -z "$RUN_OUT" ]]; then
  pass "scenario 15: one-letter-prefix ID 'A-12' does not fire the banner"
else
  fail "scenario 15: expected empty stdout for 'A-12', got: $RUN_OUT"
fi

echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
