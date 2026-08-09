#!/usr/bin/env bash
# Purpose: Emits a skill-load instruction to stdout when skill_auto_load is enabled in the
#          dinostack config. Called by Claude Code, Codex, and Gemini hook handlers.
#          Codex and Gemini already always-load the full methodology via their own root files
#          (.codex/AGENTS.md, .gemini/GEMINI.md), so this script gates them out unconditionally
#          before even reading the flag - the nudge would be pure waste for them.
# Public API: bash hooks/skill-auto-load-check.sh (no args; reads ~/.claude/agentic-engineering.json)
#             AE_ADAPTER=gemini selects the Gemini skip path (Gemini has no reliable script-dir
#             signature to detect on its own, so its hook wiring must set this explicitly).
#             Codex is auto-detected via script_dir (*/.codex/hooks) - AE_ADAPTER=codex is not
#             set anywhere in this repo, so detection must not depend on it being present.
# Upstream deps: ~/.claude/agentic-engineering.json (optional; missing = silent exit)
# Downstream consumers: .claude/install.sh (UserPromptSubmit hook), .codex/config/hooks.json
#                       (UserPromptSubmit hook), .gemini/install.sh (BeforeAgent hook)
# Failure modes: always exits 0; missing config, false flag, or codex/gemini adapter = silent
#                no-op; never blocks hook chain
# Performance: <5ms on the codex/gemini exit path (shell only, no python3);
#              <50ms otherwise (adds one python3 JSON parse)

ae_config="$HOME/.claude/agentic-engineering.json"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
adapter="${AE_ADAPTER:-}"
if [[ -z "$adapter" && "$script_dir" == *"/.codex/hooks" ]]; then
  adapter="codex"
fi

# Adapters whose own root file already always-loads the full methodology get zero
# benefit from this nudge, regardless of the skill_auto_load flag - checked BEFORE
# reading the flag so this always fires for them.
case "$adapter" in
  codex|gemini)
    exit 0
    ;;
esac

skill_auto_load=$(python3 -c "
import json, sys
try:
    with open('$ae_config') as f:
        val = json.load(f).get('skill_auto_load', False)
        print('true' if val is True else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")

if [[ "$skill_auto_load" == "true" ]]; then
  skill_path="$HOME/.claude/skills/dinostack/SKILL.md"
  echo "SKILL CHECK [dinostack]: skill_auto_load=true."
  echo "Before responding to any software development request, read $skill_path."
  echo "Do not implement directly - follow the delegation and risk classification protocol in that file."
fi

exit 0
