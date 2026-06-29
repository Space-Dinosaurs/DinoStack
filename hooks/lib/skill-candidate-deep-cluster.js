#!/usr/bin/env node
'use strict';

/**
 * Purpose: Wrap-time skill-candidate deep-cluster helper. Merges LLM-extracted
 *          friction-domain clusters from a wrap session into the shared
 *          skill-candidate tally. Complements the Stop-hook events path without
 *          replacing it: both paths write the same tally; each deduplicates via
 *          its own applied-set (`learnDatesApplied` for the events path,
 *          `wrapSessionsApplied` for this path). A domain is surfaced to
 *          skill-candidates.md at most once regardless of which path crosses
 *          the threshold (shared `surfacedAt` guard). Per-session dedup: a
 *          session that calls this helper more than once for the same domain
 *          increments the count exactly once.
 *
 * Public API (CommonJS):
 *   mergeClusterResults(cwd, sessionId, clusters) -> void
 *     Library entry point. Merges an array of LLM-extracted cluster entries
 *     into the tally and appends to skill-candidates.md on first threshold
 *     crossing. Soft-fail: never throws. Bad input / corrupt tally returns
 *     without writing.
 *     clusters: Array<{ domain: string, exampleNote: string, suggestedArtifact?: string }>
 *
 * CLI entrypoint (see require.main guard at bottom):
 *   node hooks/lib/skill-candidate-deep-cluster.js <cwd> <session_id> <clusters-json-path>
 *   Reads the clusters array from the JSON file at <clusters-json-path>,
 *   calls mergeClusterResults(cwd, sessionId, clusters), always exits 0.
 *   Missing/empty <session_id> or unreadable/[] clusters file -> clean no-op.
 *
 * Upstream deps: Node built-ins (fs, path). Reuses internal helpers from
 *   hooks/lib/skill-candidate-detector.js (_readTally, _writeTally,
 *   _appendCandidate, _routingArtifact, CANDIDATE_THRESHOLD).
 * Writes (via library):
 *   [cwd]/.agentic/.skill-candidate-tally.json (atomic tmp+rename via _writeTally)
 *   [cwd]/.agentic/skill-candidates.md (appended on first threshold crossing)
 *
 * Downstream consumers:
 *   /wrap Part D (content/commands/wrap.md - later unit)
 *   /implement-ticket Phase 11b conductor post-return (content/commands/implement-ticket.md - later unit)
 *
 * Failure modes: Never throws. Any write error is silently swallowed.
 *   Concurrent session (Stop hook + wrap): last-writer-wins on the tally
 *   (atomic tmp+rename guarantees no corruption; a count may be lost - acceptable
 *   at threshold 3, inherited V1 limitation). Corrupt or missing tally is treated
 *   as empty state and rebuilt from clusters only for this session.
 *
 * Performance: O(clusters * 1) file reads+writes per call. Single tally read,
 *   single atomic write. No network, no subprocesses, no npm deps.
 */

const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------------------
// Reuse detector internals (write-path helpers + taxonomy).
// ---------------------------------------------------------------------------

const detectorPath = path.join(__dirname, 'skill-candidate-detector.js');
const {
  _readTally,
  _writeTally,
  _appendCandidate,
  _routingArtifact,
  CANDIDATE_THRESHOLD,
} = require(detectorPath);

// ---------------------------------------------------------------------------
// Valid artifact types from the routing taxonomy.
// ---------------------------------------------------------------------------

const VALID_ARTIFACTS = new Set(['command', 'named-agent', 'preset', 'lint-rule']);

/**
 * Validate a suggestedArtifact hint from the LLM.
 * Falls back to the routing taxonomy result, then to 'command'.
 *
 * @param {string|undefined} llmHint - artifact hint from the LLM (may be absent/invalid)
 * @param {string} domain - domain tag for taxonomy fallback
 * @returns {'command'|'named-agent'|'preset'|'lint-rule'}
 */
function _resolveArtifact(llmHint, domain) {
  if (llmHint && VALID_ARTIFACTS.has(llmHint)) {
    return llmHint;
  }
  return _routingArtifact(domain);
}

// ---------------------------------------------------------------------------
// Public: mergeClusterResults
// ---------------------------------------------------------------------------

/**
 * Merge LLM-extracted friction-domain clusters from one wrap session into the
 * shared skill-candidate tally.
 *
 * For each cluster:
 * - If sessionId is already in wrapSessionsApplied for that domain -> skip (dedup).
 * - Else: increment count by 1, append sessionId to wrapSessionsApplied, set
 *   firstSeen (if new) and lastSeen = now, resolve suggestedArtifact.
 * - When a domain first crosses CANDIDATE_THRESHOLD and has no surfacedAt, append
 *   to skill-candidates.md (append-once, dismiss-safe: no revive if surfacedAt set).
 *
 * The LLM does NOT supply count/firstSeen/lastSeen - this helper owns them.
 * Soft-fail: any error is swallowed; no throw.
 *
 * @param {string} cwd - Absolute project root path.
 * @param {string} sessionId - Current wrap session ID.
 * @param {Array<{domain: string, exampleNote: string, suggestedArtifact?: string}>} clusters
 * @returns {void}
 */
