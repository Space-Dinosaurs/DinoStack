#!/usr/bin/env bash
# Purpose: Regression guard for .kimi/install.sh's link-health CLASSIFICATION
#          logic (DS-185 round 4/5) - distinct from
#          bin/tests/test_check_kimi_skill_embed_budget.sh, which exercises
#          the gate script (scripts/check-kimi-skill-embed-budget.sh) in
#          isolation and never invokes install.sh's own decision of whether
#          a given gate diagnostic degrades (appends the fallback body onto
#          AGENTS.md) or warns-only (leaves AGENTS.md a lean stub). This is
#          the exact gap flagged as a Major in the round-3 Skeptic review:
#          the classification broke three times across rounds 1-3 with zero
#          coverage of install.sh's own branch. Exercises the fail-safe
#          allowlist added in round 4 and the deferred-advisory ordering
#          fixed in round 5 (M1): only an EXACT match on one of the two
#          known-benign gate diagnostics ("ABOVE CEILING."/"ABOVE STUB
#          CEILING." for a healthy size boundary, "is likely intentional."
#          for a healthy file-count-over stale pin, now reachable ONLY after
#          the gate has verified every found file's heading is present)
#          warns without appending; every other outcome - a missing gate
#          script, a crashed gate, a dropped source file (an under-count,
#          which yields the REAL "embed incomplete" diagnostic), or a
#          genuinely broken (below-floor) body - degrades.
#
# Public API: ./bin/tests/test_kimi_install_link_health_classification.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, python3 (used by install.sh/build.sh
#                internally), mktemp, perl (used by build.sh).
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: any scenario's observed exit code, AGENTS.md size class,
#                or expected diagnostic substring does not match ->
#                FAIL naming the scenario and what was observed.
#
# Test hygiene (M3, DS-185 round 5): every tracked file any scenario might
#               mutate or remove (PROTECTED_FILES below - the gate script,
#               build-methodology.sh, the two rules files, one sections
#               file, budget-gate.sh, and the two build OUTPUTS
#               .kimi/AGENTS.md / .kimi/skills/dinostack/SKILL.md) is
#               snapshotted ONCE into a single mktemp -d scratch root before
#               any scenario runs. Restoration is a byte-for-byte `cp -f`
#               from that snapshot back onto the live path - recreating a
#               scenario-deleted file just as readily as reverting a
#               scenario-edited one - and is wired to a SINGLE `trap ...
#               EXIT INT TERM` registered once at the top of the script, so
#               an interruption (Ctrl-C, a CI timeout) mid-scenario still
#               restores every fixture. Restoring the two build OUTPUTS from
#               the pre-test snapshot (rather than `git checkout --`, which
#               would silently discard any uncommitted local edit to them)
#               is deliberate: a developer's pre-existing working-tree state
#               for those two files, not `HEAD`'s, is what "restored" means
#               here. Final hygiene diffs live content against that same
#               snapshot for the same reason - a pre-existing uncommitted
#               change elsewhere in the repo (e.g. to this gate script
#               itself, mid-development) must not register as a hygiene
#               failure the suite caused.
#
# Performance: ~15-25 s wall time (runs install.sh 7 times).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
INSTALL_SH="$REPO_DIR/.kimi/install.sh"
GATE_SCRIPT="$REPO_DIR/scripts/check-kimi-skill-embed-budget.sh"

if [[ ! -f "$INSTALL_SH" ]]; then
  echo "FAIL: $INSTALL_SH not found" >&2
  exit 1
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

# ------------------------------------------------------------------------
# M3 (DS-185 round 5): single scratch root + single EXIT/INT/TERM trap.
# Every tracked path a scenario might edit or delete is snapshotted here
# ONCE, before any scenario runs, and restored from this snapshot (never
# from `git checkout`, never via a per-scenario RETURN trap - `RETURN`
# fires on function/sourced-script return, never on a `{ }` group, so the
# round-4 suite's `trap _restore_s1 RETURN` was silently inert).
# ------------------------------------------------------------------------
PROTECTED_FILES=(
  "scripts/check-kimi-skill-embed-budget.sh"
  "scripts/build-methodology.sh"
  "scripts/lib/budget-gate.sh"
  "content/rules/code-standards.md"
  "content/rules/conventions.md"
  "content/sections/12-protocol-details.md"
  ".kimi/AGENTS.md"
  ".kimi/skills/dinostack/SKILL.md"
)

