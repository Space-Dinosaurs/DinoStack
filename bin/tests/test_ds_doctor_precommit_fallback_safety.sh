#!/usr/bin/env bash
# Purpose: Regression tests for bin/ds-doctor's _resolve_hook_src failure
#          handling. On any resolution failure, _resolve_hook_src must
#          return None - NEVER the historical repo_dir/hooks/pre-commit
#          hardcode, which is the wrong target by construction for a
#          linked-worktree repo_dir (the exact Major this branch exists to
#          close). Falling back to that hardcode on failure would fail
#          toward the defect, silently, on the common unattended path
#          (`ds-update` -> `ds-doctor --fix`).
#
#          Covers every documented failure trigger individually:
#            1. scripts/lib/precommit.sh missing entirely
#            2. scripts/lib/precommit.sh present but resolve_hook_src
#               undefined there
#            3. bash unavailable on PATH (real OSError/FileNotFoundError)
#            4. a subprocess.SubprocessError (e.g. TimeoutExpired)
#          Plus one end-to-end assertion: check_git_precommit WARNs (not
#          FIX) and performs no symlink write when the source cannot be
#          resolved.
#
# Public API: ./bin/tests/test_ds_doctor_precommit_fallback_safety.sh
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
# Performance: < 2 s wall time (pure git + shell + python, no network -
#              the timeout trigger is exercised via monkeypatching
#              subprocess.run, never a real 10 s wait).

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

# _init_repo <dir>: bare git init, no scripts/lib at all.
_init_repo() {
  local dir="$1"
  mkdir -p "$dir"
  (
    cd "$dir"
    git init -q
    git config user.email test@test.com
    git config user.name Test
    mkdir -p hooks
    printf '#!/usr/bin/env bash\nexit 0\n' > hooks/pre-commit
    chmod +x hooks/pre-commit
    git add hooks/pre-commit
    git commit -q -m init
  )
}

# ---------------------------------------------------------------------------
# Trigger 1: scripts/lib/precommit.sh missing entirely.
# ---------------------------------------------------------------------------
TMPROOT1="$(mktemp -d)"
T1="$TMPROOT1/trigger1-repo"
_init_repo "$T1"

