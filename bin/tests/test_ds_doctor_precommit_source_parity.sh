#!/usr/bin/env bash
# Purpose: Assert that bin/ds-doctor's _resolve_hook_src (Python) and
#          scripts/lib/precommit.sh's REAL resolve_hook_src (bash) agree on
#          the expected pre-commit hook symlink SOURCE across three
#          topologies: an ordinary checkout, a linked git worktree, and a
#          checkout missing hooks/pre-commit entirely. "Both sides agree"
#          alone is not a sufficient regression guard here - a double
#          regression (both resolvers independently repointing into the
#          worktree) would still pass an agreement-only check, so the
#          linked-worktree case additionally pins the resolved path to the
#          PRIMARY checkout's hooks/pre-commit specifically, not merely
#          "whatever the two sides happen to agree on".
#
# Both sides of the comparison source the REPO'S OWN real
# scripts/lib/precommit.sh (cp'd from REPO_ROOT into each fixture repo, not
# an embedded stand-in). A prior round of this test used an embedded
# fixture copy of resolve_hook_src for BOTH sides of the comparison; a
# Skeptic review demonstrated that renaming the real resolve_hook_src to
# resolve_precommit_source (an ordinary refactor of the shared lib) left
# this test fully green while silently reintroducing the exact Major this
# branch exists to close - the parity check was verifying two copies of
# itself, never the real library. A precondition assertion below hard-fails
# (never skips) if the real library is missing or does not define
# resolve_hook_src, since a silently-skipped assertion is indistinguishable
# from a passing one in a CI job log.
#
# No topology here needs a synthetic stand-in: all three only differ in
# fixture repo LAYOUT (ordinary checkout / linked worktree / no
# hooks/pre-commit), not in which resolve_hook_src implementation is under
# test - so the real library is used throughout, with no embedded copy
# retained anywhere in this file.
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
#                the real repo is never touched (its precommit.sh is only
#                READ and cp'd, never written).
#
# Performance: < 2 s wall time (pure git + shell + python, no network).

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOCTOR="$SCRIPT_DIR/ds-doctor"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REAL_LIB="$REPO_ROOT/scripts/lib/precommit.sh"

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

# ---------------------------------------------------------------------------
# Precondition (hard failure, never a skip): the real library must exist
# and define resolve_hook_src, or every topology below would silently
# exercise nothing.
# ---------------------------------------------------------------------------
if [[ ! -f "$REAL_LIB" ]]; then
  _fail "precondition: $REAL_LIB not found - cannot exercise the real resolve_hook_src (hard failure, not a skip)"
elif ! grep -qE '^resolve_hook_src[[:space:]]*\(\)' "$REAL_LIB"; then
  _fail "precondition: $REAL_LIB does not define resolve_hook_src - cannot exercise the real function (hard failure, not a skip)"
else
  _pass "precondition: $REAL_LIB defines resolve_hook_src"
fi

# _bash_resolve <repo_dir>: source the REAL scripts/lib/precommit.sh and
# call its resolve_hook_src in a fresh subshell.
_bash_resolve() {
  local repo_dir="$1"
  bash -c 'source "$1"; resolve_hook_src "$2"' _ "$REAL_LIB" "$repo_dir"
}

