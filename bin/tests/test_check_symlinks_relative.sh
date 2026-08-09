#!/usr/bin/env bash
# Purpose: Regression guard for DS-104. scripts/check-symlinks-relative.sh is
#          the CI gate that fails when any of the four
#          .claude/skills/dinostack/{agents,commands,references,rules}
#          symlinks is absolutized in the committed tree. A gate that has
#          only ever been observed passing has not been verified - this test
#          exercises both directions: it must FAIL against a constructed
#          commit with an absolutized symlink, and PASS against one with all
#          four relative.
#
# Public API: ./bin/tests/test_check_symlinks_relative.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, mktemp. Builds a throwaway git repo under a temp
#                directory - never touches the real checkout's HEAD or refs.
#
# Downstream consumers: developer running locally before commit; CI
#                        (the bin-sh-tests job in
#                        .github/workflows/bin-tests.yml auto-discovers
#                        bin/tests/test_*.sh).
#
# Failure modes: gate script missing -> immediate FAIL. Gate does not exit 1
#                on an absolutized fixture, or does not exit 0 on a relative
#                fixture -> FAIL with the observed exit code.
#
# Performance: < 1 s wall time (pure git plumbing, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/check-symlinks-relative.sh"

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

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  rm -rf "$TMP_ROOT"
}
trap _cleanup EXIT

FIXTURE_REPO="$TMP_ROOT/fixture-repo"
mkdir -p "$FIXTURE_REPO"
(
  cd "$FIXTURE_REPO"
  git init -q
  git config user.email "test@example.com"
  git config user.name "DS-104 fixture"
) || { _fail "could not init fixture repo"; exit 1; }

SKILL_DIR="$FIXTURE_REPO/.claude/skills/dinostack"
mkdir -p "$SKILL_DIR" "$FIXTURE_REPO/content"

build_commit() {
  # $1 = commit message; remaining pairs of (name, target) build one
  # symlink each under $SKILL_DIR.
  local msg="$1"
  shift
  (
    cd "$FIXTURE_REPO" || exit 1
    while [[ $# -gt 0 ]]; do
      local name="$1" target="$2"
      shift 2
      rm -f ".claude/skills/dinostack/$name"
      ln -s "$target" ".claude/skills/dinostack/$name"
    done
    git add -A .claude
    git commit -q -m "$msg"
  )
}

# --- Fixture 1: all four relative (must PASS) ---
build_commit "all relative" \
  agents "../../../content/agents" \
  commands "../../../content/commands" \
  references "../../../content/references" \
  rules "../../../content/rules"

GOOD_SHA="$(cd "$FIXTURE_REPO" && git rev-parse HEAD)"

if (cd "$FIXTURE_REPO" && bash "$GATE_SCRIPT" "$GOOD_SHA") >/dev/null 2>&1; then
  _pass "gate exits 0 against an all-relative commit"
else
  rc=$?
  _fail "gate exited $rc against an all-relative commit (expected 0)"
fi

# --- Fixture 2: one absolutized (must FAIL) ---
build_commit "rules absolutized" \
  rules "$FIXTURE_REPO/content/rules"

BAD_SHA="$(cd "$FIXTURE_REPO" && git rev-parse HEAD)"

if (cd "$FIXTURE_REPO" && bash "$GATE_SCRIPT" "$BAD_SHA") >/dev/null 2>&1; then
  _fail "gate exited 0 against a commit with an absolutized symlink (expected non-zero)"
else
  rc=$?
  if [[ $rc -eq 1 ]]; then
    _pass "gate exits 1 against a commit with an absolutized symlink"
  else
    _fail "gate exited $rc against an absolutized commit (expected 1)"
  fi
fi

# --- Sanity: gate also passes against the real repo's current HEAD ---
if (cd "$REPO_DIR" && bash "$GATE_SCRIPT" HEAD) >/dev/null 2>&1; then
  _pass "gate exits 0 against this repo's current HEAD"
else
  rc=$?
  _fail "gate exited $rc against this repo's current HEAD (expected 0) - a real symlink may be absolutized"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
