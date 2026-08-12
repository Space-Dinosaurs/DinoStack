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
 *   path.join(os.homedir(), '.claude') when none is set.
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

function resolveClaudeConfigDir() {
  for (const varName of CONFIG_DIR_ENV) {
    const raw = process.env[varName];
    if (typeof raw === 'string' && raw.trim()) {
      return raw.trim();
    }
  }
  return path.join(os.homedir(), '.claude');
}

module.exports = { resolveClaudeConfigDir, CONFIG_DIR_ENV };
