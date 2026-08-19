#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-kimi-skill-embed-budget.sh
#          (DS-185's Kimi equivalent of check-skill-embed-budget.sh -
#          flagged as needing a suite of its own, matching the three
#          pre-existing budget-gate suites, in the DS-185 round-2 review).
#          Exercises one executed mutation per axis: SKILL.md below FLOOR,
#          SKILL.md above CEILING, AGENTS.md above AGENTS_CEILING, a
#          section source file's heading dropped from SKILL.md (embed
#          incomplete), a section source file outright missing (count
#          below EXPECTED_SECTION_COUNT), a rules source file outright
#          added beyond EXPECTED_RULES_COUNT, and the pass path built from
#          the real repo's live-derived constants (never a hand-typed
#          copy).
#
# Public API: ./bin/tests/test_check_kimi_skill_embed_budget.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, wc, python3, grep, cut (FLOOR/CEILING/
#                AGENTS_CEILING/EXPECTED_SECTION_COUNT/EXPECTED_RULES_COUNT
#                are parsed out of the real gate script with grep|cut, so
#                this suite never hardcodes a copy that can drift from the
#                live values).
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script missing -> immediate FAIL. Any scenario's
#                observed exit code or message does not match the expected
#                shape -> FAIL naming the scenario and what was observed.
#
# Test hygiene: never mutates any tracked file in the working tree. Every
#               fixture lives under a mktemp -d directory removed on exit
#               via trap.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
GATE_SCRIPT="$REPO_ROOT/scripts/check-kimi-skill-embed-budget.sh"
LIB_SCRIPT="$REPO_ROOT/scripts/lib/budget-gate.sh"

PASS_COUNT=0
FAIL_COUNT=0

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "PASS: $1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "FAIL: $1"
}

if [[ ! -f "$GATE_SCRIPT" ]]; then
  echo "FAIL: gate script not found at $GATE_SCRIPT"
  exit 1
fi
if [[ ! -f "$LIB_SCRIPT" ]]; then
  echo "FAIL: shared lib not found at $LIB_SCRIPT"
  exit 1
fi

_parse_const() {
  # _parse_const <NAME> -> prints the integer value of NAME=<int> in the
  # real gate script. Never hand-typed - re-derived every run.
  grep -m1 "^$1=" "$GATE_SCRIPT" | cut -d= -f2
}

SKILL_FLOOR="$(_parse_const SKILL_FLOOR)"
SKILL_CEILING="$(_parse_const SKILL_CEILING)"
AGENTS_CEILING="$(_parse_const AGENTS_CEILING)"
EXPECTED_SECTION_COUNT="$(_parse_const EXPECTED_SECTION_COUNT)"
EXPECTED_RULES_COUNT="$(_parse_const EXPECTED_RULES_COUNT)"

for v in SKILL_FLOOR SKILL_CEILING AGENTS_CEILING EXPECTED_SECTION_COUNT EXPECTED_RULES_COUNT; do
  if [[ -z "${!v}" ]]; then
    echo "FAIL: could not parse $v out of $GATE_SCRIPT"
    exit 1
  fi
done

TMPROOT="$(mktemp -d)"
trap 'rm -rf "$TMPROOT"' EXIT

# build_fixture <name> -> creates $TMPROOT/<name>/{scripts,content} laid out
# so budget_repo_dir (dirname of the script's own dir) resolves correctly,
# with EXPECTED_SECTION_COUNT section files and EXPECTED_RULES_COUNT
# non-manifest rules files (plus module-manifest.md, excluded by the gate),
# each carrying a distinct top-level "## Heading". Returns the fixture root
# via echo.
build_fixture() {
  local name="$1"
  local root="$TMPROOT/$name"
  mkdir -p "$root/scripts/lib" "$root/content/sections" "$root/content/rules" \
    "$root/.kimi/skills/dinostack"
  cp "$GATE_SCRIPT" "$root/scripts/check-kimi-skill-embed-budget.sh"
  cp "$LIB_SCRIPT" "$root/scripts/lib/budget-gate.sh"

  local i
  for ((i = 1; i <= EXPECTED_SECTION_COUNT; i++)); do
    printf '%02d' "$i" > /dev/null
    {
      echo "## Section ${i}"
      echo ""
      echo "Body text for section ${i}."
    } > "$root/content/sections/$(printf '%02d' "$i")-section.md"
  done
  for ((i = 1; i <= EXPECTED_RULES_COUNT; i++)); do
    {
      echo "## Rule ${i}"
      echo ""
      echo "Body text for rule ${i}."
    } > "$root/content/rules/rule-${i}.md"
  done
  {
    echo "## Module manifest"
    echo ""
    echo "Excluded from the embed-completeness check by name."
  } > "$root/content/rules/module-manifest.md"

  echo "$root"
}

# write_skill_md <root> <bytes> [omit_heading_of]
#   Writes a SKILL.md at <root>/.kimi/skills/dinostack/SKILL.md padded to
#   at least <bytes> bytes, containing every section/rules heading from the
#   fixture EXCEPT the one matching [omit_heading_of] (a section/rule file
#   basename), if given.
write_skill_md() {
  local root="$1" min_bytes="$2" omit="${3:-}"
  local out="$root/.kimi/skills/dinostack/SKILL.md"
  : > "$out"
  local f base
  for f in "$root/content/sections/"*.md "$root/content/rules/"*.md; do
    base="$(basename "$f")"
    [[ "$base" == "module-manifest.md" ]] && continue
    if [[ -n "$omit" && "$base" == "$omit" ]]; then
      continue
    fi
    grep -m1 '^## ' "$f" >> "$out"
    echo "" >> "$out"
  done
  local cur_bytes
  cur_bytes="$(wc -c < "$out" | tr -d '[:space:]')"
  if (( cur_bytes < min_bytes )); then
    python3 -c "
import sys
pad = $min_bytes - $cur_bytes
with open('$out', 'a') as f:
    f.write('x' * pad)
"
  fi
}

