#!/usr/bin/env bash
# Codex UserPromptSubmit hook — Risk classification reminder
#
# Mirrors the Claude Code risk-reminder hook. Plain text on stdout is added
# as extra developer context by Codex for UserPromptSubmit events.
#
# Input: JSON on stdin (session_id, cwd, prompt, etc.) - not used here.
# Output: Plain text on stdout injected as developer context before the turn.
#
# This hook requires codex_hooks = true in ~/.codex/config.toml [features].

cat <<'REMINDER'
BEFORE ANY ACTION: classify risk first.
- Elevated risk = spawn Worker + Skeptic in background. Do NOT act directly.
- Direct action ONLY for: reads, answering from memory, screenshots, synthesizing subagent results, diagnostic-only logging.
- When in doubt, classify Elevated.
REMINDER
