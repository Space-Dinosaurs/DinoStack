#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-npm-audit.sh. The gate's whole
#          value is its failure PREDICATE - "an advisory with a non-breaking
#          fix available", not "an advisory of severity >= high" - so these
#          scenarios drive the predicate directly through the gate's
#          --classify mode with pre-captured npm audit --json payloads.
#
#          --classify exists precisely so this suite can be deterministic:
#          live mode's verdict against the REAL registry changes whenever the
#          upstream advisory database changes, so a test asserting on that
#          would be a test of npmjs.com, and would go red on an unrelated day.
#
#          LIVE MODE IS NONETHELESS COVERED, by a stub `npm` on PATH in a
#          scratch tree (scenarios 14+). Determinism is what --classify buys,
#          and a stub buys the same thing without giving up coverage: the
#          ${CI} split, the missing-lockfile exit 2, the multi-manifest
#          aggregation loop, and the precedence between a detected advisory
#          and a manifest that could not be audited are all live-mode-only
#          code, and a suite that drove only --classify asserted NOTHING
#          about any of them. That gap is how a bug shipped in which an
#          actionable advisory found in one manifest was silently discarded
#          when a later manifest failed to audit, printing its own FAIL line
#          and then exiting 0 SKIPPED. Scenario 16 is that regression.
#
#          The load-bearing scenario is the one that separates "the audit
#          found nothing" from "the audit did not run": npm emits a bare
#          {message, error} object when the advisory endpoint is
#          unreachable, and that payload parses as valid JSON with no
#          vulnerabilities key. A classifier that counted keys would read it
#          as zero vulnerabilities and go green having asserted nothing.
#
# Public API: ./bin/tests/test_check_npm_audit.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, node (the gate's classifier is node; node is
#                required, never skipped - a skip here would be
#                indistinguishable from a pass). zsh is required for the
#                bash/zsh parity assertion when running under CI (the
#                assertion FAILS if zsh is absent under CI); locally it is
#                skipped so contributors without zsh can run the rest.
#
# Downstream consumers: developer running locally before commit;
#                        scripts/check-local.sh (via the bin-sh-tests loop);
#                        CI (the bin-sh-tests job in bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script missing -> immediate FAIL. Any scenario whose
#                observed exit code or output does not match the expected
#                shape -> FAIL naming the scenario and what was observed.
#
# Test hygiene: never mutates any tracked file. Every fixture lives under a
#               mktemp -d removed on exit via trap. NEVER touches the network:
#               --classify scenarios do not invoke npm at all, and live-mode
#               scenarios run against a stub `npm` on a PATH this file sets,
#               inside a scratch tree, never the real npm and never the real
#               registry. The gate script under test
#               is COPIED from the working tree for those, so a mutation to
#               scripts/check-npm-audit.sh is picked up here. Runs correctly
#               from any cwd.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-npm-audit.sh"

if [[ ! -f "$GATE_SCRIPT" ]]; then
  echo "FAIL: $GATE_SCRIPT not found" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "FAIL: node not on PATH - the gate's classifier is node, so this suite" >&2
  echo "      cannot assert anything without it. Refusing to skip." >&2
  exit 1
fi

PASS=0
FAIL=0

_fail() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

_pass() {
  echo "pass: $1"
  PASS=$((PASS + 1))
}

TMP_ROOT="$(mktemp -d -t check-npm-audit-tests.XXXXXX)"
trap 'rm -rf "$TMP_ROOT"' EXIT

# write_fixture <name> <json>
write_fixture() {
  printf '%s\n' "$2" >"$TMP_ROOT/$1.json"
  printf '%s' "$TMP_ROOT/$1.json"
}

# run_classify <fixture-path> -> sets RC and OUT
RC=0
OUT=""
run_classify() {
  OUT="$(bash "$GATE_SCRIPT" --classify "$1" 2>&1)"
  RC=$?
}

# expect <label> <fixture-path> <expected-rc> [substring that must appear]
expect() {
  local label="$1" path="$2" want="$3" needle="${4:-}"
  run_classify "$path"
  if [[ "$RC" -ne "$want" ]]; then
    _fail "$label: expected exit $want, got $RC. Output: $OUT"
    return
  fi
  if [[ -n "$needle" && "$OUT" != *"$needle"* ]]; then
    _fail "$label: exit $RC correct but output lacked '$needle'. Output: $OUT"
    return
  fi
  _pass "$label"
}