_SCRATCH_ROOT="$(mktemp -d)"

_backup_path_for() {
  printf '%s/%s' "$_SCRATCH_ROOT" "$(printf '%s' "$1" | tr '/' '_')"
}

_snapshot_protected_files() {
  local rel
  for rel in "${PROTECTED_FILES[@]}"; do
    if [[ -f "$REPO_DIR/$rel" ]]; then
      cp "$REPO_DIR/$rel" "$(_backup_path_for "$rel")"
    fi
  done
}

_restore_protected_files() {
  local rel backup
  for rel in "${PROTECTED_FILES[@]}"; do
    backup="$(_backup_path_for "$rel")"
    if [[ -f "$backup" ]]; then
      mkdir -p "$(dirname "$REPO_DIR/$rel")"
      cp -f "$backup" "$REPO_DIR/$rel"
    fi
  done
}

FAKE_HOME_TO_CLEAN=""

_cleanup_fake_home() {
  [[ -n "${FAKE_HOME_TO_CLEAN:-}" && -d "$FAKE_HOME_TO_CLEAN" ]] && rm -rf "$FAKE_HOME_TO_CLEAN"
  FAKE_HOME_TO_CLEAN=""
}

_global_cleanup() {
  local rc=$?
  _restore_protected_files
  _cleanup_fake_home
  rm -rf "$_SCRATCH_ROOT" 2>/dev/null || true
  exit "$rc"
}
trap _global_cleanup EXIT INT TERM

_snapshot_protected_files

# Runs install.sh with a fresh fake HOME, non-interactively. Captures
# stdout+stderr into $OUT_LOG and the exit code into $INSTALL_RC.
_run_install() {
  local fake_home
  fake_home="$(mktemp -d)"
  mkdir -p "$fake_home/.kimi"
  OUT_LOG="$fake_home/out.log"
  HOME="$fake_home" bash "$INSTALL_SH" --mode=opt-out --profile=default \
    < /dev/null > "$OUT_LOG" 2>&1
  INSTALL_RC=$?
  FAKE_HOME_TO_CLEAN="$fake_home"
}

# ============================================================
# Scenario 1: healthy body, SKILL.md ceiling breach -> warn only, no degrade
# ============================================================
{
  sed -i.orig 's/^SKILL_CEILING=[0-9]*$/SKILL_CEILING=1000/' "$GATE_SCRIPT"
  rm -f "$GATE_SCRIPT.orig"

  _run_install

  if [[ "$INSTALL_RC" -ne 0 ]]; then
    _fail "scenario 1 (healthy ceiling breach): install.sh exited $INSTALL_RC (expected 0)"
  elif ! grep -qF 'reported an advisory' "$OUT_LOG"; then
    _fail "scenario 1: expected the benign advisory-boundary warning, none found"
  elif grep -qF 'Appending the full methodology body' "$OUT_LOG"; then
    _fail "scenario 1: fallback was appended on a healthy ceiling-only breach (should warn only)"
  else
    agents_bytes="$(wc -c < "$REPO_DIR/.kimi/AGENTS.md" | tr -d '[:space:]')"
    if [[ "$agents_bytes" -gt 8000 ]]; then
      _fail "scenario 1: AGENTS.md grew to $agents_bytes B on a healthy ceiling breach (expected lean stub)"
    else
      _pass "scenario 1: healthy SKILL.md ceiling breach warns only, AGENTS.md stays a lean stub ($agents_bytes B)"
    fi
  fi

  _restore_protected_files
  _cleanup_fake_home
}

