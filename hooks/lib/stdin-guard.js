#!/usr/bin/env node

/**
 * Purpose: Shared bounded-stdin reader for hooks that must not block a
 *          harness's shutdown path when the spawning process never closes
 *          stdin. Reads process.stdin with two chunk-driven timers
 *          (first-byte, re-armed inactivity) plus a one-shot absolute
 *          deadline and a running max-bytes cap, plus early-completion-by-
 *          parse gated behind a cheap tail precheck, so a hook exits fast
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
 *     options.absoluteTimeoutMs (default DEFAULT_ABSOLUTE_TIMEOUT_MS) - a
 *       one-shot wall-clock deadline armed once at read start and never
 *       re-armed by chunk activity, independent of the inactivity timer.
 *     options.maxStdinBytes (default DEFAULT_MAX_STDIN_BYTES) - a running
 *       total-bytes cap; exceeding it resolves early with whatever has
 *       accumulated so far.
 *     options.tryParse: a function(str) that throws on incomplete/invalid
 *       input (default JSON.parse); pass null to disable early-completion.
 *     Never rejects - always resolves with the string accumulated so far.
 *   DEFAULT_FIRST_BYTE_TIMEOUT_MS - 750
 *   DEFAULT_INACTIVITY_TIMEOUT_MS - 5000
 *   DEFAULT_ABSOLUTE_TIMEOUT_MS - 10000
 *   DEFAULT_MAX_STDIN_BYTES - 10 * 1024 * 1024 (10 MiB)
 *
 * Upstream deps: Node built-ins only (process.stdin). No npm dependencies.
 *                process.stdin.setEncoding('utf8') delegates multi-byte
 *                character boundary handling to Node's internal
 *                StringDecoder, so a chunk split mid-codepoint is assembled
 *                correctly (sidesteps the truncation bug class documented
 *                against hooks/wrap-daemon.js's manual byte-cap logic).
 *
 * Downstream consumers: wired into all 9 stdin-blocking hooks:
 *                        hooks/stop-context.js,
 *                        hooks/post-tool-use-capture-nudge.js,
 *                        hooks/session-end-wrap.js,
 *                        hooks/pre-tool-use-spawn-emit.js,
 *                        .codex/hooks/stop-context-codex.js,
 *                        .gemini/hooks/stop-context-gemini.js,
 *                        .copilot/hooks/stop-context-copilot.js, and
 *                        .cursor/hooks/stop-context-cursor.js, plus
 *                        .github/hooks/stop-context-copilot.js (a generated
 *                        mirror of the .copilot port, not hand-authored).
 *                        All 9 call readStdinGuarded() with zero arguments
 *                        (pure defaults).
 *
 * Failure modes: Never rejects. Every resolution path returns whatever
 *                string has been accumulated so far via one of five routes:
 *                (1) parse-success - options.tryParse (default JSON.parse)
 *                is only attempted when the accumulated string's trailing
 *                non-whitespace character is '}' or ']' (a cheap tail
 *                precheck - see Performance); when attempted and it does not
 *                throw, resolves immediately without waiting for EOF;
 *                (2) EOF - the stream's 'end' event fires (stdin closed
 *                normally), resolves immediately, preserving the existing
 *                fast path (~3-20ms) when the spawning harness closes stdin
 *                promptly; (3) inactivity timeout - the inactivity timer
 *                (re-armed on every chunk) fires after data has started
 *                arriving but stalls (resolves with whatever arrived), or
 *                the first-byte timer fires with zero bytes received
 *                (resolves ''); (4) absolute deadline - a one-shot
 *                wall-clock timer armed once at read start (never re-armed)
 *                fires regardless of ongoing chunk activity, bounding a
 *                writer that drips non-JSON data faster than the inactivity
 *                window forever; (5) byte cap - the running total-bytes
 *                counter exceeds options.maxStdinBytes, bounding unbounded
 *                memory growth from a runaway writer. A stream 'error' event
 *                is treated as an EOF-equivalent: resolves with whatever
 *                accumulated, never propagates the error. All timers
 *                (first-byte, inactivity, absolute) are cleared and all
 *                listeners removed before resolving; cleanup also calls
 *                process.stdin.pause() followed by a guarded stdin.unref()
 *                (only invoked when the stream actually exposes unref, since
 *                not every stream-like object does) so an idle process is
 *                free to exit on every resolution path - including the
 *                primary target scenario where the writer never closes the
 *                pipe. pause() alone does NOT release the underlying
 *                pipe/socket handle from the event loop in that scenario
 *                (verified empirically on Node v24: a process that has
 *                received data, paused stdin, and removed all listeners
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
 *                delivery duration - which the absolute deadline and byte
 *                cap now bound instead.
 *
 * Scope note (early-completion-by-parse): the tail precheck above only
 *                fires for accumulated strings ending in '}' or ']' - i.e.
 *                top-level JSON object/array payloads. A top-level scalar
 *                payload (a bare number, string, or boolean) never matches
 *                the precheck and therefore never early-completes
 *                mid-stream; it resolves at EOF or via one of the bounded
 *                backstops above instead. This is an intentional scope
 *                narrowing (previously every chunk was reparsed regardless
 *                of shape) that also removes the scalar-truncation risk a
 *                naive every-chunk reparse could hit at a coincidental split
 *                point.
 *
 * Performance: Typical resolution is dominated by the spawning harness's own
 *              behavior, not this module: ~3-20ms when stdin closes promptly
 *              (EOF path), near-instant once a complete object/array payload
 *              has arrived (parse-success path), and otherwise bounded by
 *              firstByteTimeoutMs / inactivityTimeoutMs / absoluteTimeoutMs /
 *              maxStdinBytes in the worst case (silent, stalled, or runaway
 *              stdin). The parse attempt itself is gated behind a cheap tail
 *              check (scan backward from the end of the accumulated string
 *              until the first non-whitespace character - O(1) amortized
 *              when there is no trailing whitespace), so a non-JSON or
 *              still-incomplete payload no longer re-parses the entire
 *              accumulated buffer on every chunk (was O(n^2) in the worst
 *              case pre-fix). No polling; entirely event-driven off the
 *              'data' / 'end' / 'error' events plus three timers.
 */

