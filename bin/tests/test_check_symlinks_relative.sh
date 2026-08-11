#!/usr/bin/env bash
# Purpose: Regression guard for DS-104 (ref mode) and DS-136 (--staged mode)
#          of scripts/check-symlinks-relative.sh - the CI/pre-commit gate
#          that fails when any of the four
#          .claude/skills/agentic-engineering/{agents,commands,references,rules}
#          symlinks are absolutized. A gate that has only ever been observed
#          passing has not been verified - this test exercises both
#          directions in both modes: it must FAIL against a constructed
#          commit/index with an absolutized symlink, and PASS against one
#          with all four relative. --staged mode additionally reproduces a
#          Critical field-position bug that nearly shipped into
#          hooks/pre-commit: `git ls-tree <ref>` emits <mode> <type> <sha>
#          while `git ls-files -s` emits <mode> <sha> <stage> - sharing one
#          awk parse across both modes crashes staged mode with
#          `git cat-file -p 0` -> "fatal: Not a valid object name".
#
#          SKILL_DIR/LINKS in check-symlinks-relative.sh are cwd-relative
#          (".claude/skills/agentic-engineering", not tied to the real
#          checkout's absolute path), so a synthetic fixture repo built at
#          that same relative path under a throwaway git init exercises the
#          gate identically to the real repo, in both ref and --staged
#          mode - no clone of the live repo is required for either mode.
#
# Public API: ./bin/tests/test_check_symlinks_relative.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, mktemp. Builds a throwaway git repo under a temp
#                directory - never touches the real checkout's HEAD, refs,
#                or index.
#
# Downstream consumers: developer running locally before commit; CI
#                        (bin-sh-tests.yml auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script missing -> immediate FAIL. Gate does not exit 1
#                on an absolutized fixture, or does not exit 0 on a relative
#                fixture (ref or --staged mode) -> FAIL with the observed
#                exit code. --staged mode additionally FAILs if the
#                field-position crash signature (fatal: / Not a valid
#                object name) reappears on stderr.
#
# Performance: < 1 s wall time (pure git plumbing, no network, no clone).

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
trap _cleanup EXIT INT TERM

FIXTURE_REPO="$TMP_ROOT/fixture-repo"
mkdir -p "$FIXTURE_REPO"
(
  cd "$FIXTURE_REPO"
  git init -q
  git config user.email "test@example.com"
  git config user.name "DS-104 fixture"
) || { _fail "could not init fixture repo"; exit 1; }

SKILL_DIR="$FIXTURE_REPO/.claude/skills/agentic-engineering"
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
      rm -f ".claude/skills/agentic-engineering/$name"
      ln -s "$target" ".claude/skills/agentic-engineering/$name"
    done
    git add -A .claude
    git commit -q -m "$msg"
  )
}

stage_change() {
  # Same shape as build_commit but stages without committing - leaves the
  # mutation in the index only, for exercising --staged mode against a
  # dirty index.
  shift # discard the unused message arg (kept for call-site symmetry)
  (
    cd "$FIXTURE_REPO" || exit 1
    while [[ $# -gt 0 ]]; do
      local name="$1" target="$2"
      shift 2
      rm -f ".claude/skills/agentic-engineering/$name"
      ln -s "$target" ".claude/skills/agentic-engineering/$name"
    done
    git add -A .claude
  )
}

# --- Fixture 1: all four relative (must PASS, ref mode) ---
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

# ---------------------------------------------------------------------------
# --staged Test A: a clean index (right after the GOOD_SHA commit above)
# exits 0.
# ---------------------------------------------------------------------------
if (cd "$FIXTURE_REPO" && bash "$GATE_SCRIPT" --staged) >/dev/null 2>&1; then
  _pass "--staged: clean index exits 0"
else
  rc=$?
  _fail "--staged: clean index exited $rc (expected 0)"
fi

# ---------------------------------------------------------------------------
# --staged Test B (Critical reproduction): stage an absolutized symlink
# without committing, assert exit 1, AND assert stderr does NOT contain the
# field-position crash signature. Asserting only on exit code would not
# distinguish a crash from a correct rejection (both exit nonzero).
# ---------------------------------------------------------------------------
stage_change "stage absolutized rules (uncommitted)" \
  rules "$FIXTURE_REPO/content/rules"

set +e
staged_out="$(cd "$FIXTURE_REPO" && bash "$GATE_SCRIPT" --staged 2>&1)"
staged_rc=$?
set -e

if [[ "$staged_rc" -eq 1 ]]; then
  _pass "--staged: absolutized symlink staged (uncommitted) exits 1"
else
  _fail "--staged: absolutized symlink staged (uncommitted) expected exit 1, got $staged_rc"
fi

if [[ "$staged_out" == *"fatal:"* || "$staged_out" == *"Not a valid object name"* ]]; then
  _fail "--staged: field-position crash signature reappeared: $staged_out"
else
  _pass "--staged: no field-position crash signature"
fi

# Restore the index to the GOOD_SHA relative state before the next mutation.
(cd "$FIXTURE_REPO" && git reset -q --hard "$GOOD_SHA")

# ---------------------------------------------------------------------------
# --staged Test C: staging a deletion of a watched symlink (uncommitted)
# exits 0 - a legitimate removal must not block the commit that removes it.
# ---------------------------------------------------------------------------
(cd "$FIXTURE_REPO" && git rm -q ".claude/skills/agentic-engineering/rules")

if (cd "$FIXTURE_REPO" && bash "$GATE_SCRIPT" --staged) >/dev/null 2>&1; then
  _pass "--staged: staged deletion of watched symlink exits 0"
else
  rc=$?
  _fail "--staged: staged deletion of watched symlink exited $rc (expected 0)"
fi

(cd "$FIXTURE_REPO" && git reset -q --hard "$GOOD_SHA")

# --- Fixture 2: one absolutized (must FAIL, ref mode) ---
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
