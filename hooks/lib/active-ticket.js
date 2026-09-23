/**
 * Purpose: DS-246. Mechanically resolve the ticket a spawn works on, so hook
 *          spawn telemetry carries a `task_id` for every spawn type without
 *          the conductor having to emit it. Tiers, first hit wins:
 *            1. batch_state - `<agenticDir>/batch-state.json` whose
 *               `session_id` is this session, `status === 'active'`, and
 *               exactly one ticket is `in_progress`.
 *            2. invocation - the session's newest /ds-implement-ticket
 *               invocation (a `<command-name>` slash tag or a Skill
 *               tool_use whose `skill` ends with `ds-implement-ticket`),
 *               when its args name exactly one key T. Two staleness guards
 *               apply, because operators switch tickets in plain text:
 *               veto - a spawn whose description names keys of T's own
 *               project (same prefix), none of them T, is not credited;
 *               expiry - once any Agent/Task tool_use after the invocation
 *               (other than this spawn's own) names such keys without T, T
 *               stays expired until the next invocation. Keys with another
 *               prefix (ADR-038, GLM-4, SHA-256) never count.
 *            3. none, with a note naming why.
 *
 * Public API (CommonJS):
 *   resolveActiveTicket({agenticDir, sessionId, transcriptPath, toolUseId,
 *                        spawnDescription}) -> {ticketId, source, note}
 *     source: 'batch_state' | 'invocation' | 'none'. note is null unless
 *     source is 'none': 'no_transcript', 'no_invocation',
 *     'invocation_no_key', 'invocation_ambiguous:<k1,k2>',
 *     'invocation_vetoed:<keys>', 'invocation_expired:<key>',
 *     'resolver_error'.
 *   invocationKeys(args) -> string[]   (exported for tests)
 *   descriptionKeys(text, ticketKey) -> string[]  (exported for tests;
 *     only keys sharing ticketKey's prefix, excluding date-shaped IDs;
 *     [] when ticketKey has no project prefix)
 *
 * Upstream deps: Node built-ins (fs, path); ./spawn-events.js (streamLines);
 *   ./prune-aged.js (pruneAgedFiles).
 *   Reads `<agenticDir>/batch-state.json` and the parent-session transcript
 *   (at most its last MAX_SCAN_BYTES, incrementally). Writes
 *   `<agenticDir>/.ticket-scan-<sessionId>.json`
 *   `{path, offset, invocation:{key,ts,note}|null, expired_by:[{key,tool_use_id}]}`
 *   via pid-suffixed tmp + rename; `expired_by` keeps at most two entries
 *   so this spawn's own tool_use can be excluded. On a session's first
 *   call (no valid cache yet) it deletes `.ticket-scan-*` files in
 *   agenticDir whose mtime is older than 7 days.
 *
 * Downstream consumers: hooks/pre-tool-use-spawn-emit.js,
 *   hooks/subagent-stop-spawn-emit.js (fallback when the paired start has
 *   no task_id).
 *
 * Failure modes: never throws; any error yields {ticketId:null,
 *   source:'none', note}. A corrupt or foreign cache is treated as absent.
 *   A transcript that shrank since the cached offset is rescanned.
 *
 * Performance: after the first call per session only the bytes appended
 *   since the cached offset are read; only lines containing
 *   `ds-implement-ticket` or `"tool_use"` are JSON-parsed.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { streamLines } = require('./spawn-events.js');
const { pruneAgedFiles } = require('./prune-aged.js');

const MAX_SCAN_BYTES = 256 * 1024 * 1024;
const KEY_RE = /^([A-Z][A-Z0-9_]+)-\d+$/;
// `(?!-\d)` drops date-shaped IDs (PL-20260913-006), which can share a
// project's prefix and are never a bare ticket key.
const DESC_KEY_RE = /\b([A-Z][A-Z0-9_]+)-\d+\b(?!-\d)/g;
const CACHE_PREFIX = '.ticket-scan-';
const CACHE_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
const COMMAND_RE = /<command-name>\/?(?:[\w.-]+:)?ds-implement-ticket<\/command-name>/;
const ARGS_RE = /<command-args>([\s\S]*?)<\/command-args>/;

function none(note) {
  return { ticketId: null, source: 'none', note };
}

function invocationKeys(args) {
  const tokens = String(args || '').split(/[\s,]+/).filter(Boolean);
  while (tokens.length && /^\w+=/.test(tokens[tokens.length - 1])) tokens.pop();
  const keys = new Set();
  for (const raw of tokens) {
    const t = raw.replace(/^[(\[<"'`]+|[)\]>"'`.;:]+$/g, '');
    const browse = /\/browse\/([A-Z][A-Z0-9_]+-\d+)/.exec(t);
    const issue = /\/issues\/(\d+)/.exec(t);
    if (browse) keys.add(browse[1]);
    else if (issue) keys.add(`#${issue[1]}`);
    else if (/^#\d+$/.test(t) || KEY_RE.test(t)) keys.add(t);
  }
  return [...keys];
}

function descriptionKeys(text, ticketKey) {
  const project = KEY_RE.exec(String(ticketKey || ''));
  if (!project) return [];
  const keys = new Set();
  for (const m of String(text || '').matchAll(DESC_KEY_RE)) {
    if (m[1] === project[1]) keys.add(m[0]);
  }
  return [...keys];
}

function invocationFrom(args, ts) {
  const keys = invocationKeys(args);
  if (keys.length === 1) return { key: keys[0], ts, note: null };
  return { key: null, ts, note: keys.length ? `invocation_ambiguous:${keys.join(',')}` : 'invocation_no_key' };
}

function userText(message) {
  const c = message && message.content;
  if (typeof c === 'string') return c;
  if (!Array.isArray(c)) return '';
  return c.filter((b) => b && b.type === 'text' && typeof b.text === 'string').map((b) => b.text).join('\n');
}

function readBatchTicket(agenticDir, sessionId) {
  try {
    const state = JSON.parse(fs.readFileSync(path.join(agenticDir, 'batch-state.json'), 'utf8'));
    if (!state || state.session_id !== sessionId || state.status !== 'active') return null;
    const active = (Array.isArray(state.tickets) ? state.tickets : [])
      .filter((t) => t && t.status === 'in_progress' && typeof t.ticket_id === 'string' && t.ticket_id);
    return active.length === 1 ? active[0].ticket_id : null;
  } catch (_) {
    return null;
  }
}

function loadCache(cachePath, transcriptPath) {
  try {
    const c = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
    if (c && c.path === transcriptPath && Number.isInteger(c.offset) && c.offset >= 0
        && Array.isArray(c.expired_by)
        && (c.invocation === null || (typeof c.invocation === 'object' && 'key' in c.invocation))) {
      return c;
    }
  } catch (_) { /* absent or corrupt: rescan */ }
  return null;
}

