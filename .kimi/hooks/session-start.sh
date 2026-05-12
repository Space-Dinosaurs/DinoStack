#!/usr/bin/env bash
# Kimi SessionStart hook - Agentic Engineering activation check
#
# Prints a visible reminder when entering a project where agentic-engineering
# should be active. Kimi CLI SessionStart hook stdout is logged; we print to
# stderr for visibility in the terminal.
#
# Input: JSON on stdin with {session_id, cwd, source}
# Output: none (exit 0 = allow session to start)

set -euo pipefail

read -r input

# Extract cwd from JSON (simple parse, robust enough for our payload)
cwd=$(echo "$input" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || echo "")
source=$(echo "$input" | python3 -c "import sys,json; print(json.load(sys.stdin).get('source',''))" 2>/dev/null || echo "")

if [[ -z "$cwd" ]]; then
  exit 0
fi

# Check if project has agentic-engineering marker or .kimi/AGENTS.md
has_marker=false
if [[ -f "$cwd/AGENTS.md" ]]; then
  if grep -qi "agentic-engineering: opt-in" "$cwd/AGENTS.md" 2>/dev/null; then
    has_marker=true
  fi
fi
if [[ -f "$cwd/.kimi/AGENTS.md" ]]; then
  has_marker=true
fi

# Also check global config mode
ae_config="$HOME/.claude/agentic-engineering.json"
mode="opt-out"
if [[ -f "$ae_config" ]]; then
  mode=$(python3 -c "
import json, sys
try:
    with open('$ae_config') as f:
        print(json.load(f).get('mode', 'opt-out'))
except Exception:
    print('opt-out')
" 2>/dev/null || echo "opt-out")
fi

# Only show reminder if the project looks like it should use agentic-engineering
# (has marker OR has .kimi/AGENTS.md OR mode=opt-out with no explicit opt-out marker)
if [[ "$has_marker" == "true" ]]; then
  >&2 echo ""
  >&2 echo "┌─────────────────────────────────────────────────────────────────────┐"
  >&2 echo "│  agentic-engineering: ACTIVE in this project                        │"
  >&2 echo "│  Load the skill: /skill:agentic-engineering                         │"
  >&2 echo "│  Conductor rule: delegate ALL work to subagents. No direct tools.   │"
  >&2 echo "└─────────────────────────────────────────────────────────────────────┘"
  >&2 echo ""
fi

exit 0
