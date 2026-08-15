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
#
# The .agentic/ read is anchored at the nearest .git ancestor of the payload
# cwd via hooks/lib/repo-root.sh's resolve_agentic_root, not the payload cwd
# verbatim, and NEVER falls back to `pwd` - a stray cd or a drifted
# harness-supplied cwd could otherwise point this hook at a phantom
# .agentic/ tree wherever the process happens to be. On resolution failure
# (payload has no cwd, or no .git ancestor is found), the hook SKIPS the
# lookup entirely and emits {}.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../hooks/lib/repo-root.sh
source "$SCRIPT_DIR/../../hooks/lib/repo-root.sh"

# Resolve workspace root from stdin JSON (cwd field). Never falls back to
# `pwd` - see the header comment above.
PAYLOAD_CWD=""
if command -v python3 >/dev/null 2>&1; then
  PAYLOAD_CWD="$(python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('cwd', ''))
except Exception:
    print('')
" 2>/dev/null || true)"
fi

CWD=""
if [[ -n "$PAYLOAD_CWD" ]]; then
  CWD="$(resolve_agentic_root "$PAYLOAD_CWD")"
fi

if [[ -z "$CWD" ]]; then
  printf '{}\n'
  exit 0
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
