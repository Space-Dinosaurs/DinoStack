#!/usr/bin/env bash
# Purpose: Live (real headless Chrome) regression suite for scripts/check-
#          slide-overflow.js. Builds two tiny fixture decks (one clean, one
#          deliberately overflowing) via marp directly, then runs the node
#          script against them and asserts exit codes + message content for
#          the clean path, the overflow path, the per-deck fresh-context
#          count, and the font fail-closed predicate's two axes.
#
# Public API: bash scripts/check-slide-overflow-live-selftest.sh
#             Prints one PASS/FAIL line per scenario; exits non-zero if any
#             scenario fails.
#
# Upstream deps: scripts/check-slide-overflow.js; scripts/node_modules/.bin/
#                marp (renders fixtures directly - NOT via build-slides.sh,
#                which only knows about docs/slides/*-slides.md); network
#                (Chrome-for-Testing download on a cold cache, Google Fonts).
#
# Downstream consumers: .github/workflows/slides-sync.yml check-slide-
#                        overflow job (runs after check-slide-overflow.sh).
#                        Deliberately lives under scripts/, NOT bin/tests/,
#                        so it is NOT discovered by the required bin-sh-
#                        tests glob (which must stay browserless).
#
# Failure modes: any scenario's assertion failure sets FAILED=1 and the
#                script exits 1 at the end - no vacuous-pass patterns (no
#                `cmd || echo`, no counter that never reaches the exit).
#                `npm ci` DELETES node_modules before reinstalling, which
#                would also delete the Chrome-for-Testing cache living under
#                node_modules/.chrome-for-testing-cache - see scripts/check-
#                slide-overflow.sh's Failure modes for why the staleness
#                check below compares normalized `packages` maps via node
#                rather than a byte-for-byte `cmp` (which would ALWAYS
#                report stale and force a Chrome re-download on every run).
#
# Performance: cold run needs network for `npm ci` (via the staleness gate
#              below) and Chrome-for-Testing download; warm runs still need
#              network for Google Fonts unless AE_TEST_BLOCK_HOSTS scenarios
#              intentionally block them.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS_DIR="$REPO_DIR/scripts"
CHECK_JS="$SCRIPTS_DIR/check-slide-overflow.js"

lockfile_in_sync() {
  node -e '
    const fs = require("fs");
    function norm(p) {
      const data = JSON.parse(fs.readFileSync(p, "utf8"));
      const packages = { ...(data.packages || {}) };
      delete packages[""];
      return JSON.stringify(packages);
    }
    process.exit(norm(process.argv[1]) === norm(process.argv[2]) ? 0 : 1);
  ' "$1" "$2"
}

if [ ! -x "$SCRIPTS_DIR/node_modules/.bin/marp" ] \
  || [ ! -f "$SCRIPTS_DIR/node_modules/.package-lock.json" ] \
  || ! lockfile_in_sync "$SCRIPTS_DIR/node_modules/.package-lock.json" "$SCRIPTS_DIR/package-lock.json"; then
  if ! npm ci --prefix "$SCRIPTS_DIR" --no-audit --no-fund; then
    echo "check-slide-overflow-live-selftest: npm ci --prefix scripts failed" >&2
    exit 1
  fi
fi

MARP="$SCRIPTS_DIR/node_modules/.bin/marp"

FAILED=0
_pass() { echo "PASS: $1"; }
_fail() { echo "FAIL: $1"; FAILED=1; }

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/slide-overflow-selftest.XXXXXX")"
cleanup() { rm -rf "$TMP_ROOT"; }
trap cleanup EXIT

FRONTMATTER="$TMP_ROOT/frontmatter.txt"
sed -n '1,153p' "$REPO_DIR/docs/slides/how-it-works-slides.md" > "$FRONTMATTER"

# Fixture A: one short clean slide.
FIXTURE_A_MD="$TMP_ROOT/fixtureA.md"
cat "$FRONTMATTER" > "$FIXTURE_A_MD"
cat >> "$FIXTURE_A_MD" <<'EOF'

<!-- _class: lead -->

## clean-slide

A short clean slide with almost no content.
EOF

# Fixture B: a slide with a callout containing enough repeated text to
# clearly overflow (target >800px).
FIXTURE_B_MD="$TMP_ROOT/fixtureB.md"
cat "$FRONTMATTER" > "$FIXTURE_B_MD"
{
  echo ""
  echo "## overflow-slide"
  echo ""
  echo '<div class="callout">'
  for i in $(seq 1 60); do
    echo "This is repeated filler text designed to overflow the 720px slide boundary by a wide margin. Line number ${i}."
    echo ""
  done
  echo '</div>'
} >> "$FIXTURE_B_MD"

FIXTURE_A_HTML="$TMP_ROOT/fixtureA.html"
FIXTURE_B_HTML="$TMP_ROOT/fixtureB.html"