write_agents_md() {
  local root="$1" bytes="$2"
  python3 -c "
with open('$root/.kimi/AGENTS.md', 'w') as f:
    f.write('x' * $bytes)
"
}

run_gate() {
  local root="$1"
  (cd "$root" && bash scripts/check-kimi-skill-embed-budget.sh 2>&1)
}

# --- Scenario 1: pass path -------------------------------------------------
{
  root="$(build_fixture pass)"
  write_skill_md "$root" "$SKILL_FLOOR"
  write_agents_md "$root" 100
  out="$(run_gate "$root")"
  rc=$?
  if [[ $rc -eq 0 ]] && grep -q "kimi skill embed budget check: OK" <<<"$out"; then
    pass "pass path exits 0 with OK banner"
  else
    fail "pass path expected exit 0 + OK banner, got rc=$rc, output: $out"
  fi
}

# --- Scenario 2: SKILL.md below FLOOR --------------------------------------
{
  root="$(build_fixture floor)"
  write_skill_md "$root" "$((SKILL_FLOOR - 1000))"
  write_agents_md "$root" 100
  # Truncate padding is fine, but must not accidentally clear headings -
  # the completeness check runs BEFORE the floor check, so make this
  # fixture pass completeness first by keeping all headings, just short.
  out="$(run_gate "$root")"
  rc=$?
  if [[ $rc -ne 0 ]] && grep -q "BELOW FLOOR" <<<"$out"; then
    pass "SKILL.md below FLOOR fails with BELOW FLOOR message"
  else
    fail "expected BELOW FLOOR failure, got rc=$rc, output: $out"
  fi
}

# --- Scenario 3: SKILL.md above CEILING ------------------------------------
{
  root="$(build_fixture ceiling)"
  write_skill_md "$root" "$((SKILL_CEILING + 1000))"
  write_agents_md "$root" 100
  out="$(run_gate "$root")"
  rc=$?
  if [[ $rc -ne 0 ]] && grep -q "ABOVE CEILING" <<<"$out"; then
    pass "SKILL.md above CEILING fails with ABOVE CEILING message"
  else
    fail "expected ABOVE CEILING failure, got rc=$rc, output: $out"
  fi
}

# --- Scenario 4: AGENTS.md above AGENTS_CEILING ----------------------------
{
  root="$(build_fixture agents_ceiling)"
  write_skill_md "$root" "$SKILL_FLOOR"
  write_agents_md "$root" "$((AGENTS_CEILING + 500))"
  out="$(run_gate "$root")"
  rc=$?
  if [[ $rc -ne 0 ]] && grep -q "ABOVE STUB CEILING" <<<"$out"; then
    pass "AGENTS.md above AGENTS_CEILING fails with ABOVE STUB CEILING message"
  else
    fail "expected ABOVE STUB CEILING failure, got rc=$rc, output: $out"
  fi
}

# --- Scenario 5: embed incomplete - heading dropped, count unchanged ------
{
  root="$(build_fixture dropped_heading)"
  omit_name="$(basename "$(ls "$root"/content/sections/*.md | head -1)")"
  write_skill_md "$root" "$SKILL_FLOOR" "$omit_name"
  write_agents_md "$root" 100
  out="$(run_gate "$root")"
  rc=$?
  if [[ $rc -ne 0 ]] && grep -q "missing.*heading" <<<"$out"; then
    pass "dropped section heading fails embed-completeness check"
  else
    fail "expected embed-incomplete (missing heading) failure, got rc=$rc, output: $out"
  fi
}

# --- Scenario 6: section source file outright missing (count mismatch) ---
{
  root="$(build_fixture missing_section)"
  rm "$(ls "$root"/content/sections/*.md | tail -1)"
  write_skill_md "$root" "$SKILL_FLOOR"
  write_agents_md "$root" 100
  out="$(run_gate "$root")"
  rc=$?
  if [[ $rc -ne 0 ]] && grep -q "file count mismatch" <<<"$out"; then
    pass "missing section source file fails on file count mismatch"
  else
    fail "expected file count mismatch failure, got rc=$rc, output: $out"
  fi
}

# --- Scenario 7: rules source file outright added beyond expected count --
{
  root="$(build_fixture extra_rule)"
  {
    echo "## Extra Rule"
    echo ""
    echo "Unexpected extra rule file."
  } > "$root/content/rules/extra-rule.md"
  write_skill_md "$root" "$SKILL_FLOOR"
  write_agents_md "$root" 100
  out="$(run_gate "$root")"
  rc=$?
  if [[ $rc -ne 0 ]] && grep -q "file count mismatch" <<<"$out"; then
    pass "extra rules source file fails on file count mismatch"
  else
    fail "expected file count mismatch failure, got rc=$rc, output: $out"
  fi
}

echo ""
echo "=== $PASS_COUNT passed, $FAIL_COUNT failed ==="
if [[ $FAIL_COUNT -ne 0 ]]; then
  exit 1
fi
exit 0
