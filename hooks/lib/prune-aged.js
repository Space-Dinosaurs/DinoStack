/**
 * Purpose: Best-effort age-based sweep for hooks that leave one small file
 *          per session in a state directory. Deletes entries whose name
 *          starts with a given prefix and whose mtime is older than a
 *          retention window, so per-session files do not accumulate forever.
 *
 * Public API (CommonJS):
 *   pruneAgedFiles(dir, prefix, retentionMs) -> undefined
 *
 * Upstream deps: Node built-ins (fs, path).
 *
 * Downstream consumers: hooks/lib/active-ticket.js (`.ticket-scan-*` caches),
 *   hooks/conductor-overreach-nudge.js (`_pruneAgedSentinels`, the
 *   `.conductor-overreach-fired-*` sentinels).
 *
 * Failure modes: never throws. An unreadable directory skips the sweep; a
 *   stat or unlink error on one entry skips only that entry.
 *
 * Performance: one readdirSync, plus a statSync (and for aged entries an
 *   unlinkSync) per prefix-matching entry.
 */

'use strict';

const fs = require('fs');
const path = require('path');

function pruneAgedFiles(dir, prefix, retentionMs) {
  try {
    const now = Date.now();
    for (const name of fs.readdirSync(dir)) {
      if (!name.startsWith(prefix)) continue;
      const entryPath = path.join(dir, name);
      try {
        if (now - fs.statSync(entryPath).mtimeMs > retentionMs) fs.unlinkSync(entryPath);
      } catch (_) { /* per-entry best-effort */ }
    }
  } catch (_) { /* directory unreadable: sweep next time */ }
}

module.exports = { pruneAgedFiles };
