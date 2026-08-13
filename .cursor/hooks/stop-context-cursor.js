#!/usr/bin/env node

/**
 * Purpose: Cursor `stop` hook - session context writer. Reads the Cursor
 *          stop-hook JSON payload from stdin (bounded, never blocks Cursor's
 *          shutdown path) and writes a minimal <cwd>/.agentic/context.md so
 *          the next session (any harness) has lightweight context about what
 *          was happening. Modeled on .codex/hooks/stop-context-codex.js's
 *          read-parse-guard-write skeleton, adapted to Cursor's own payload
 *          shape (see docs/planning/cursor-stop-hook-plan.md Addendum for the
 *          finalized field mapping, sourced from https://cursor.com/docs).
 *
 * Public API: when run directly as the hook script (`require.main ===
 *             module`), no export - `run().catch(exitOk)` fires at load
 *             time exactly as before. When required by another module
 *             (`require.main !== module`, test-only), `run()` is NOT
 *             invoked and `{ readTranscriptExcerpt }` is exported instead,
 *             so hooks/tests/test-stop-context-cursor.js can drive the
 *             bounded-read/TOCTOU logic directly without spawning the full
 *             hook. This guard never changes behavior for the real
 *             Cursor-invoked path.
 *
 * Upstream deps: Node built-ins only (fs, path) plus
 *                ../../hooks/lib/stdin-guard.js (readStdinGuarded - the
 *                shared bounded-stdin reader; see that module's manifest for
 *                the first-byte/inactivity timer contract). No npm
 *                dependencies. Reads process.env.CURSOR_PROJECT_DIR,
 *                process.env.CLAUDE_PROJECT_DIR, and
 *                process.env.CURSOR_TRANSCRIPT_PATH as fallbacks when the
 *                payload omits the corresponding field.
 *
 * Downstream consumers: Cursor's `stop` hook, wired via
 *                        ~/.cursor/hooks.json at an absolute path substituted
 *                        by .cursor/install.sh's converge step (sibling unit
 *                        - not part of this file). Cursor has no snapshot
 *                        mechanism, so this file runs from the live checkout
 *                        at the path baked in at install time.
 *
 * Failure modes: Every path is silent-success exit 0 with `{}` on stdout -
 *                this hook NEVER emits `followup_message` (a non-empty value
 *                makes Cursor auto-submit a user message and engage its
 *                loop_limit machinery) and NEVER exits 2 (Cursor treats exit
 *                2 as "block the action"). Malformed/absent stdin, malformed
 *                JSON, and a non-object payload all resolve to the same
 *                silent exit-0 path. When the payload carries no
 *                workspace-root-equivalent field and neither
 *                CURSOR_PROJECT_DIR nor CLAUDE_PROJECT_DIR is set, this is a
 *                GUARDED SAFE NO-OP (Scope B contingency): exit 0, no write,
 *                because there is no directory to write into. The resolved
 *                cwd is CANONICALIZED via path.resolve(cwd) before any path
 *                join (not rejected) - this normalizes a trailing slash,
 *                `/./` segments, `//` double-slashes, and any `..`
 *                traversal component into a clean absolute path, so a
 *                non-canonical-but-legitimate workspace root (Cursor's exact
 *                workspace_roots formatting is an unverified empirical gap)
 *                still gets its context.md written instead of silently
 *                no-op'ing. This is strictly safer than a reject-on-mismatch
 *                comparison would be: the only path segments ever joined to
 *                cwd downstream are the fixed constants '.agentic' and
 *                'context.md' (never attacker- or payload-controlled), so
 *                there is no traversal surface a reject branch would have
 *                protected that normalization does not already close. An
 *                oversized or unreadable transcript file never blocks the
 *                write path - the path is opened exactly ONCE via
 *                fs.openSync, and BOTH the size check (fs.fstatSync) and the
 *                bounded read (fs.readSync) are performed against that SAME
 *                file descriptor. This closes the TOCTOU window a
 *                path-based statSync+readFileSync pair would otherwise leave
 *                open (an attacker swapping a symlink between the two calls
 *                could defeat the size gate and force an unbounded read of
 *                whatever the path resolves to next - the fd stays bound to
 *                the original inode regardless of any later swap). The fd is
 *                opened O_NONBLOCK so a FIFO with no writer cannot hang the
 *                open() call itself; combined with an explicit
 *                stat.isFile() check, directories, FIFOs, and devices are
 *                rejected before any read is attempted (unlike the old
 *                behavior, which relied on readFileSync's EISDIR exception
 *                for directories and would have hung indefinitely on a
 *                writer-less FIFO). Anything over 256 KB is skipped entirely
 *                in favor of a placeholder string, and the read buffer is
 *                additionally capped at min(stat.size, 256 KB) so no more
 *                than the cap is ever allocated or read regardless of race.
 *                DOCUMENTED NON-PARTICIPATION: like the existing Copilot
 *                port, this hook does an UNCONDITIONAL context.md write and
 *                does NOT participate in the Claude-only wrap-lock/deferral
 *                machinery (writeContextMdOrSpill / wrapLockHeld /
 *                spillover). A concurrent Claude `/ds-wrap` and a Cursor session
 *                on the same project can have this write land over that
 *                enrichment; this is a decision, not an oversight - it
 *                mirrors the pre-existing Copilot convention, context.md is
 *                by design overwritten each session, and the severity is low.
 *
 * Performance: Bounded by hooks/lib/stdin-guard.js's own timers (~3-20ms on
 *              the common EOF/early-parse paths, worst case
 *              firstByteTimeoutMs/inactivityTimeoutMs/absoluteTimeoutMs, plus
 *              a maxStdinBytes cap on total stdin size). The transcript read,
 *              when attempted, is a single openSync/fstatSync pair plus
 *              (only when under the 256 KB cap and isFile() is true) a
 *              single bounded readSync - never proportional to a transcript
 *              larger than the cap, and never blocking on a non-regular
 *              file.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { readStdinGuarded } = require('../../hooks/lib/stdin-guard.js');

const TRANSCRIPT_MAX_BYTES = 256 * 1024;
const TRANSCRIPT_TAIL_CHARS = 2000;

// Cursor's stop-hook contract: ALWAYS return {} on stdout. A non-empty
// followup_message causes Cursor to auto-submit a user message (loop_limit
// machinery) - this hook must never set that key. Exit code 2 means "block
// the action" in Cursor - this hook never exits 2; every path below is a
// silent-success exit 0.
const successOutput = JSON.stringify({});

function exitOk() {
  try {
    process.stdout.write(successOutput);
  } catch (_) {
    // stdout may already be closed at shutdown - nothing more to do.
  }
  process.exit(0);
}

/**
 * Read at most a bounded tail excerpt of the transcript file as a
 * last-activity hint. The transcript file format is undocumented, so this
 * never attempts to parse it - just a raw tail excerpt for a human reading
 * context.md.
 *
 * Security: opens transcriptPath exactly ONCE via fs.openSync and performs
 * BOTH the size check (fs.fstatSync) and the bounded read (fs.readSync)
 * against that SAME file descriptor, so a symlink (or the path itself)
 * being swapped after the check can never affect what actually gets read -
 * the fd stays bound to the original inode. The fd is opened with
 * O_NONBLOCK so a FIFO with no writer cannot hang the open() call itself;
 * an explicit stat.isFile() check then rejects directories, FIFOs, and
 * devices before any read is attempted. The read buffer is capped at
 * min(stat.size, TRANSCRIPT_MAX_BYTES) so no more than the cap is ever
 * allocated or read. Never throws, never blocks.
 * @param {string|null} transcriptPath
 * @returns {string}
 */