# ============================================================
# Scenario 2: healthy body, stale EXPECTED_SECTION_COUNT pin (found >
# expected) -> warn only, no degrade
# ============================================================
{
  sed -i.orig 's/^EXPECTED_SECTION_COUNT=12$/EXPECTED_SECTION_COUNT=11/' "$GATE_SCRIPT"
  rm -f "$GATE_SCRIPT.orig"

  _run_install

  if [[ "$INSTALL_RC" -ne 0 ]]; then
    _fail "scenario 2 (stale count pin): install.sh exited $INSTALL_RC (expected 0)"
  elif ! grep -qF 'reported an advisory' "$OUT_LOG"; then
    _fail "scenario 2: expected the benign advisory-boundary warning, none found"
  elif grep -qF 'Appending the full methodology body' "$OUT_LOG"; then
    _fail "scenario 2: fallback was appended on a healthy stale-count-pin breach (should warn only)"
  else
    agents_bytes="$(wc -c < "$REPO_DIR/.kimi/AGENTS.md" | tr -d '[:space:]')"
    if [[ "$agents_bytes" -gt 8000 ]]; then
      _fail "scenario 2: AGENTS.md grew to $agents_bytes B on a stale-count-pin breach (expected lean stub)"
    else
      _pass "scenario 2: healthy stale-count-pin breach warns only, AGENTS.md stays a lean stub ($agents_bytes B)"
    fi
  fi

  _restore_protected_files
  _cleanup_fake_home
}

# ============================================================
# Scenario 3: genuinely broken (below-floor) body -> must degrade
# ============================================================
{
  BUILD_METHODOLOGY="$REPO_DIR/scripts/build-methodology.sh"
  cat > "$BUILD_METHODOLOGY" <<'STUB'
#!/usr/bin/env bash
echo "stub methodology body - simulates a broken assembly step"
STUB
  chmod +x "$BUILD_METHODOLOGY"

  _run_install

  if [[ "$INSTALL_RC" -ne 0 ]]; then
    _fail "scenario 3 (below-floor body): install.sh exited $INSTALL_RC (expected 0)"
  elif ! grep -qF 'BELOW FLOOR' "$OUT_LOG" && ! grep -qiF 'suspiciously small' "$OUT_LOG"; then
    _fail "scenario 3: expected a BELOW FLOOR / suspiciously small diagnostic, none found"
  elif ! grep -qF 'Appending the full methodology body' "$OUT_LOG"; then
    _fail "scenario 3: expected the fallback to be appended on a genuinely broken body, it was not"
  elif ! grep -qF '## Fallback: full methodology body' "$REPO_DIR/.kimi/AGENTS.md"; then
    _fail "scenario 3: AGENTS.md is missing the '## Fallback: full methodology body' marker install.sh's own fallback writes"
  elif ! grep -qF '## Writing Style' "$REPO_DIR/.kimi/AGENTS.md"; then
    # Minor (DS-185 round 5): a bare byte-count check (>8000 B) does not
    # verify the appended content IS the fallback body - in this exact
    # scenario the append is rules-only content, because
    # scripts/build-methodology.sh itself was stubbed by the same
    # mutation, so METHODOLOGY.md's own contribution is a one-line stub
    # rather than the real methodology text, while install.sh still prints
    # "Appending the full methodology body". This grep checks for a
    # distinctive heading from content/rules/conventions.md - present
    # regardless of METHODOLOGY.md's health - proving real rules content
    # landed, not just padding.
    _fail "scenario 3: AGENTS.md fallback is missing rules content ('## Writing Style' from conventions.md) - the byte count alone does not prove real content was appended"
  else
    agents_bytes="$(wc -c < "$REPO_DIR/.kimi/AGENTS.md" | tr -d '[:space:]')"
    if [[ "$agents_bytes" -le 8000 ]]; then
      _fail "scenario 3: AGENTS.md stayed a lean stub ($agents_bytes B) on a genuinely broken body"
    else
      _pass "scenario 3: below-floor body degrades, AGENTS.md fallback appended with verified rules content ($agents_bytes B)"
    fi
  fi

  _restore_protected_files
  _cleanup_fake_home
}

