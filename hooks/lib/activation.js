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
 * Activation layers (first hit wins):
 *   1. <cwd>/.agentic/active          -> ACTIVE
 *   2. <cwd>/.agentic/active.session  -> ACTIVE
 *   3. <cwd>/.agentic/dormant         -> DORMANT (tombstone overrides auto-detect)
 *   4. <cwd>/.agentic/ dir exists     -> ACTIVE (zero-migration auto-detect)
 *   5. cwd in ~/.agentic/activation.list -> ACTIVE
 *   6. none                           -> DORMANT
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
 * Performance: <10ms - at most 4 fs.existsSync calls plus one small list read.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

function inAllowlist(cwd) {
  try {
    const listPath = path.join(os.homedir(), '.agentic', 'activation.list');
    const target = fs.realpathSync(cwd);
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
      if (rp === target) return true;
    }
  } catch (_) {
    // missing/unreadable list or unresolvable cwd -> not in allowlist
  }
  return false;
}

function isActive(cwd) {
  try {
    if (typeof cwd !== 'string' || !cwd.trim()) return true; // indeterminate -> ACTIVE
    const agentic = path.join(cwd.trim(), '.agentic');
    if (fs.existsSync(path.join(agentic, 'active'))) return true;
    if (fs.existsSync(path.join(agentic, 'active.session'))) return true;
    if (fs.existsSync(path.join(agentic, 'dormant'))) return false; // tombstone
    if (fs.existsSync(agentic) && fs.statSync(agentic).isDirectory()) return true; // auto-detect
    if (inAllowlist(cwd.trim())) return true;
    return false; // dormant
  } catch (_) {
    return true; // fail ACTIVE
  }
}

module.exports = { isActive };
