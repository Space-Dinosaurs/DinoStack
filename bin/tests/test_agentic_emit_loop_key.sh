#!/usr/bin/env bash
# Purpose: Pin all SIX rows of bin/agentic-emit's phase-resolution order, which
#          selects the per-ticket keyed loop-state file
#          ($AGENTIC_DIR/loop-state-$AGENTIC_LOOP_KEY.json) and falls back to
#          the legacy .agentic/loop-state.json only in the one row where that
#          is the honest answer:
#            1. AGENTIC_LOOP_KEY set AND that keyed file exists -> use it
#            2. AGENTIC_LOOP_KEY set AND that file is ABSENT     -> "unknown"
#            3. env unset, EXACTLY ONE loop-state-*.json         -> use it
#            4. env unset, 2+ keyed files                        -> "unknown"
#            5. env unset, zero keyed, legacy file exists        -> use legacy
#            6. otherwise                                        -> "unknown"
#
#          Rows 2 and 4 are the load-bearing ones and the reason this file
#          exists. AGENTIC_LOOP_KEY is an LLM-honored convention, not a
#          guarantee. If row 2 fell through to the legacy file, or row 4 broke
#          the tie on newest mtime, every event emitted under a stale or absent
#          key would be attributed to whatever unrelated ticket's file happened
#          to be on disk - confidently-wrong telemetry, which is strictly worse
#          than the honestly-absent "unknown". A mutation that reintroduces
#          either fallback passes rows 1/3/5/6 and fails here.
#
#          Row 5 is also the legacy-compatibility pin: a pre-keying checkout
#          with only .agentic/loop-state.json must keep resolving its phase
#          exactly as before this change.
#
# Public API: none (executable test). Run with:
#             bash bin/tests/test_agentic_emit_loop_key.sh
#
# Upstream deps: bash 3.2+, python3 (stdlib), and bin/agentic-emit itself,
#                invoked as a real subprocess (not sourced) so the AGENTIC_DIR
#                and AGENTIC_LOOP_KEY env seams are exercised the way callers
#                use them.
#
# Downstream consumers: the `bin-sh-tests` CI job, which glob-discovers
#                       bin/tests/test_*.sh - no CI wiring needed.
#
# Failure modes: every verdict routes through _pass/_fail and the exit code is
#                derived from the FAIL counter. This file runs `set -uo
#                pipefail` WITHOUT -e (matching its sibling suites), so a bare
#                `[[ ... ]]` would have its verdict discarded and the suite
#                would report "0 failed" on a real miss. All state lives under
#                a mktemp dir; the repo is never written to.
#
# Performance: < 2 s wall time (a handful of subprocess invocations, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
EMIT="$REPO_DIR/bin/agentic-emit"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

_eq() { # _eq <label> <actual> <expected>
  if [[ "$2" == "$3" ]]; then _pass "$1 = $2"; else _fail "$1: got '$2' want '$3'"; fi
}

if [[ ! -x "$EMIT" ]]; then
  echo "FAIL: $EMIT not found or not executable" >&2
  exit 1
fi

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

# Emit one event into a fresh state dir and read back the resolved phase.
# Args: <case-label> [KEY|-] <plant-spec>...
#   plant-spec is `<filename>=<last_phase>`; `-` for KEY means env unset.
_phase_for() { # _phase_for <case> <key|-> <plant...>
  local label="$1" key="$2"; shift 2
  local dir="$TMP_ROOT/$label"
  mkdir -p "$dir/.agentic"
  local spec name val
  for spec in "$@"; do
    name="${spec%%=*}"
    val="${spec#*=}"
    printf '{"last_phase":"%s"}' "$val" > "$dir/.agentic/$name"
  done
  if [[ "$key" == "-" ]]; then
    AGENTIC_DIR="$dir/.agentic" "$EMIT" spawn_start engineer - '{}' >/dev/null 2>&1
  else
    AGENTIC_DIR="$dir/.agentic" AGENTIC_LOOP_KEY="$key" \
      "$EMIT" spawn_start engineer - '{}' >/dev/null 2>&1
  fi
  python3 - "$dir/.agentic/events.jsonl" <<'PY'
import json, sys
try:
    line = [l for l in open(sys.argv[1]) if l.strip()][-1]
    print(json.loads(line).get("phase", "<no-phase-field>"))
except Exception as e:
    print("<read-error:%s>" % e)
PY
}

echo "--- bin/agentic-emit phase resolution, all six rows ---"

