#!/usr/bin/env node

/**
 * Purpose: Shared activation guard for agentic-engineering Node hooks. Required
 *          by stop-context.js, session-end-wrap.js, and the capture/emit JS
 *          hooks, which call isActive(cwd) as the first side-effect gate. When a
 *          project is dormant the hook returns/exits 0 with no output, so the
 *          globally-registered methodology hooks become instant no-ops. In
 *          particular stop-context.js stops writing .agentic/events.jsonl in
 *          non-active projects.
 *
 * Activation layers (first hit wins), evaluated per candidate root while
 * walking from cwd up to the outermost git root (so worktree-isolated
 * subagents inherit the project root's activation instead of going silently
 * dormant):
 *   1. <root>/.agentic/active          -> ACTIVE
 *   2. <root>/.agentic/active.session  -> ACTIVE
 *   3. <root>/.agentic/dormant         -> DORMANT (tombstone overrides auto-detect)
 *   4. <root>/.agentic/ dir exists     -> ACTIVE (zero-migration auto-detect)
 *   5. any candidate root in ~/.agentic/activation.list -> ACTIVE
 *   6. none                            -> DORMANT
 *
 * Worktree-zone hardening: candidate roots at or below
 * <outermost-git-root>/.agentic/worktrees/ are subagent scratch space, not
 * operator boundaries. Markers at those levels (active, active.session,
 * dormant) are IGNORED and the walk continues up: a subagent must not be
 * able to disable enforce-* hooks by writing its own dormant tombstone, and
 * an active marker in scratch space is meaningless. The project root's own
 * markers always decide.
 *
 * Public API: isActive(cwd) -> boolean
 *   true  = active (hook should run). false = dormant (hook should no-op).
 *   FAIL-ACTIVE: a falsy / non-string / blank cwd OR any stat error returns
 *   true. A guard bug must never silently kill methodology for active users
 *   (plan R3).
 *
 * Upstream deps: Node core only (fs, path, os). No npm deps, no parse on hot path.
 * Downstream consumers: hooks/stop-context.js, hooks/session-end-wrap.js,
 *                       hooks/post-tool-use-capture-nudge.js,
 *                       hooks/pre-tool-use-spawn-emit.js, hooks/wrap-daemon.js.
 * Failure modes: never throws. Returns true on any error (fail-ACTIVE).
 * Performance: <10ms - a few fs.existsSync calls per ancestor plus at most one
 *              small list read (only reached when no project marker).
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

// Outermost .git-bearing ancestor (incl. start), or null when no checkout
// exists above start. Worktrees carry a .git *file*; the main checkout a
// .git *dir*; existsSync covers both.
function gitBound(start) {
  let top = null;
  let cur = start;
  for (;;) {
    if (fs.existsSync(path.join(cur, '.git'))) top = cur;
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  return top;
}

// Candidate project roots from start up to the outermost git root (inclusive).
// With no checkout above, returns [start] (legacy exact-cwd behavior; the walk
// never escapes into an ancestor .agentic dir such as ~/.agentic).
function iterRoots(start, bound) {
  const roots = [];
  let cur = start;
  for (;;) {
    roots.push(cur);
    if (bound === null || cur === bound) break;
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  return roots;
}

// True when root is at or below <bound>/.agentic/worktrees/ (subagent scratch
// space; markers there are ignored). Pure path math on canonical paths.
function inWorktreeZone(root, bound) {
  if (bound === null) return false;
  const rel = path.relative(bound, root);
  const parts = rel.split(path.sep);
  return parts.length >= 2 && parts[0] === '.agentic' && parts[1] === 'worktrees';
}

// True/False for a marker at one candidate root, null to keep walking.
// Precedence mirrors the legacy single-cwd order (nearest ancestor wins).
function decideAt(root) {
  const agentic = path.join(root, '.agentic');
  if (fs.existsSync(path.join(agentic, 'active'))) return true;
  if (fs.existsSync(path.join(agentic, 'active.session'))) return true;
  if (fs.existsSync(path.join(agentic, 'dormant'))) return false; // tombstone
  try {
    if (fs.existsSync(agentic) && fs.statSync(agentic).isDirectory()) return true;
  } catch (_) {
    // stat race -> treat as no marker, keep walking
  }
  return null;
}

function inAllowlist(roots) {
  try {
    const listPath = path.join(os.homedir(), '.agentic', 'activation.list');
    const targets = new Set();
    for (const r of roots) {
      try {
        targets.add(fs.realpathSync(r));
      } catch (_) {
        targets.add(r);
      }
    }
    const raw = fs.readFileSync(listPath, 'utf8');
    for (const line of raw.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let rp;
      try {
        rp = fs.realpathSync(trimmed);
      } catch (_) {
        rp = trimmed;
      }
      if (targets.has(rp)) return true;
    }
  } catch (_) {
    // missing/unreadable list or unresolvable root -> not in allowlist
  }
  return false;
}

function isActive(cwd) {
  try {
    if (typeof cwd !== 'string' || !cwd.trim()) return true; // indeterminate -> ACTIVE
    let start;
    try {
      start = fs.realpathSync(cwd.trim());
    } catch (_) {
      start = cwd.trim();
    }
    const bound = gitBound(start);
    const roots = iterRoots(start, bound);
    for (const root of roots) {
      if (inWorktreeZone(root, bound)) continue; // subagent scratch space
      let decision = null;
      try {
        decision = decideAt(root);
      } catch (_) {
        decision = null;
      }
      if (decision !== null) return decision;
    }
    if (inAllowlist(roots)) return true;
    return false; // dormant
  } catch (_) {
    return true; // fail ACTIVE
  }
}

module.exports = { isActive };
