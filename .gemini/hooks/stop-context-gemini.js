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
 *
 * Stdin is read via hooks/lib/stdin-guard.js's readStdinGuarded() (a bounded
 * reader with a first-byte timeout and a re-armed inactivity timeout) instead
 * of a blocking fs.readFileSync(0), so this hook cannot hang Gemini's
 * shutdown path when the spawning process never closes stdin.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { readStdinGuarded } = require('../../hooks/lib/stdin-guard.js');

// Always exit cleanly - this is a best-effort context save. Hoisted to module
// scope so both run()'s internal paths and the top-level run().catch() (which
// must handle a rejection before run() reaches this declaration) can
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
For richer context (paths referenced, tools used, uncommitted changes), run /ds-wrap
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

  // conductor_overreach detection port (DS unit DE): NOT INDEPENDENTLY
  // VERIFIED this session - no Gemini CLI is installed on the machine this
  // was written on, so (unlike the Codex port, where `strings` against the
  // installed binary confirmed a real `transcript_path` field pointing at
  // a structured rollout file) there is no direct evidence either way
  // about whether Gemini's SessionEnd payload carries a transcript_path or
  // equivalent structured field. An earlier version of this comment
  // asserted "the payload carries no such field" as settled fact without
  // ever having checked - that claim is withdrawn as unverified, not
  // reasserted. What is true today, mechanically: this port currently only
  // extracts cwd/session_id/last_assistant_message/model (see step 3
  // above) and does not attempt to read a transcript-path-shaped field.
  // Before porting hooks/lib/overreach-detector.js's computeOverreach
  // here, a future change should first capture a real Gemini SessionEnd
  // payload (e.g. a temporary hook that dumps stdin to a file) to
  // determine whether a structured transcript is available at all, and if
  // so in what schema - Gemini need not match either Claude's or Codex's
  // shape.

  // Gemini SessionEnd hook: exit cleanly
  process.stdout.write(successOutput);
  process.exit(0);
}

run().catch(() => { process.stdout.write(successOutput); process.exit(0); });