# Row 1: key set, keyed file present -> that file's last_phase.
_eq "row 1 (key set, keyed file present)" \
  "$(_phase_for row1 DS-90 'loop-state-DS-90.json=skeptic')" \
  "skeptic"

# Row 1 negative control: a DIFFERENT ticket's keyed file must not be read.
_eq "row 1 (key set, only a foreign keyed file present -> row 2)" \
  "$(_phase_for row1b DS-90 'loop-state-DS-91.json=qa')" \
  "unknown"

# Row 2: key set, that keyed file ABSENT, legacy PRESENT -> "unknown".
# THE CRITICAL ROW. Falling through to legacy here yields "ci_loop" and
# mis-attributes the event to an unrelated ticket.
_eq "row 2 (key set, keyed file absent, legacy present -> NO fallthrough)" \
  "$(_phase_for row2 DS-90 'loop-state.json=ci_loop')" \
  "unknown"

# Row 3: env unset, exactly one keyed file -> use it.
_eq "row 3 (env unset, exactly one keyed file)" \
  "$(_phase_for row3 - 'loop-state-DS-90.json=quality_gate')" \
  "quality_gate"

# Row 4: env unset, 2+ keyed files -> "unknown", no newest-mtime tiebreak.
_eq "row 4 (env unset, 2+ keyed files -> ambiguous, no mtime tiebreak)" \
  "$(_phase_for row4 - 'loop-state-DS-90.json=skeptic' 'loop-state-DS-91.json=qa')" \
  "unknown"

# Row 4 must hold even when a legacy file is also present.
_eq "row 4 (env unset, 2+ keyed files plus legacy -> still unknown)" \
  "$(_phase_for row4b - 'loop-state-DS-90.json=skeptic' 'loop-state-DS-91.json=qa' 'loop-state.json=ci_loop')" \
  "unknown"

# Row 5: env unset, zero keyed files, legacy present -> legacy (back-compat).
_eq "row 5 (env unset, zero keyed, legacy present -> legacy)" \
  "$(_phase_for row5 - 'loop-state.json=ci_loop')" \
  "ci_loop"

# Row 6: nothing at all -> "unknown".
_eq "row 6 (no loop-state file of any kind)" \
  "$(_phase_for row6 -)" \
  "unknown"

# Row 6 variants: a keyed file that is unparseable, and one with no last_phase.
mkdir -p "$TMP_ROOT/row6b/.agentic"
printf 'not json at all' > "$TMP_ROOT/row6b/.agentic/loop-state-DS-90.json"
AGENTIC_DIR="$TMP_ROOT/row6b/.agentic" AGENTIC_LOOP_KEY=DS-90 \
  "$EMIT" spawn_start engineer - '{}' >/dev/null 2>&1
_eq "row 6 (keyed file present but unparseable -> fail-soft unknown)" \
  "$(python3 -c 'import json,sys;print(json.loads(open(sys.argv[1]).read().strip().splitlines()[-1]).get("phase"))' "$TMP_ROOT/row6b/.agentic/events.jsonl")" \
  "unknown"

_eq "row 6 (keyed file present, no last_phase field -> unknown)" \
  "$(_phase_for row6c DS-90 'loop-state-DS-90.json=')" \
  "unknown"

# A `.tmp` staging sibling must not be counted as a keyed candidate by row 3/4.
mkdir -p "$TMP_ROOT/row3b/.agentic"
printf '{"last_phase":"skeptic"}' > "$TMP_ROOT/row3b/.agentic/loop-state-DS-90.json"
printf '{"last_phase":"qa"}' > "$TMP_ROOT/row3b/.agentic/loop-state-DS-91.json.tmp"
AGENTIC_DIR="$TMP_ROOT/row3b/.agentic" "$EMIT" spawn_start engineer - '{}' >/dev/null 2>&1
_eq "row 3 (a .tmp staging sibling is not a keyed candidate)" \
  "$(python3 -c 'import json,sys;print(json.loads(open(sys.argv[1]).read().strip().splitlines()[-1]).get("phase"))' "$TMP_ROOT/row3b/.agentic/events.jsonl")" \
  "skeptic"

# The caller must never be raised to: agentic-emit is best-effort and exits 0.
AGENTIC_DIR="$TMP_ROOT/row6/.agentic" AGENTIC_LOOP_KEY='../../etc/passwd' \
  "$EMIT" spawn_start engineer - '{}' >/dev/null 2>&1
_eq "a traversal-shaped AGENTIC_LOOP_KEY never raises to the caller" "$?" "0"

echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -gt 0 ]] && exit 1
exit 0
