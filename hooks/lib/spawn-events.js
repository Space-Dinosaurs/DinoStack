/**
 * Purpose: DS-246. One resolver for where hook spawn telemetry lives, shared
 *          by its writers and readers. Hook spawn_start/spawn_complete rows
 *          are written to the PRIMARY checkout's `.agentic/events.jsonl`
 *          (resolveMainRepoRoot), so a SubagentStop whose cwd is a linked
 *          isolation worktree no longer lands in a worktree-local file that
 *          is discarded with the worktree. Readers whose own writes stay at
 *          the cwd root (session_total, capture-gap cursor) merge this
 *          session's primary-root spawn rows back in.
 *
 * Public API (CommonJS):
 *   spawnEventsPath(cwd) -> string
 *     `<resolveMainRepoRoot(cwd).root>/.agentic/events.jsonl`.
 *   readSessionEventsRaw(cwd, sessionId) -> string|null
 *     The cwd-root events.jsonl content plus, when the primary root differs,
 *     the primary root's `data.source === 'hook'` spawn_start/spawn_complete
 *     lines whose `data.session_uuid === sessionId`, stable-sorted by `ts`
 *     (a line with no readable `ts` keeps its predecessor's). null when
 *     neither file has content, matching the "absent file" contract of the
 *     cachedRaw parameters in stop-context.js and capture-gap.js.
 *   streamLines(filePath, startOffset, onLine, opts?) -> {endOffset, size}|null
 *     Reads filePath from startOffset to its size at call time in 1 MiB
 *     chunks, calling onLine(string) per newline-terminated line. With
 *     opts.flushTail a final unterminated line is also delivered. endOffset
 *     is the byte offset after the last delivered terminated line. null
 *     when the file cannot be stat'd or opened.
 *
 * Upstream deps: Node built-ins (fs, path); ./repo-root.js
 *                (resolveAgenticCwd, resolveMainRepoRoot).
 *
 * Downstream consumers: hooks/pre-tool-use-spawn-emit.js and
 *   hooks/subagent-stop-spawn-emit.js (spawnEventsPath; the stop hook also
 *   uses streamLines for transcript scans), hooks/lib/active-ticket.js
 *   (streamLines), hooks/stop-context.js and hooks/lib/capture-gap.js
 *   (readSessionEventsRaw).
 *
 * Failure modes: never throws. Unreadable files are treated as absent;
 *   malformed lines in the primary file are skipped; cwd-root lines are
 *   passed through verbatim.
 *
 * Performance: readSessionEventsRaw reads both files whole (the same cost
 *   the callers already paid for the cwd file) and JSON-parses only
 *   primary-root lines that contain the session id.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { resolveAgenticCwd, resolveMainRepoRoot } = require('./repo-root.js');

const CHUNK_BYTES = 1024 * 1024;
const TS_RE = /"ts"\s*:\s*"([^"]+)"/;

function spawnEventsPath(cwd) {
  return path.join(resolveMainRepoRoot(cwd).root, '.agentic', 'events.jsonl');
}

function readIfPresent(p) {
  try {
    return fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  } catch (_) {
    return null;
  }
}

function keyedLines(raw, filter) {
  const out = [];
  let lastKey = '';
  for (const line of raw.split('\n')) {
    if (!line.trim()) continue;
    if (filter && !filter(line)) continue;
    const m = TS_RE.exec(line);
    if (m) lastKey = m[1];
    out.push({ key: lastKey, line });
  }
  return out;
}

function readSessionEventsRaw(cwd, sessionId) {
  const cwdPath = path.join(resolveAgenticCwd(cwd), '.agentic', 'events.jsonl');
  const mainPath = spawnEventsPath(cwd);
  const cwdRaw = readIfPresent(cwdPath);
  if (mainPath === cwdPath || !sessionId) return cwdRaw;
  const mainRaw = readIfPresent(mainPath);
  if (!mainRaw) return cwdRaw;

  const extra = keyedLines(mainRaw, (line) => {
    if (line.indexOf(sessionId) === -1) return false;
    let obj;
    try { obj = JSON.parse(line); } catch (_) { return false; }
    const d = (obj && obj.data) || {};
    return d.source === 'hook'
      && (obj.event === 'spawn_start' || obj.event === 'spawn_complete')
      && d.session_uuid === sessionId;
  });
  if (extra.length === 0) return cwdRaw;

  const merged = keyedLines(cwdRaw || '').concat(extra);
  merged.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  return merged.map((e) => e.line).join('\n') + '\n';
}

function streamLines(filePath, startOffset, onLine, opts) {
  const flushTail = !!(opts && opts.flushTail);
  let fd;
  let size;
  try {
    size = fs.statSync(filePath).size;
    fd = fs.openSync(filePath, 'r');
  } catch (_) {
    return null;
  }
  let pos = Math.max(0, startOffset || 0);
  let endOffset = pos;
  let pending = Buffer.alloc(0);
  const buf = Buffer.alloc(CHUNK_BYTES);
  try {
    while (pos < size) {
      const n = fs.readSync(fd, buf, 0, Math.min(CHUNK_BYTES, size - pos), pos);
      if (n <= 0) break;
      pos += n;
      let data = pending.length ? Buffer.concat([pending, buf.subarray(0, n)]) : buf.subarray(0, n);
      let from = 0;
      let nl;
      while ((nl = data.indexOf(10, from)) !== -1) {
        onLine(data.toString('utf8', from, nl));
        endOffset += nl - from + 1;
        from = nl + 1;
      }
      pending = Buffer.from(data.subarray(from));
      data = null;
    }
  } finally {
    try { fs.closeSync(fd); } catch (_) { /* ignore */ }
  }
  if (flushTail && pending.length) onLine(pending.toString('utf8'));
  return { endOffset, size };
}

module.exports = { spawnEventsPath, readSessionEventsRaw, streamLines };
