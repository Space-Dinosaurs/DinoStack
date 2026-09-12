#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-npm-audit.sh. The gate's whole
#          value is its failure PREDICATE - "an advisory with a non-breaking
#          fix available", not "an advisory of severity >= high" - so these
#          scenarios drive the predicate directly through the gate's
#          --classify mode with pre-captured npm audit --json payloads.
#
#          --classify exists precisely so this suite can be deterministic:
#          live mode's verdict changes whenever the upstream advisory
#          database changes, so a test asserting on live output would be a
#          test of npmjs.com, and would go red on an unrelated day.
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
#               mktemp -d removed on exit via trap. Never touches the
#               network - every scenario uses --classify, which does not
#               invoke npm at all. Runs correctly from any cwd.

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

echo
echo "passed: $PASS, failed: $FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
exit 0
