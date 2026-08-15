/**
 * Purpose: Resolves the repo-root directory to anchor `.agentic/` state
 *          writes, instead of trusting the harness-supplied payload `cwd`
 *          verbatim. Prevents phantom `.agentic/` trees being written at
 *          whatever directory a stray `cd` (or a payload `cwd` that drifts
 *          across Bash tool calls) happens to leave the process in.
 *
 * Public API: resolveAgenticCwdWithDiagnostics(startDir) -> { root, driftLevels, foundGitAncestor }
 *             resolveAgenticCwd(startDir) -> string
 *
 * Upstream deps: node:fs (realpathSync, existsSync), node:path
 *
 * Downstream consumers: hooks/lib/wrap-marker.js, hooks/stop-context.js,
 *   hooks/pre-tool-use-spawn-emit.js, hooks/subagent-stop-spawn-emit.js,
 *   hooks/conductor-overreach-nudge.js, hooks/post-tool-use-capture-nudge.js,
 *   hooks/session-end-wrap.js, hooks/wrap-daemon.js,
 *   hooks/lib/skill-candidate-detector.js, hooks/lib/state-mark.js,
 *   hooks/lib/capture-gap.js, hooks/lib/context-rollup.js,
 *   bin/ds-wrap-acquire-lock, bin/ds-wrap-release-lock
 *
 * Failure modes: never throws. EACCES/ENOENT at any level along the walk is
 *   treated as "not found here, keep walking". If no `.git` ancestor is
 *   found within MAX_DEPTH, returns the realpath'd startDir unchanged with
 *   foundGitAncestor:false - callers must treat that as a resolution
 *   failure and SKIP the write, never silently write at the fallback path.
 *
 * Performance: a handful of fs.existsSync calls per invocation (at most
 *   MAX_DEPTH), no subprocess, no network.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const MAX_DEPTH = 64;

/**
 * Realpath-pin startDir and walk up looking for a `.git` entry
 * (file or directory - EXISTENCE ONLY, never isDirectory()/isFile()).
 * A linked git worktree's `.git` is a FILE, not a directory, so a
 * dir-only check fails in the most common execution environment here.
 */
function resolveAgenticCwdWithDiagnostics(startDir) {
  let real;
  try {
    real = fs.realpathSync(startDir);
  } catch (_err) {
    real = startDir;
  }

  let current = real;
  let driftLevels = 0;

  for (let i = 0; i <= MAX_DEPTH; i += 1) {
    let hasGit = false;
    try {
      hasGit = fs.existsSync(path.join(current, '.git'));
    } catch (_err) {
      hasGit = false;
    }

    if (hasGit) {
      return { root: current, driftLevels, foundGitAncestor: true };
    }

    const parent = path.dirname(current);
    if (parent === current) {
      // Reached filesystem root without finding a `.git` ancestor.
      break;
    }
    current = parent;
    driftLevels += 1;
    if (driftLevels > MAX_DEPTH) {
      break;
    }
  }

  return { root: real, driftLevels: 0, foundGitAncestor: false };
}

function resolveAgenticCwd(startDir) {
  return resolveAgenticCwdWithDiagnostics(startDir).root;
}

module.exports = {
  resolveAgenticCwdWithDiagnostics,
  resolveAgenticCwd,
  MAX_DEPTH,
};
