#!/usr/bin/env node

/**
 * Purpose: Shared bounded-stdin reader for hooks that must not block a
 *          harness's shutdown path when the spawning process never closes
 *          stdin. Reads process.stdin with two timers (first-byte,
 *          inactivity) plus early-completion-by-parse, so a hook exits fast
 *          when no payload is coming while a slow-but-legitimate payload is
 *          still read in full. Extracted from the blocking
 *          `fs.readFileSync(0, 'utf8')` pattern shared by seven hooks
 *          (round-1 Skeptic Finding 1 / plan-Skeptic M1 on
 *          docs/planning/cursor-stop-hook-plan.md), which hangs indefinitely
 *          when the spawning harness (e.g. Cursor's composer session-end
 *          path) never closes stdin.
 *
 * Public API (CommonJS, all exported on module.exports):
 *   readStdinGuarded(options) -> Promise<string>
 *     options.firstByteTimeoutMs (default DEFAULT_FIRST_BYTE_TIMEOUT_MS)
 *     options.inactivityTimeoutMs (default DEFAULT_INACTIVITY_TIMEOUT_MS)
 *     options.tryParse: a function(str) that throws on incomplete/invalid
 *       input (default JSON.parse); pass null to disable early-completion.
 *     Never rejects - always resolves with the string accumulated so far.
 *   DEFAULT_FIRST_BYTE_TIMEOUT_MS - 750
 *   DEFAULT_INACTIVITY_TIMEOUT_MS - 5000
 *
 * Upstream deps: Node built-ins only (process.stdin). No npm dependencies.
 *                process.stdin.setEncoding('utf8') delegates multi-byte
 *                character boundary handling to Node's internal
 *                StringDecoder, so a chunk split mid-codepoint is assembled
 *                correctly (sidesteps the truncation bug class documented
 *                against hooks/wrap-daemon.js's manual byte-cap logic).
 *
 * Downstream consumers: the seven hardened stdin-blocking hooks
 *                        (hooks/stop-context.js,
 *                        hooks/post-tool-use-capture-nudge.js,
 *                        hooks/session-end-wrap.js,
 *                        hooks/pre-tool-use-spawn-emit.js,
 *                        .codex/hooks/stop-context-codex.js,
 *                        .gemini/hooks/stop-context-gemini.js,
 *                        .copilot/hooks/stop-context-copilot.js) plus the new
 *                        .cursor/hooks/stop-context-cursor.js port - all being
 *                        wired to this module in sibling units of the same
 *                        plan (docs/planning/cursor-stop-hook-plan.md Unit A
 *                        item 6-8, Unit B item 1). This unit ships the module
 *                        and its own tests only; no consumer is modified yet.
 *
 * Failure modes: Never rejects. Every resolution path returns whatever
 *                string has been accumulated so far via one of three routes:
 *                (1) parse-success - options.tryParse (default JSON.parse)
 *                does not throw on the accumulated string after some data
 *                chunk, resolves immediately without waiting for EOF;
 *                (2) EOF - the stream's 'end' event fires (stdin closed
 *                normally), resolves immediately, preserving the existing
 *                fast path (~3-20ms) when the spawning harness closes stdin
 *                promptly; (3) timeout - either the first-byte timer fires
 *                with zero bytes received (resolves '') or the inactivity
 *                timer fires after data has started arriving but stalls
 *                (resolves with whatever arrived). A stream 'error' event is
 *                treated as an EOF-equivalent: resolves with whatever
 *                accumulated, never propagates the error. All timers are
 *                cleared and all listeners removed before resolving; cleanup
 *                also calls process.stdin.pause() followed by a guarded
 *                stdin.unref() (only invoked when the stream actually
 *                exposes unref, since not every stream-like object does) so
 *                an idle process is free to exit on every resolution path -
 *                including the primary target scenario where the writer
 *                never closes the pipe. pause() alone does NOT release the
 *                underlying pipe/socket handle from the event loop in that
 *                scenario (verified empirically on Node v24: a process that
 *                has received data, paused stdin, and removed all listeners
 *                still hangs indefinitely if the writer holds the pipe
 *                open); unref() is what actually lets the process exit.
 *                DOCUMENTED TRADE-OFF: if a real payload's first
 *                byte takes longer than firstByteTimeoutMs to arrive (default
 *                750ms; e.g. the spawning machine is under extreme load at
 *                session exit), this function resolves '' and the caller
 *                treats it as no payload, missing that session's write for a
 *                rare, silent, single-session best-effort case. This is a
 *                deliberate trade against the sub-second exit requirement
 *                (a hook that never closes stdin must still exit fast); the
 *                inactivity timer, not the first-byte timer, governs
 *                everything once the first byte has arrived, so this window
 *                only gates payload START latency, not total payload size or
 *                delivery duration.
 *
 * Performance: Typical resolution is dominated by the spawning harness's own
 *              behavior, not this module: ~3-20ms when stdin closes promptly
 *              (EOF path), near-instant once a complete payload has arrived
 *              (parse-success path), and bounded by firstByteTimeoutMs /
 *              inactivityTimeoutMs in the worst case (silent or stalled
 *              stdin). No polling; entirely event-driven off the 'data' /
 *              'end' / 'error' events plus two timers.
 */

