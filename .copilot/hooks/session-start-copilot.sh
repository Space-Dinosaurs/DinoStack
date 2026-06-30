#!/usr/bin/env bash
# VS Code Copilot SessionStart hook - Session context loader
#
# If .agentic/context.md exists in the workspace root, injects its contents as
# additionalContext so Copilot starts each session with prior session context.
#
# Input: JSON on stdin (cwd, session_id, etc.)
# Output: JSON on stdout with hookSpecificOutput.additionalContext (or empty object).
#
# Reference: VS Code Copilot Extensibility - hooks reference (SessionStart output format).

set -euo pipefail

# Resolve workspace root from stdin JSON (cwd field), fall back to pwd
CWD=""
if command -v python3 >/dev/null 2>&1; then
  CWD="$(python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('cwd', ''))
except Exception:
    print('')
" 2>/dev/null || true)"
fi

if [[ -z "$CWD" ]]; then
  CWD="$(pwd)"
fi

CONTEXT_FILE="$CWD/.agentic/context.md"

if [[ -f "$CONTEXT_FILE" ]]; then
  context_content="$(cat "$CONTEXT_FILE")"
  # Escape for JSON string: backslashes first, then double-quotes, then newlines
  context_escaped="${context_content//\\/\\\\}"
  context_escaped="${context_escaped//\"/\\\"}"
  context_escaped="${context_escaped//$'\n'/\\n}"
  printf '{"hookSpecificOutput":{"additionalContext":"%s"}}\n' "$context_escaped"
else
  printf '{}\n'
fi
