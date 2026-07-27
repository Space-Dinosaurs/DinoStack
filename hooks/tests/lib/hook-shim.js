#!/usr/bin/env node

/**
 * Purpose: Shared test helper that re-anchors a hook script's RELATIVE
 *          `require('./lib/<name>.js')` calls to absolute paths so a shimmed copy
 *          written to os.tmpdir() still loads the REAL repo libs.
 *
 *          Extracted because the rewrite was hand-maintained as a per-library
 *          `.replace()` chain in five test files, with an assertion that no
 *          relative `./lib/` require survived. Every new hook library therefore
 *          broke N test files at once with a FATAL that named the file to patch -
 *          which is exactly what happened when hooks/lib/context-rollup.js was
 *          added. Rewriting GENERICALLY retires that whole class of breakage: a
 *          future library needs no test edit at all.
 *
 * Public API (CommonJS):
 *   reanchorHookRequires(source, libDir, opts) -> string
 *
 * Upstream deps: Node built-ins only (none required at module scope). No fs
 *                access - the caller owns reading the hook and writing the shim.
 *
 * Downstream consumers: hooks/tests/test-capture-gap.js,
 *                       hooks/tests/test-stop-context-health.js,
 *                       hooks/tests/test-stop-context-telemetry.js.
 *                       (test-post-tool-use-capture-nudge.js and
 *                       test-post-tool-use-skill-nudge.js still carry their own
 *                       inline chains; migrate them when next touched.)
 *
 * Failure modes: throws a descriptive Error when a relative `./lib/` require
 *                survives the rewrite - a loud failure is correct here, because a
 *                surviving relative require would make the shim load a
 *                nonexistent /tmp/lib/... path and fail confusingly later.
 *
 * Performance: two regex passes over one source string. Negligible.
 */

'use strict';

/**
 * Rewrite every `require('./lib/<name>.js')` in `source` to an absolute path
 * under `libDir`.
 *
 * @param {string} source - The hook script's source text.
 * @param {string} libDir - Absolute path to the real hooks/lib directory.
 * @param {{skipPattern?: RegExp}} [opts] - `skipPattern` names libraries that are
 *   deliberately NOT rewritten because they are required LAZILY inside a
 *   function rather than at module scope (default: skill-candidate*, which the
 *   Stop hook loads only when its toggle is on).
 * @returns {string}
 * @throws {Error} when any relative `./lib/` require survives the rewrite.
 */
function reanchorHookRequires(source, libDir, opts) {
  const o = opts || {};
  const skip = o.skipPattern || /^skill-candidate/;
  const sep = libDir.endsWith('/') ? '' : '/';

  const rewritten = source.replace(
    /require\((['"])\.\/lib\/([A-Za-z0-9._-]+)\1\)/g,
    (whole, _q, name) => (skip.test(name) ? whole : `require(${JSON.stringify(libDir + sep + name)})`)
  );

  // The survivor scan must use the CALLER'S skip set, not a hardcoded name -
  // hardcoding `skill-candidate` here would silently ignore a genuine survivor
  // whenever a caller passed a different skipPattern, which is the one thing
  // this assertion exists to catch.
  const survivors = (rewritten.match(/require\(['"]\.\/lib\/([A-Za-z0-9._-]+)['"]\)/g) || [])
    .filter((hit) => {
      const m = hit.match(/\.\/lib\/([A-Za-z0-9._-]+)/);
      return !(m && skip.test(m[1]));
    });
  if (survivors.length > 0) {
    throw new Error(
      'reanchorHookRequires: a relative ./lib/ require survived the rewrite: '
      + survivors.join(', ')
    );
  }
  return rewritten;
}

module.exports = { reanchorHookRequires };
