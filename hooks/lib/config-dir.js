#!/usr/bin/env node

/**
 * Purpose: Shared harness config-dir resolver, mirroring the precedence in
 *          bin/_lib.py's resolve_claude_config_dir() (itself modeled on
 *          bin/ds-identity's PROFILE_CONFIG_DIR_ENV) so a JS-side hook
 *          reading transcripts under a harness config dir does not
 *          hardcode `~/.claude` - the bug this module exists to fix (see
 *          bin/ds-parse-subagent-usage's Failure modes for the measured
 *          root cause: on a machine where CLAUDE_CONFIG_DIR points
 *          elsewhere, a hardcoded ~/.claude path silently resolves to an
 *          empty directory and every reader downstream sees "no data").
 *
 * Public API (CommonJS): resolveClaudeConfigDir() -> string
 *   Returns the active harness config dir as an absolute path string.
 *   Precedence: AGENTIC_CONFIG_DIR > CLAUDE_CONFIG_DIR > CODEX_HOME >
 *   PI_CODING_AGENT_DIR, first non-blank wins. Falls back to
 *   path.join(os.homedir(), '.claude') when none is set. A leading `~`
 *   (bare `~`, or `~/...`) in the env var's value is expanded to
 *   os.homedir() before path.resolve() absolutizes the result (round-2
 *   fix: this mirrors bin/_lib.py's resolve_claude_config_dir(), which
 *   already applied os.path.expanduser() - an unquoted shell would expand
 *   `~` before either process ever saw it, but a quoted profile value or a
 *   JSON/launchd/systemd/Docker env block never goes through a shell, so
 *   the two impls diverged on exactly the redirected-config-dir machine
 *   this module exists to support; Python found the transcript, Node built
 *   an unexpandable literal `~/...` path that can never exist).
 *
 * Upstream deps: Node built-ins only (os, path). No npm dependencies.
 *
 * Downstream consumers: hooks/subagent-stop-spawn-emit.js
 *   (resolveTranscriptPath()).
 *
 * Failure modes: Never throws. An unset/blank env var is treated as
 *   absent. This is a READ-ONLY lookup (transcript discovery) - unlike a
 *   write-target resolver, it deliberately does NOT check that the
 *   resolved path stays under $HOME or is free of symlink components;
 *   callers must handle a nonexistent config dir themselves (e.g. by
 *   falling through to a bounded glob).
 *
 * Performance: A handful of process.env reads - negligible.
 */

'use strict';

const os = require('os');
const path = require('path');

const CONFIG_DIR_ENV = [
  'AGENTIC_CONFIG_DIR',
  'CLAUDE_CONFIG_DIR',
  'CODEX_HOME',
  'PI_CODING_AGENT_DIR',
];

/**
 * Expand a leading `~` (bare `~`, or `~/...`) to os.homedir(), then
 * absolutize via path.resolve(). Mirrors Python's
 * os.path.abspath(os.path.expanduser(raw)) - see resolveClaudeConfigDir's
 * header comment for why both steps are required here.
 */
function absolutize(raw) {
  let expanded = raw;
  if (expanded === '~') {
    expanded = os.homedir();
  } else if (expanded.startsWith('~/') || expanded.startsWith(`~${path.sep}`)) {
    expanded = path.join(os.homedir(), expanded.slice(2));
  }
  return path.resolve(expanded);
}

function resolveClaudeConfigDir() {
  for (const varName of CONFIG_DIR_ENV) {
    const raw = process.env[varName];
    if (typeof raw === 'string' && raw.trim()) {
      return absolutize(raw.trim());
    }
  }
  return path.join(os.homedir(), '.claude');
}

module.exports = { resolveClaudeConfigDir, CONFIG_DIR_ENV };
