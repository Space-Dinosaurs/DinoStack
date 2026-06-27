#!/usr/bin/env node
'use strict';

/**
 * Purpose: Skill-candidate detector. Clusters recurring manual-workflow friction
 *          signals (tool_failure_workaround events + learnings.md Domain entries)
 *          by domain_tag and surfaces candidate skill opportunities when a domain
 *          crosses the lifetime threshold. Two export paths: the Stop-hook write
 *          path (runSkillCandidateScan) and a read-only peek path
 *          (peekActiveCandidates) for the Layer-2 in-session PostToolUse nudge.
 *
 * Public API (CommonJS, all exported on module.exports):
 *   runSkillCandidateScan(cwd, sessionId) -> Promise<void>
 *     Stop-hook write path. Reads events.jsonl from the cursor, merges learnings.md
 *     domain distinct-date counts, updates tally, appends to skill-candidates.md
 *     when a domain first crosses CANDIDATE_THRESHOLD. Cursor advances ONLY after
 *     a successful tally write (self-healing on force-kill). Never throws.
 *   peekActiveCandidates(cwd) -> Array<{domain, count, suggestedArtifact, exampleNote, firstSeen, lastSeen}>
 *     Read-only path. Reads the tally only; never writes, never advances the cursor.
 *     Returns candidates with count >= CANDIDATE_THRESHOLD. Fail-open to [].
 *   CANDIDATE_THRESHOLD - number (3). Exported for test use.
 *
 * Upstream deps: Node built-ins only (fs, path, os). Reads:
 *   [cwd]/.agentic/events.jsonl (tool_failure_workaround events)
 *   [cwd]/.agentic/.skill-candidate-cursor (high-water mark, ISO8601)
 *   [cwd]/.agentic/.skill-candidate-tally.json (domain tally state)
 *   [cwd]/.agentic/learnings.md (secondary: Domain + Discovered date entries)
 * Writes (runSkillCandidateScan only):
 *   [cwd]/.agentic/.skill-candidate-tally.json (atomic tmp+rename)
 *   [cwd]/.agentic/.skill-candidate-cursor (ISO8601 high-water mark)
 *   [cwd]/.agentic/skill-candidates.md (appended when domain first crosses threshold)
 *
 * Downstream consumers:
 *   hooks/stop-context.js (Stop-hook write path; NOT YET WIRED - to be wired in a later unit)
 *   hooks/post-tool-use-capture-nudge.js (Layer-2 peek path; NOT YET WIRED - later unit)
 *
 * Failure modes: runSkillCandidateScan never throws - top-level try/catch absorbs
 *   all errors. peekActiveCandidates fails open to []. Tally writes use tmp+rename
 *   for atomicity; a crash between rename and cursor-advance leaves the cursor
 *   unadvanced, so the next run re-reads the same events (bounded double-count,
 *   acceptable at threshold 3). Concurrent sessions: last-writer-wins on the tally
 *   (accepted V1 limitation; no lock). Missing or corrupt tally is treated as empty
 *   state and rebuilt from the event scan.
 *
 * Performance: O(events since cursor) for the write path; single file read for the
 *   peek path. Typical: <10 ms per Stop-hook call on files up to a few thousand
 *   lines. No network, no subprocesses, no npm deps.
 *
 * V1 known limitation: clustering is exact-match on domain_tag. Fragmented tags
 *   (e.g. "adapter-interface" vs "adapter-interfaces") produce FALSE NEGATIVES
 *   (missed patterns), not false positives - the conservative, acceptable failure
 *   mode. No fuzzy/stemming match in V1.
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Lifetime count at which a domain is promoted to a skill candidate. */
const CANDIDATE_THRESHOLD = 3;

/**
 * Routing taxonomy: maps a domain tag's heuristic category to a suggested
 * skill artifact type. Applied in order; default is 'command'.
 *
 * Keywords matched against the domain_tag string (lowercase, substring).
 */
const ROUTING_RULES = [
  // lint-rule must be checked before named-agent: tags like 'ruff-format-check' contain
  // 'check' (named-agent keyword) AND 'ruff' (lint-rule keyword); lint-rule wins.
  { keywords: ['lint', 'format', 'eslint', 'ruff', 'mypy', 'typecheck', 'type-check'], artifact: 'lint-rule' },
  { keywords: ['review', 'check', 'audit', 'verify', 'inspect'], artifact: 'named-agent' },
  { keywords: ['prefer', 'style', 'tone', 'voice', 'preset', 'profile'], artifact: 'preset' },
];

