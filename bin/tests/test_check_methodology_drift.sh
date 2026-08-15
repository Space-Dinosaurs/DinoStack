#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-methodology-drift.sh, the per-file
#          methodology baseline gate introduced by DS-174. Exercises: clean
#          match, per-file hash mismatch, path-set additions/deletions/renames,
#          manifest parse rejections (legacy single-hash format, malformed data
#          lines, duplicate basenames, non-canonical comment lines), the CI
#          hard-fail when neither sha256sum nor shasum exists, and
#          --regenerate atomicity/idempotency.
#
# Public API: ./bin/tests/test_check_methodology_drift.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, cp, seq, grep, awk, wc. sha256sum or shasum -a 256
#                (the suite hard-fails if neither exists).
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script or build script missing -> immediate FAIL. Any
#                scenario's observed exit code or message does not match the
#                expected shape -> FAIL naming the scenario and what was observed.
#
# Test hygiene: never mutates any tracked file in the working tree. All fixture
#               repos live under a mktemp -d directory removed on exit via trap.
#               Does not touch network. Runs correctly from any cwd.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-methodology-drift.sh"
BUILD_SCRIPT="$REPO_DIR/scripts/build-methodology.sh"

if [[ ! -f "$GATE_SCRIPT" ]]; then
  echo "FAIL: $GATE_SCRIPT not found" >&2
  exit 1
fi
if [[ ! -f "$BUILD_SCRIPT" ]]; then
  echo "FAIL: $BUILD_SCRIPT not found" >&2
  exit 1
fi

# Up-front guard: the gate and every scenario below need a working hasher.
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
  echo "FAIL: neither sha256sum nor shasum available; cannot hash fixture files" >&2
  exit 1
fi

BASH_PATH="$(command -v bash)"

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

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  rm -rf "$TMP_ROOT"
}
trap _cleanup EXIT

CANONICAL_HEADER='# methodology baseline: one <basename> <sha256> line per content/sections/[0-9][0-9]-*.md'

# --- Build a scratch fixture repo the gate can run against. Mirrors the
#     resident-budget test's fixture pattern: copies the real scripts into the
#     fixture so REPO_DIR resolves inside the fixture.
# $1 = fixture dir.
build_fixture() {
  local dir="$1"
  mkdir -p "$dir/scripts" "$dir/content/sections"
  cp "$GATE_SCRIPT" "$dir/scripts/check-methodology-drift.sh"
  cp "$BUILD_SCRIPT" "$dir/scripts/build-methodology.sh"
  local n
  for n in $(seq -w 1 12); do
    printf 'section %s\n' "$n" > "$dir/content/sections/${n}-fixture.md"
  done
}

# --- Base fixture: 12 files + a regenerated manifest. Cloned by each scenario.
BASE="$TMP_ROOT/base"
build_fixture "$BASE"
if ! (cd "$BASE" && bash scripts/check-methodology-drift.sh --regenerate) >/dev/null 2>&1; then
  echo "FAIL: base fixture --regenerate failed" >&2
  exit 1
fi

# --- Scenario (a): clean match ---
A="$TMP_ROOT/a"
cp -R "$BASE" "$A"
a_out="$(cd "$A" && bash scripts/check-methodology-drift.sh 2>&1)"
a_rc=$?
if [[ $a_rc -eq 0 && "$a_out" == "methodology drift check: OK (12 files)" ]]; then
  _pass "(a) clean 12-file match exits 0 printing the pinned OK line"
else
  _fail "(a) clean match expected rc=0 and 'methodology drift check: OK (12 files)', got rc=$a_rc out=[$a_out]"
fi

# --- Scenario (b): byte-edit a section file -> hash mismatch ---
B="$TMP_ROOT/b"
cp -R "$BASE" "$B"
printf 'tamper\n' >> "$B/content/sections/04-fixture.md"
b_out="$(cd "$B" && bash scripts/check-methodology-drift.sh 2>&1)"
b_rc=$?
if [[ $b_rc -ne 0 ]] && echo "$b_out" | grep -q '04-fixture.md' && echo "$b_out" | grep -q 'expected:' && echo "$b_out" | grep -q 'current:'; then
  _pass "(b) byte-edit fires a hash mismatch naming the basename + expected/current"
else
  _fail "(b) byte-edit expected rc!=0 + basename + expected/current hashes, got rc=$b_rc out=[$b_out]"