function mergeClusterResults(cwd, sessionId, clusters) {
  try {
    // Input validation.
    if (!cwd || typeof cwd !== 'string') return;
    if (!sessionId || typeof sessionId !== 'string' || !sessionId.trim()) return;
    if (!Array.isArray(clusters) || clusters.length === 0) return;

    const sid = sessionId.trim();

    // Read current tally (empty state if missing/corrupt).
    const tally = _readTally(cwd);

    const now = new Date().toISOString();
    let tallyDirty = false;
    const newlyPromoted = []; // domains that first cross threshold this merge

    for (const cluster of clusters) {
      // Validate cluster shape.
      if (!cluster || typeof cluster !== 'object') continue;
      const domain = typeof cluster.domain === 'string' ? cluster.domain.trim() : '';
      if (!domain) continue;
      const exampleNote = typeof cluster.exampleNote === 'string' ? cluster.exampleNote : '';

      const existing = tally.candidates[domain] || null;

      // Per-session dedup: if this session already contributed to this domain, skip.
      const appliedSessions = existing && Array.isArray(existing.wrapSessionsApplied)
        ? existing.wrapSessionsApplied
        : [];
      if (appliedSessions.includes(sid)) continue;

      // Threshold state before this increment.
      const prevCount = existing ? (existing.count || 0) : 0;
      const wasBelow = prevCount < CANDIDATE_THRESHOLD;

      // Increment.
      const newCount = prevCount + 1;
      const nowAbove = newCount >= CANDIDATE_THRESHOLD;

      // firstSeen: only set when the domain is new.
      const firstSeen = (existing && existing.firstSeen) ? existing.firstSeen : now;

      // lastSeen: always now (most recent wrap).
      const lastSeen = now;

      // exampleNote: prefer existing (stable across sessions); use cluster note if no prior.
      const resolvedNote = (existing && existing.exampleNote)
        ? existing.exampleNote
        : exampleNote;

      // suggestedArtifact: prefer existing (stable); resolve for new domains.
      const suggestedArtifact = (existing && existing.suggestedArtifact)
        ? existing.suggestedArtifact
        : _resolveArtifact(cluster.suggestedArtifact, domain);

      // surfacedAt: one-shot append-once guard.
      // justCrossed fires ONLY when transitioning from below to at/above for the first time.
      // If surfacedAt is already set (human may have dismissed or events path surfaced it),
      // we do NOT re-append - the guard holds regardless of how surfacedAt was set.
      const surfacedAt = (existing && existing.surfacedAt) || null;
      const justCrossed = wasBelow && nowAbove && !surfacedAt;

      // Preserve learnDatesApplied from the events path (never touch it here).
      const learnDatesApplied = (existing && Array.isArray(existing.learnDatesApplied))
        ? existing.learnDatesApplied
        : [];

      // Update wrapSessionsApplied.
      const updatedSessions = [...appliedSessions, sid];

      tally.candidates[domain] = {
        count: newCount,
        exampleNote: resolvedNote,
        firstSeen,
        lastSeen,
        suggestedArtifact,
        surfacedAt: justCrossed ? now : surfacedAt,
        learnDatesApplied,
        wrapSessionsApplied: updatedSessions,
      };

      if (justCrossed) {
        newlyPromoted.push(domain);
      }

      tallyDirty = true;
    }

    if (!tallyDirty) return;

    // Write tally atomically.
    _writeTally(cwd, tally);

    // Append to skill-candidates.md for newly promoted domains.
    for (const domain of newlyPromoted) {
      try {
        _appendCandidate(cwd, domain, tally.candidates[domain]);
      } catch (_) {
        // soft-fail: candidate file write error does not block the merge
      }
    }
  } catch (_) {
    // Top-level safety net: never throw.
  }
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

module.exports = { mergeClusterResults };

// ---------------------------------------------------------------------------
// CLI entrypoint
// ---------------------------------------------------------------------------

if (require.main === module) {
  // node skill-candidate-deep-cluster.js <cwd> <session_id> <clusters-json-path>
  // Always exits 0 (soft-fail).
  const [, , cwd, sessionId, clustersJsonPath] = process.argv;

  if (!cwd || !sessionId || !sessionId.trim() || !clustersJsonPath) {
    process.exit(0);
  }

  let clusters;
  try {
    const raw = fs.readFileSync(clustersJsonPath, 'utf8');
    clusters = JSON.parse(raw);
  } catch (_) {
    process.exit(0);
  }

  if (!Array.isArray(clusters) || clusters.length === 0) {
    process.exit(0);
  }

  mergeClusterResults(cwd, sessionId, clusters);
  process.exit(0);
}