if ! "$MARP" --no-stdin "$FIXTURE_A_MD" -o "$FIXTURE_A_HTML" >/dev/null 2>&1; then
  echo "check-slide-overflow-live-selftest: marp render failed for fixtureA.md" >&2
  exit 1
fi
if ! "$MARP" --no-stdin "$FIXTURE_B_MD" -o "$FIXTURE_B_HTML" >/dev/null 2>&1; then
  echo "check-slide-overflow-live-selftest: marp render failed for fixtureB.md" >&2
  exit 1
fi

EMPTY_BASELINE="$TMP_ROOT/empty-baseline.json"
echo '{}' > "$EMPTY_BASELINE"

# --- Scenario 1: clean fixture -> exit 0 ---
out1="$(node "$CHECK_JS" --deck "$FIXTURE_A_HTML" --baseline "$EMPTY_BASELINE" 2>&1)"
rc1=$?
if [ "$rc1" -eq 0 ]; then
  _pass "clean fixture exits 0"
else
  _fail "clean fixture exited $rc1 (expected 0): $out1"
fi

# --- Scenario 6 (checked here, alongside scenario 1's normal online run) ---
if echo "$out1" | grep -q "FONT LOAD ERROR"; then
  _fail "clean fixture's normal online run unexpectedly reported a FONT LOAD ERROR: $out1"
else
  _pass "clean fixture's normal online run reports no FONT LOAD ERROR"
fi

# --- Scenario 2: overflow fixture -> exit 1, OVERFLOW line naming its slide id ---
out2="$(node "$CHECK_JS" --deck "$FIXTURE_B_HTML" --baseline "$EMPTY_BASELINE" 2>&1)"
rc2=$?
if [ "$rc2" -eq 1 ]; then
  _pass "overflow fixture exits 1"
else
  _fail "overflow fixture exited $rc2 (expected 1): $out2"
fi
# Marp assigns purely numeric section ids (not derived from heading text);
# fixtureB has exactly one content slide after the frontmatter, so its id is
# "1" (measured).
if echo "$out2" | grep -q "OVERFLOW fixtureB.html slide 1"; then
  _pass "overflow fixture's OVERFLOW line names fixtureB's slide id"
else
  _fail "overflow fixture's output did not name the overflowing slide id: $out2"
fi

# --- Scenario 3: context-count guard - exactly 2 context-created lines for 2 decks ---
out3="$(AE_DEBUG_CONTEXT_COUNT=1 node "$CHECK_JS" --deck "$FIXTURE_A_HTML" --deck "$FIXTURE_B_HTML" --baseline "$EMPTY_BASELINE" 2>&1)"
count3="$(echo "$out3" | grep -c '^context-created$')"
if [ "$count3" -eq 2 ]; then
  _pass "two decks produce exactly 2 context-created lines"
else
  _fail "expected exactly 2 context-created lines for 2 decks, got $count3: $out3"
fi

# --- Scenario 4: font partial-failure (block gstatic, the font FILE host) ---
out4="$(AE_TEST_BLOCK_HOSTS=fonts.gstatic.com node "$CHECK_JS" --deck "$FIXTURE_A_HTML" --baseline "$EMPTY_BASELINE" 2>&1)"
rc4=$?
if [ "$rc4" -eq 2 ]; then
  _pass "blocking fonts.gstatic.com exits 2"
else
  _fail "blocking fonts.gstatic.com exited $rc4 (expected 2): $out4"
fi
if echo "$out4" | grep -q "font face(s) failed to load"; then
  _pass "blocking fonts.gstatic.com names the failed-to-load axis"
else
  _fail "blocking fonts.gstatic.com did not name the failed-to-load axis: $out4"
fi

# --- Scenario 5: font offline (block both googleapis CSS host and gstatic file host) ---
out5="$(AE_TEST_BLOCK_HOSTS=fonts.googleapis.com,fonts.gstatic.com node "$CHECK_JS" --deck "$FIXTURE_A_HTML" --baseline "$EMPTY_BASELINE" 2>&1)"
rc5=$?
if [ "$rc5" -eq 2 ]; then
  _pass "blocking both font hosts exits 2"
else
  _fail "blocking both font hosts exited $rc5 (expected 2): $out5"
fi
# Measured (not assumed): blocking fonts.googleapis.com prevents the @import
# CSS itself from ever being fetched, so no @font-face rule is ever parsed
# and document.fonts.size is 0 - the "no fonts registered" axis, not the
# "failed to load" axis (which requires the CSS to have loaded but the font
# FILE fetch specifically to fail, as in scenario 4).
if echo "$out5" | grep -q "no fonts registered"; then
  _pass "blocking both font hosts names the no-fonts-registered axis (the @import CSS itself never loads)"
else
  _fail "blocking both font hosts did not name the expected axis: $out5"
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "check-slide-overflow-live-selftest: ALL SCENARIOS PASSED"
  exit 0
else
  echo "check-slide-overflow-live-selftest: ONE OR MORE SCENARIOS FAILED" >&2
  exit 1
fi