# --- Scenario 1: actionable, fixAvailable object with isSemVerMajor false ---
# The core positive case. This is the js-yaml/brace-expansion shape: a fix
# exists and does not break anything, so somebody can act on it today.
F_ACTIONABLE="$(write_fixture actionable '{
  "auditReportVersion": 2,
  "vulnerabilities": {
    "js-yaml": {
      "name": "js-yaml",
      "severity": "high",
      "fixAvailable": { "name": "js-yaml", "version": "3.13.1", "isSemVerMajor": false }
    }
  },
  "metadata": { "vulnerabilities": { "high": 1, "total": 1 } }
}')"
expect "actionable advisory (non-breaking fix) fails the gate" \
  "$F_ACTIONABLE" 1 "ACTIONABLE"

# --- Scenario 2: actionable, fixAvailable === true -------------------------
# npm uses a bare boolean when the fix needs no top-level version change.
F_TRUE="$(write_fixture fix_true '{
  "auditReportVersion": 2,
  "vulnerabilities": {
    "brace-expansion": {
      "name": "brace-expansion",
      "severity": "high",
      "fixAvailable": true
    }
  },
  "metadata": { "vulnerabilities": { "high": 1, "total": 1 } }
}')"
expect "actionable advisory (fixAvailable === true) fails the gate" \
  "$F_TRUE" 1 "ACTIONABLE"

# --- Scenario 3: breaking-only passes -------------------------------------
# This is the exact shape scripts/package-lock.json carries on main today:
# four high-severity advisories whose only remedy is a semver-major
# downgrade of @marp-team/marp-cli. The gate MUST pass, or main is red
# permanently and the gate gets ignored or ripped out.
F_BREAKING="$(write_fixture breaking '{
  "auditReportVersion": 2,
  "vulnerabilities": {
    "extract-zip": {
      "name": "extract-zip",
      "severity": "high",
      "fixAvailable": { "name": "@marp-team/marp-cli", "version": "2.4.0", "isSemVerMajor": true }
    }
  },
  "metadata": { "vulnerabilities": { "high": 1, "total": 1 } }
}')"
expect "breaking-only advisory passes the gate" \
  "$F_BREAKING" 0 "breaking-only"

# --- Scenario 4: unfixable passes ------------------------------------------
F_UNFIXABLE="$(write_fixture unfixable '{
  "auditReportVersion": 2,
  "vulnerabilities": {
    "some-pkg": {
      "name": "some-pkg",
      "severity": "critical",
      "fixAvailable": false
    }
  },
  "metadata": { "vulnerabilities": { "critical": 1, "total": 1 } }
}')"
expect "unfixable advisory passes the gate even at critical severity" \
  "$F_UNFIXABLE" 0 "unfixable"

# --- Scenario 5: mixed - one actionable among breaking-only ----------------
# Guards against a bucket-counting bug where a large standing population
# masks a single actionable advisory.
F_MIXED="$(write_fixture mixed '{
  "auditReportVersion": 2,
  "vulnerabilities": {
    "extract-zip": {
      "name": "extract-zip",
      "severity": "high",
      "fixAvailable": { "name": "@marp-team/marp-cli", "version": "2.4.0", "isSemVerMajor": true }
    },
    "puppeteer-core": {
      "name": "puppeteer-core",
      "severity": "high",
      "fixAvailable": { "name": "@marp-team/marp-cli", "version": "2.4.0", "isSemVerMajor": true }
    },
    "js-yaml": {
      "name": "js-yaml",
      "severity": "moderate",
      "fixAvailable": { "name": "js-yaml", "version": "3.13.1", "isSemVerMajor": false }
    }
  },
  "metadata": { "vulnerabilities": { "high": 2, "moderate": 1, "total": 3 } }
}')"
expect "one actionable advisory among breaking-only ones still fails" \
  "$F_MIXED" 1 "js-yaml"

# --- Scenario 6: clean report passes ---------------------------------------
F_CLEAN="$(write_fixture clean '{
  "auditReportVersion": 2,
  "vulnerabilities": {},
  "metadata": { "vulnerabilities": { "total": 0 } }
}')"
expect "clean report passes" "$F_CLEAN" 0 "no actionable advisory"

