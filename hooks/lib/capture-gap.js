#!/usr/bin/env node

/**
 * Purpose: Shared capture-gap detector. Determines whether the current session
 *          has a learning-worthy event (debugger/investigator root cause,
 *          skeptic major/critical resolved, or tool-failure workaround) with no
 *          learning captured yet, so callers can surface a capture nudge. Pure
 *          read-only detection: reads .agentic/events.jsonl and
 *          .agentic/learnings.md, runs one git diff subprocess for guardrail
 *          suppression, and returns a result object. Extracted verbatim from
 *          hooks/stop-context.js (detectCaptureGap, GUARDRAIL_PATTERNS,
 *          _tokenize) so the Stop-hook backstop and the in-session
 *          PostToolUse(Task) nudge share one implementation.
 *
 * Public API (CommonJS, all exported on module.exports):
 *   detectCaptureGap(cwd, sessionId[, cachedEventsRaw])
 *     -> { shouldNudge: boolean, residualOnly: boolean, lastEventTs: string|null }
 *     cachedEventsRaw: pre-read events.jsonl string (null=absent/unreadable,
 *     undefined=back-compat file read). See param JSDoc on detectCaptureGap.
 *   GUARDRAIL_PATTERNS - RegExp[] of guardrail-file basename patterns.
 *   _tokenize(str) -> string[] - domain-proximity tokenizer.
 *
 * Upstream deps: Node built-ins only (fs, path, child_process). Reads
 *                [cwd]/.agentic/events.jsonl (learning-worthy events),
 *                [cwd]/.agentic/learnings.md (today-dated LRN/KNW suppression),
 *                [cwd]/.agentic/.capture-gap-last-sweep (pagination cursor, READ
 *                only - the cursor WRITE stays in stop-context.js's
 *                appendCaptureGapNoticeToContextMd, the sole cursor writer).
 *                Runs `git diff --name-only origin/HEAD..HEAD` (primary) /
 *                `git diff --name-only HEAD~1 HEAD` (fallback) for guardrail
 *                suppression. No npm dependencies. No writes.
 *
 * Downstream consumers: hooks/stop-context.js (Stop-hook backstop that appends a
 *                        nudge to context.md for the NEXT session) and
 *                        hooks/post-tool-use-capture-nudge.js (PostToolUse(Task)
 *                        hook that injects an in-session additionalContext nudge).
 *
 * Failure modes: Never throws. All errors are absorbed and return
 *                { shouldNudge: false, residualOnly: false, lastEventTs: null }.
 *                A missing events.jsonl, a non-git cwd, a missing learnings.md,
 *                or a malformed event line are all tolerated silently. The git
 *                diff subprocess soft-fails (no suppression applied) on any
 *                error. Pure read-only: no on-disk state is mutated, so the
 *                function is idempotent and safe to call on every spawn.
 *
 * Performance: ~5-20 ms typical; at most one git diff subprocess call (5 s
 *              timeout, soft-fail) and two synchronous file reads. The git
 *              subprocess runs ONLY once a learning-worthy event with no captured
 *              learning is found (conditions (a) and (b) hold), so the common
 *              no-event case costs a single file read and returns early.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

// ---------------------------------------------------------------------------
// Capture-gap detector
// ---------------------------------------------------------------------------

/**
 * Guardrail glob patterns used to detect test / lint / schema files added
 * during the session. Matched against the basename of each changed path.
 * @type {RegExp[]}
 */
const GUARDRAIL_PATTERNS = [
  /test/i,
  /spec/i,
  /\.eslintrc/i,
  /\.schema\./i,
  /ruff\.toml/i,
  /mypy\.ini/i,
];

/**
 * Normalize a string into tokens for domain-proximity matching.
 * Splits on '/', '.', '-', '_' and lowercases; filters tokens shorter than 4
 * chars (too generic to carry domain signal).
 *
 * @param {string} str
 * @returns {string[]}
 */
function _tokenize(str) {
  return str.toLowerCase().split(/[\/.\-_]/).filter((t) => t.length >= 4);
}