if python3 -c "
import importlib.util
from importlib.machinery import SourceFileLoader
loader = SourceFileLoader('ds_doctor', '$DOCTOR')
spec = importlib.util.spec_from_loader('ds_doctor', loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
import sys
sys.exit(0 if mod._resolve_hook_src(mod.Path('$T1')) is None else 1)
"; then
  _pass "Trigger 1 (missing scripts/lib/precommit.sh): _resolve_hook_src returns None"
else
  _fail "Trigger 1 (missing scripts/lib/precommit.sh): _resolve_hook_src did NOT return None"
fi

# ---------------------------------------------------------------------------
# Trigger 2: scripts/lib/precommit.sh present but resolve_hook_src
# undefined there (an unrelated library file, or a stale pre-#640 copy).
# ---------------------------------------------------------------------------
TMPROOT2="$(mktemp -d)"
T2="$TMPROOT2/trigger2-repo"
_init_repo "$T2"
mkdir -p "$T2/scripts/lib"
cat > "$T2/scripts/lib/precommit.sh" <<'LIB_EOF'
# shellcheck shell=bash
# Deliberately does NOT define resolve_hook_src - simulates a stale
# pre-#640 copy of this library, or an unrelated file at the same path.
some_other_function() {
  echo "not resolve_hook_src"
}
LIB_EOF
(cd "$T2" && git add scripts/lib/precommit.sh && git commit -q -m "stale lib")

if python3 -c "
import importlib.util
from importlib.machinery import SourceFileLoader
loader = SourceFileLoader('ds_doctor', '$DOCTOR')
spec = importlib.util.spec_from_loader('ds_doctor', loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
import sys
sys.exit(0 if mod._resolve_hook_src(mod.Path('$T2')) is None else 1)
"; then
  _pass "Trigger 2 (resolve_hook_src undefined in lib): _resolve_hook_src returns None"
else
  _fail "Trigger 2 (resolve_hook_src undefined in lib): _resolve_hook_src did NOT return None"
fi

# ---------------------------------------------------------------------------
# Trigger 3: bash unavailable on PATH - a real OSError/FileNotFoundError,
# not a simulated one. Achieved by passing an empty PATH into the
# subprocess environment (the function builds its env from os.environ, so
# patching os.environ["PATH"] before the call reaches the child process
# exactly as it would if the operator's real PATH lacked bash).
# ---------------------------------------------------------------------------
TMPROOT3="$(mktemp -d)"
T3="$TMPROOT3/trigger3-repo"
_init_repo "$T3"
mkdir -p "$T3/scripts/lib"
cp "$REAL_LIB" "$T3/scripts/lib/precommit.sh"
(cd "$T3" && git add scripts/lib/precommit.sh && git commit -q -m "real lib")

if python3 -c "
import importlib.util, os
from importlib.machinery import SourceFileLoader
loader = SourceFileLoader('ds_doctor', '$DOCTOR')
spec = importlib.util.spec_from_loader('ds_doctor', loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
os.environ['PATH'] = ''
import sys
sys.exit(0 if mod._resolve_hook_src(mod.Path('$T3')) is None else 1)
"; then
  _pass "Trigger 3 (bash unavailable, empty PATH): _resolve_hook_src returns None (real OSError)"
else
  _fail "Trigger 3 (bash unavailable, empty PATH): _resolve_hook_src did NOT return None"
fi

# ---------------------------------------------------------------------------
# Trigger 4: subprocess.SubprocessError (TimeoutExpired). Monkeypatches
# subprocess.run to raise directly - exercises the real except clause
# without a real 10 s wait.
# ---------------------------------------------------------------------------
TMPROOT4="$(mktemp -d)"
T4="$TMPROOT4/trigger4-repo"
_init_repo "$T4"
mkdir -p "$T4/scripts/lib"
cp "$REAL_LIB" "$T4/scripts/lib/precommit.sh"
(cd "$T4" && git add scripts/lib/precommit.sh && git commit -q -m "real lib")

if python3 -c "
import importlib.util, subprocess
from importlib.machinery import SourceFileLoader
loader = SourceFileLoader('ds_doctor', '$DOCTOR')
spec = importlib.util.spec_from_loader('ds_doctor', loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

def raiser(*a, **k):
    raise subprocess.TimeoutExpired(cmd='bash', timeout=10)

orig = subprocess.run
subprocess.run = raiser
try:
    result = mod._resolve_hook_src(mod.Path('$T4'))
finally:
    subprocess.run = orig

import sys
sys.exit(0 if result is None else 1)
"; then
  _pass "Trigger 4 (subprocess.TimeoutExpired): _resolve_hook_src returns None"
else
  _fail "Trigger 4 (subprocess.TimeoutExpired): _resolve_hook_src did NOT return None"
fi

# ---------------------------------------------------------------------------
# End-to-end: check_git_precommit WARNs (not FIX) and performs NO symlink
# write when _resolve_hook_src cannot resolve a target. Reuses Trigger 1's
# fixture layout (missing scripts/lib/precommit.sh) via a full ds-doctor
# --fix invocation, confirming the fallback-safety fix holds through the
# real CLI entrypoint, not just the unit-level function.
# ---------------------------------------------------------------------------
TEMP_HOME="$(mktemp -d)"
E2E_REPO="$TEMP_HOME/e2e-repo"
_init_repo "$E2E_REPO"

mkdir -p "$TEMP_HOME/.agentic"
cat > "$TEMP_HOME/.agentic/agentic-engineering-config.json" <<CONFIG_EOF
{
  "repo_dir": "$E2E_REPO"
}
CONFIG_EOF

# unset CLAUDE_CONFIG_DIR: a real value set in the invoking session would
# make _plugins_dir() resolve OUTSIDE TEMP_HOME during this full ds-doctor
# invocation (DS-198 round 3, Skeptic Major 2 sweep).
OUT=$(HOME="$TEMP_HOME" CLAUDE_CONFIG_DIR= python3 "$DOCTOR" --fix 2>&1)

if echo "$OUT" | grep -q "WARN git_precommit:"; then
  _pass "End-to-end: check_git_precommit WARNs when the hook source cannot be resolved"
else
  _fail "End-to-end: expected a WARN git_precommit line, got:\n$OUT"
fi

if echo "$OUT" | grep -qE "FIX symlink: .*git_precommit|FIX symlink: .*pre-commit"; then
  _fail "End-to-end: a symlink FIX was announced despite the unresolved hook source (should be WARN-only, no write attempt):\n$OUT"
else
  _pass "End-to-end: no symlink FIX announced for git_precommit when the hook source cannot be resolved"
fi

if [[ -e "$E2E_REPO/.git/hooks/pre-commit" || -L "$E2E_REPO/.git/hooks/pre-commit" ]]; then
  _fail "End-to-end: a pre-commit symlink was written at $E2E_REPO/.git/hooks/pre-commit despite the unresolved hook source"
else
  _pass "End-to-end: no pre-commit symlink was written when the hook source could not be resolved"
fi

rm -rf "$TMPROOT1" "$TMPROOT2" "$TMPROOT3" "$TMPROOT4" "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