# --- Scenario 7: endpoint failure is exit 2, NOT exit 0 --------------------
# The load-bearing scenario. This is the literal payload npm 11.4.2 writes to
# stdout when the advisory endpoint is unreachable (captured against an
# unroutable registry). It is valid JSON with no vulnerabilities key, so a
# naive classifier reads it as "0 vulnerabilities" and goes green.
F_ENDPOINT="$(write_fixture endpoint_failure '{
  "message": "request to https://registry.npmjs.org/-/npm/v1/security/advisories/bulk failed, reason: connect ECONNREFUSED",
  "error": { "summary": "", "detail": "" }
}')"
expect "registry failure payload is exit 2 (did-not-run), never 0" \
  "$F_ENDPOINT" 2 "the audit did not run"

# --- Scenario 8: malformed JSON is exit 2 ----------------------------------
F_MALFORMED="$(write_fixture malformed 'not json at all {{{')"
expect "malformed payload is exit 2" "$F_MALFORMED" 2 "not JSON"

# --- Scenario 9: report with no vulnerabilities KEY is exit 2 --------------
# Distinct from scenario 7: a payload that has auditReportVersion but whose
# vulnerabilities key is missing entirely is still "did not run", not clean.
F_NOVULNKEY="$(write_fixture no_vuln_key '{ "auditReportVersion": 2 }')"
expect "report lacking a vulnerabilities key is exit 2, not a clean pass" \
  "$F_NOVULNKEY" 2 "the audit did not run"

# --- Scenario 9b: a vulnerabilities object with NO auditReportVersion ------
# Isolates the auditReportVersion clause of the did-not-run guard. Scenarios
# 7 and 9 are both caught by the sibling `vulnerabilities` clause alone, so
# without this fixture the auditReportVersion clause has no reddening
# mutation - deleting it leaves the suite green. This payload is the one
# shape where the two clauses disagree: a well-formed empty vulnerabilities
# map with no report version is a truncated/partial response, not a clean
# audit, and reading it as "0 vulnerabilities" is the exact no-op-as-zero
# failure this guard exists to prevent.
F_NOVERSION="$(write_fixture no_report_version '{ "vulnerabilities": {} }')"
expect "a vulnerabilities map with no auditReportVersion is exit 2, not a clean pass" \
  "$F_NOVERSION" 2 "the audit did not run"

# --- Scenario 9c: a bare `null` payload is exit 2 --------------------------
# Isolates the `report === null` clause of the did-not-run guard. Without this
# fixture that clause has no reddening mutation: deleting it lets `typeof null
# === "object"` pass, and the very next property read throws a TypeError, so
# the classifier CRASHES instead of reporting. The exit code alone does not
# discriminate (a crash is mapped to did-not-run too, deliberately), so the
# assertion is on the MESSAGE - a reported did-not-run says so in words, a
# crash prints a node stack trace instead.
F_NULL="$(write_fixture null_payload 'null')"
expect "a bare null payload is a reported exit 2, not a classifier crash" \
  "$F_NULL" 2 "the audit did not run"

# --- Scenario 10: unrecognised fixAvailable shape fails toward noticing ----
F_WEIRD="$(write_fixture weird_shape '{
  "auditReportVersion": 2,
  "vulnerabilities": {
    "odd-pkg": { "name": "odd-pkg", "severity": "low", "fixAvailable": "maybe" }
  },
  "metadata": { "vulnerabilities": { "low": 1, "total": 1 } }
}')"
expect "unrecognised fixAvailable shape is treated as actionable" \
  "$F_WEIRD" 1 "unrecognised fixAvailable shape"

# --- Scenario 11: argument handling ---------------------------------------
OUT="$(bash "$GATE_SCRIPT" --classify "$TMP_ROOT/does-not-exist.json" 2>&1)"
RC=$?
if [[ "$RC" -eq 2 && "$OUT" == *"not found"* ]]; then
  _pass "--classify on a missing file is exit 2"
else
  _fail "--classify on a missing file: expected exit 2 and 'not found', got $RC: $OUT"
fi

OUT="$(bash "$GATE_SCRIPT" --bogus-flag 2>&1)"
RC=$?
if [[ "$RC" -eq 2 && "$OUT" == *"unknown argument"* ]]; then
  _pass "unknown argument is exit 2"
else
  _fail "unknown argument: expected exit 2 and 'unknown argument', got $RC: $OUT"
fi

OUT="$(bash "$GATE_SCRIPT" --classify 2>&1)"
RC=$?
if [[ "$RC" -eq 2 ]]; then
  _pass "--classify with no file argument is exit 2"
else
  _fail "--classify with no argument: expected exit 2, got $RC: $OUT"
fi

