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
- If agentic-engineering is active in this project, the main session is the conductor.
- The conductor delegates shippable edits to a named engineer Worker; Elevated work also requires a fresh Skeptic review.
- Low-risk reads, diagnostics, synthesis, and other allowed Low tasks remain direct-action OK.
- When in doubt, classify Elevated.
REMINDER
