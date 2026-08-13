#!/usr/bin/env bash
# Purpose: Regression guard for DS-57. .codex/config/hooks.json wires each
#          hook command to self-locate at runtime via
#          dirname(dirname(realpath($HOME/.codex/hooks.json)))/hooks/<script>
#          - a script that is committed nowhere gets silently dropped (the
#          hook fires, the resolved path does not exist, nothing errors).
#          This test asserts every "command" entry in the checkout's
#          .codex/config/hooks.json resolves to an existing, executable
#          file - the same failure mode DS-57 fixed for
#          skill-auto-load-check.sh.
#
# Public API: ./bin/tests/test_codex_hooks_resolve.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, mktemp.
#
# Downstream consumers: developer running locally before commit; CI
#                        (wired into .github/workflows/adapter-sync.yml).
#
# Failure modes: any command whose resolved script path does not exist (or
#                is not executable) fails the test. A temporary fake HOME is
#                used to stand in for ~/.codex/hooks.json -> the real HOME
#                is never touched. Only the path-resolution expression
#                inside each command is evaluated (via bash command
#                substitution) - the interpreter is never actually invoked,
#                so this test has no side effects even if a resolved script
#                has some. On bash 3.2 (macOS default), the previous
#                `mapfile -t COMMANDS < <(python3 -c "...")` form both failed
#                (mapfile does not exist pre-4.0) and, once worked around,
#                left COMMANDS unset when hooks.json had zero entries - an
#                unguarded "${COMMANDS[@]}" expansion under `set -u` then
#                raised "unbound variable" before this test's own empty-set
#                diagnostic could print. Fixed by writing the extractor's
#                output to a temp file and reading it back with a `while
#                read` loop, and by guarding the loop expansion with
#                "${COMMANDS[@]+"${COMMANDS[@]}"}".
#
# Performance: < 1 s wall time (pure shell + python3, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOKS_JSON="$REPO_DIR/.codex/config/hooks.json"

if [[ ! -f "$HOOKS_JSON" ]]; then
  echo "FAIL: $HOOKS_JSON not found" >&2
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

# Stand in for ~/.codex/hooks.json -> .codex/config/hooks.json, exactly as
# .codex/install.sh wires it (a symlink), so realpath-based self-location in
# each command resolves the same way it would for a real install.
FAKE_HOME="$TMP_ROOT/home"
mkdir -p "$FAKE_HOME/.codex"
ln -s "$HOOKS_JSON" "$FAKE_HOME/.codex/hooks.json"

# Extract every "command" string from hooks.json (order-independent walk).
# The path is passed as sys.argv[1] rather than interpolated into the Python
# source string, so a checkout path containing a quote or $ cannot break the
# script. bash 3.2 (macOS default) lacks `mapfile`, so the output is written
# to a temp file and read back with a `while read` loop instead - see
# bin/tests/test_tasks_jsonl_fold.sh:60-68 for why a pipe-fed `while read`
# (subshell discards state) is also avoided.
_CMDS_TMP="$TMP_ROOT/commands.txt"
python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)

def walk(node):
    if isinstance(node, dict):
        cmd = node.get('command')
        if isinstance(cmd, str):
            print(cmd)
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)
    return
    yield

list(walk(data))
" "$HOOKS_JSON" > "$_CMDS_TMP"

COMMANDS=()
while IFS= read -r line; do
  COMMANDS+=("$line")
done < "$_CMDS_TMP"

if [[ ${#COMMANDS[@]} -eq 0 ]]; then
  _fail "no 'command' entries found in $HOOKS_JSON - parser or fixture regressed"
else
  _pass "found ${#COMMANDS[@]} command entries in $HOOKS_JSON"
fi

for cmd in "${COMMANDS[@]+"${COMMANDS[@]}"}"; do
  # Each command has the shape:
  #   <interpreter> "<path-expression-with-$(...)-substitutions>"
  # Extract just the quoted path expression and evaluate it under FAKE_HOME
  # (command-substitution-only - never invokes the interpreter itself).
  if [[ "$cmd" =~ ^[a-zA-Z0-9_]+[[:space:]]+\"(.+)\"$ ]]; then
    path_expr="${BASH_REMATCH[1]}"
  else
    _fail "command does not match '<interpreter> \"<path>\"' shape: $cmd"
    continue
  fi

  resolved="$(HOME="$FAKE_HOME" bash -c "printf '%s' \"$path_expr\"" 2>/dev/null)"

  if [[ -z "$resolved" ]]; then
    _fail "command resolved to an empty path: $cmd"
    continue
  fi

  if [[ ! -f "$resolved" ]]; then
    _fail "command resolves to a missing script: $resolved (command: $cmd)"
    continue
  fi

  if [[ ! -x "$resolved" ]]; then
    _fail "command resolves to a non-executable script: $resolved (command: $cmd)"
    continue
  fi

  _pass "command resolves to an existing, executable script: $resolved"
done

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
