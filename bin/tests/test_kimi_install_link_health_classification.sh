#!/usr/bin/env bash
# Purpose: Regression guard for .kimi/install.sh's link-health CLASSIFICATION
#          logic (DS-185 round 4) - distinct from
#          bin/tests/test_check_kimi_skill_embed_budget.sh, which exercises
#          the gate script (scripts/check-kimi-skill-embed-budget.sh) in
#          isolation and never invokes install.sh's own decision of whether
#          a given gate diagnostic degrades (appends the fallback body onto
#          AGENTS.md) or warns-only (leaves AGENTS.md a lean stub). This is
#          the exact gap flagged as a Major in the round-3 Skeptic review:
#          the classification broke three times across rounds 1-3 with zero
#          coverage of install.sh's own branch. Exercises the fail-safe
#          allowlist added in round 4: only an EXACT match on one of the two
#          known-benign gate diagnostics ("ABOVE CEILING."/"ABOVE STUB
#          CEILING." for a healthy size boundary, "is likely intentional."
#          for a healthy file-count-over stale pin) warns without
#          appending; every other outcome - a missing gate script, a
#          crashed gate, a dropped source file, or a genuinely broken
#          (below-floor) body - degrades.
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
# Test hygiene: each scenario mutates a tracked file (content/rules/*.md,
#               scripts/check-kimi-skill-embed-budget.sh's constants, or
#               scripts/build-methodology.sh) and restores it via trap
#               before the next scenario runs. .kimi/AGENTS.md and
#               .kimi/skills/dinostack/SKILL.md (both build.sh outputs) are
#               git-checked-out back to a clean state after every run. All
#               HOME-scoped install artifacts live under a mktemp -d
#               removed on exit.
#
# Performance: ~15-25 s wall time (runs install.sh 5 times).

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

_clean_build_outputs() {
  git -C "$REPO_DIR" checkout -- .kimi/AGENTS.md .kimi/skills/dinostack/SKILL.md 2>/dev/null || true
}

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

_cleanup_fake_home() {
  [[ -n "${FAKE_HOME_TO_CLEAN:-}" && -d "$FAKE_HOME_TO_CLEAN" ]] && rm -rf "$FAKE_HOME_TO_CLEAN"
}

# ============================================================
# Scenario 1: healthy body, SKILL.md ceiling breach -> warn only, no degrade
# ============================================================
{
  cp "$GATE_SCRIPT" "$GATE_SCRIPT.bak"
  _restore_s1() { mv "$GATE_SCRIPT.bak" "$GATE_SCRIPT" 2>/dev/null || true; _clean_build_outputs; _cleanup_fake_home; }
  trap _restore_s1 RETURN 2>/dev/null || true

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

  mv "$GATE_SCRIPT.bak" "$GATE_SCRIPT" 2>/dev/null || true
  _clean_build_outputs
  _cleanup_fake_home
}

# ============================================================
# Scenario 2: healthy body, stale EXPECTED_SECTION_COUNT pin (found >
# expected) -> warn only, no degrade
# ============================================================
{
  cp "$GATE_SCRIPT" "$GATE_SCRIPT.bak"

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

  mv "$GATE_SCRIPT.bak" "$GATE_SCRIPT" 2>/dev/null || true
  _clean_build_outputs
  _cleanup_fake_home
}

# ============================================================
# Scenario 3: genuinely broken (below-floor) body -> must degrade
# ============================================================
{
  BUILD_METHODOLOGY="$REPO_DIR/scripts/build-methodology.sh"
  cp "$BUILD_METHODOLOGY" "$BUILD_METHODOLOGY.bak"
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
  else
    agents_bytes="$(wc -c < "$REPO_DIR/.kimi/AGENTS.md" | tr -d '[:space:]')"
    if [[ "$agents_bytes" -le 8000 ]]; then
      _fail "scenario 3: AGENTS.md stayed a lean stub ($agents_bytes B) on a genuinely broken body"
    else
      _pass "scenario 3: below-floor body degrades, AGENTS.md fallback appended ($agents_bytes B)"
    fi
  fi

  mv "$BUILD_METHODOLOGY.bak" "$BUILD_METHODOLOGY" 2>/dev/null || true
  _clean_build_outputs
  _cleanup_fake_home
}

# ============================================================
# Scenario 4: missing content/rules/*.md source files (a whole embedded
# source file dropped from assembly) -> must degrade
# ============================================================
{
  RULES_BACKUP="$(mktemp -d)"
  mv "$REPO_DIR/content/rules/code-standards.md" "$RULES_BACKUP/"
  mv "$REPO_DIR/content/rules/conventions.md" "$RULES_BACKUP/"

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

  mv "$RULES_BACKUP/code-standards.md" "$REPO_DIR/content/rules/" 2>/dev/null || true
  mv "$RULES_BACKUP/conventions.md" "$REPO_DIR/content/rules/" 2>/dev/null || true
  rmdir "$RULES_BACKUP" 2>/dev/null || true
  _clean_build_outputs
  _cleanup_fake_home
}

# ============================================================
# Scenario 5a: crashed gate (missing scripts/lib/budget-gate.sh dependency)
# -> must degrade
# ============================================================
{
  LIB_BACKUP="$(mktemp -d)"
  mv "$REPO_DIR/scripts/lib/budget-gate.sh" "$LIB_BACKUP/"

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

  mv "$LIB_BACKUP/budget-gate.sh" "$REPO_DIR/scripts/lib/" 2>/dev/null || true
  rmdir "$LIB_BACKUP" 2>/dev/null || true
  _clean_build_outputs
  _cleanup_fake_home
}

# ============================================================
# Scenario 5b: missing gate script entirely -> must degrade
# ============================================================
{
  GATE_BACKUP="$(mktemp -d)"
  mv "$GATE_SCRIPT" "$GATE_BACKUP/"

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

  mv "$GATE_BACKUP/check-kimi-skill-embed-budget.sh" "$GATE_SCRIPT" 2>/dev/null || true
  rmdir "$GATE_BACKUP" 2>/dev/null || true
  _clean_build_outputs
  _cleanup_fake_home
}

# ============================================================
# Sanity: repo left clean
# ============================================================
_dirty="$(git -C "$REPO_DIR" status --porcelain -- content/rules scripts/lib/budget-gate.sh scripts/build-methodology.sh scripts/check-kimi-skill-embed-budget.sh .kimi/AGENTS.md .kimi/skills/dinostack/SKILL.md 2>&1)"
if [[ -n "$_dirty" ]]; then
  _fail "post-suite hygiene: tracked files left dirty:"$'\n'"$_dirty"
else
  _pass "post-suite hygiene: all tracked fixture files restored"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
