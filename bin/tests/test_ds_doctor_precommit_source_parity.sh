#!/usr/bin/env bash
# Purpose: Assert that bin/ds-doctor's _resolve_hook_src (Python) and
#          scripts/lib/precommit.sh's resolve_hook_src (bash) agree on the
#          expected pre-commit hook symlink SOURCE across three topologies:
#          an ordinary checkout, a linked git worktree, and a checkout
#          missing hooks/pre-commit entirely. "Both sides agree" alone is
#          not a sufficient regression guard here - a double regression
#          (both resolvers independently repointing into the worktree)
#          would still pass an agreement-only check, so the linked-worktree
#          case additionally pins the resolved path to the PRIMARY
#          checkout's hooks/pre-commit specifically, not merely "whatever
#          the two sides happen to agree on".
#
# This test uses its OWN embedded fixture copy of resolve_hook_src /
# resolve_git_hooks_dir / _precommit_canonical_repo_dir, matching the fixed
# behavior shipped by PR #640 on origin/main - NOT this checkout's own
# scripts/lib/precommit.sh, which does not yet define resolve_hook_src
# (out of scope for this branch; a concurrent branch owns that file). See
# bin/tests/test_agentic_doctor.sh's T18 fixture-setup comment for the same
# rationale. bin/ds-doctor's _resolve_hook_src shells into whatever
# scripts/lib/precommit.sh actually exists at repo_dir/scripts/lib -
# pointing repo_dir at a fixture repo carrying this embedded copy exercises
# the real bash resolve_hook_src, not a stand-in.
#
# Public API: ./bin/tests/test_ds_doctor_precommit_source_parity.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, python3, mktemp.
#
# Downstream consumers: developer running locally before commit; CI via
#                       .github/workflows/bin-tests.yml (auto-discovered by
#                       its `for f in bin/tests/test_*.sh` loop - no
#                       explicit per-file wiring needed).
#
# Failure modes: any assertion failure prints the failing assertion and
#                exits 1. All fixtures live under a temporary directory;
#                the real repo is never touched.
#
# Performance: < 2 s wall time (pure git + shell + python, no network).

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOCTOR="$SCRIPT_DIR/ds-doctor"

if [[ ! -f "$DOCTOR" ]]; then
  echo "FAIL: $DOCTOR not found" >&2
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

FIXTURE_PRECOMMIT_SH='# shellcheck shell=bash
_precommit_canonical_repo_dir() {
  local d="$1"
  if [[ -z "$d" ]]; then
    echo "$d"
    return 0
  fi
  (cd "$d" 2>/dev/null && pwd -P) || echo "$d"
}

