#!/usr/bin/env bash
# Purpose: Regression test for Codex skill auto-load hook wiring.
# Public API: bash bin/tests/test_codex_skill_auto_load_hook.sh

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

PASS=0
FAIL=0

pass() { echo "PASS: $*"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $*" >&2; FAIL=$((FAIL + 1)); }

TMP_ROOT="$(mktemp -d)"
cleanup() { rm -rf "$TMP_ROOT"; }
trap cleanup EXIT

HOME_CODEX="$TMP_ROOT/home-codex"
SNAPSHOT="$TMP_ROOT/snapshot"
mkdir -p "$HOME_CODEX/.claude" "$HOME_CODEX/.codex" "$SNAPSHOT/.codex/config" "$SNAPSHOT/hooks"

printf '{"skill_auto_load": true}\n' > "$HOME_CODEX/.claude/agentic-engineering.json"
cp "$REPO_DIR/.codex/config/hooks.json" "$SNAPSHOT/.codex/config/hooks.json"
cp "$REPO_DIR/hooks/skill-auto-load-check.sh" "$SNAPSHOT/hooks/skill-auto-load-check.sh"
ln -s "$SNAPSHOT/.codex/config/hooks.json" "$HOME_CODEX/.codex/hooks.json"

skill_cmd="$(python3 - "$SNAPSHOT/.codex/config/hooks.json" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
for block in data["hooks"]["UserPromptSubmit"]:
    for hook in block["hooks"]:
        command = hook.get("command", "")
        if "skill-auto-load-check.sh" in command:
            print(command)
            raise SystemExit(0)
raise SystemExit("skill-auto-load-check command not found")
PYEOF
)"

if [[ "$skill_cmd" == *"AE_ADAPTER=codex"* ]]; then
  pass "codex hook command sets AE_ADAPTER=codex"
else
  fail "codex hook command does not set AE_ADAPTER=codex: $skill_cmd"
fi

if [[ "$skill_cmd" == *'/hooks/skill-auto-load-check.sh'* ]]; then
  pass "codex hook command targets root hooks directory"
else
  fail "codex hook command does not target root hooks directory: $skill_cmd"
fi

out="$(HOME="$HOME_CODEX" bash -c "$skill_cmd" 2>&1)"
if [[ "$out" == *"$HOME_CODEX/.agents/skills/agentic-engineering/SKILL.md"* ]]; then
  pass "codex skill auto-load output points at ~/.agents skill path"
else
  fail "expected codex ~/.agents skill path, got: $out"
fi

if [[ "$out" != *"$HOME_CODEX/.claude/skills/agentic-engineering/SKILL.md"* ]]; then
  pass "codex skill auto-load output does not point at Claude skill path"
else
  fail "codex output still points at Claude skill path: $out"
fi

echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
