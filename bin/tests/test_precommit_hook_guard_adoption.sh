#!/usr/bin/env bash
# Purpose: End-to-end check that bin/tests/test_hooks_snapshot_migration.sh
#          puts the pre-commit hook back even when it dies right after its
#          first .claude/install.sh run. Builds two copies of that file cut
#          after the first install and forced to `exit 1`: POSTFIX as it
#          stands, PREFIX with its precommit_hook_guard_save line removed.
#          Both copies are derived from the current working-tree file, so
#          the check needs no git history or origin/* ref. Asserts PREFIX
#          leaves a hook behind (the escape reproduces) and POSTFIX leaves
#          the hooks dir as it found it (the guard works).
#
#          Both runs point core.hooksPath at an empty temp dir through
#          GIT_CONFIG_COUNT/KEY/VALUE, which `git rev-parse --git-path hooks`
#          honors in install.sh and the guard alike, so the real checkout's
#          hook is never touched; a final assertion confirms it.
#
# Public API: ./bin/tests/test_precommit_hook_guard_adoption.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, git >= 2.31 (GIT_CONFIG_COUNT), plus
#                whatever .claude/install.sh needs.
#
# Performance: two partial .claude/install.sh runs, each with a build pass.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SOURCE_TEST="$REPO_DIR/bin/tests/test_hooks_snapshot_migration.sh"

PASS=0
FAIL=0
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }

TMP_ROOT="$(mktemp -d)"
_cleanup() { rm -rf "$TMP_ROOT"; }
trap _cleanup EXIT INT TERM

_real_hook_state() {
  local hooks_dir hook
  hooks_dir="$(git -C "$REPO_DIR" rev-parse --git-path hooks 2>/dev/null)" || { echo "(unresolved)"; return; }
  case "$hooks_dir" in /*) : ;; *) hooks_dir="$REPO_DIR/$hooks_dir" ;; esac
  hook="$hooks_dir/pre-commit"
  if [[ -L "$hook" ]]; then readlink "$hook"
  elif [[ -e "$hook" ]]; then cksum < "$hook"
  else echo "(absent)"
  fi
}

# _build_copy <PREFIX|POSTFIX> <out>
_build_copy() {
  python3 - "$SOURCE_TEST" "$2" "$1" "$REPO_DIR" <<'PYEOF'
import sys
src_path, out_path, variant, repo_dir = sys.argv[1:5]
src = open(src_path).read()

repo_line = 'REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"\n'
if src.count(repo_line) != 1:
    sys.exit("REPO_DIR line not found exactly once")
src = src.replace(repo_line, "REPO_DIR='%s'\n" % repo_dir.replace("'", "'\\''"))

save_line = 'precommit_hook_guard_save "$REPO_DIR"\n'
if src.count(save_line) != 1:
    sys.exit("expected exactly one guard save line, found %d" % src.count(save_line))
if variant == "PREFIX":
    src = src.replace(save_line, "")
elif variant != "POSTFIX":
    sys.exit("unknown variant " + variant)

marker = 'claude: first install.sh run exited non-zero'
end = src.index('\nfi\n', src.index(marker)) + len('\nfi\n')
open(out_path, "w").write(src[:end] + "\nexit 1\n")
PYEOF
}

# _run_copy <copy> <hooks_dir> <home>
_run_copy() {
  mkdir -p "$2" "$3/.claude"
  GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0="$2" \
    HOME="$3" bash "$1" < /dev/null > "$3/.out" 2>&1
}

REAL_BEFORE="$(_real_hook_state)"

if _build_copy PREFIX "$TMP_ROOT/prefix.sh"; then
  _run_copy "$TMP_ROOT/prefix.sh" "$TMP_ROOT/hooks-prefix" "$TMP_ROOT/home-prefix"
  if [[ -e "$TMP_ROOT/hooks-prefix/pre-commit" || -L "$TMP_ROOT/hooks-prefix/pre-commit" ]]; then
    _pass "without the guard save, an early exit leaves install.sh's pre-commit hook behind"
  else
    _fail "without the guard save, no pre-commit hook was left behind - the reproduction did not fire (output: $TMP_ROOT/home-prefix/.out)"
    tail -20 "$TMP_ROOT/home-prefix/.out" >&2
  fi
else
  _fail "could not build the PREFIX copy of test_hooks_snapshot_migration.sh"
fi

if _build_copy POSTFIX "$TMP_ROOT/postfix.sh"; then
  _run_copy "$TMP_ROOT/postfix.sh" "$TMP_ROOT/hooks-postfix" "$TMP_ROOT/home-postfix"
  if grep -q "claude: first install.sh run" "$TMP_ROOT/home-postfix/.out" \
     && [[ ! -e "$TMP_ROOT/hooks-postfix/pre-commit" && ! -L "$TMP_ROOT/hooks-postfix/pre-commit" ]]; then
    _pass "with the guard save, an early exit after the first install.sh restores the hooks dir"
  else
    _fail "with the guard save, the hooks dir was not restored after an early exit"
    tail -20 "$TMP_ROOT/home-postfix/.out" >&2
  fi
else
  _fail "could not build the POSTFIX copy of test_hooks_snapshot_migration.sh"
fi

REAL_AFTER="$(_real_hook_state)"
if [[ "$REAL_AFTER" == "$REAL_BEFORE" ]]; then
  _pass "the real checkout's pre-commit hook is unchanged ($REAL_AFTER)"
else
  _fail "the real checkout's pre-commit hook changed: '$REAL_BEFORE' -> '$REAL_AFTER'"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed."
[[ "$FAIL" -eq 0 ]]