# ============================================================
# Scenario 4: missing content/rules/*.md source files (ALL of them - the
# "no rules files found in" branch, distinct from an under-count) -> must
# degrade
# ============================================================
{
  rm -f "$REPO_DIR/content/rules/code-standards.md" "$REPO_DIR/content/rules/conventions.md"

  _run_install

  if [[ "$INSTALL_RC" -ne 0 ]]; then
    _fail "scenario 4 (missing rules files): install.sh exited $INSTALL_RC (expected 0)"
  elif ! grep -qF 'not on the known-benign allowlist' "$OUT_LOG"; then
    _fail "scenario 4: expected a not-on-the-known-benign-allowlist degrade diagnostic, none found"
  elif ! grep -qF 'Appending the full methodology body' "$OUT_LOG"; then
    _fail "scenario 4: expected the fallback to be appended when rules source files are missing, it was not"
  else
    agents_bytes="$(wc -c < "$REPO_DIR/.kimi/AGENTS.md" | tr -d '[:space:]')"
    if [[ "$agents_bytes" -le 8000 ]]; then
      _fail "scenario 4: AGENTS.md stayed a lean stub ($agents_bytes B) with rules files missing"
    else
      _pass "scenario 4: missing rules source files degrade, AGENTS.md fallback appended ($agents_bytes B)"
    fi
  fi

  _restore_protected_files
  _cleanup_fake_home
}

# ============================================================
# Scenario 5a: crashed gate (missing scripts/lib/budget-gate.sh dependency)
# -> must degrade
# ============================================================
{
  rm -f "$REPO_DIR/scripts/lib/budget-gate.sh"

  _run_install

  if [[ "$INSTALL_RC" -ne 0 ]]; then
    _fail "scenario 5a (crashed gate): install.sh exited $INSTALL_RC (expected 0)"
  elif ! grep -qF 'not on the known-benign allowlist' "$OUT_LOG"; then
    _fail "scenario 5a: expected a not-on-the-known-benign-allowlist degrade diagnostic, none found"
  elif ! grep -qF 'Appending the full methodology body' "$OUT_LOG"; then
    _fail "scenario 5a: expected the fallback to be appended when the gate crashes, it was not"
  else
    agents_bytes="$(wc -c < "$REPO_DIR/.kimi/AGENTS.md" | tr -d '[:space:]')"
    if [[ "$agents_bytes" -le 8000 ]]; then
      _fail "scenario 5a: AGENTS.md stayed a lean stub ($agents_bytes B) with the gate crashed"
    else
      _pass "scenario 5a: crashed gate degrades, AGENTS.md fallback appended ($agents_bytes B)"
    fi
  fi

  _restore_protected_files
  _cleanup_fake_home
}

# ============================================================
# Scenario 5b: missing gate script entirely -> must degrade
# ============================================================
{
  rm -f "$GATE_SCRIPT"

  _run_install

  if [[ "$INSTALL_RC" -ne 0 ]]; then
    _fail "scenario 5b (missing gate script): install.sh exited $INSTALL_RC (expected 0)"
  elif ! grep -qF 'cannot verify embed completeness' "$OUT_LOG"; then
    _fail "scenario 5b: expected a cannot-verify-embed-completeness degrade diagnostic, none found"
  elif ! grep -qF 'Appending the full methodology body' "$OUT_LOG"; then
    _fail "scenario 5b: expected the fallback to be appended when the gate script is missing, it was not"
  else
    agents_bytes="$(wc -c < "$REPO_DIR/.kimi/AGENTS.md" | tr -d '[:space:]')"
    if [[ "$agents_bytes" -le 8000 ]]; then
      _fail "scenario 5b: AGENTS.md stayed a lean stub ($agents_bytes B) with the gate script missing"
    else
      _pass "scenario 5b: missing gate script degrades, AGENTS.md fallback appended ($agents_bytes B)"
    fi
  fi

  _restore_protected_files
  _cleanup_fake_home
}

