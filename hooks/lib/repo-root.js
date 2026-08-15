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
 *   bin/ds-wrap-acquire-lock, bin/ds-wrap-release-lock,
 *   .copilot/hooks/stop-context-copilot.js, .github/hooks/stop-context-copilot.js,
 *   .cursor/hooks/stop-context-cursor.js
 *
 * Failure modes: never throws. EACCES/ENOENT at any level along the walk is
 *   treated as "not found here, keep walking". If no `.git` ancestor is
 *   found within MAX_DEPTH, returns the realpath'd startDir unchanged with
 *   foundGitAncestor:false.
 *
 *   ROUND-2 REWORK (adversarial review Major 6): this file previously
 *   stated an UNCONDITIONAL "callers must SKIP, never silently write at
 *   the fallback path" contract that no plain `resolveAgenticCwd()`
 *   caller in the repo actually implemented - every one of them (12 JS
 *   consumers below, at last audit) uses the returned path directly and
 *   discards foundGitAncestor. That is a deliberate, reviewed choice for
 *   MOST of them, not an unfixed bug: these are advisory nudge state,
 *   telemetry caches, and enforcement counters (config-nudge suppression
 *   sentinels, capture-gap cursors, skill-candidate tallies, events.jsonl
 *   appends) whose worst case on the rare "no .git ancestor anywhere up
 *   the tree" path (e.g. a harness cwd of $HOME or /tmp - NOT the far
 *   more common "drifted into a subdirectory of a real repo" case, which
 *   foundGitAncestor:true already handles correctly) is a degraded,
 *   recoverable advisory artifact - not silent corruption of real project
 *   state.
 *
 *   ROUND-3 REWORK (adversarial review Minor 2): "at a non-repo location"
 *   above understated where the fallback root actually lands for the
 *   common $HOME case specifically - it is NOT some inert throwaway
 *   scratch directory. When start_dir has no `.git` ancestor anywhere up
 *   to and including $HOME, the fallback root IS $HOME itself, and these
 *   consumers' `<root>/.agentic/...` writes then land inside the REAL
 *   global `~/.agentic/` store - still "degraded, recoverable" in the
 *   sense that nothing here corrupts a real PROJECT's state (the
 *   correctness property this section defends), but not the low-stakes
 *   "harmless scratch write" the prior wording implied. Two consumers
 *   genuinely DO skip on
 *   foundGitAncestor:false because a write at the wrong location would
 *   actively corrupt cross-session state: `hooks/enforce-skeptic-round-
 *   cap.py` (a round counter) and `hooks/session-start-wrap.sh` (guards
 *   every write on `-n "$resolved_root"`, zero `|| echo "$cwd"`
 *   fallback) - both Python/shell callers of the sibling resolvers below,
 *   not this file. `bin/ds-identity`'s `write-hook`/`resolve-hook` (the
 *   Stop-hook session-log telemetry path, which fires on every turn) was
 *   added to this stricter category in the same round-2 rework: telemetry
 *   misattributed to a phantom non-repo `.agentic/session-log/` is a
 *   correctness bug (wrong developer_id/project_slug), not a merely
 *   degraded advisory. Callers needing the SKIP discipline must consult
 *   `foundGitAncestor` explicitly via `resolveAgenticCwdWithDiagnostics`
 *   and refuse the write themselves when it is false - this module never
 *   enforces that policy on a caller's behalf.
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