'use strict';

const DEFAULT_FIRST_BYTE_TIMEOUT_MS = 750;
const DEFAULT_INACTIVITY_TIMEOUT_MS = 5000;
const DEFAULT_ABSOLUTE_TIMEOUT_MS = 10000;
const DEFAULT_MAX_STDIN_BYTES = 10 * 1024 * 1024; // 10 MiB

// ---------------------------------------------------------------------------
// Bounded stdin reader
// ---------------------------------------------------------------------------

/**
 * Read process.stdin with a first-byte timeout, an inactivity timeout
 * re-armed on every chunk, a one-shot absolute deadline, a max-bytes cap,
 * and early-completion-by-parse. Never rejects.
 *
 * @param {{
 *   firstByteTimeoutMs?: number,
 *   inactivityTimeoutMs?: number,
 *   absoluteTimeoutMs?: number,
 *   maxStdinBytes?: number,
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
  const absoluteTimeoutMs = typeof opts.absoluteTimeoutMs === 'number'
    ? opts.absoluteTimeoutMs
    : DEFAULT_ABSOLUTE_TIMEOUT_MS;
  const maxStdinBytes = typeof opts.maxStdinBytes === 'number'
    ? opts.maxStdinBytes
    : DEFAULT_MAX_STDIN_BYTES;
  // 'tryParse' in opts distinguishes "not provided" (default JSON.parse)
  // from "explicitly null" (early-completion disabled) from "a function".
  const tryParse = Object.prototype.hasOwnProperty.call(opts, 'tryParse')
    ? opts.tryParse
    : JSON.parse;

  return new Promise((resolve) => {
    const stdin = process.stdin;
    let resolved = false;
    let accumulated = '';
    let accumulatedBytes = 0;
    let firstByteTimer = null;
    let inactivityTimer = null;
    let absoluteTimer = null;

    function clearTimers() {
      if (firstByteTimer) {
        clearTimeout(firstByteTimer);
        firstByteTimer = null;
      }
      if (inactivityTimer) {
        clearTimeout(inactivityTimer);
        inactivityTimer = null;
      }
      if (absoluteTimer) {
        clearTimeout(absoluteTimer);
        absoluteTimer = null;
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

    // Returns the last non-whitespace character in str, or '' when str is
    // empty or all whitespace. Bounded by the amount of trailing
    // whitespace (typically none), not by str's full length, so this stays
    // O(1) amortized instead of re-scanning the whole accumulated buffer.
    function lastNonWhitespaceChar(str) {
      for (let i = str.length - 1; i >= 0; i--) {
        const ch = str[i];
        if (ch !== ' ' && ch !== '\n' && ch !== '\r' && ch !== '\t') {
          return ch;
        }
      }
      return '';
    }

    function onData(chunk) {
      if (firstByteTimer) {
        clearTimeout(firstByteTimer);
        firstByteTimer = null;
      }
      accumulated += chunk;
      accumulatedBytes += Buffer.byteLength(chunk, 'utf8');

      if (accumulatedBytes > maxStdinBytes) {
        // Byte cap exceeded - fail open with whatever has accumulated so
        // far instead of growing memory unboundedly for a runaway writer.
        finish(accumulated);
        return;
      }

      if (tryParse) {
        // Only attempt a parse when the accumulated string looks like it
        // could be a complete object/array (trailing '}' or ']') - avoids
        // re-parsing the entire buffer on every chunk for payloads that
        // are not yet complete or are not JSON at all (was O(n^2) in the
        // worst case). See the "Scope note" in the module manifest.
        const tail = lastNonWhitespaceChar(accumulated);
        if (tail === '}' || tail === ']') {
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

    // Absolute deadline: armed once, here, at read start - never re-armed
    // by chunk activity (unlike the inactivity timer). Bounds a writer that
    // drips non-JSON data faster than inactivityTimeoutMs forever.
    absoluteTimer = setTimeout(() => {
      finish(accumulated);
    }, absoluteTimeoutMs);

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
  DEFAULT_ABSOLUTE_TIMEOUT_MS,
  DEFAULT_MAX_STDIN_BYTES,
};
