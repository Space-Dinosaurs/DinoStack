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

echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