# An EMPTY --classify path must be a usage error, never a silent fall-through
# to a live network audit. Deriving "are we classifying?" from the filename
# being non-empty made `--classify ""` run the exact thing the caller asked
# not to run. The second assertion is the load-bearing one: exit 2 alone could
# also be a live audit that failed, so this checks no live audit was attempted.
OUT="$(bash "$GATE_SCRIPT" --classify "" 2>&1)"
RC=$?
if [[ "$RC" -eq 2 && "$OUT" != *"auditing"* ]]; then
  _pass "--classify with an empty path is exit 2 and runs no live audit"
else
  _fail "--classify '': expected exit 2 with no live audit, got $RC: $OUT"
fi

# --- Scenario 12: both real lockfiles are in the gate's coverage -----------
# A coverage assertion, not a predicate one. If a manifest is added or the
# MANIFEST_DIRS list is trimmed, this fails rather than letting the gate
# quietly audit less than the repo actually ships.
for lock in package-lock.json scripts/package-lock.json; do
  if [[ -f "$REPO_DIR/$lock" ]]; then
    _pass "lockfile present in repo: $lock"
  else
    _fail "expected lockfile missing from repo: $lock (update MANIFEST_DIRS and this list together)"
  fi
done

MANIFEST_LINE="$(grep -n '^MANIFEST_DIRS=' "$GATE_SCRIPT")"
if [[ "$MANIFEST_LINE" == *'"."'* && "$MANIFEST_LINE" == *'"scripts"'* ]]; then
  _pass "MANIFEST_DIRS covers both the root and scripts manifests"
else
  _fail "MANIFEST_DIRS does not cover both manifests: $MANIFEST_LINE"
fi

# --- Scenario 13: bash/zsh parity -----------------------------------------
# The gate runs under whatever shell a contributor or CI invokes it with.
# AGENTS.md records a gate that iterated once under zsh while printing ALL
# PASS under bash.
if command -v zsh >/dev/null 2>&1; then
  bash_out="$(bash "$GATE_SCRIPT" --classify "$F_MIXED" 2>&1)"
  bash_rc=$?
  zsh_out="$(zsh "$GATE_SCRIPT" --classify "$F_MIXED" 2>&1)"
  zsh_rc=$?
  if [[ "$bash_rc" -eq "$zsh_rc" && "$bash_out" == "$zsh_out" ]]; then
    _pass "bash and zsh produce identical exit code and output"
  else
    _fail "bash/zsh diverged - bash($bash_rc): [$bash_out] zsh($zsh_rc): [$zsh_out]"
  fi
elif [[ -n "${CI:-}" ]]; then
  _fail "zsh absent on PATH in CI - the parity assertion cannot be skipped here"
else
  echo "SKIP: zsh not on PATH - skipping parity assertion (local only; CI fails instead)"
fi

# ===========================================================================
# LIVE MODE (scenarios 14+). No network: a stub `npm` is prepended to PATH in
# a scratch tree, so every live-mode branch below is exercised against a
# payload this file controls. The gate script is copied from the working tree,
# so mutating scripts/check-npm-audit.sh reddens these.
# ===========================================================================
BASH_BIN="$(command -v bash)"
LIVE_ROOT="$TMP_ROOT/live"
LIVE_TREE="$LIVE_ROOT/tree"
LIVE_BIN="$LIVE_ROOT/bin"
mkdir -p "$LIVE_TREE/scripts" "$LIVE_BIN"

# The stub reads the payload for each manifest from a file next to itself, so
# each scenario sets the two payloads and needs no environment plumbing.
cat >"$LIVE_BIN/npm" <<'STUB'
#!/usr/bin/env bash
# Stub npm. Emits a canned `npm audit --json` payload per manifest, chosen by
# the --prefix the gate passes. Never touches the network.
stub_dir="$(cd "$(dirname "$0")" && pwd)"
prefix=""
take=""
for a in "$@"; do
  if [ -n "$take" ]; then prefix="$a"; take=""; fi
  if [ "$a" = "--prefix" ]; then take=1; fi
done
case "$prefix" in
  */scripts) cat "$stub_dir/scripts.json" ;;
  *)         cat "$stub_dir/root.json" ;;
esac
STUB
chmod +x "$LIVE_BIN/npm"