function readTranscriptExcerpt(transcriptPath) {
  if (!transcriptPath) return '(not available)';
  let fd = null;
  try {
    // O_NONBLOCK: avoid hanging open() on a FIFO/named-pipe with no writer.
    // Has no effect on a regular file (the legitimate case).
    fd = fs.openSync(transcriptPath, fs.constants.O_RDONLY | fs.constants.O_NONBLOCK);

    // fstatSync on the SAME fd - this is the TOCTOU fix: the size check and
    // the read below both reference the same open inode, so a path-level
    // swap between them (e.g. a symlink retarget) can no longer defeat the
    // size gate or redirect the read.
    const stat = fs.fstatSync(fd);
    if (!stat.isFile()) return '(not available)';
    if (stat.size > TRANSCRIPT_MAX_BYTES) return '(transcript too large)';

    let raw = '';
    const size = Math.min(stat.size, TRANSCRIPT_MAX_BYTES);
    if (size > 0) {
      const buffer = Buffer.alloc(size);
      const bytesRead = fs.readSync(fd, buffer, 0, size, 0);
      raw = buffer.toString('utf8', 0, bytesRead).trim();
    }
    if (!raw) return '(not available)';
    return raw.length > TRANSCRIPT_TAIL_CHARS
      ? '...' + raw.slice(-TRANSCRIPT_TAIL_CHARS)
      : raw;
  } catch (_) {
    return '(not available)';
  } finally {
    if (fd !== null) {
      try { fs.closeSync(fd); } catch (_) { /* already closed or fd invalid */ }
    }
  }
}