/**
 * Derive the suggested skill artifact type from a domain tag.
 * @param {string} domainTag
 * @returns {'command'|'named-agent'|'preset'|'lint-rule'}
 */
function _routingArtifact(domainTag) {
  const lower = domainTag.toLowerCase();
  for (const rule of ROUTING_RULES) {
    if (rule.keywords.some((kw) => lower.includes(kw))) {
      return rule.artifact;
    }
  }
  return 'command';
}

// ---------------------------------------------------------------------------
// Tally file helpers
// ---------------------------------------------------------------------------

/**
 * Tally file path.
 * @param {string} cwd
 * @returns {string}
 */
function _tallyPath(cwd) {
  return path.join(cwd, '.agentic', '.skill-candidate-tally.json');
}

/**
 * Cursor file path.
 * @param {string} cwd
 * @returns {string}
 */
function _cursorPath(cwd) {
  return path.join(cwd, '.agentic', '.skill-candidate-cursor');
}

/**
 * Read and parse the tally file. Returns a default empty tally if missing or corrupt.
 * @param {string} cwd
 * @returns {{ version: number, lastCursorTs: string|null, candidates: Object }}
 */
function _readTally(cwd) {
  const defaultTally = { version: 1, lastCursorTs: null, candidates: {} };
  try {
    const raw = fs.readFileSync(_tallyPath(cwd), 'utf8');
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || !parsed.candidates) {
      return defaultTally;
    }
    return { version: 1, lastCursorTs: parsed.lastCursorTs || null, candidates: parsed.candidates || {} };
  } catch (_) {
    return defaultTally;
  }
}

/**
 * Write the tally atomically via tmp+rename.
 * @param {string} cwd
 * @param {object} tally
 * @throws if the write or rename fails (caller wraps in try/catch)
 */
function _writeTally(cwd, tally) {
  const dest = _tallyPath(cwd);
  // Ensure .agentic/ exists.
  const agenticDir = path.join(cwd, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });

  const tmpPath = `${dest}.tmp.${process.pid}.${Date.now()}`;
  fs.writeFileSync(tmpPath, JSON.stringify(tally, null, 2) + '\n', 'utf8');
  fs.renameSync(tmpPath, dest);
}

/**
 * Read the cursor high-water mark. Falls back to tally.lastCursorTs if the
 * cursor file is missing or corrupt (recovery path after force-kill).
 * @param {string} cwd
 * @param {string|null} tallyLastCursorTs - recovery fallback from tally
 * @returns {string} ISO8601 or '' (empty = no prior scan)
 */
function _readCursor(cwd, tallyLastCursorTs) {
  try {
    const raw = fs.readFileSync(_cursorPath(cwd), 'utf8').trim();
    if (raw) return raw;
  } catch (_) { /* silent */ }
  // Recovery: cursor file missing, fall back to tally value.
  return tallyLastCursorTs || '';
}

/**
 * Write the cursor high-water mark.
 * @param {string} cwd
 * @param {string} ts - ISO8601
 * @throws if the write fails
 */
function _writeCursor(cwd, ts) {
  fs.writeFileSync(_cursorPath(cwd), ts + '\n', 'utf8');
}

// ---------------------------------------------------------------------------
// Events scanning
// ---------------------------------------------------------------------------

/**
 * Scan events.jsonl for tool_failure_workaround events with data.session_uuid
 * set, occurring after cursorTs.
 *
 * Returns: { domainCounts: Map<string, {count, exampleNote, lastSeen}>, maxTs: string|null }
 *   domainCounts: per-domain aggregation for events in this scan window
 *   maxTs: the maximum ts seen in this scan (for cursor advance); null if no events
 *
 * @param {string} cwd
 * @param {string} cursorTs - ISO8601 or '' (empty = read from beginning)
 * @returns {{ domainCounts: Map<string,object>, maxTs: string|null }}
 */