resolve_git_hooks_dir() {
  local repo_dir="$1"
  local hooks_dir
  if ! hooks_dir="$(git -C "$repo_dir" rev-parse --git-path hooks 2>/dev/null)" || [[ -z "$hooks_dir" ]]; then
    return 1
  fi
  case "$hooks_dir" in
    /*) : ;;
    *) hooks_dir="$repo_dir/$hooks_dir" ;;
  esac
  echo "$hooks_dir"
}

resolve_hook_src() {
  local repo_dir="$1"
  repo_dir="$(_precommit_canonical_repo_dir "$repo_dir")"
  local fallback="$repo_dir/hooks/pre-commit"

  local git_dir common_dir
  if ! git_dir="$(git -C "$repo_dir" rev-parse --path-format=absolute --git-dir 2>/dev/null)" || [[ -z "$git_dir" ]]; then
    echo "$fallback"
    return 0
  fi
  if ! common_dir="$(git -C "$repo_dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || [[ -z "$common_dir" ]]; then
    echo "$fallback"
    return 0
  fi

  if [[ "$git_dir" == "$common_dir" ]]; then
    echo "$fallback"
    return 0
  fi

  local common_worktree candidate
  common_worktree="$(dirname "$common_dir")"
  candidate="$common_worktree/hooks/pre-commit"
  if [[ -z "$common_worktree" || ! -f "$candidate" ]]; then
    echo "$fallback"
    return 0
  fi

  echo "$candidate"
}
'

# _bash_resolve <repo_dir>: run the fixture's resolve_hook_src in a fresh
# subshell (never pollutes this test script's own function namespace).
_bash_resolve() {
  local repo_dir="$1"
  local lib
  lib="$(mktemp)"
  printf '%s' "$FIXTURE_PRECOMMIT_SH" > "$lib"
  bash -c 'source "$1"; resolve_hook_src "$2"' _ "$lib" "$repo_dir"
  rm -f "$lib"
}

# _python_resolve <repo_dir>: import bin/ds-doctor as a module and call its
# private _resolve_hook_src directly - the exact function check_git_precommit
# calls, not a reimplementation.
_python_resolve() {
  local repo_dir="$1"
  python3 -c "
import importlib.util
from importlib.machinery import SourceFileLoader
loader = SourceFileLoader('ds_doctor', '$DOCTOR')
spec = importlib.util.spec_from_loader('ds_doctor', loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
print(mod._resolve_hook_src(mod.Path('$repo_dir')))
"
}

# ---------------------------------------------------------------------------
# Topology 1: ordinary checkout with hooks/pre-commit and a real
# scripts/lib/precommit.sh (the fixture copy).
# ---------------------------------------------------------------------------
TMP1="$(mktemp -d)"
ORDINARY="$TMP1/ordinary-repo"
mkdir -p "$ORDINARY"
(
  cd "$ORDINARY"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p hooks scripts/lib
  printf '#!/usr/bin/env bash\nexit 0\n' > hooks/pre-commit
  chmod +x hooks/pre-commit
  printf '%s' "$FIXTURE_PRECOMMIT_SH" > scripts/lib/precommit.sh
  git add hooks/pre-commit scripts/lib/precommit.sh
  git commit -q -m init
)

BASH_ORDINARY="$(_bash_resolve "$ORDINARY")"
PY_ORDINARY="$(_python_resolve "$ORDINARY")"
REAL_ORDINARY_HOOK="$(python3 -c "import os; print(os.path.realpath('$ORDINARY/hooks/pre-commit'))")"

if [[ "$(python3 -c "import os; print(os.path.realpath('$BASH_ORDINARY'))")" == "$REAL_ORDINARY_HOOK" && \
      "$(python3 -c "import os; print(os.path.realpath('$PY_ORDINARY'))")" == "$REAL_ORDINARY_HOOK" ]]; then
  _pass "Topology 1 (ordinary checkout): bash and python agree, both resolve to the checkout's own hooks/pre-commit"
else
  _fail "Topology 1 (ordinary checkout): bash='$BASH_ORDINARY' python='$PY_ORDINARY' expected='$REAL_ORDINARY_HOOK'"
fi

# ---------------------------------------------------------------------------
# Topology 2: linked git worktree. Direct pin (not just "both sides agree")
# - the resolved path must be the PRIMARY checkout's hooks/pre-commit
# specifically, never the worktree's own copy. A double regression (both
# resolvers independently repointing into the worktree) would still pass
# an agreement-only assertion; this pin closes that gap.
# ---------------------------------------------------------------------------
TMP2="$(mktemp -d)"
PRIMARY="$TMP2/primary-repo"
mkdir -p "$PRIMARY"
(
  cd "$PRIMARY"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p hooks scripts/lib
  printf '#!/usr/bin/env bash\nexit 0\n' > hooks/pre-commit
  chmod +x hooks/pre-commit
  printf '%s' "$FIXTURE_PRECOMMIT_SH" > scripts/lib/precommit.sh
  git add hooks/pre-commit scripts/lib/precommit.sh
  git commit -q -m init
)
WORKTREE="$TMP2/linked-worktree"
(
  cd "$PRIMARY"
  git worktree add -q -b parity-wt-branch "$WORKTREE"
)

BASH_WT="$(_bash_resolve "$WORKTREE")"
PY_WT="$(_python_resolve "$WORKTREE")"
REAL_PRIMARY_HOOK="$(python3 -c "import os; print(os.path.realpath('$PRIMARY/hooks/pre-commit'))")"
REAL_WORKTREE_HOOK="$(python3 -c "import os; print(os.path.realpath('$WORKTREE/hooks/pre-commit'))")"

if [[ "$(python3 -c "import os; print(os.path.realpath('$BASH_WT'))")" == "$REAL_PRIMARY_HOOK" ]]; then
  _pass "Topology 2 (linked worktree): bash resolves to the PRIMARY checkout, not the worktree"
else
  _fail "Topology 2 (linked worktree): bash resolved '$BASH_WT', expected the primary hook '$REAL_PRIMARY_HOOK' (worktree's own copy would be '$REAL_WORKTREE_HOOK')"
fi

if [[ "$(python3 -c "import os; print(os.path.realpath('$PY_WT'))")" == "$REAL_PRIMARY_HOOK" ]]; then
  _pass "Topology 2 (linked worktree): python resolves to the PRIMARY checkout, not the worktree"
else
  _fail "Topology 2 (linked worktree): python resolved '$PY_WT', expected the primary hook '$REAL_PRIMARY_HOOK' (worktree's own copy would be '$REAL_WORKTREE_HOOK')"
fi

if [[ "$BASH_WT" == "$PY_WT" ]]; then
  _pass "Topology 2 (linked worktree): bash and python agree on the raw resolved path"
else
  _fail "Topology 2 (linked worktree): bash='$BASH_WT' python='$PY_WT' - disagree"
fi

# ---------------------------------------------------------------------------
# Topology 3: checkout missing hooks/pre-commit entirely. Both sides must
# still degrade to the historical fallback (repo_dir/hooks/pre-commit) -
# neither raises, neither returns an empty string.
# ---------------------------------------------------------------------------
TMP3="$(mktemp -d)"
NO_HOOK="$TMP3/no-hook-repo"
mkdir -p "$NO_HOOK/scripts/lib"
(
  cd "$NO_HOOK"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  printf '%s' "$FIXTURE_PRECOMMIT_SH" > scripts/lib/precommit.sh
  git add scripts/lib/precommit.sh
  git commit -q -m init
)

BASH_NOHOOK="$(_bash_resolve "$NO_HOOK")"
PY_NOHOOK="$(_python_resolve "$NO_HOOK")"
EXPECTED_FALLBACK="$(python3 -c "import os; print(os.path.realpath('$NO_HOOK'))")/hooks/pre-commit"

if [[ "$BASH_NOHOOK" == "$EXPECTED_FALLBACK" ]]; then
  _pass "Topology 3 (missing hooks/pre-commit): bash falls back to repo_dir/hooks/pre-commit"
else
  _fail "Topology 3 (missing hooks/pre-commit): bash resolved '$BASH_NOHOOK', expected fallback '$EXPECTED_FALLBACK'"
fi

if [[ "$PY_NOHOOK" == "$EXPECTED_FALLBACK" ]]; then
  _pass "Topology 3 (missing hooks/pre-commit): python falls back to repo_dir/hooks/pre-commit"
else
  _fail "Topology 3 (missing hooks/pre-commit): python resolved '$PY_NOHOOK', expected fallback '$EXPECTED_FALLBACK'"
fi

rm -rf "$TMP1" "$TMP2" "$TMP3"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
