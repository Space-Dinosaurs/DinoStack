#!/usr/bin/env node

/**
 * Purpose: Write lightweight Codex Stop-event session continuity to the
 *          harness-owned hashed global context path.
 *
 * Public API: stdin JSON Stop payload; stdout `{}` with process exit 0.
 *
 * Upstream deps: Node.js standard library and hooks/lib/stdin-guard.js.
 *
 * Downstream consumers: .codex/config/hooks.json and later Codex sessions that
 *                       read ~/.codex/projects/[hash]/context.md.
 *
 * Failure modes: malformed, missing, oversized, or stalled stdin and filesystem
 *                errors fail silently with `{}`; project-local context is not
 *                written by this hook. An interruption can leave context.md truncated or torn.
 *
 * Performance: one bounded stdin read and one bounded direct non-atomic local file write.
 *
 * Codex Stop Hook - Session Context Writer
 *
 * Reads the Stop hook JSON payload from stdin and writes a minimal context.md
 * to ~/.codex/projects/[hash]/ so the next session has lightweight context
 * about what was happening.
 *
 * NOTE: This is a thinner version of the Claude Code stop-context.js.
 * The full Claude Code hook uses Claude Code's transcript format which differs
 * from Codex's. This stub captures: cwd, last assistant message, session_id,
 * and timestamp. For richer context, run $wrap before ending a session.
 *
 * Codex Stop hook requirements:
 *  - Must output JSON on stdout when exiting 0
 *  - Exit 0 with {} means success, Codex continues normally
 *  - Silent failure: any error exits 0 with {}
 *
 * Output path: ~/.codex/projects/[hash]/context.md
 *   where hash = cwd with every '/' replaced by '-' (leading '-' is kept)
 *   This mirrors the ~/.claude/projects/[hash]/ convention used by Claude Code.
 *
 * Stdin is read via hooks/lib/stdin-guard.js's readStdinGuarded() (a bounded
 * reader with a first-byte timeout and a re-armed inactivity timeout) instead
 * of a blocking fs.readFileSync(0), so this hook cannot hang Codex's shutdown
 * path when the spawning process never closes stdin.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { readStdinGuarded } = require('../../hooks/lib/stdin-guard.js');

// Always exit with valid JSON for Codex Stop hook compliance. Hoisted to
// module scope so both run()'s internal paths and the top-level run().catch()
// (which must handle a rejection before run() reaches this declaration) can
// reference the same value.
const successOutput = JSON.stringify({});

async function run() {
  // --- 1. Read stdin ---
  const raw = await readStdinGuarded();

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
  const projectDir = path.join(os.homedir(), '.codex', 'projects', hash);
  const outputPath = path.join(projectDir, 'context.md');

  // --- 5. Format content ---
  const dateStr = new Date().toISOString().slice(0, 10);

  const lastMsgSection = lastAssistantMessage
    ? (lastAssistantMessage.length > 300
      ? lastAssistantMessage.slice(0, 297) + '...'
      : lastAssistantMessage)
    : '(not available)';

  const content = `# Session Context
*Auto-updated by Codex Stop hook — ${dateStr}. Overwritten each session.*
*Project: ${cwd}*
*Session ID: ${sessionId}*
*Model: ${model}*

## Last Assistant Message

${lastMsgSection}

## Notes

This context file is a thin Codex port of the Claude Code stop-context hook.
For richer context (paths referenced, tools used, uncommitted changes), run $wrap
before ending a session.
`;

  // --- 6. Write file (silent failure) ---
  try {
    fs.mkdirSync(projectDir, { recursive: true });
    fs.writeFileSync(outputPath, content, 'utf8');
  } catch (_) {
    // Silent failure
  }

  // conductor_overreach detection port (DS unit DE): the Claude Code
  // hooks/conductor-overreach-nudge.js detector needs a structured
  // tool_use transcript (payload.transcript, an array of message objects
  // with tool_use/tool_result content blocks) to count conductor
  // investigation calls vs spawns. Codex's Stop payload carries no such
  // field - only cwd, session_id, last_assistant_message, and model (see
  // step 3 above) - so there is no data to run computeOverreach() against.
  // Not wired here; if a future Codex payload version exposes a structured
  // tool-call transcript, require('../../hooks/lib/overreach-detector.js')
  // and call computeOverreach(payload.transcript, threshold) the same way
  // conductor-overreach-nudge.js does.

  // Codex Stop hook: must return JSON on stdout
  process.stdout.write(successOutput);
  process.exit(0);
}

run().catch(() => { process.stdout.write(successOutput); process.exit(0); });
