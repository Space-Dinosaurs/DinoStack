#!/usr/bin/env bash
# VS Code Copilot PreToolUse hook - Risk classification reminder
#
# Copilot's PreToolUse hook injects context via JSON envelope on stdout.
# Plain text on stdout is NOT injected - the JSON envelope is required.
#
# Input: JSON on stdin (tool name, input parameters, session info) - not used here.
# Output: JSON on stdout with hookSpecificOutput.additionalContext containing
#         the reminder text, which Copilot prepends to the model context for the turn.
#
# Reference: VS Code Copilot Extensibility - hooks reference (PreToolUse output format).

cat <<'REMINDER'
{
  "hookSpecificOutput": {
    "additionalContext": "BEFORE ANY ACTION: classify risk first.\n- Elevated risk = spawn Worker + Skeptic in background. Do NOT act directly.\n- Direct action ONLY for: reads, answering from memory, screenshots, synthesizing subagent results, diagnostic-only logging.\n- When in doubt, classify Elevated."
  }
}
REMINDER
