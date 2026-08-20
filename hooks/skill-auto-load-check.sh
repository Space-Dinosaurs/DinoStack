#!/usr/bin/env bash
# Purpose: Emits a skill-load instruction to stdout when skill_auto_load is enabled in the
#          dinostack config. Called by Claude Code, Codex, and Gemini hook handlers. Neither
#          Codex nor Gemini always-loads the full methodology via its own root file anymore:
#          as of DS-183, .codex/AGENTS.md is a minimal trigger-load stub (not an always-loaded
#          embed), and as of DS-184, .gemini/GEMINI.md is likewise a small stub pointing at the
#          trigger-loaded dinostack skill (.gemini/skills/dinostack/SKILL.md). Both harnesses
#          now get the same nudge Claude Code does, each pointed at its own skill load path -
#          without it, a session with skill_auto_load=true gets neither the resident body nor
#          a nudge, and the skill loads only if the model voluntarily follows its stub's own
#          "load on trigger" prose.
# Public API: bash hooks/skill-auto-load-check.sh (no args; reads ~/.claude/agentic-engineering.json)
#             AE_ADAPTER=gemini selects the Gemini skill_path branch (Gemini has no reliable
#             script-dir signature to detect on its own, so its hook wiring must set this
#             explicitly). Codex is auto-detected via script_dir (*/.codex/hooks) -
#             AE_ADAPTER=codex is not set anywhere in this repo, so detection must not depend
#             on it being present.
# Upstream deps: ~/.claude/agentic-engineering.json (optional; missing = silent exit)
# Downstream consumers: .claude/install.sh (UserPromptSubmit hook), .codex/config/hooks.json
#                       (UserPromptSubmit hook), .gemini/install.sh (BeforeAgent hook)
# Failure modes: always exits 0; missing config or false flag = silent no-op; never blocks
#                hook chain
# Performance: <50ms (adds one python3 JSON parse) on every adapter path

ae_config="$HOME/.claude/agentic-engineering.json"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
adapter="${AE_ADAPTER:-}"
if [[ -z "$adapter" && "$script_dir" == *"/.codex/hooks" ]]; then
  adapter="codex"
fi

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
  case "$adapter" in
    gemini)
      skill_path="$HOME/.gemini/skills/dinostack/SKILL.md"
      load_instruction="invoke the dinostack skill (activate_skill), or read $skill_path directly if activate_skill is unavailable in this session"
      ;;
    codex)
      skill_path="$HOME/.agents/skills/dinostack/SKILL.md"
      load_instruction="read $skill_path"
      ;;
    *)
      skill_path="$HOME/.claude/skills/dinostack/SKILL.md"
      load_instruction="read $skill_path"
      ;;
  esac
  echo "SKILL CHECK [dinostack]: skill_auto_load=true."
  echo "Before responding to any software development request, $load_instruction."
  echo "Do not implement directly - follow the delegation and risk classification protocol in that file."
fi

exit 0
