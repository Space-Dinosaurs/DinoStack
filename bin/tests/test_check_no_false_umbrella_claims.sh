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
# Every entry in the gate's own SCAN_PATHS must exist in the scratch tree -
# the gate now hard-fails (round 6 Minor 5) if one of them doesn't, so the
# scratch fixture must materialize all of them, not just the ones this
# test's mutations actually write into.
mkdir -p "$SCRATCH/scripts" "$SCRATCH/content/commands" "$SCRATCH/bin" \
  "$SCRATCH/docs" "$SCRATCH/hooks"
cp "$GATE_SCRIPT" "$SCRATCH/scripts/check-no-false-umbrella-claims.sh"
touch "$SCRATCH/README.md" "$SCRATCH/AGENTS.md" "$SCRATCH/CONTRIBUTING.md"

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
# content/ is itself a required SCAN_PATHS entry (round 6 Minor 5) - recreate
# it empty so its removal above doesn't trip the gate's own existence check.
mkdir -p "$SCRATCH/content"
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

# --- Mutation 5 (round 6 Minor 5): a SCAN_PATHS entry that does not exist
#     (a typo, or a path later removed from the repo) must hard-fail the
#     gate rather than silently scanning nothing for it. Mutation 4's loop
#     above deletes AGENTS.md/CONTRIBUTING.md/hooks/... after testing each -
#     re-materialize every real SCAN_PATHS entry here so this mutation's
#     failure is actually about 'nonexistent-typo-path', not a leftover
#     missing path from an earlier mutation. ---
touch "$SCRATCH/AGENTS.md" "$SCRATCH/CONTRIBUTING.md"
mkdir -p "$SCRATCH/hooks"
sed \
  's|^SCAN_PATHS=(content bin docs README.md AGENTS.md CONTRIBUTING.md hooks scripts)$|SCAN_PATHS=(content bin docs README.md AGENTS.md CONTRIBUTING.md hooks scripts nonexistent-typo-path)|' \
  "$GATE_SCRIPT" > "$SCRATCH/scripts/check-no-false-umbrella-claims.sh"
if ! grep -q 'nonexistent-typo-path' "$SCRATCH/scripts/check-no-false-umbrella-claims.sh"; then
  _fail "sed substitution of SCAN_PATHS did not apply - test fixture itself is broken, not the gate"
else
  out="$(cd "$SCRATCH" && bash "scripts/check-no-false-umbrella-claims.sh" 2>&1)"
  rc=$?
  if [[ $rc -ne 0 ]] && printf '%s' "$out" | grep -q 'nonexistent-typo-path'; then
    _pass "gate hard-fails with a named-path error when a SCAN_PATHS entry does not exist"
  else
    _fail "gate exited $rc (expected non-zero, with the missing path named) when a SCAN_PATHS entry does not exist - a typo'd path would silently scan nothing"
  fi
fi
# Restore the un-mutated gate copy for cleanliness (scratch dir is removed
# by the trap regardless; explicit for readability).
cp "$GATE_SCRIPT" "$SCRATCH/scripts/check-no-false-umbrella-claims.sh"

# --- Mutation 6 (round 8 MAJOR 2): an EXISTING-but-UNREADABLE scan path
#     (e.g. `chmod 000`) must hard-fail the gate the same way a nonexistent
#     path does. Mutation 5 only proves the gate reacts to a nonexistent
#     path - it passes identically whether the guard uses `-e` (exists) or
#     `-r` (readable), because a nonexistent path fails both tests. `-e`
#     would silently scan an unreadable path as empty and stay green; only
#     `-r` catches it. This mutation is the one that actually distinguishes
#     the two, and is run in two directions: (a) against the real,
#     currently-shipped `-r` gate, expecting a hard-fail naming the
#     unreadable path, and (b) against a throwaway copy with `-r` reverted
#     to `-e`, expecting the opposite - a silent pass - which proves this
#     mutation is capable of going red and would have caught a revert of
#     the round-8 hardening.
#
#     GitHub Actions runs `bin-sh-tests` as the non-root `runner` user, so
#     `chmod 000` is non-vacuous there. A root user (e.g. a local sandboxed
#     dev shell) can read a chmod'd-000 file regardless of its mode bits, so
#     this mutation SKIPS with a notice under root rather than false-passing
#     silently.
if [[ "$(id -u)" -eq 0 ]]; then
  echo "SKIP: Mutation 6 (chmod 000 unreadable scan path) - running as root, chmod 000 is not enforced for root and would false-pass; re-run as a non-root user to exercise this mutation"
else
  touch "$SCRATCH/AGENTS.md" "$SCRATCH/CONTRIBUTING.md"
  mkdir -p "$SCRATCH/hooks"
  chmod 000 "$SCRATCH/AGENTS.md"

  # (a) real, currently-shipped -r gate: must hard-fail, naming AGENTS.md.
  out="$(cd "$SCRATCH" && bash "scripts/check-no-false-umbrella-claims.sh" 2>&1)"
  rc=$?
  if [[ $rc -ne 0 ]] && printf '%s' "$out" | grep -q 'AGENTS.md'; then
    _pass "gate hard-fails with a named-path error when a SCAN_PATHS entry exists but is unreadable (chmod 000)"
  else
    _fail "gate exited $rc (expected non-zero, with the unreadable path named) when a SCAN_PATHS entry is chmod 000 - an unreadable path would silently scan as empty"
  fi

  # (b) throwaway copy with -r reverted to -e: must NOT catch it (proves the
  #     assertion above is not vacuous - it would have failed against the
  #     pre-round-8 `-e` gate).
  sed 's/\[ ! -r "\$scan_path" \]/[ ! -e "$scan_path" ]/' \
    "$GATE_SCRIPT" > "$SCRATCH/scripts/check-no-false-umbrella-claims.sh"
  if ! grep -q '\[ ! -e "\$scan_path" \]' "$SCRATCH/scripts/check-no-false-umbrella-claims.sh"; then
    _fail "sed reversion of -r to -e did not apply - test fixture itself is broken, not the gate"
  else
    out="$(cd "$SCRATCH" && bash "scripts/check-no-false-umbrella-claims.sh" 2>&1)"
    rc=$?
    if [[ $rc -eq 0 ]]; then
      _pass "confirmed pre-fix: a gate using -e instead of -r silently passes (exit 0) against a chmod 000 scan path - proves Mutation 6(a) is a genuine regression guard"
    else
      _fail "expected the pre-fix -e gate to silently pass (exit 0) against chmod 000 as a sanity check that this mutation can go red, but it exited $rc"
    fi
  fi

  chmod 644 "$SCRATCH/AGENTS.md" 2>/dev/null || true
  rm -f "$SCRATCH/AGENTS.md" "$SCRATCH/CONTRIBUTING.md"
  # Restore the un-mutated gate copy again.
  cp "$GATE_SCRIPT" "$SCRATCH/scripts/check-no-false-umbrella-claims.sh"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
