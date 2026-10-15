#!/usr/bin/env bash
# Purpose: Regression test for hooks/pre-commit's staged-Python selection.
#          The hook sends staged bin/ds-* and bin/agentic-* CLIs to ruff and
#          mypy, but only those that are actually Python: an extension-less
#          CLI qualifies only by a python shebang. Before the fix, every
#          extension-less bin/ds-* name matched, so staging a bash CLI such
#          as bin/ds-lane handed it to `ruff check` and blocked the commit
#          with thousands of syntax errors.
#
# Public API: ./bin/tests/test_precommit_python_selection.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, mktemp, scripts/check-symlinks-relative.sh (the
#                hook runs it, so the fixture carries relative skill
#                symlinks for it to accept). Runs the hook in a throwaway fixture repo
#                with stub `ruff`/`mypy` executables first on PATH that record
#                their argv, so the real tools are neither needed nor invoked.
#
# Downstream consumers: developer running locally before commit; CI
#                       (bin-tests.yml auto-discovers bin/tests/test_*.sh).
#
# Failure modes: a staged non-Python bin CLI reaching ruff, or a staged
#                Python CLI/hook not reaching it -> FAIL naming the case.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
unset GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

STUB_BIN="$TMP/stub-bin"
RUFF_LOG="$TMP/ruff.log"
mkdir -p "$STUB_BIN"
cat > "$STUB_BIN/ruff" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$@" >> "$RUFF_LOG"
EOF
cat > "$STUB_BIN/mypy" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$STUB_BIN/ruff" "$STUB_BIN/mypy"
export PATH="$STUB_BIN:$PATH"

FIXTURE="$TMP/repo"
mkdir -p "$FIXTURE/hooks" "$FIXTURE/scripts" "$FIXTURE/bin"
cp "$REPO_ROOT/hooks/pre-commit" "$FIXTURE/hooks/pre-commit"
cp "$REPO_ROOT/scripts/check-symlinks-relative.sh" "$FIXTURE/scripts/check-symlinks-relative.sh"
printf '#!/usr/bin/env bash\necho bash\n' > "$FIXTURE/bin/ds-bashcli"
printf '#!/usr/bin/env node\nconsole.log(1)\n' > "$FIXTURE/bin/ds-nodecli"
printf '#!/usr/bin/env python3\nprint(1)\n' > "$FIXTURE/bin/ds-pycli"
printf 'print(1)\n' > "$FIXTURE/hooks/sample.py"
mkdir -p "$FIXTURE/.claude/skills/dinostack"
for link in agents commands references rules; do
  ln -s "../../../content/$link" "$FIXTURE/.claude/skills/dinostack/$link"
done

git -C "$FIXTURE" init -q
git -C "$FIXTURE" config user.email test@example.com
git -C "$FIXTURE" config user.name Test
git -C "$FIXTURE" add -A
git -C "$FIXTURE" commit -qm fixture --no-verify

FAIL=0

# Stage a trivial edit to each path given, run the hook, then reset.
run_hook_with_staged() {
  : > "$RUFF_LOG"
  local p
  for p in "$@"; do
    printf '# edit\n' >> "$FIXTURE/$p"
    git -C "$FIXTURE" add -- "$p"
  done
  if ! (cd "$FIXTURE" && bash hooks/pre-commit) > "$TMP/hook.out" 2>&1; then
    echo "FAIL: hook exited non-zero with staged: $*" >&2
    cat "$TMP/hook.out" >&2
    FAIL=1
  fi
  git -C "$FIXTURE" reset -q --hard HEAD
}

assert_not_linted() {
  if grep -qxF "$1" "$RUFF_LOG"; then
    echo "FAIL: $1 is not Python but was passed to ruff ($2)" >&2
    FAIL=1
  else
    echo "PASS: $1 not passed to ruff ($2)"
  fi
}

assert_linted() {
  if grep -qxF "$1" "$RUFF_LOG"; then
    echo "PASS: $1 passed to ruff ($2)"
  else
    echo "FAIL: $1 is Python but was not passed to ruff ($2)" >&2
    FAIL=1
  fi
}

run_hook_with_staged bin/ds-bashcli
assert_not_linted bin/ds-bashcli "bash CLI staged alone"
if [[ -s "$RUFF_LOG" ]]; then
  echo "FAIL: ruff ran with only a bash CLI staged" >&2
  FAIL=1
fi

run_hook_with_staged bin/ds-nodecli
assert_not_linted bin/ds-nodecli "node CLI staged alone"

run_hook_with_staged bin/ds-bashcli bin/ds-pycli hooks/sample.py
assert_not_linted bin/ds-bashcli "bash CLI staged with Python files"
assert_linted bin/ds-pycli "python-shebang CLI"
assert_linted hooks/sample.py ".py hook"

: > "$RUFF_LOG"
ln -s ds-bashcli "$FIXTURE/bin/agentic-bashcli"
ln -s ds-pycli "$FIXTURE/bin/agentic-pycli"
git -C "$FIXTURE" add bin/agentic-bashcli bin/agentic-pycli
(cd "$FIXTURE" && bash hooks/pre-commit) > "$TMP/hook.out" 2>&1 || { cat "$TMP/hook.out" >&2; FAIL=1; }
assert_not_linted bin/agentic-bashcli "compat symlink to a bash CLI"
assert_linted bin/agentic-pycli "compat symlink to a Python CLI"

if [[ "$FAIL" -ne 0 ]]; then
  echo "test_precommit_python_selection: FAIL" >&2
  exit 1
fi
echo "test_precommit_python_selection: PASS"
