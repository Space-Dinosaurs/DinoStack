#!/usr/bin/env node

/**
 * Cursor Stop Hook - Session Context Writer
 *
 * Reads the Stop hook JSON payload from stdin and writes a minimal context.md
 * to ~/.cursor/projects/[hash]/ so the next session has lightweight context
 * about what was happening.
 *
 * NOTE: This is a Cursor port of the Claude Code stop-context hook.
 * The full Claude Code hook uses Claude Code's transcript format which differs
 * from Cursor's. This stub captures: cwd, last assistant message, session_id,
 * and timestamp. For richer context, run /wrap manually before ending a session.
 *
 * Cursor Stop hook requirements:
 *  - Must output JSON on stdout when exiting 0
 *  - Exit 0 with {} means success, Cursor continues normally
 *  - Silent failure: any error exits 0 with {}
 *
 * Output path: ~/.cursor/projects/[hash]/context.md
 *   where hash = cwd with every '/' replaced by '-' (leading '-' is kept)
 *   This mirrors the ~/.claude/projects/[hash]/ convention used by Claude Code.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

function run() {
  // Always exit with valid JSON for Cursor Stop hook compliance
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
  const hash = cwd.replace(/\//g, '-');
  const projectDir = path.join(os.homedir(), '.cursor', 'projects', hash);
  const outputPath = path.join(projectDir, 'context.md');

  // --- 5. Format content ---
  const dateStr = new Date().toISOString().slice(0, 10);

  const lastMsgSection = lastAssistantMessage
    ? (lastAssistantMessage.length > 300
      ? lastAssistantMessage.slice(0, 297) + '...'
      : lastAssistantMessage)
    : '(not available)';

  const content = `# Session Context
*Auto-updated by Cursor Stop hook — ${dateStr}. Overwritten each session.*
*Project: ${cwd}*
*Session ID: ${sessionId}*
*Model: ${model}*

## Last Assistant Message

${lastMsgSection}

## Notes

This context file is a Cursor port of the Claude Code stop-context hook.
For richer context (paths referenced, tools used, uncommitted changes), run /wrap
manually before ending a session.
`;

  // --- 6. Write file (silent failure) ---
  try {
    fs.mkdirSync(projectDir, { recursive: true });
    fs.writeFileSync(outputPath, content, 'utf8');
  } catch (_) {
    // Silent failure
  }

  // Cursor Stop hook: must return JSON on stdout
  process.stdout.write(successOutput);
  process.exit(0);
}

run();