function saveCache(cachePath, state) {
  const tmp = `${cachePath}.tmp-${process.pid}`;
  try {
    fs.writeFileSync(tmp, JSON.stringify(state), 'utf8');
    fs.renameSync(tmp, cachePath);
  } catch (_) {
    try { fs.unlinkSync(tmp); } catch (_e) { /* never created */ }
  }
}

function applyRecord(state, obj) {
  const msg = obj.message;
  if (obj.type === 'user') {
    const text = userText(msg);
    if (COMMAND_RE.test(text)) {
      const args = ARGS_RE.exec(text);
      state.invocation = invocationFrom(args ? args[1] : '', obj.timestamp || null);
      state.expired_by = [];
    }
    return;
  }
  if (obj.type !== 'assistant' || !msg || !Array.isArray(msg.content)) return;
  for (const block of msg.content) {
    if (!block || block.type !== 'tool_use') continue;
    const input = block.input || {};
    if (block.name === 'Skill' && String(input.skill || '').endsWith('ds-implement-ticket')) {
      state.invocation = invocationFrom(input.args, obj.timestamp || null);
      state.expired_by = [];
    } else if ((block.name === 'Agent' || block.name === 'Task') && state.invocation && state.invocation.key) {
      const keys = descriptionKeys(input.description, state.invocation.key);
      if (keys.length && !keys.includes(state.invocation.key) && state.expired_by.length < 2
          && !state.expired_by.some((e) => e.tool_use_id === block.id)) {
        state.expired_by.push({ key: keys[0], tool_use_id: block.id || null });
      }
    }
  }
}

function scanTranscript(agenticDir, sessionId, transcriptPath) {
  const safeSid = String(sessionId).replace(/[^\w.-]/g, '_');
  const cachePath = path.join(agenticDir, `${CACHE_PREFIX}${safeSid}.json`);
  let size;
  try {
    size = fs.statSync(transcriptPath).size;
  } catch (_) {
    return null;
  }
  let state = loadCache(cachePath, transcriptPath);
  if (!state) pruneAgedFiles(agenticDir, CACHE_PREFIX, CACHE_RETENTION_MS);
  if (!state || state.offset > size) {
    state = { path: transcriptPath, offset: 0, invocation: null, expired_by: [] };
  }
  const capStart = Math.max(0, size - MAX_SCAN_BYTES);
  const jumped = capStart > state.offset;
  const start = jumped ? capStart : state.offset;
  let skipFirst = jumped && capStart > 0;

  const res = streamLines(transcriptPath, start, (line) => {
    if (skipFirst) { skipFirst = false; return; }
    if (line.indexOf('ds-implement-ticket') === -1 && line.indexOf('"tool_use"') === -1) return;
    let obj;
    try { obj = JSON.parse(line); } catch (_) { return; }
    if (obj && typeof obj === 'object') applyRecord(state, obj);
  });
  if (!res) return null;
  state.offset = res.endOffset;
  try {
    fs.mkdirSync(agenticDir, { recursive: true });
    saveCache(cachePath, state);
  } catch (_) { /* cache is an optimisation only */ }
  return state;
}

function resolveActiveTicket(opts) {
  try {
    const { agenticDir, sessionId, transcriptPath, toolUseId, spawnDescription } = opts || {};
    if (agenticDir && sessionId) {
      const batchTicket = readBatchTicket(agenticDir, sessionId);
      if (batchTicket) return { ticketId: batchTicket, source: 'batch_state', note: null };
    }
    if (!agenticDir || !sessionId || !transcriptPath) return none('no_transcript');

    const state = scanTranscript(agenticDir, sessionId, transcriptPath);
    if (!state) return none('no_transcript');
    if (!state.invocation) return none('no_invocation');
    const T = state.invocation.key;
    if (!T) return none(state.invocation.note || 'invocation_no_key');

    const keys = descriptionKeys(spawnDescription, T);
    if (keys.length && !keys.includes(T)) return none(`invocation_vetoed:${keys.join(',')}`);
    const expirer = state.expired_by.find((e) => !toolUseId || e.tool_use_id !== toolUseId);
    if (expirer) return none(`invocation_expired:${expirer.key}`);
    return { ticketId: T, source: 'invocation', note: null };
  } catch (_) {
    return none('resolver_error');
  }
}

module.exports = { resolveActiveTicket, invocationKeys, descriptionKeys };
