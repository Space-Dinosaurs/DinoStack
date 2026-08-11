#!/usr/bin/env bash
# Purpose: Regression guard for scripts/check-no-false-umbrella-claims.sh
#          (round 4 rework, fix/shipped-gitignore-umbrella-gaps, MAJOR 4;
#          widened in round 5 Minor 4 after four same-meaning paraphrases -
#          "the scoped .gitignore block from Step 9", "Step 9's own
#          gitignore block", "a targeted gitignore denylist block", and "a
#          targeted DENYLIST" - survived the round-4 pattern set unscathed).
#          The gate has only ever been observed passing on the fixed tree -
#          that alone does not prove it can catch a real regression. This
#          test exercises both directions against the REAL repo tree: it
#          must PASS against the current tree (already proven clean) and
#          FAIL when one of the five known-false sentence shapes, OR one of
#          the four round-5 paraphrases, is reintroduced via a throwaway
#          mutated copy, never against the real checkout.
#
# Public API: ./bin/tests/test_check_no_false_umbrella_claims.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, grep, mktemp. Never mutates the real checkout - copies
#                the minimum set of scanned paths into a scratch directory,
#                mutates the scratch copy, and points the gate at it via a
#                cd-and-run pattern (the gate is written to `cd` to its own
#                repo root via BASH_SOURCE, so it is invoked with the scratch
#                dir's own copy of the script instead).
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script missing -> immediate FAIL. Gate does not exit 1
#                against a reintroduced false sentence, or does not exit 0
#                against the clean real tree -> FAIL with the observed exit
#                code.
#
# Performance: < 1 s wall time (pure grep, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-no-false-umbrella-claims.sh"

if [[ ! -f "$GATE_SCRIPT" ]]; then
  echo "FAIL: $GATE_SCRIPT not found" >&2
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

# --- Sanity: gate passes against the real repo's current tree ---
if (cd "$REPO_DIR" && bash "$GATE_SCRIPT") >/dev/null 2>&1; then
  _pass "gate exits 0 against this repo's current tree"
else
  rc=$?
  _fail "gate exited $rc against this repo's current tree (expected 0) - a false umbrella claim may have regressed"
fi

# --- Mutation: reintroduce one of the five known-false sentence shapes into
#     a scratch copy of the repo's scanned surface, confirm the gate goes
#     RED against it. Never touches the real checkout. ---
TMP_ROOT="$(mktemp -d)"
_cleanup() {
  rm -rf "$TMP_ROOT"
}
trap _cleanup EXIT

SCRATCH="$TMP_ROOT/repo"
mkdir -p "$SCRATCH/scripts" "$SCRATCH/content/commands" "$SCRATCH/bin" "$SCRATCH/docs"
cp "$GATE_SCRIPT" "$SCRATCH/scripts/check-no-false-umbrella-claims.sh"
touch "$SCRATCH/README.md"

cat > "$SCRATCH/content/commands/ds-init-project.md" <<'EOF'
### 9. Create `.gitignore`

If the user later creates that project-local file, it is already gitignored
by the `.agentic/role-models.yml` pattern in this Step's own block above; do
NOT add a carve-out.
EOF

if (cd "$SCRATCH" && bash "scripts/check-no-false-umbrella-claims.sh") >/dev/null 2>&1; then
  _fail "gate exited 0 against a scratch tree with a reintroduced 'this Step's own block' sentence (expected non-zero)"
else
  rc=$?
  if [[ $rc -eq 1 ]]; then
    _pass "gate exits 1 against a reintroduced 'this Step's own block' sentence"
  else
    _fail "gate exited $rc against a reintroduced sentence (expected 1)"
  fi
fi

# --- Mutation 2: an allow-listed occurrence of the same phrase must NOT
#     fail the gate. ---
cat > "$SCRATCH/content/commands/ds-init-project.md" <<'EOF'
### 9. Create `.gitignore`

Historically this text said the pattern lived in this Step's own block above, before round 3 inverted Step 9 to delegate to ds-migrate apply. <!-- false-umbrella-claim-ok -->
EOF

if (cd "$SCRATCH" && bash "scripts/check-no-false-umbrella-claims.sh") >/dev/null 2>&1; then
  _pass "gate exits 0 against an allow-listed occurrence of the same phrase"
else
  rc=$?
  _fail "gate exited $rc against an allow-listed occurrence (expected 0) - the allow-list marker is not being honored"
fi

# --- Mutation 3: the four round-5 paraphrases, each in its own scratch
#     file, each must independently redden the gate. ---
_assert_paraphrase_reddens() {
  local label="$1" phrase="$2"
  printf '%s\n' "$phrase" > "$SCRATCH/content/commands/ds-init-project.md"
  if (cd "$SCRATCH" && bash "scripts/check-no-false-umbrella-claims.sh") >/dev/null 2>&1; then
    _fail "gate exited 0 against a reintroduced '$label' paraphrase (expected non-zero)"
  else
    rc=$?
    if [[ $rc -eq 1 ]]; then
      _pass "gate exits 1 against a reintroduced '$label' paraphrase"
    else
      _fail "gate exited $rc against a reintroduced '$label' paraphrase (expected 1)"
    fi
  fi
}

_assert_paraphrase_reddens "scoped .gitignore block" "the scoped .gitignore block from Step 9"
_assert_paraphrase_reddens "Step 9's own gitignore block" "Step 9's own gitignore block"
_assert_paraphrase_reddens "targeted gitignore denylist block" "a targeted gitignore denylist block"
_assert_paraphrase_reddens "uppercase DENYLIST" "a targeted DENYLIST"

# --- Mutation 4: the widened SCAN_PATHS (AGENTS.md, CONTRIBUTING.md, hooks/,
#     scripts/) must each be scanned, not just the round-4 set. Verify with
#     a phrase placed in each newly-added path. ---
rm -f "$SCRATCH/content/commands/ds-init-project.md"
rmdir "$SCRATCH/content/commands" "$SCRATCH/content" 2>/dev/null
for newpath in "AGENTS.md" "CONTRIBUTING.md" "hooks/some-hook.md" "scripts/some-script.md"; do
  mkdir -p "$SCRATCH/$(dirname "$newpath")"
  printf 'a targeted DENYLIST\n' > "$SCRATCH/$newpath"
  if (cd "$SCRATCH" && bash "scripts/check-no-false-umbrella-claims.sh") >/dev/null 2>&1; then
    _fail "gate exited 0 against a forbidden phrase placed in $newpath (expected non-zero) - SCAN_PATHS may not cover it"
  else
    rc=$?
    if [[ $rc -eq 1 ]]; then
      _pass "gate exits 1 against a forbidden phrase placed in $newpath"
    else
      _fail "gate exited $rc against a forbidden phrase in $newpath (expected 1)"
    fi
  fi
  rm -f "$SCRATCH/$newpath"
done

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