function _scanEvents(cwd, cursorTs) {
  const domainCounts = new Map();
  let maxTs = null;

  let raw = '';
  try {
    raw = fs.readFileSync(path.join(cwd, '.agentic', 'events.jsonl'), 'utf8');
  } catch (_) {
    return { domainCounts, maxTs };
  }

  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try { obj = JSON.parse(trimmed); } catch (_) { continue; }
    if (!obj || typeof obj !== 'object') continue;

    // Only tool_failure_workaround events.
    if (obj.event !== 'tool_failure_workaround') continue;

    const data = obj.data || {};

    // session_uuid MUST be present (mirrors capture-gap.js exclusion rule).
    if (!data.session_uuid) continue;

    const ts = typeof obj.ts === 'string' ? obj.ts : '';

    // Cursor pagination: skip events at or before the high-water mark.
    if (cursorTs && ts && ts <= cursorTs) continue;

    const domainTag = (typeof data.domain_tag === 'string' && data.domain_tag.trim())
      ? data.domain_tag.trim()
      : null;
    if (!domainTag) continue;

    // Track max ts for cursor advance.
    if (ts && (!maxTs || ts > maxTs)) maxTs = ts;

    const existing = domainCounts.get(domainTag);
    if (existing) {
      existing.count += 1;
      if (ts && (!existing.lastSeen || ts > existing.lastSeen)) existing.lastSeen = ts;
      // Keep exampleNote from first occurrence; it's illustrative, not aggregated.
    } else {
      domainCounts.set(domainTag, {
        count: 1,
        exampleNote: typeof data.note === 'string' ? data.note : '',
        firstSeen: ts || new Date().toISOString(),
        lastSeen: ts || new Date().toISOString(),
      });
    }
  }

  return { domainCounts, maxTs };
}

// ---------------------------------------------------------------------------
// Learnings.md scanning
// ---------------------------------------------------------------------------

/**
 * Parse .agentic/learnings.md and return a Map<domain, Set<dateString>> of
 * distinct Discovered: dates per **Domain:** value.
 *
 * Format expected (from the learnings schema):
 *   **Domain:** <domain-tag>
 *   **Discovered:** <YYYY-MM-DD>
 *
 * Both fields may appear anywhere in a learning entry block. We scan all lines
 * and pair the most recent **Domain:** seen with any subsequent **Discovered:**
 * before the next **Domain:**.
 *
 * @param {string} cwd
 * @returns {Map<string, Set<string>>} domain -> set of discovered date strings
 */
