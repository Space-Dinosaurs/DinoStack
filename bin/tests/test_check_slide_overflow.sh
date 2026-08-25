#!/usr/bin/env bash
# Purpose: Browserless regression guard for scripts/check-slide-overflow.js's
#          compare/ratchet logic. Deliberately exercises ONLY the
#          --measurements-json code path (hand-written JSON fixtures under
#          mktemp -d) - it never invokes puppeteer-core, @puppeteer/browsers,
#          npm ci, or network, so it is safe to run in the required bin-sh-
#          tests glob (which must stay browserless). The live-Chrome
#          scenarios (font fail-closed axes, fresh-context-per-deck,
#          real overflow rendering) live in scripts/check-slide-overflow-
#          live-selftest.sh instead, which is NOT discovered by that glob.
#
# Public API: ./bin/tests/test_check_slide_overflow.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: node (guarded: absent -> hard FAIL under CI=true, else a
#                SKIP line and exit 0, mirroring bin/tests/test_check_
#                resident_budget.sh's zsh-parity guard); scripts/check-slide-
#                overflow.js.
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script missing -> immediate FAIL. Any scenario's
#                observed exit code or message does not match the expected
#                shape -> FAIL naming the scenario and what was observed.
#
# Test hygiene: never mutates any tracked file in the working tree. All
#               fixture JSON files live under a mktemp -d directory removed
#               on exit via trap. Does not touch network or a browser.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-slide-overflow.js"

if [[ ! -f "$GATE_SCRIPT" ]]; then
  echo "FAIL: $GATE_SCRIPT not found" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  if [[ -n "${CI:-}" ]]; then
    echo "FAIL: node not found on PATH in CI" >&2
    exit 1
  else
    echo "SKIP: node not found on PATH - skipping bin/tests/test_check_slide_overflow.sh"
    exit 0
  fi
fi

PASS=0
FAIL=0

_fail() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

_pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/test-check-slide-overflow.XXXXXX")"
cleanup() { rm -rf "$TMP_ROOT"; }
trap cleanup EXIT

write_json() {
  local path="$1"
  local content="$2"
  printf '%s' "$content" > "$path"
}

run_gate() {
  local measurements="$1"
  local baseline="$2"
  node "$GATE_SCRIPT" --measurements-json "$measurements" --baseline "$baseline" 2>&1
}

# --- Scenario (a): non-baselined overflow -> exit 1 + correct OVERFLOW line ---
MEAS_A="$TMP_ROOT/meas-a.json"
BASE_A="$TMP_ROOT/base-a.json"
write_json "$MEAS_A" '[{"deck":"a-slides.html","slides":[{"id":"1","title":"Slide One","scrollHeight":730}]}]'
write_json "$BASE_A" '{}'
out_a="$(run_gate "$MEAS_A" "$BASE_A")"
rc_a=$?
if [[ "$rc_a" -eq 1 ]]; then
  _pass "(a) non-baselined overflow exits 1"
else
  _fail "(a) non-baselined overflow exited $rc_a (expected 1): $out_a"
fi
if echo "$out_a" | grep -q 'OVERFLOW a-slides.html slide 1 ("Slide One")'; then
  _pass "(a) non-baselined overflow prints the expected OVERFLOW line"
else
  _fail "(a) non-baselined overflow's output did not match: $out_a"
fi

# --- Scenario (b): baselined overflow -> exit 0 ---
MEAS_B="$TMP_ROOT/meas-b.json"
BASE_B="$TMP_ROOT/base-b.json"
write_json "$MEAS_B" '[{"deck":"b-slides.html","slides":[{"id":"1","title":"Slide One","scrollHeight":730}]}]'
write_json "$BASE_B" '{"b-slides.html":["1"]}'
out_b="$(run_gate "$MEAS_B" "$BASE_B")"
rc_b=$?
if [[ "$rc_b" -eq 0 ]]; then
  _pass "(b) baselined overflow exits 0"
else
  _fail "(b) baselined overflow exited $rc_b (expected 0): $out_b"