# _python_resolve <repo_dir>: import bin/ds-doctor as a module and call its
# private _resolve_hook_src directly - the exact function check_git_precommit
# calls, not a reimplementation. It shells into repo_dir's OWN
# scripts/lib/precommit.sh (a cp of the real one, per fixture below).
_python_resolve() {
  local repo_dir="$1"
  python3 -c "
import importlib.util
from importlib.machinery import SourceFileLoader
loader = SourceFileLoader('ds_doctor', '$DOCTOR')
spec = importlib.util.spec_from_loader('ds_doctor', loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
result = mod._resolve_hook_src(mod.Path('$repo_dir'))
print(result if result is not None else '')
"
}

# ---------------------------------------------------------------------------
# Topology 1: ordinary checkout with hooks/pre-commit and a real (cp'd)
# scripts/lib/precommit.sh.
# ---------------------------------------------------------------------------
TMP1="$(mktemp -d)"
ORDINARY="$TMP1/ordinary-repo"
mkdir -p "$ORDINARY/scripts/lib"
(
  cd "$ORDINARY"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p hooks
  printf '#!/usr/bin/env bash\nexit 0\n' > hooks/pre-commit
  chmod +x hooks/pre-commit
  cp "$REAL_LIB" scripts/lib/precommit.sh
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
mkdir -p "$PRIMARY/scripts/lib"
(
  cd "$PRIMARY"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p hooks
  printf '#!/usr/bin/env bash\nexit 0\n' > hooks/pre-commit
  chmod +x hooks/pre-commit
  cp "$REAL_LIB" scripts/lib/precommit.sh
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
# Topology 3: checkout missing hooks/pre-commit entirely (but WITH a real
# scripts/lib/precommit.sh). resolve_hook_src's ordinary-checkout fallback
# branch is NOT existence-gated (see the real function's own header), so
# both sides must still degrade to the historical
# repo_dir/hooks/pre-commit STRING even though that path does not exist on
# disk - neither raises, neither returns empty.
# ---------------------------------------------------------------------------
TMP3="$(mktemp -d)"
NO_HOOK="$TMP3/no-hook-repo"
mkdir -p "$NO_HOOK/scripts/lib"
(
  cd "$NO_HOOK"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  cp "$REAL_LIB" scripts/lib/precommit.sh
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

# ---------------------------------------------------------------------------
# Regression: an ambient GIT_DIR/GIT_WORK_TREE in the CALLING process's
# environment must not override the explicit repo_dir argument.
# _resolve_hook_src's subprocess.run passes an explicit env=; without the
# scrub, a caller with GIT_DIR set (e.g. mid-rebase, a wrapper script, a
# git hook) makes the child `git`/`bash -c 'source ...; resolve_hook_src'`
# invocation silently resolve against GIT_DIR's repo instead of the
# WORKTREE path actually passed in. Reuses Topology 2's primary/worktree
# fixture: with GIT_DIR pointed at the PRIMARY checkout while resolving
# for the WORKTREE, the answer must still be the primary hook (same
# correct answer as Topology 2 got without any GIT_DIR override) - not a
# path derived from GIT_DIR's own git-common-dir composed with the WRONG
# working tree.
# ---------------------------------------------------------------------------
PY_WT_GITDIR_SET="$(python3 -c "
import importlib.util, os
from importlib.machinery import SourceFileLoader
loader = SourceFileLoader('ds_doctor', '$DOCTOR')
spec = importlib.util.spec_from_loader('ds_doctor', loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
os.environ['GIT_DIR'] = '$PRIMARY/.git'
result = mod._resolve_hook_src(mod.Path('$WORKTREE'))
print(result if result is not None else '')
")"

if [[ "$(python3 -c "import os; print(os.path.realpath('$PY_WT_GITDIR_SET'))" 2>/dev/null)" == "$REAL_PRIMARY_HOOK" ]]; then
  _pass "Env scrub: ambient GIT_DIR does not change the resolved answer for an explicit worktree repo_dir"
else
  _fail "Env scrub: ambient GIT_DIR=$PRIMARY/.git changed the resolved answer for repo_dir=$WORKTREE - got '$PY_WT_GITDIR_SET', expected '$REAL_PRIMARY_HOOK'"
fi

# ---------------------------------------------------------------------------
# Regression: _resolve_git_hooks_dir must ALSO scrub the ambient git env -
# this is the WRITE DESTINATION resolver, not the symlink SOURCE resolver
# above, and the two are separate functions with separate subprocess.run
# calls. Reuses ORDINARY (Topology 1, repo A) and PRIMARY (Topology 2,
# repo B) as two distinct ordinary repos: with GIT_DIR pointed at repo B
# while resolving repo A's hooks dir, the answer must still be repo A's
# own hooks dir - not repo B's (the exact failure mode: GIT_DIR silently
# overrides -C for git plumbing commands regardless of which repo_dir was
# actually passed in).
# ---------------------------------------------------------------------------
PY_HOOKS_DIR_GITDIR_SET="$(python3 -c "
import importlib.util, os
from importlib.machinery import SourceFileLoader
loader = SourceFileLoader('ds_doctor', '$DOCTOR')
spec = importlib.util.spec_from_loader('ds_doctor', loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
os.environ['GIT_DIR'] = '$PRIMARY/.git'
result = mod._resolve_git_hooks_dir(mod.Path('$ORDINARY'))
print(result if result is not None else '')
")"

REAL_ORDINARY_HOOKS_DIR="$(python3 -c "import os; print(os.path.realpath('$ORDINARY/.git/hooks'))")"
REAL_PRIMARY_HOOKS_DIR="$(python3 -c "import os; print(os.path.realpath('$PRIMARY/.git/hooks'))")"

if [[ "$(python3 -c "import os; print(os.path.realpath('$PY_HOOKS_DIR_GITDIR_SET'))" 2>/dev/null)" == "$REAL_ORDINARY_HOOKS_DIR" ]]; then
  _pass "Env scrub: _resolve_git_hooks_dir - ambient GIT_DIR does not change the resolved hooks DIRECTORY for an explicit repo_dir"
else
  _fail "Env scrub: _resolve_git_hooks_dir - ambient GIT_DIR=$PRIMARY/.git changed the resolved hooks dir for repo_dir=$ORDINARY - got '$PY_HOOKS_DIR_GITDIR_SET', expected '$REAL_ORDINARY_HOOKS_DIR' (repo B's own would be '$REAL_PRIMARY_HOOKS_DIR')"
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