'use strict';

const DEFAULT_FIRST_BYTE_TIMEOUT_MS = 750;
const DEFAULT_INACTIVITY_TIMEOUT_MS = 5000;

// ---------------------------------------------------------------------------
// Bounded stdin reader
// ---------------------------------------------------------------------------

/**
 * Read process.stdin with a first-byte timeout, an inactivity timeout
 * re-armed on every chunk, and early-completion-by-parse. Never rejects.
 *
 * @param {{
 *   firstByteTimeoutMs?: number,
 *   inactivityTimeoutMs?: number,
 *   tryParse?: ((accumulated: string) => unknown) | null,
 * }} [options]
 * @returns {Promise<string>} the string accumulated from stdin, via
 *   whichever resolution path fires first.
 */
function readStdinGuarded(options) {
  const opts = options || {};
  const firstByteTimeoutMs = typeof opts.firstByteTimeoutMs === 'number'
    ? opts.firstByteTimeoutMs
    : DEFAULT_FIRST_BYTE_TIMEOUT_MS;
  const inactivityTimeoutMs = typeof opts.inactivityTimeoutMs === 'number'
    ? opts.inactivityTimeoutMs
    : DEFAULT_INACTIVITY_TIMEOUT_MS;
  // 'tryParse' in opts distinguishes "not provided" (default JSON.parse)
  // from "explicitly null" (early-completion disabled) from "a function".
  const tryParse = Object.prototype.hasOwnProperty.call(opts, 'tryParse')
    ? opts.tryParse
    : JSON.parse;

  return new Promise((resolve) => {
    const stdin = process.stdin;
    let resolved = false;
    let accumulated = '';
    let firstByteTimer = null;
    let inactivityTimer = null;

    function clearTimers() {
      if (firstByteTimer) {
        clearTimeout(firstByteTimer);
        firstByteTimer = null;
      }
      if (inactivityTimer) {
        clearTimeout(inactivityTimer);
        inactivityTimer = null;
      }
    }

    function cleanup() {
      clearTimers();
      stdin.removeListener('data', onData);
      stdin.removeListener('end', onEnd);
      stdin.removeListener('error', onError);
      try {
        stdin.pause();
      } catch (_) {
        /* stdin may already be in an unusable state - safe to ignore */
      }
      // pause() alone does not release the underlying pipe/socket handle
      // from the event loop when a writer still holds the other end open
      // (the exact never-closing-stdin scenario this module exists to
      // survive) - unref() is required so an idle process can actually
      // exit. Guarded: unref is not defined on every stream-like object
      // (e.g. a plain EventEmitter stand-in used in tests), so this must
      // never assume it exists.
      try {
        if (typeof stdin.unref === 'function') {
          stdin.unref();
        }
      } catch (_) {
        /* ignore */
      }
    }

    function finish(value) {
      if (resolved) return;
      resolved = true;
      cleanup();
      resolve(value);
    }

    function armInactivityTimer() {
      if (inactivityTimer) clearTimeout(inactivityTimer);
      inactivityTimer = setTimeout(() => {
        finish(accumulated);
      }, inactivityTimeoutMs);
    }

    function onData(chunk) {
      if (firstByteTimer) {
        clearTimeout(firstByteTimer);
        firstByteTimer = null;
      }
      accumulated += chunk;

      if (tryParse) {
        try {
          tryParse(accumulated);
          // Non-throwing parse: the accumulated string is a complete,
          // well-formed payload. Resolve immediately - do not wait for EOF.
          finish(accumulated);
          return;
        } catch (_) {
          // Not yet a complete/valid payload - keep accumulating.
        }
      }

      armInactivityTimer();
    }

    function onEnd() {
      finish(accumulated);
    }

    function onError() {
      finish(accumulated);
    }

    try {
      stdin.setEncoding('utf8');
    } catch (_) {
      // stdin unusable (e.g. already destroyed) - fall through to the
      // first-byte timeout, which will resolve '' when no data arrives.
    }

    stdin.on('data', onData);
    stdin.on('end', onEnd);
    stdin.on('error', onError);

    firstByteTimer = setTimeout(() => {
      finish('');
    }, firstByteTimeoutMs);

    try {
      stdin.resume();
    } catch (_) {
      /* adding the 'data' listener above already switches to flowing mode */
    }
  });
}

module.exports = {
  readStdinGuarded,
  DEFAULT_FIRST_BYTE_TIMEOUT_MS,
  DEFAULT_INACTIVITY_TIMEOUT_MS,
};