function _parseLearningsDomains(cwd) {
  const result = new Map();
  let raw = '';
  try {
    raw = fs.readFileSync(path.join(cwd, '.agentic', 'learnings.md'), 'utf8');
  } catch (_) {
    return result;
  }

  let currentDomain = null;
  for (const line of raw.split('\n')) {
    // Match **Domain:** <value>
    const domainMatch = line.match(/^\*\*Domain:\*\*\s*(.+)/);
    if (domainMatch) {
      currentDomain = domainMatch[1].trim();
      if (!result.has(currentDomain)) {
        result.set(currentDomain, new Set());
      }
      continue;
    }

    // Match **Discovered:** <YYYY-MM-DD>
    if (currentDomain) {
      const discoveredMatch = line.match(/^\*\*Discovered:\*\*\s*(\d{4}-\d{2}-\d{2})/);
      if (discoveredMatch) {
        result.get(currentDomain).add(discoveredMatch[1]);
      }
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// skill-candidates.md writer
// ---------------------------------------------------------------------------

/**
 * Append a new candidate entry to .agentic/skill-candidates.md.
 * Creates the file if absent; appends otherwise.
 *
 * @param {string} cwd
 * @param {string} domain
 * @param {object} entry - tally candidate entry
 */
function _appendCandidate(cwd, domain, entry) {
  const filePath = path.join(cwd, '.agentic', 'skill-candidates.md');
  const dateStr = new Date().toISOString().slice(0, 10);

  const block = [
    ``,
    `## ${domain}`,
    ``,
    `- **Suggested artifact:** ${entry.suggestedArtifact}`,
    `- **Lifetime count:** ${entry.count}`,
    `- **First seen:** ${entry.firstSeen || dateStr}`,
    `- **Last seen:** ${entry.lastSeen || dateStr}`,
    `- **Surfaced:** ${entry.surfacedAt}`,
    entry.exampleNote ? `- **Example:** ${entry.exampleNote}` : null,
    ``,
  ].filter((l) => l !== null).join('\n');

  // Create file with header if absent.
  if (!fs.existsSync(filePath)) {
    fs.writeFileSync(
      filePath,
      `# Skill Candidates\n\nDetected recurring friction patterns that may warrant a new skill.\nCall to action: invoke the \`skill-creator\` skill to convert a candidate into a reusable skill.\n`,
      'utf8'
    );
  }

  fs.appendFileSync(filePath, block, 'utf8');
}

// ---------------------------------------------------------------------------
// Public: runSkillCandidateScan
// ---------------------------------------------------------------------------

/**
 * Stop-hook write path. Reads events.jsonl from the cursor (or tally fallback),
 * merges learnings.md distinct-date counts, updates the tally, appends to
 * skill-candidates.md when a domain first crosses CANDIDATE_THRESHOLD.
 *
 * Cursor advances ONLY after a successful tally write (self-healing on force-kill:
 * a crashed run leaves the cursor unadvanced, so the next run re-reads the same
 * events without losing increments).
 *
 * Never throws. All errors are absorbed by the top-level try/catch.
 *
 * @param {string} cwd - Absolute project root path.
 * @param {string|null} sessionId - Current session uuid (for logging context, not filtering here).
 * @returns {Promise<void>}
 */
async function runSkillCandidateScan(cwd, sessionId) {
  try {
    // 1. Read current tally (empty state if missing/corrupt).
    const tally = _readTally(cwd);

    // 2. Read cursor; fall back to tally.lastCursorTs if cursor file is gone.
    const cursorTs = _readCursor(cwd, tally.lastCursorTs);

    // 3. Scan events.jsonl for tool_failure_workaround events after cursor.
    const { domainCounts: eventsMap, maxTs: eventsMaxTs } = _scanEvents(cwd, cursorTs);

    // 4. Scan learnings.md for distinct Discovered: dates per **Domain:**.
    const learningsMap = _parseLearningsDomains(cwd);

    // 5. Determine the union of all domains to process.
    const allDomains = new Set([...eventsMap.keys(), ...learningsMap.keys()]);
    if (allDomains.size === 0 && !eventsMaxTs) {
      // Nothing to process; do not advance cursor.
      return;
    }

    // 6. Merge into tally candidates.
    const now = new Date().toISOString();
    let tallyDirty = false;
    const newlyPromoted = []; // domains that first crossed threshold this scan

    for (const domain of allDomains) {
      const evInfo = eventsMap.get(domain);
      const learnDates = learningsMap.get(domain);

      // Events contribution this scan.
      const evDelta = evInfo ? evInfo.count : 0;

      // Learnings contribution: only NEW distinct Discovered: dates not yet counted.
      // learnDatesApplied is persisted in the tally so re-scans of unchanged
      // learnings.md add 0 (fixes double-count on every Stop-hook call).
      let learnDelta = 0;
      let newLearnDates = null;
      if (learnDates && learnDates.size > 0) {
        const existing = tally.candidates[domain] || null;
        const appliedSet = new Set(existing && Array.isArray(existing.learnDatesApplied)
          ? existing.learnDatesApplied
          : []);
        newLearnDates = new Set([...learnDates].filter((d) => !appliedSet.has(d)));
        learnDelta = newLearnDates.size;
      }

      const delta = evDelta + learnDelta;
      if (delta === 0) continue;

      const existing = tally.candidates[domain] || null;
      const wasBelow = !existing || existing.count < CANDIDATE_THRESHOLD;
      const prevCount = existing ? existing.count : 0;
      const newCount = prevCount + delta;

      // Determine firstSeen (earliest timestamp seen for this domain).
      let firstSeen = existing ? existing.firstSeen : null;
      if (evInfo && evInfo.firstSeen) {
        firstSeen = firstSeen
          ? (evInfo.firstSeen < firstSeen ? evInfo.firstSeen : firstSeen)
          : evInfo.firstSeen;
      }
      if (!firstSeen) firstSeen = now;

      // Determine lastSeen (most recent).
      let lastSeen = existing ? existing.lastSeen : null;
      if (evInfo && evInfo.lastSeen) {
        lastSeen = lastSeen
          ? (evInfo.lastSeen > lastSeen ? evInfo.lastSeen : lastSeen)
          : evInfo.lastSeen;
      }
      if (!lastSeen) lastSeen = now;

      // ExampleNote: prefer existing (stable); use evInfo.exampleNote if no prior.
      const exampleNote = (existing && existing.exampleNote)
        ? existing.exampleNote
        : (evInfo ? evInfo.exampleNote : '');

      // Derive suggested artifact from domain tag.
      const suggestedArtifact = (existing && existing.suggestedArtifact)
        ? existing.suggestedArtifact
        : _routingArtifact(domain);

      // Track whether we are newly crossing the threshold.
      const nowAbove = newCount >= CANDIDATE_THRESHOLD;
      const surfacedAt = (existing && existing.surfacedAt) || null;
      const justCrossed = wasBelow && nowAbove && !surfacedAt;

      // Compute the updated learnDatesApplied set: union of previously applied
      // dates with any new ones added this scan. Persisted atomically with count
      // so a crashed write leaves neither count nor applied-set advanced.
      const prevApplied = existing && Array.isArray(existing.learnDatesApplied)
        ? existing.learnDatesApplied
        : [];
      const updatedApplied = newLearnDates && newLearnDates.size > 0
        ? [...new Set([...prevApplied, ...newLearnDates])]
        : prevApplied;

      tally.candidates[domain] = {
        count: newCount,
        exampleNote,
        firstSeen,
        lastSeen,
        suggestedArtifact,
        surfacedAt: justCrossed ? now : surfacedAt,
        learnDatesApplied: updatedApplied,
      };

      if (justCrossed) {
        newlyPromoted.push(domain);
      }

      tallyDirty = true;
    }

    // Update lastCursorTs in the tally (used as recovery fallback).
    if (eventsMaxTs) {
      tally.lastCursorTs = eventsMaxTs;
      tallyDirty = true;
    }

    if (!tallyDirty) return;

    // 7. Write tally atomically. Cursor advances ONLY after this succeeds.
    _writeTally(cwd, tally);

    // 8. Append to skill-candidates.md for newly promoted domains.
    for (const domain of newlyPromoted) {
      try {
        _appendCandidate(cwd, domain, tally.candidates[domain]);
      } catch (_) { /* soft-fail: candidate file write error does not block cursor advance */ }
    }

    // 9. Advance the cursor ONLY after a successful tally write.
    // This is the self-healing guarantee: a force-kill before this point leaves
    // the cursor unadvanced, so the next run re-reads those events without losing
    // any increment.
    if (eventsMaxTs) {
      try { _writeCursor(cwd, eventsMaxTs); } catch (_) { /* soft-fail */ }
    }
  } catch (_) {
    // Top-level safety net: any unexpected error must not crash the Stop hook.
  }
}

// ---------------------------------------------------------------------------
// Public: peekActiveCandidates
// ---------------------------------------------------------------------------

/**
 * Read-only path for Layer-2 in-session nudge. Reads the tally only; NEVER
 * writes, NEVER advances the cursor.
 *
 * @param {string} cwd - Absolute project root path.
 * @returns {Array<{domain: string, count: number, suggestedArtifact: string, exampleNote: string, firstSeen: string, lastSeen: string, surfacedAt: string|null}>}
 */
function peekActiveCandidates(cwd) {
  try {
    const tally = _readTally(cwd);
    const result = [];
    for (const [domain, entry] of Object.entries(tally.candidates)) {
      if (entry.count >= CANDIDATE_THRESHOLD) {
        result.push({
          domain,
          count: entry.count,
          suggestedArtifact: entry.suggestedArtifact || 'command',
          exampleNote: entry.exampleNote || '',
          firstSeen: entry.firstSeen || '',
          lastSeen: entry.lastSeen || '',
          surfacedAt: entry.surfacedAt || null,
        });
      }
    }
    return result;
  } catch (_) {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

module.exports = {
  runSkillCandidateScan,
  peekActiveCandidates,
  CANDIDATE_THRESHOLD,
  // Internal helpers exported for testing only.
  _routingArtifact,
  _readTally,
  _writeTally,
  _readCursor,
  _writeCursor,
  _scanEvents,
  _parseLearningsDomains,
  _appendCandidate,
};