# ============================================================
# Scenario 6 (M2, DS-185 round 5): healthy body, .kimi/AGENTS.md stub
# ceiling breach -> warn only, no degrade. Distinct from scenario 1, which
# only ever breaches the SKILL.md ceiling - nothing before this scenario
# exercised the "AGENTS.md ABOVE STUB CEILING." allowlist arm at all, so a
# deletion of that arm from install.sh's classification (M2 mutation 1)
# would previously go undetected by this suite.
# ============================================================
{
  sed -i.orig 's/^AGENTS_CEILING=[0-9]*$/AGENTS_CEILING=100/' "$GATE_SCRIPT"
  rm -f "$GATE_SCRIPT.orig"

  _run_install

  if [[ "$INSTALL_RC" -ne 0 ]]; then
    _fail "scenario 6 (AGENTS.md stub ceiling breach): install.sh exited $INSTALL_RC (expected 0)"
  elif ! grep -qF 'reported an advisory' "$OUT_LOG"; then
    _fail "scenario 6: expected the benign advisory-boundary warning, none found"
  elif grep -qF 'Appending the full methodology body' "$OUT_LOG"; then
    _fail "scenario 6: fallback was appended on a healthy AGENTS.md-stub-ceiling-only breach (should warn only)"
  else
    agents_bytes="$(wc -c < "$REPO_DIR/.kimi/AGENTS.md" | tr -d '[:space:]')"
    if [[ "$agents_bytes" -gt 8000 ]]; then
      _fail "scenario 6: AGENTS.md grew to $agents_bytes B on a healthy stub-ceiling breach (expected lean stub, still under 8000 B)"
    else
      _pass "scenario 6: healthy AGENTS.md stub-ceiling breach warns only, AGENTS.md stays a lean stub ($agents_bytes B)"
    fi
  fi

  _restore_protected_files
  _cleanup_fake_home
}

# ============================================================
# Scenario 7 (M2, DS-185 round 5): a genuine UNDER-count - one
# content/sections/*.md source file dropped from assembly (11 found,
# 12 expected) - must degrade. This is the real "embed incomplete"
# diagnostic (distinct from scenario 4's "no rules files found in" early
# branch, which never reaches that text at all) - nothing before this
# scenario exercised it, so a re-broadening of install.sh's allowlist to
# `|| grep -qF 'embed incomplete'` (M2 mutation 2 - literally round 3's
# fail-open) would previously go undetected by this suite.
# ============================================================
{
  rm -f "$REPO_DIR/content/sections/12-protocol-details.md"

  _run_install

  if [[ "$INSTALL_RC" -ne 0 ]]; then
    _fail "scenario 7 (dropped section file, under-count): install.sh exited $INSTALL_RC (expected 0)"
  elif ! grep -qF 'not on the known-benign allowlist' "$OUT_LOG"; then
    _fail "scenario 7: expected a not-on-the-known-benign-allowlist degrade diagnostic, none found"
  elif ! grep -qF 'Appending the full methodology body' "$OUT_LOG"; then
    _fail "scenario 7: expected the fallback to be appended when a section source file is missing, it was not"
  else
    agents_bytes="$(wc -c < "$REPO_DIR/.kimi/AGENTS.md" | tr -d '[:space:]')"
    if [[ "$agents_bytes" -le 8000 ]]; then
      _fail "scenario 7: AGENTS.md stayed a lean stub ($agents_bytes B) with a section source file missing"
    else
      _pass "scenario 7: dropped section file (under-count) degrades, AGENTS.md fallback appended ($agents_bytes B)"
    fi
  fi

  _restore_protected_files
  _cleanup_fake_home
}

# ============================================================
# Sanity: repo left clean, diffed against the pre-test snapshot (not
# `git status --porcelain`/HEAD - a pre-existing uncommitted edit to one of
# these files, e.g. mid-development on the gate script itself, must not
# register as a hygiene failure this suite caused).
# ============================================================
_dirty=""
for _rel in "${PROTECTED_FILES[@]}"; do
  _backup="$(_backup_path_for "$_rel")"
  _live="$REPO_DIR/$_rel"
  if [[ -f "$_backup" && ! -f "$_live" ]]; then
    _dirty="$_dirty
  $_rel: missing after suite ran (expected restored)"
  elif [[ -f "$_backup" && -f "$_live" ]] && ! cmp -s "$_backup" "$_live"; then
    _dirty="$_dirty
  $_rel: content differs from its pre-test snapshot"
  fi
done
if [[ -n "$_dirty" ]]; then
  _fail "post-suite hygiene: fixture files left dirty relative to their pre-test snapshot:$_dirty"
else
  _pass "post-suite hygiene: all tracked fixture files match their pre-test snapshot"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