async function run() {
  // --- 1. Read stdin (bounded - never blocks Cursor's shutdown path) ---
  const raw = await readStdinGuarded();
  if (!raw || !raw.trim()) return exitOk();

  // --- 2. Parse JSON ---
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (_) {
    return exitOk();
  }
  if (!payload || typeof payload !== 'object') return exitOk();

  // --- 3. Resolve cwd from workspace_roots[0], with env fallbacks ---
  let cwd = null;
  if (
    Array.isArray(payload.workspace_roots) &&
    typeof payload.workspace_roots[0] === 'string' &&
    payload.workspace_roots[0].trim()
  ) {
    cwd = payload.workspace_roots[0].trim();
  } else if (typeof process.env.CURSOR_PROJECT_DIR === 'string' && process.env.CURSOR_PROJECT_DIR.trim()) {
    cwd = process.env.CURSOR_PROJECT_DIR.trim();
  } else if (typeof process.env.CLAUDE_PROJECT_DIR === 'string' && process.env.CLAUDE_PROJECT_DIR.trim()) {
    cwd = process.env.CLAUDE_PROJECT_DIR.trim();
  }

  // Scope B contingency: no workspace/cwd-equivalent field anywhere -
  // guarded safe no-op, nothing to write to and nothing safe to guess.
  if (!cwd) return exitOk();

  // Canonicalize (never reject): path.resolve normalizes a trailing slash,
  // '/./' segments, '//' double-slashes, and any '..' traversal component
  // into a clean absolute path. A reject-on-mismatch comparison here would
  // false-positive on any of those purely cosmetic variants (Cursor's exact
  // workspace_roots formatting is unverified) and silently skip the write
  // for a legitimate cwd. Normalizing is strictly safer AND lossless: the
  // only segments ever joined to cwd below are the fixed constants
  // '.agentic' and 'context.md', so there is nothing attacker-controlled
  // for a reject branch to have protected that this does not already close.
  cwd = path.resolve(cwd);

  // --- 4. Extract remaining fields (all optional, all defensive) ---
  const sessionId = (typeof payload.conversation_id === 'string' && payload.conversation_id.trim())
    ? payload.conversation_id.trim()
    : ((typeof payload.session_id === 'string' && payload.session_id.trim())
      ? payload.session_id.trim()
      : '(unknown)');

  const model = (typeof payload.model === 'string' && payload.model.trim())
    ? payload.model.trim()
    : ((typeof payload.model_id === 'string' && payload.model_id.trim())
      ? payload.model_id.trim()
      : '(unknown)');

  const stopStatus = (typeof payload.status === 'string' && payload.status.trim())
    ? payload.status.trim()
    : null;

  const transcriptPath = (typeof payload.transcript_path === 'string' && payload.transcript_path.trim())
    ? payload.transcript_path.trim()
    : ((typeof process.env.CURSOR_TRANSCRIPT_PATH === 'string' && process.env.CURSOR_TRANSCRIPT_PATH.trim())
      ? process.env.CURSOR_TRANSCRIPT_PATH.trim()
      : null);

  const lastActivity = readTranscriptExcerpt(transcriptPath);

  // --- 5. Compute output path ---
  const agenticDir = path.join(cwd, '.agentic');
  const outputPath = path.join(agenticDir, 'context.md');

  // --- 6. Format content (same shape as the Codex/Copilot ports) ---
  const dateStr = new Date().toISOString().slice(0, 10);
  const statusLine = stopStatus ? `*Status: ${stopStatus}*\n` : '';

  const content = `# Session Context
*Auto-updated by Cursor Stop hook - ${dateStr}. Overwritten each session.*
*Project: ${cwd}*
*Session ID: ${sessionId}*
*Model: ${model}*
${statusLine}
## Last Activity

${lastActivity}

## Notes

This context file is written by the Cursor stop hook.
For richer context (paths referenced, tools used, uncommitted changes), run /ds-wrap
manually before ending a session.
`;

  // --- 7. Write file (silent failure) ---
  try {
    fs.mkdirSync(agenticDir, { recursive: true });
    fs.writeFileSync(outputPath, content, 'utf8');
  } catch (_) {
    // Silent failure - matches every sibling port's convention.
  }

  // conductor_overreach detection port (DS unit DE): same gap as the Codex
  // and Gemini ports - the Claude Code detector (hooks/lib/
  // overreach-detector.js's computeOverreach) needs a structured
  // payload.transcript array of tool_use/tool_result blocks. Cursor's Stop
  // payload instead carries an undocumented-format transcript_path (see
  // readTranscriptExcerpt above), read only as a bounded raw-text tail
  // excerpt, not structured tool-call data. Not wired here for the same
  // reason. If a future Cursor payload exposes a structured tool-call
  // transcript, require('../../hooks/lib/overreach-detector.js') and call
  // computeOverreach(payload.transcript, threshold).

  exitOk();
}

// Test-only export: when required (not run as the top-level script), expose
// readTranscriptExcerpt so hooks/tests/test-stop-context-cursor.js can drive
// it directly (e.g. to monkeypatch fs for a deterministic TOCTOU
// regression). Guarded so this never changes runtime behavior when executed
// as the hook script itself.
if (require.main !== module) {
  module.exports = { readTranscriptExcerpt };
} else {
  run().catch(exitOk);
}
