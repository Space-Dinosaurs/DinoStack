#!/usr/bin/env bash
# Purpose: Regression test for Gemini skill auto-load hook wiring. Originally
#          DS-143 (Gemini always-loaded the full methodology via
#          .gemini/GEMINI.md, so the shared skill-auto-load-check.sh script
#          gated Gemini out unconditionally with zero output). As of DS-184,
#          .gemini/GEMINI.md is a small stub pointing at the trigger-loaded
#          dinostack skill (.gemini/skills/dinostack/SKILL.md) instead of
#          carrying the methodology body itself, so Gemini now gets the same
#          non-empty nudge Claude does - pointed at its own skill path,
#          rather than Claude's ~/.claude/skills/dinostack/SKILL.md. Gemini
#          still has no detectable script_dir signature of its own (unlike
#          Codex's */.codex/hooks shape), so .gemini/install.sh must tag the
#          BeforeAgent SKILL_CMD it writes with AE_ADAPTER=gemini. This
#          asserts both halves: the real install.sh actually writes that tag
#          into ~/.gemini/settings.json, and the shared hook script honors
#          it with the Gemini-specific nudge text.
#
# Public API: ./bin/tests/test_gemini_skill_auto_load_hook.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, git, mktemp.
#
# Downstream consumers: developer running locally before commit; CI
#   (bin-sh-tests auto-discovers bin/tests/test_*.sh).
#
# Failure modes: any assertion failure prints the failing assertion and exits
#                1. A temporary fake HOME is used; the real ~/.gemini is
#                never touched. .gemini/install.sh is run against the REAL
#                checkout - only $HOME is sandboxed - and it invokes
#                .gemini/build.sh (regenerates .gemini/ adapter artifacts in
#                the live tree from content/); verified it does not write
#                <repo>/.git/hooks/pre-commit and does not invoke
#                .claude/build.sh or .cursor/build.sh (unlike the .claude/
#                .codex/.kimi install paths exercised in
#                bin/tests/test_hooks_snapshot_migration.sh). The
#                precommit-hook-guard save/restore calls here are
#                belt-and-braces, not load-bearing - kept for parity with the
#                sibling test in case .gemini/install.sh's build chain
#                changes later, not because the current chain touches it.
#
# Performance: ~5-10s wall time (one .gemini/install.sh run, which invokes
#              .gemini/build.sh only).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

# shellcheck source=bin/tests/lib/precommit-hook-guard.sh
. "$REPO_DIR/bin/tests/lib/precommit-hook-guard.sh"

PASS=0
FAIL=0

pass() { echo "PASS: $*"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $*" >&2; FAIL=$((FAIL + 1)); }

TMP_ROOT="$(mktemp -d)"
cleanup() {
  precommit_hook_guard_restore
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

HOME_GEMINI="$TMP_ROOT/home-gemini"
mkdir -p "$HOME_GEMINI/.gemini" "$HOME_GEMINI/.claude"

# Pre-seed skill_auto_load: true so the zero-output assertion below actually
# exercises the AE_ADAPTER=gemini gate rather than passing vacuously because
# the flag defaulted to false (install.sh only prompts - defaulting to "no"
# under < /dev/null - when the key is absent; a pre-existing key is preserved
# verbatim).
printf '{"skill_auto_load": true}\n' > "$HOME_GEMINI/.claude/agentic-engineering.json"

precommit_hook_guard_save "$REPO_DIR"

HOME="$HOME_GEMINI" bash "$REPO_DIR/.gemini/install.sh" --mode=opt-out --profile=default \
  < /dev/null > "$TMP_ROOT/install_out.log" 2>&1
INSTALL_RC=$?

if [[ $INSTALL_RC -ne 0 ]]; then
  echo "  [install.sh output]:" >&2
  cat "$TMP_ROOT/install_out.log" >&2
  fail ".gemini/install.sh exited $INSTALL_RC"
fi

SETTINGS="$HOME_GEMINI/.gemini/settings.json"
if [[ ! -f "$SETTINGS" ]]; then
  fail ".gemini/install.sh did not write $SETTINGS"
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

skill_cmd="$(python3 -c "
import json
with open('$SETTINGS') as f:
    d = json.load(f)
for block in d['hooks'].get('BeforeAgent', []):
    for h in block.get('hooks', []):
        command = h.get('command', '')
        if 'skill-auto-load-check.sh' in command:
            print(command)
            raise SystemExit(0)
raise SystemExit('skill-auto-load-check command not found')
" 2>&1)"

if [[ "$skill_cmd" == *"AE_ADAPTER=gemini"* ]]; then
  pass "gemini BeforeAgent skill-auto-load-check command carries the AE_ADAPTER=gemini tag"
else
  fail "gemini BeforeAgent skill-auto-load-check command missing AE_ADAPTER=gemini tag: $skill_cmd"
fi

out="$(HOME="$HOME_GEMINI" bash -c "$skill_cmd" 2>&1)"
if [[ -n "$out" ]] && [[ "$out" == *"$HOME_GEMINI/.gemini/skills/dinostack/SKILL.md"* ]]; then
  pass "gemini skill auto-load emits a non-empty nudge pointing at .gemini/skills/dinostack/SKILL.md (DS-184)"
else
  fail "expected a nudge naming .gemini/skills/dinostack/SKILL.md for gemini, got: $out"
fi

echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