/**
 * Detect whether this session has learning-worthy events with no learnings
 * captured. Pure function: reads files, runs one git subprocess, returns a
 * result object. Never throws - all errors are absorbed and return
 * { shouldNudge: false, residualOnly: false, lastEventTs: null }.
 *
 * Three conditions must ALL hold for shouldNudge === true:
 *   (a) At least one learning-worthy event this session (debugger/investigator
 *       spawn_complete, skeptic spawn_complete with major/critical resolved, or
 *       tool_failure_workaround). Events without session_uuid are DELIBERATELY
 *       EXCLUDED (inverse of scanSessionAggregate which includes absent uuids
 *       for back-compat). This exclusion prevents false nags from legacy event
 *       lines whose session cannot be determined. Self-heals after one post-upgrade
 *       session where emits carry session_uuid.
 *   (b) No today-dated [LRN- or [KNW- entries in .agentic/learnings.md.
 *   (c) No domain-proximate guardrail added this session (suppression). The
 *       suppressor checks git diff --name-only origin/HEAD..HEAD (all session
 *       commits since branch diverged from upstream - primary) falling back to
 *       git diff --name-only HEAD~1 HEAD (single-commit fallback when no
 *       upstream ref exists). If guardrails were added but none are domain-
 *       proximate with the event domain tokens, residualOnly is set true and
 *       the nudge still fires with residual-WHY wording.
 *
 * lastEventTs is the ts of the most recent learning-worthy event encountered in
 * the scan, or null when no worthy event was found. Callers use it as the dedup
 * key for the in-session nudge ((session_id, lastEventTs) tuple) so a single
 * worthy event nudges at most once per session.
 *
 * @param {string} cwd - Project root (absolute, already validated by caller).
 * @param {string|null} sessionId - Stop / PostToolUse payload session_id (harness uuid).
 * @param {string|null} [cachedEventsRaw] - Pre-read events.jsonl contents from
 *   run()'s single read. When provided (non-undefined), the file is NOT re-read;
 *   null means the file was absent or unreadable at read time (treated same as
 *   missing file: function returns no-nudge immediately). When omitted (undefined),
 *   falls back to reading eventsPath directly for back-compat with callers that
 *   do not thread the cache (e.g. the PostToolUse hook).
 * @returns {{ shouldNudge: boolean, residualOnly: boolean, lastEventTs: string|null }}
 */
