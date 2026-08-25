#!/usr/bin/env bash
# Purpose: Browserless regression guard for scripts/check-slide-overflow.js's
#          compare/ratchet logic and CLI-level safety nets. Most scenarios
#          exercise ONLY the --measurements-json code path (hand-written
#          JSON fixtures under mktemp -d). Scenario (g) is the exception: it
#          copies check-slide-overflow.js into a scratch directory alongside
#          a STUB @puppeteer/browsers/puppeteer-core (an abandoned-promise
#          install() and an unreachable launch()) to reproduce Skeptic
#          finding CRIT-silent-exit deterministically - it still touches no
#          real network, npm, or browser, so it stays safe for the required
#          bin-sh-tests glob (which must stay browserless). The live-Chrome
#          scenarios (font fail-closed axes, fresh-context-per-deck, real
#          overflow rendering) live in scripts/check-slide-overflow-live-
#          selftest.sh instead, which is NOT discovered by that glob.
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

# --- Scenario (g): CRIT-silent-exit completion sentinel ---
# Reproduces the Skeptic's method: a scratch node_modules with a stub
# @puppeteer/browsers whose install() returns an abandoned promise (never
# resolves, never rejects) and a stub puppeteer-core whose launch() would
# error if ever reached. Before the fix, main()'s promise chain never
# settles, node drains the event loop, and the process exits 0 with ZERO
# output. Reddening mutation: delete the `process.on('exit', ...)` sentinel
# block from check-slide-overflow.js (leaving the markCompleted() call
# sites in place, now unused) - confirmed manually: exit 0, no output.
SENTINEL_DIR="$TMP_ROOT/sentinel-test"
mkdir -p "$SENTINEL_DIR/node_modules/@puppeteer/browsers"
mkdir -p "$SENTINEL_DIR/node_modules/puppeteer-core"
cp "$GATE_SCRIPT" "$SENTINEL_DIR/check-slide-overflow.js"

write_json "$SENTINEL_DIR/node_modules/@puppeteer/browsers/package.json" \
  '{"name":"@puppeteer/browsers","version":"0.0.0-stub","main":"index.js"}'
cat > "$SENTINEL_DIR/node_modules/@puppeteer/browsers/index.js" <<'EOF'
'use strict';
exports.install = function install() {
  return new Promise(() => {});
};
exports.computeExecutablePath = function computeExecutablePath() {
  return '/nonexistent/chrome';
};
exports.detectBrowserPlatform = function detectBrowserPlatform() {
  return 'linux';
};
exports.resolveBuildId = async function resolveBuildId() {
  return 'stub-build-id';
};
EOF

write_json "$SENTINEL_DIR/node_modules/puppeteer-core/package.json" \
  '{"name":"puppeteer-core","version":"0.0.0-stub","main":"index.js"}'
cat > "$SENTINEL_DIR/node_modules/puppeteer-core/index.js" <<'EOF'
'use strict';
exports.launch = async function launch() {
  throw new Error('stub puppeteer-core launch() should never be called in this test');
};
EOF

out_g="$(cd "$SENTINEL_DIR" && timeout 20 node check-slide-overflow.js --deck /tmp/does-not-need-to-exist.html 2>&1)"
rc_g=$?
if [[ "$rc_g" -eq 1 ]]; then
  _pass "(g) abandoned install() promise exits 1, not a silent 0"
else
  _fail "(g) abandoned install() promise exited $rc_g (expected 1): $out_g"
fi
if echo "$out_g" | grep -q 'aborted before reaching a verdict'; then
  _pass "(g) abandoned install() promise prints the sentinel message"
else
  _fail "(g) abandoned install() promise's output did not match: $out_g"
fi

# --- Scenario (h): --repeat requires a positive integer ---
out_h="$(node "$GATE_SCRIPT" --measurements-json "$MEAS_A" --baseline "$BASE_A" --repeat abc 2>&1)"
rc_h=$?
if [[ "$rc_h" -ne 0 ]]; then
  _pass "(h) --repeat abc exits non-zero"
else
  _fail "(h) --repeat abc exited 0 (expected non-zero)"
fi
if echo "$out_h" | grep -q -- '--repeat requires a positive integer'; then
  _pass "(h) --repeat abc prints a clear error"
else
  _fail "(h) --repeat abc's output did not match: $out_h"
fi

# --- Scenario (i): --dump-overflows + --measurements-json is rejected ---
out_i="$(node "$GATE_SCRIPT" --dump-overflows --measurements-json "$MEAS_A" --baseline "$BASE_A" 2>&1)"
rc_i=$?
if [[ "$rc_i" -ne 0 ]]; then
  _pass "(i) --dump-overflows + --measurements-json exits non-zero"
else
  _fail "(i) --dump-overflows + --measurements-json exited 0 (expected non-zero)"
fi
if echo "$out_i" | grep -q -- '--dump-overflows and --measurements-json are mutually exclusive'; then
  _pass "(i) --dump-overflows + --measurements-json prints a clear error"
else
  _fail "(i) --dump-overflows + --measurements-json's output did not match: $out_i"
fi

# --- Scenario (j): --deck scoping in --measurements-json mode ---
# A measurements file with TWO decks, --deck naming only one -> only that
# deck's failure is reported; the other deck's overflow must not leak in.
MEAS_J="$TMP_ROOT/meas-j.json"
BASE_J="$TMP_ROOT/base-j.json"
write_json "$MEAS_J" '[{"deck":"x-slides.html","slides":[{"id":"1","title":"X One","scrollHeight":730}]},{"deck":"y-slides.html","slides":[{"id":"1","title":"Y One","scrollHeight":730}]}]'
write_json "$BASE_J" '{}'
out_j="$(node "$GATE_SCRIPT" --measurements-json "$MEAS_J" --baseline "$BASE_J" --deck x-slides.html 2>&1)"
rc_j=$?
if [[ "$rc_j" -eq 1 ]]; then
  _pass "(j) --deck scoping exits 1 for the named deck's own overflow"
else
  _fail "(j) --deck scoping exited $rc_j (expected 1): $out_j"
fi
if echo "$out_j" | grep -q 'OVERFLOW x-slides.html slide 1'; then
  _pass "(j) --deck scoping reports the named deck's overflow"
else
  _fail "(j) --deck scoping did not report the named deck's overflow: $out_j"
fi
if echo "$out_j" | grep -q 'y-slides.html'; then
  _fail "(j) --deck scoping leaked the unscoped deck's failure: $out_j"
else
  _pass "(j) --deck scoping did not leak the unscoped deck's failure"
fi

echo ""
echo "PASS=$PASS FAIL=$FAIL"
if [[ "$FAIL" -eq 0 ]]; then
  exit 0
else
  exit 1
fi