fi

# --- Scenario (c): add a 13th section -> path-set mismatch (extra) ---
C="$TMP_ROOT/c"
cp -R "$BASE" "$C"
printf 'section 13\n' > "$C/content/sections/13-extra.md"
c_out="$(cd "$C" && bash scripts/check-methodology-drift.sh 2>&1)"
c_rc=$?
if [[ $c_rc -ne 0 ]] && echo "$c_out" | grep -q '13-extra.md'; then
  _pass "(c) added section fires a path-set mismatch naming the extra basename"
else
  _fail "(c) added section expected rc!=0 naming 13-extra.md, got rc=$c_rc out=[$c_out]"
fi

# --- Scenario (d): delete a section -> path-set mismatch (missing) ---
D="$TMP_ROOT/d"
cp -R "$BASE" "$D"
rm "$D/content/sections/05-fixture.md"
d_out="$(cd "$D" && bash scripts/check-methodology-drift.sh 2>&1)"
d_rc=$?
if [[ $d_rc -ne 0 ]] && echo "$d_out" | grep -q '05-fixture.md'; then
  _pass "(d) deleted section fires a path-set mismatch naming the missing basename"
else
  _fail "(d) deleted section expected rc!=0 naming 05-fixture.md, got rc=$d_rc out=[$d_out]"
fi

# --- Scenario (e): rename/renumber -> path-set mismatch naming missing + extra ---
E="$TMP_ROOT/e"
cp -R "$BASE" "$E"
mv "$E/content/sections/03-fixture.md" "$E/content/sections/13-fixture.md"
e_out="$(cd "$E" && bash scripts/check-methodology-drift.sh 2>&1)"
e_rc=$?
if [[ $e_rc -ne 0 ]] && echo "$e_out" | grep -q '03-fixture.md' && echo "$e_out" | grep -q '13-fixture.md'; then
  _pass "(e) rename/renumber fires a path-set mismatch naming both missing and extra"
else
  _fail "(e) rename expected rc!=0 naming 03-fixture.md and 13-fixture.md, got rc=$e_rc out=[$e_out]"
fi

# --- Scenario (f): duplicate basename in manifest -> rejected ---
F="$TMP_ROOT/f"
cp -R "$BASE" "$F"
dup_line="$(grep '^02-fixture.md ' "$F/scripts/.methodology-baseline.sha256")"
printf '%s\n' "$dup_line" >> "$F/scripts/.methodology-baseline.sha256"
f_out="$(cd "$F" && bash scripts/check-methodology-drift.sh 2>&1)"
f_rc=$?
if [[ $f_rc -ne 0 ]] && echo "$f_out" | grep -q 'duplicate basename'; then
  _pass "(f) duplicate basename in manifest is rejected"
else
  _fail "(f) duplicate basename expected rc!=0 + 'duplicate basename', got rc=$f_rc out=[$f_out]"
fi

# --- Scenario (g1): legacy single-hash manifest -> rejected with --regenerate hint ---
G1="$TMP_ROOT/g1"
cp -R "$BASE" "$G1"
printf 'f761e5b5e50f138018269d33dc704de5376762e4f7efac388c3b8c8588b06a35\n' > "$G1/scripts/.methodology-baseline.sha256"
g1_out="$(cd "$G1" && bash scripts/check-methodology-drift.sh 2>&1)"
g1_rc=$?
if [[ $g1_rc -ne 0 ]] && echo "$g1_out" | grep -q -- '--regenerate'; then
  _pass "(g1) legacy single-hash manifest is rejected with a --regenerate hint"
else
  _fail "(g1) legacy single-hash manifest expected rc!=0 + --regenerate hint, got rc=$g1_rc out=[$g1_out]"
fi

# --- Scenario (g2): missing manifest -> exit 1 with --regenerate hint ---
G2="$TMP_ROOT/g2"
cp -R "$BASE" "$G2"
rm "$G2/scripts/.methodology-baseline.sha256"
g2_out="$(cd "$G2" && bash scripts/check-methodology-drift.sh 2>&1)"
g2_rc=$?
if [[ $g2_rc -ne 0 ]] && echo "$g2_out" | grep -q -- '--regenerate'; then
  _pass "(g2) missing manifest exits 1 with a --regenerate hint"