function detectCaptureGap(cwd, sessionId, cachedEventsRaw) {
  try {
    if (!sessionId) return { shouldNudge: false, residualOnly: false, lastEventTs: null };

    // --- (a) Scan events.jsonl for learning-worthy events this session ---
    const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');

    // Pagination: read only lines after the last sweep cursor.
    let lastSweepTs = '';
    try {
      const cursorPath = path.join(cwd, '.agentic', '.capture-gap-last-sweep');
      if (fs.existsSync(cursorPath)) {
        lastSweepTs = fs.readFileSync(cursorPath, 'utf8').trim();
      }
    } catch (_) { /* silent */ }

    let rawEvents = '';
    if (cachedEventsRaw !== undefined) {
      // Caller threaded the cached read: null means absent/unreadable.
      if (cachedEventsRaw === null) return { shouldNudge: false, residualOnly: false, lastEventTs: null };
      rawEvents = cachedEventsRaw;
    } else {
      // Back-compat: no cache provided, read the file directly.
      try {
        if (fs.existsSync(eventsPath)) {
          rawEvents = fs.readFileSync(eventsPath, 'utf8');
        }
      } catch (_) { return { shouldNudge: false, residualOnly: false, lastEventTs: null }; }
    }

    const eventLines = rawEvents.split('\n');
    // On cold start (no cursor), cap to the last 100 lines.
    const linesToScan = lastSweepTs
      ? eventLines
      : eventLines.slice(-100);

    const LEARNING_AGENTS = new Set(['debugger', 'investigator']);
    let hasLearningWorthyEvent = false;
    let lastWorthyTs = null;
    const eventDomainTokens = new Set();

    for (const line of linesToScan) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let obj;
      try { obj = JSON.parse(trimmed); } catch (_) { continue; }

      const data = (obj && obj.data) || {};

      // DELIBERATE: lines without data.session_uuid are EXCLUDED here.
      // This is the inverse of scanSessionAggregate (which includes absent uuids
      // for back-compat). The backstop must not nag on legacy event lines from
      // prior sessions that lack session attribution - that would cause false
      // positives on every session until the file rotates. scanSessionAggregate
      // keeps absent=include for back-compat; only this backstop uses absent=exclude.
      if (!data.session_uuid || data.session_uuid !== sessionId) continue;

      // Pagination: skip lines at or before the last sweep timestamp.
      if (lastSweepTs && obj.ts && obj.ts <= lastSweepTs) continue;

      const ev = obj.event;
      const agentName = (obj.agent || '').toLowerCase();

      let worthy = false;
      if (ev === 'tool_failure_workaround') {
        worthy = true;
      } else if (ev === 'spawn_complete') {
        if (LEARNING_AGENTS.has(agentName)) {
          worthy = true;
        } else if (agentName === 'skeptic') {
          const fc = data.findings_count || {};
          if ((Number(fc.critical) || 0) > 0 || (Number(fc.major) || 0) > 0) {
            if (data.signed_off) worthy = true;
          }
        }
        // NOTE: skeptic-with-findings trigger stays degraded for hook-emitted
        // spawn_start events because hook payloads carry no findings_count or
        // signed_off data (harness ceiling). Only spawn_complete-based skeptic
        // events can satisfy the findings/sign-off criteria above.
      } else if (ev === 'spawn_start' && data.source === 'hook') {
        // Hook-emitted spawn_start revives the debugger/investigator capture-gap
        // trigger in ad-hoc sessions where no conductor spawn_complete is emitted.
        // Skeptic findings trigger remains degraded (no findings_count/signed_off
        // available from hook payloads).
        if (LEARNING_AGENTS.has(agentName)) {
          worthy = true;
        }
      }

      if (worthy) {
        hasLearningWorthyEvent = true;
        // Track the ts of the most recent learning-worthy event for dedup.
        // Lines are scanned in file order (oldest -> newest), so the last
        // assignment wins. Guard against absent ts.
        if (typeof obj.ts === 'string' && obj.ts) {
          lastWorthyTs = obj.ts;
        }
        // Collect domain tokens from domain_tag and tool references
        for (const src of [data.domain_tag, data.tool]) {
          if (typeof src === 'string' && src) {
            for (const tok of _tokenize(src)) eventDomainTokens.add(tok);
          }
        }
      }
    }

    if (!hasLearningWorthyEvent) return { shouldNudge: false, residualOnly: false, lastEventTs: null };

    // --- (b) Check .agentic/learnings.md for today-dated entries ---
    const todayStr = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
    try {
      const learningsPath = path.join(cwd, '.agentic', 'learnings.md');
      if (fs.existsSync(learningsPath)) {
        const learningsRaw = fs.readFileSync(learningsPath, 'utf8');
        // Match [LRN-YYYYMMDD-XXX] or [KNW-YYYYMMDD-XXX] with today's date, OR
        // a "Discovered: YYYY-MM-DD" line dated today.
        const dateCompact = todayStr.replace(/-/g, '');
        const hasToday =
          learningsRaw.includes(`[LRN-${dateCompact}`) ||
          learningsRaw.includes(`[KNW-${dateCompact}`) ||
          learningsRaw.includes(`Discovered: ${todayStr}`);
        if (hasToday) return { shouldNudge: false, residualOnly: false, lastEventTs: lastWorthyTs };
      }
    } catch (_) { /* silent - absent learnings.md means no learning captured */ }

    // --- (c) Guardrail suppression ---
    // Collect names of guardrail files added this session via git diff.
    // Primary: git diff --name-only origin/HEAD..HEAD  (all commits since branch diverged)
    // Fallback: git diff --name-only HEAD~1 HEAD       (last commit only; used when no upstream)
    let changedPaths = [];
    try {
      let diffOutput = '';
      try {
        diffOutput = execSync(
          'git diff --name-only origin/HEAD..HEAD',
          { cwd, timeout: 5000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }
        );
      } catch (_primaryErr) {
        // No upstream ref - fall back to last commit only.
        try {
          diffOutput = execSync(
            'git diff --name-only HEAD~1 HEAD',
            { cwd, timeout: 5000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }
          );
        } catch (_) { /* no commits yet or non-git dir; diffOutput stays '' */ }
      }
      changedPaths = diffOutput.split('\n').map((p) => p.trim()).filter(Boolean);
    } catch (_) { /* soft-fail: no suppression applied */ }

    const addedGuardrailPaths = changedPaths.filter((p) => {
      const base = path.basename(p);
      if (GUARDRAIL_PATTERNS.some((re) => re.test(base))) return true;
      // Also match directory segments: tests/, evals/, spec/
      return /(?:^|\/)(?:tests|evals|spec)\//i.test(p + '/');
    });

    if (addedGuardrailPaths.length === 0) {
      // No guardrails added - fire standard nudge.
      return { shouldNudge: true, residualOnly: false, lastEventTs: lastWorthyTs };
    }

    // Check domain proximity: does any guardrail path share a >=4-char token
    // with any event domain token?
    let domainProximate = false;
    if (eventDomainTokens.size > 0) {
      for (const gp of addedGuardrailPaths) {
        const gpTokens = _tokenize(gp);
        if (gpTokens.some((t) => eventDomainTokens.has(t))) {
          domainProximate = true;
          break;
        }
      }
    }

    if (domainProximate) {
      // Domain-proximate guardrail added - suppress nudge entirely.
      return { shouldNudge: false, residualOnly: false, lastEventTs: lastWorthyTs };
    }

    // Guardrails added but none domain-proximate - fire with residual-WHY text.
    return { shouldNudge: true, residualOnly: true, lastEventTs: lastWorthyTs };
  } catch (_) {
    // Top-level safety net: any unexpected error -> no nudge (never blocks exit).
    return { shouldNudge: false, residualOnly: false, lastEventTs: null };
  }
}

module.exports = {
  detectCaptureGap,
  GUARDRAIL_PATTERNS,
  _tokenize,
};