# A PATH entry holding node but deliberately NO npm, for the missing-npm
# branch. node must stay reachable: the gate checks node first, and this
# scenario is about what happens after that check passes.
NO_NPM_BIN="$LIVE_ROOT/nonpm"
mkdir -p "$NO_NPM_BIN"
ln -s "$(command -v node)" "$NO_NPM_BIN/node"
for t in mktemp rm; do
  if command -v "$t" >/dev/null 2>&1; then ln -s "$(command -v "$t")" "$NO_NPM_BIN/$t"; fi
done

# The two PATH values the live scenarios run under. LIVE_PATH prepends the
# stub so the gate finds it first; NO_NPM_PATH is the no-npm dir ALONE, since
# a prefix would leave the real npm reachable further down.
LIVE_PATH="$LIVE_BIN:$PATH"
NO_NPM_PATH="$NO_NPM_BIN"

# set_payloads <root-json> <scripts-json>
set_payloads() {
  printf '%s\n' "$1" >"$LIVE_BIN/root.json"
  printf '%s\n' "$2" >"$LIVE_BIN/scripts.json"
}

P_ACTIONABLE='{"auditReportVersion":2,"vulnerabilities":{"js-yaml":{"name":"js-yaml","severity":"high","fixAvailable":{"name":"js-yaml","version":"3.13.1","isSemVerMajor":false}}}}'
P_CLEAN='{"auditReportVersion":2,"vulnerabilities":{},"metadata":{"vulnerabilities":{"total":0}}}'
P_ENDPOINT='{"message":"request to https://registry.npmjs.org/-/npm/v1/security/advisories/bulk failed, reason: connect ECONNREFUSED","error":{"summary":"","detail":""}}'

# run_live <tree-dir> <PATH-value> <ci-value, empty = off CI>
# The PATH is passed WHOLE, not as a prefix: the missing-npm scenario needs a
# PATH the real npm is not reachable through at all, and prepending a stub dir
# would leave it findable further down and assert nothing.
run_live() {
  local tree="$1" pathval="$2" ci="$3"
  if [[ -n "$ci" ]]; then
    OUT="$(CI="$ci" PATH="$pathval" "$BASH_BIN" "$tree/scripts/check-npm-audit.sh" 2>&1)"
  else
    OUT="$(unset CI; PATH="$pathval"; "$BASH_BIN" "$tree/scripts/check-npm-audit.sh" 2>&1)"
  fi
  RC=$?
}

# expect_live <label> <tree> <PATH-value> <ci> <expected-rc> [needle] [forbidden]
expect_live() {
  local label="$1" tree="$2" bindir="$3" ci="$4" want="$5"
  local needle="${6:-}" forbidden="${7:-}"
  run_live "$tree" "$bindir" "$ci"
  if [[ "$RC" -ne "$want" ]]; then
    _fail "$label: expected exit $want, got $RC. Output: $OUT"
    return
  fi
  if [[ -n "$needle" && "$OUT" != *"$needle"* ]]; then
    _fail "$label: exit $RC correct but output lacked '$needle'. Output: $OUT"
    return
  fi
  if [[ -n "$forbidden" && "$OUT" == *"$forbidden"* ]]; then
    _fail "$label: output contained forbidden text '$forbidden'. Output: $OUT"
    return
  fi
  _pass "$label"
}

# Fresh copy of the gate + two lockfiles the stub never reads (their CONTENT
# is irrelevant; their PRESENCE is what the gate checks).
install_live_tree() {
  cp "$GATE_SCRIPT" "$LIVE_TREE/scripts/check-npm-audit.sh"
  printf '{}\n' >"$LIVE_TREE/package-lock.json"
  printf '{}\n' >"$LIVE_TREE/scripts/package-lock.json"
}
install_live_tree

# --- Scenario 14: the ${CI} split -------------------------------------------
# Same condition, two outcomes, and the asymmetry is the whole safety argument
# for the off-CI skip existing at all. If the CI branch ever degrades to a
# skip, a CI job goes green having asserted nothing.
set_payloads "$P_ENDPOINT" "$P_ENDPOINT"
expect_live "live: unreachable registry under CI is a hard exit 2" \
  "$LIVE_TREE" "$LIVE_PATH" "1" 2 "the audit did not run under CI"
expect_live "live: unreachable registry off CI is a loud SKIPPED, exit 0" \
  "$LIVE_TREE" "$LIVE_PATH" "" 0 "SKIPPED"