else
  _fail "(g2) missing manifest expected rc!=0 + --regenerate hint, got rc=$g2_rc out=[$g2_out]"
fi

# --- Scenario (h): malformed line (3 fields) -> exit 1 ---
H="$TMP_ROOT/h"
cp -R "$BASE" "$H"
printf '01-fixture.md abc123 xyz\n' >> "$H/scripts/.methodology-baseline.sha256"
h_out="$(cd "$H" && bash scripts/check-methodology-drift.sh 2>&1)"
h_rc=$?
if [[ $h_rc -ne 0 ]] && echo "$h_out" | grep -q 'malformed'; then
  _pass "(h) malformed data line (3 fields) is rejected"
else
  _fail "(h) malformed 3-field line expected rc!=0 + 'malformed', got rc=$h_rc out=[$h_out]"
fi

# --- Scenario (i): CI hard-fail when neither hasher exists ---
I="$TMP_ROOT/i"
cp -R "$BASE" "$I"
i_out="$(cd "$I" && env PATH="/nonexistent" CI=true "$BASH_PATH" scripts/check-methodology-drift.sh 2>&1)"
i_rc=$?
if [[ $i_rc -ne 0 ]] && echo "$i_out" | grep -q 'neither sha256sum nor shasum'; then
  _pass "(i) CI=true with no hasher on PATH hard-fails with a diagnostic (not a skip)"
else
  _fail "(i) CI hard-fail expected rc!=0 + 'neither sha256sum nor shasum', got rc=$i_rc out=[$i_out]"
fi

# --- Scenario (j): --regenerate emits header + 12 data lines; idempotent ---
J="$TMP_ROOT/j"
cp -R "$BASE" "$J"
(cd "$J" && bash scripts/check-methodology-drift.sh --regenerate) >/dev/null 2>&1
j1="$(cat "$J/scripts/.methodology-baseline.sha256")"
j_total="$(wc -l < "$J/scripts/.methodology-baseline.sha256" | tr -d ' ')"
j_data="$(grep -c '^[0-9]' "$J/scripts/.methodology-baseline.sha256")"
j_header="$(head -1 "$J/scripts/.methodology-baseline.sha256")"
j_names="$(grep '^[0-9]' "$J/scripts/.methodology-baseline.sha256" | awk '{print $1}')"
j_sorted="$(printf '%s\n' "$j_names" | sort)"
(cd "$J" && bash scripts/check-methodology-drift.sh --regenerate) >/dev/null 2>&1
j2="$(cat "$J/scripts/.methodology-baseline.sha256")"
if [[ "$j_total" == "13" && "$j_data" == "12" && "$j_header" == "$CANONICAL_HEADER" && "$j_names" == "$j_sorted" && "$j1" == "$j2" ]]; then
  _pass "(j) --regenerate writes header+12 sorted data lines and is idempotent"
else
  _fail "(j) regenerate expected 13 total/12 data/canonical header/sorted/idempotent; got total=$j_total data=$j_data header=[$j_header] sorted=$([ "$j_names" == "$j_sorted" ] && echo yes || echo no) idempotent=$([ "$j1" == "$j2" ] && echo yes || echo no)"
fi

# --- Header-rejection: a non-canonical comment line -> exit 1 ---
K="$TMP_ROOT/k"
cp -R "$BASE" "$K"
printf '# some other comment\n' >> "$K/scripts/.methodology-baseline.sha256"
k_out="$(cd "$K" && bash scripts/check-methodology-drift.sh 2>&1)"
k_rc=$?
if [[ $k_rc -ne 0 ]] && echo "$k_out" | grep -q 'unexpected comment'; then
  _pass "non-canonical comment line is rejected"
else
  _fail "non-canonical comment line expected rc!=0 + 'unexpected comment', got rc=$k_rc out=[$k_out]"
fi

# --- Unknown arg -> usage, exit 2 ---
L="$TMP_ROOT/l"
cp -R "$BASE" "$L"
l_out="$(cd "$L" && bash scripts/check-methodology-drift.sh --bogus 2>&1)"
l_rc=$?
if [[ $l_rc -eq 2 ]] && echo "$l_out" | grep -q 'usage:'; then
  _pass "unknown argument exits 2 with usage on stderr"
else
  _fail "unknown argument expected rc=2 + usage, got rc=$l_rc out=[$l_out]"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
