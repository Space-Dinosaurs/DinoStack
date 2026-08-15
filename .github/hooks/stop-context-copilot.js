#!/usr/bin/env node

/**
 * VS Code Copilot Stop Hook - Session Context Writer
 *
 * Reads the Stop hook JSON payload from stdin and writes a minimal context.md
 * to .agentic/context.md in the workspace root so the next session has
 * lightweight context about what was happening.
 *
 * NOTE: This is modeled on .codex/hooks/stop-context-codex.js.
 * The Copilot Stop hook uses the same contract: read JSON from stdin,
 * return JSON on stdout (exit 0 with {} means success).
 *
 * Copilot Stop hook requirements:
 *  - Must output JSON on stdout when exiting 0
 *  - Exit 0 with {} means success, Copilot continues normally
 *  - Silent failure: any error exits 0 with {}
 *
 * Output path: <cwd>/.agentic/context.md
 *   Resolves workspace root from the payload's cwd field.
 *   Mirrors the .agentic/context.md convention used by the Claude Code adapter.
 *
 * Stdin is read via hooks/lib/stdin-guard.js's readStdinGuarded() (a bounded
 * reader with a first-byte timeout and a re-armed inactivity timeout) instead
 * of a blocking fs.readFileSync('/dev/stdin'), so this hook cannot hang
 * Copilot's shutdown path when the spawning process never closes stdin.
 *
 * The .agentic/ write is anchored at the nearest .git ancestor of the
 * payload cwd via hooks/lib/repo-root.js's resolveAgenticCwdWithDiagnostics,
 * not the payload cwd verbatim - a stray cd or a drifted harness-supplied
 * cwd could otherwise write a phantom .agentic/ tree wherever the process
 * happens to be. On resolution failure (no .git ancestor found), the write
 * is SKIPPED entirely rather than falling back to the unresolved cwd.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { readStdinGuarded } = require('../../hooks/lib/stdin-guard.js');
const { resolveAgenticCwdWithDiagnostics } = require('../../hooks/lib/repo-root.js');

// Always exit with valid JSON for Copilot Stop hook compliance. Hoisted to
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

  // --- 3b. Resolve the repo root anchoring the .agentic/ write, instead of
  // trusting the payload-supplied cwd verbatim. On resolution failure (no
  // .git ancestor found), SKIP the write entirely - never fall back to the
  // unresolved cwd, which would silently reproduce the phantom-tree bug
  // this resolver exists to prevent.
  const { root: agenticRoot, foundGitAncestor } = resolveAgenticCwdWithDiagnostics(cwd);
  if (!foundGitAncestor) {
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
  const agenticDir = path.join(agenticRoot, '.agentic');
  const outputPath = path.join(agenticDir, 'context.md');

  // --- 5. Format content ---
  const dateStr = new Date().toISOString().slice(0, 10);

  const lastMsgSection = lastAssistantMessage
    ? (lastAssistantMessage.length > 300
      ? lastAssistantMessage.slice(0, 297) + '...'
      : lastAssistantMessage)
    : '(not available)';

  const content = `# Session Context
*Auto-updated by Copilot Stop hook - ${dateStr}. Overwritten each session.*
*Project: ${cwd}*
*Session ID: ${sessionId}*
*Model: ${model}*

## Last Assistant Message

${lastMsgSection}

## Notes

This context file is written by the VS Code Copilot stop hook.
For richer context (paths referenced, tools used, uncommitted changes), run /ds-wrap
manually before ending a session.
`;

  // --- 6. Write file (silent failure) ---
  try {
    fs.mkdirSync(agenticDir, { recursive: true });
    fs.writeFileSync(outputPath, content, 'utf8');
  } catch (_) {
    // Silent failure
  }

  // Copilot Stop hook: must return JSON on stdout
  process.stdout.write(successOutput);
  process.exit(0);
}

run().catch(() => { process.stdout.write(successOutput); process.exit(0); });