# --- Scenario 15: both manifests audited, both clean ------------------------
# The aggregation loop's pass path. Also pins that the gate really does visit
# BOTH manifests rather than returning after the first.
set_payloads "$P_CLEAN" "$P_CLEAN"
expect_live "live: both manifests clean is exit 0" \
  "$LIVE_TREE" "$LIVE_PATH" "1" 0 "scripts/package-lock.json"

# --- Scenario 16: REGRESSION - a detected advisory is never discarded -------
# Manifest 1 yields an ACTIONABLE advisory; manifest 2 then fails to audit.
# The gate previously exited from inside the loop on manifest 2 WITHOUT
# consulting what manifest 1 found, so off CI it printed its own
# "FAIL: ... 1 actionable advisory" line and then exited 0 SKIPPED - the
# finding was real, reported, and thrown away. Both directions are asserted:
# the exit code is 1, and the output does not claim it skipped.
set_payloads "$P_ACTIONABLE" "$P_ENDPOINT"
expect_live "live: an actionable advisory outranks a later manifest failing to audit (off CI)" \
  "$LIVE_TREE" "$LIVE_PATH" "" 1 "js-yaml" "SKIPPED"
expect_live "live: the same case under CI is also a red, not a did-not-run 2" \
  "$LIVE_TREE" "$LIVE_PATH" "1" 1 "COVERAGE WAS INCOMPLETE"

# Order must not matter: the failing manifest first, the finding second.
set_payloads "$P_ENDPOINT" "$P_ACTIONABLE"
expect_live "live: same precedence when the unauditable manifest comes first" \
  "$LIVE_TREE" "$LIVE_PATH" "" 1 "js-yaml" "SKIPPED"

# --- Scenario 17: a CRASHING classifier is not a finding --------------------
# A crash inside the classifier must land on the did-not-run path, not be
# reported as an actionable advisory. node exits 1 on an uncaught exception,
# which is why the classifier's actionable verdict is 4 rather than 1: while
# both were 1 a crash was indistinguishable from a real finding and was
# announced as one - failing loud with the wrong diagnosis, sending the reader
# to hunt an advisory that does not exist.
#
# The payload must actually CRASH the classifier for this to assert anything.
# A bare `null` does not: the did-not-run guard catches it and reports
# cleanly, so a `null` fixture here reddens no mutation of the exit-code
# mapping (verified - it survived reverting the mapping). This payload gets
# PAST every guard (it is an object, has auditReportVersion, and its
# vulnerabilities value is a non-null object) and then throws on the null
# entry's property read. Crashing on it is acceptable precisely BECAUSE of
# the mapping under test: an unanticipated crash is reported as "the audit
# did not run", which is a red under CI, not a false green and not a false
# finding. That safety net is the general answer to malformed payloads; no
# classifier can enumerate every one of them in advance.
P_CRASH='{"auditReportVersion":2,"vulnerabilities":{"some-pkg":null}}'
set_payloads "$P_CRASH" "$P_CRASH"
expect_live "live: a classifier crash is a did-not-run, never 'actionable advisories found'" \
  "$LIVE_TREE" "$LIVE_PATH" "1" 2 "the audit did not run under CI" "actionable dependency advisories found"

# --- Scenario 18: a missing lockfile is exit 2 even OFF CI ------------------
# Not a skip and not subject to the ${CI} split: a renamed or deleted manifest
# must not silently shrink this gate's coverage to nothing. Asserted off CI
# precisely because that is the branch where a skip would be plausible.
MISSING_TREE="$LIVE_ROOT/missing/tree"
mkdir -p "$MISSING_TREE/scripts"
cp "$GATE_SCRIPT" "$MISSING_TREE/scripts/check-npm-audit.sh"
printf '{}\n' >"$MISSING_TREE/package-lock.json"   # root present, scripts/ absent
set_payloads "$P_CLEAN" "$P_CLEAN"
expect_live "live: a missing lockfile is exit 2 off CI, never a skip" \
  "$MISSING_TREE" "$LIVE_PATH" "" 2 "expected lockfile not found"

# --- Scenario 19: npm missing entirely --------------------------------------
# The gate's other did-not-run trigger, and the one scripts/check-local.sh
# depends on being a hard red under CI.
expect_live "live: npm absent under CI is exit 2" \
  "$LIVE_TREE" "$NO_NPM_PATH" "1" 2 "npm is not on PATH"
expect_live "live: npm absent off CI is a loud SKIPPED, exit 0" \
  "$LIVE_TREE" "$NO_NPM_PATH" "" 0 "SKIPPED"

echo
echo "passed: $PASS, failed: $FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
exit 0
