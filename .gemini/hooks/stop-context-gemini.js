#!/usr/bin/env node

/**
 * Gemini SessionEnd Hook - Session Context Writer
 *
 * Reads the SessionEnd hook JSON payload from stdin and writes a minimal context.md
 * to ~/.gemini/projects/[hash]/ so the next session has lightweight context
 * about what was happening.
 *
 * NOTE: This is a port of the Codex stop-context-codex.js. Adapted for Gemini's
 * SessionEnd hook event (matcher: "exit"). The hash derivation algorithm is
 * identical to the Codex version (cwd with every '/' replaced by '-').
 *
 * Gemini SessionEnd hook requirements:
 *  - Fires on clean session termination only (explicit /exit or graceful shutdown)
 *  - Abrupt terminations (crashes, SIGKILL) do NOT trigger this hook (best-effort)
 *  - Exit 0 means success; silent failure on errors
 *
 * Output path: ~/.gemini/projects/[hash]/context.md
 *   where hash = cwd with every '/' replaced by '-' (leading '-' is kept)
 *   This mirrors the ~/.claude/projects/[hash]/ and ~/.codex/projects/[hash]/
 *   convention used by the other adapters.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

function run() {
  // Always exit cleanly - this is a best-effort context save
  const successOutput = JSON.stringify({});

  // --- 1. Read stdin ---
  let raw = '';
  try {
    raw = fs.readFileSync(0, 'utf8');
  } catch (_) {
    process.stdout.write(successOutput);
    process.exit(0);
  }

  if (!raw.trim()) {
    process.stdout.write(successOutput);
    process.exit(0);
  }

  // --- 2. Parse JSON ---
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (_) {
    process.stdout.write(successOutput);
    process.exit(0);
  }

  // --- 3. Extract fields ---
  const cwd = (typeof payload.cwd === 'string' && payload.cwd.trim())
    ? payload.cwd.trim()
    : null;

  if (!cwd) {
    process.stdout.write(successOutput);
    process.exit(0);
  }

  const sessionId = typeof payload.session_id === 'string'
    ? payload.session_id
    : '(unknown)';

  const lastAssistantMessage = typeof payload.last_assistant_message === 'string'
    ? payload.last_assistant_message.trim()
    : null;

  const model = typeof payload.model === 'string'
    ? payload.model
    : '(unknown)';

  // --- 4. Compute output path ---
  // Hash algorithm: identical to stop-context-codex.js - replace all '/' with '-'
  const hash = cwd.replace(/\//g, '-');
  const projectDir = path.join(os.homedir(), '.gemini', 'projects', hash);
  const outputPath = path.join(projectDir, 'context.md');

  // --- 5. Format content ---
  const dateStr = new Date().toISOString().slice(0, 10);

  const lastMsgSection = lastAssistantMessage
    ? (lastAssistantMessage.length > 300
      ? lastAssistantMessage.slice(0, 297) + '...'
      : lastAssistantMessage)
    : '(not available)';

  const content = `# Session Context
*Auto-updated by Gemini SessionEnd hook - ${dateStr}. Overwritten each session.*
*Project: ${cwd}*
*Session ID: ${sessionId}*
*Model: ${model}*

## Last Assistant Message

${lastMsgSection}

## Notes

This context file is a Gemini port of the Claude Code stop-context hook.
For richer context (paths referenced, tools used, uncommitted changes), run /wrap
manually before ending a session.

Note: The SessionEnd hook fires on clean /exit only. Context may not be saved
on abrupt termination (crashes, SIGKILL).
`;

  // --- 6. Write file (silent failure) ---
  try {
    fs.mkdirSync(projectDir, { recursive: true });
    fs.writeFileSync(outputPath, content, 'utf8');
  } catch (_) {
    // Silent failure - best-effort context save
  }

  // Gemini SessionEnd hook: exit cleanly
  process.stdout.write(successOutput);
  process.exit(0);
}

run();