fi
if echo "$out_b" | grep -q '1 pre-existing baselined overflows still present'; then
  _pass "(b) baselined overflow's summary counts the baselined overflow"
else
  _fail "(b) baselined overflow's summary did not count the baselined overflow: $out_b"
fi

# --- Scenario (c): stale baseline entry (baselined id measuring 720) -> exit 1 + STALE BASELINE line ---
MEAS_C="$TMP_ROOT/meas-c.json"
BASE_C="$TMP_ROOT/base-c.json"
write_json "$MEAS_C" '[{"deck":"c-slides.html","slides":[{"id":"1","title":"Slide One","scrollHeight":720}]}]'
write_json "$BASE_C" '{"c-slides.html":["1"]}'
out_c="$(run_gate "$MEAS_C" "$BASE_C")"
rc_c=$?
if [[ "$rc_c" -eq 1 ]]; then
  _pass "(c) stale baseline entry exits 1"
else
  _fail "(c) stale baseline entry exited $rc_c (expected 1): $out_c"
fi
if echo "$out_c" | grep -q 'STALE BASELINE c-slides.html slide 1'; then
  _pass "(c) stale baseline entry prints the expected STALE BASELINE line"
else
  _fail "(c) stale baseline entry's output did not match: $out_c"
fi

# --- Scenario (d): orphan deck key -> exit 1 + "orphan deck" line ---
MEAS_D="$TMP_ROOT/meas-d.json"
BASE_D="$TMP_ROOT/base-d.json"
write_json "$MEAS_D" '[{"deck":"d-slides.html","slides":[{"id":"1","title":"Slide One","scrollHeight":100}]}]'
write_json "$BASE_D" '{"gone-slides.html":["1"]}'
out_d="$(run_gate "$MEAS_D" "$BASE_D")"
rc_d=$?
if [[ "$rc_d" -eq 1 ]]; then
  _pass "(d) orphan deck key exits 1"
else
  _fail "(d) orphan deck key exited $rc_d (expected 1): $out_d"
fi
if echo "$out_d" | grep -q 'STALE BASELINE (orphan deck) gone-slides.html'; then
  _pass "(d) orphan deck key prints the expected orphan-deck line"
else
  _fail "(d) orphan deck key's output did not match: $out_d"
fi

# --- Scenario (e): orphan slide id -> exit 1 + "orphan slide" line ---
MEAS_E="$TMP_ROOT/meas-e.json"
BASE_E="$TMP_ROOT/base-e.json"
write_json "$MEAS_E" '[{"deck":"e-slides.html","slides":[{"id":"1","title":"Slide One","scrollHeight":100}]}]'
write_json "$BASE_E" '{"e-slides.html":["1","99"]}'
out_e="$(run_gate "$MEAS_E" "$BASE_E")"
rc_e=$?
if [[ "$rc_e" -eq 1 ]]; then
  _pass "(e) orphan slide id exits 1"
else
  _fail "(e) orphan slide id exited $rc_e (expected 1): $out_e"
fi
if echo "$out_e" | grep -q 'STALE BASELINE (orphan slide) e-slides.html slide 99'; then
  _pass "(e) orphan slide id prints the expected orphan-slide line"
else
  _fail "(e) orphan slide id's output did not match: $out_e"
fi

# --- Scenario (f): missing --measurements-json file -> nonzero with clear error ---
out_f="$(node "$GATE_SCRIPT" --measurements-json "$TMP_ROOT/does-not-exist.json" --baseline "$BASE_A" 2>&1)"
rc_f=$?
if [[ "$rc_f" -ne 0 ]]; then
  _pass "(f) missing --measurements-json file exits non-zero"
else
  _fail "(f) missing --measurements-json file exited 0 (expected non-zero)"
fi
if echo "$out_f" | grep -q 'measurements-json file not found'; then
  _pass "(f) missing --measurements-json file prints a clear error"
else
  _fail "(f) missing --measurements-json file's output did not match: $out_f"
fi

echo ""
echo "PASS=$PASS FAIL=$FAIL"
if [[ "$FAIL" -eq 0 ]]; then
  exit 0
else
  exit 1
fi
