#!/usr/bin/env node

/**
 * Purpose: Claude Code SubagentStop hook. Fires deterministically when a
 *          subagent (Task/Agent spawn) actually finishes running - unlike
 *          PostToolUse(Task/Agent), which fires at spawn LAUNCH time, not
 *          completion (see hooks/pre-tool-use-spawn-emit.js header note).
 *          Prior to DS-160, `spawn_complete` was emitted ONLY via prose
 *          instructions telling the conductor LLM to run `bin/ds-emit
 *          spawn_complete ...` inline after each Agent tool call returns
 *          (content/commands/ds-implement-ticket.md). That mechanism is an
 *          LLM-semantic event with no deterministic trigger and has been
 *          observed to fire on well under 1% of real spawns (6 of ~1,640
 *          spawn_start records in this repo's own events.jsonl, none after
 *          2026-07-10). This hook closes that gap: it appends a
 *          `spawn_complete` event to [cwd]/.agentic/events.jsonl on every
 *          subagent completion, with `data.source:"hook"` (same convention
 *          as hooks/pre-tool-use-spawn-emit.js's hook-emitted spawn_start),
 *          independent of whether the conductor also emits its own richer
 *          conductor-side spawn_complete (e.g. the Skeptic calibration
 *          variant in ds-implement-ticket.md Phase 6/7/10a). Both records
 *          MAY exist on disk for the same spawn, but consumers do NOT sum
 *          them additively: hooks/stop-context.js scanSessionAggregate()
 *          (and bin/ds-cost's _aggregate_by_agent()) apply a double-count
 *          guard - when a session has a conductor-emitted (non-hook)
 *          spawn_complete, ALL hook-emitted telemetry for that session
 *          (both spawn_start and spawn_complete) is excluded from the
 *          count, treating the conductor's record as authoritative. This
 *          hook's own event is still written to disk either way (telemetry
 *          write is unconditional and does not know about session type);
 *          it is the CONSUMER that decides whether to count it.
 *
 *          Pairing: this hook does NOT receive the launching PreToolUse
 *          call's `spawn_id` directly from the harness (SubagentStop's
 *          payload shape is not documented to carry it), NOR does the
 *          SubagentStop payload reliably carry a usable `tool_use_id` of
 *          its own - measured (DS-178) at null on 612 of 612 real
 *          post-DS-160 hook-emitted `spawn_complete` PAYLOAD ROWS already
 *          on disk in this repo's own `events.jsonl` (m8 correction:
 *          these are the events THIS hook itself previously emitted, not
 *          the `.meta.json` sidecar files - the two are different objects
 *          entirely; see the sidecar measurement two sentences below for
 *          the actual sidecar-file figures), which is why every pairing before DS-178 fell
 *          through to same-session FIFO and mis-paired 79.5% of resolvable
 *          completions (58.4% carried the wrong `agent` as a direct
 *          result). DS-178 fixes this by resolving the harness-written
 *          `.meta.json` SIDECAR instead (readSidecar(), same directory as
 *          the transcript, same `agent-<agentId>` naming, `.meta.json`
 *          suffix) - measured (DS-178) at 100% `agentType` and 97.9%
 *          `toolUseId` present across 4,237 live sidecars on the machine
 *          this fix was built on. Pairing now sources its match key from
 *          `sidecarToolUseId` (the sidecar's OWN `toolUseId` field), not
 *          the payload's `tool_use_id`, and reconstructs the pairing by
 *          scanning [cwd]/.agentic/events.jsonl backward for the most
 *          recent unmatched `spawn_start` event (data.source==="hook")
 *          whose `data.session_uuid` EXACTLY equals this payload's
 *          `session_id` - session scoping is REQUIRED, not best-effort:
 *          when either side lacks a session id, or this payload's
 *          `session_id` is absent, pairing is skipped entirely (degrades
 *          to unpaired) rather than falling through to an unscoped FIFO
 *          match across sessions. Among same-session candidates, an exact
 *          `data.tool_use_id` match against `sidecarToolUseId` wins first,
 *          then FIFO (oldest unmatched spawn_start for that session wins).
 *          "Unmatched" is tracked by scanning the same window for prior
 *          spawn_complete events and excluding any spawn_id already
 *          referenced by `data.paired_spawn_id`. This is a best-effort
 *          heuristic, not a hard guarantee - see Failure modes.
 *
 *          `data.agent_source` (round-2 fix, DS-178 M1) records the
 *          PROVENANCE OF THE `agent` LABEL, not which pairing tier matched
 *          the spawn - these are different questions, verified to diverge
 *          by execution: a sidecar can carry a `toolUseId` with no
 *          `agentType` (pairs via sidecar, but the label still falls
 *          through to the matched start's `agent`), or carry an
 *          `agentType` with no `toolUseId` (labels via sidecar, but pairs
 *          via FIFO because there is no sidecar toolUseId to match on). A
 *          prior version of this field recorded the pairing tier instead
 *          and was wrong in both of those directions. `agent` and
 *          `agent_source` are now computed from the exact same precedence
 *          branch (sidecar `agentType` -> `"sidecar"`; matched start's
 *          `agent` -> `"paired_start"`; neither -> `"unknown"`), so the two
 *          fields can never disagree, and `agent_source` does not require
 *          a pairing match at all when the sidecar alone resolves the
 *          label.
 *
 *          `data.wall_seconds` is computed as (this event's ts - the matched
 *          spawn_start's ts) when a match is found; when no match is found,
 *          the event is still emitted (a "reliably-paired timestamp" per
 *          DS-160's own fallback allowance) with wall_seconds:null and
 *          paired_spawn_id:null, so a real completion signal exists even
 *          when pairing fails. A computed wall_seconds beyond
 *          MAX_SANE_WALL_SECONDS (86400 = 24h) yields wall_seconds:null
 *          (never a fabricated ceiling value) with `data.suspect` set true,
 *          rather than trusted outright - guards against a stale/mismatched
 *          pairing silently inflating a cost/telemetry rollup.
 *
 * Public API: run() - invoked immediately at module load via run() call at
 *             the bottom of the file. Not imported in production; executed
 *             as a CLI script by the Claude Code SubagentStop hook.
 *
 * Upstream deps: Node built-ins only (fs, path, os via
 *                hooks/lib/config-dir.js, child_process for the M2
 *                diff_lines resolution below). hooks/lib/repo-root.js
 *                (resolveAgenticCwd) anchors the .agentic/ dir below to
 *                the repo root instead of the raw payload cwd. No npm
 *                dependencies. Round-2 addition (M2): runs one bounded
 *                `git diff --shortstat <range>` subprocess
 *                (DIFF_SHORTSTAT_TIMEOUT_MS, 3000ms) per Skeptic
 *                completion to resolve `data.diff_lines` - the SAME
 *                bounded-subprocess pattern hooks/lib/capture-gap.js
 *                already uses for its own `git diff` call, and this file's
 *                first subprocess dependency. Skipped entirely for any
 *                non-Skeptic completion. Reads
 *                SubagentStop payload from stdin (fd 0) via the bounded
 *                reader hooks/lib/stdin-guard.js (readStdinGuarded).
 *                Reads [cwd]/.agentic/events.jsonl - bounded on BOTH the
 *                byte axis (readRecentEvents() reads at most MAX_TAIL_BYTES
 *                from the tail via fs.statSync + fs.readSync at a computed
 *                offset, never a full-file fs.readFileSync once the file
 *                exceeds that size) and the line axis (MAX_SCAN_LINES) - to
 *                find the matching spawn_start. Reads
 *                hooks/lib/config-dir.js (resolveClaudeConfigDir) and, when
 *                a transcript or sidecar resolves, the subagent's own
 *                transcript JSONL and/or `.meta.json` sidecar under
 *                <config_dir>/projects/... (transcript size-capped at
 *                MAX_TRANSCRIPT_BYTES, read synchronously; the sidecar has
 *                no comparable size cap - measured sidecars are small,
 *                fixed-shape JSON objects, not append-only logs). DS-178
 *                unit A additionally reads (best-effort, fail-open)
 *                [repo root]/.agentic/skeptic-tuid-index.json (m8
 *                correction: the bracketed segment names the REPO root,
 *                the directory THAT CONTAINS `.agentic/`, not the
 *                `.agentic/` directory itself - the prior notation
 *                "[.agentic root]/.agentic/..." double-rooted the path)
 *                and, on a hit, the corresponding
 *                [repo root]/.agentic/skeptic-round-<unit_key>.json -
 *                both WRITTEN by hooks/enforce-skeptic-round-cap.py, making
 *                this hook a READ-ONLY consumer of that hook's state, never
 *                a writer of it.
 *                Writes [cwd]/.agentic/events.jsonl via appendFileSync.
 *
 * Downstream consumers: Claude Code SubagentStop hook (wired by
 *                        .claude/install.sh). hooks/stop-context.js
 *                        scanSessionAggregate() and bin/ds-cost's
 *                        _aggregate_by_agent() both read `data.wall_seconds`
 *                        (and, as of the token-resolution addition,
 *                        `data.tokens` when present) from hook-emitted
 *                        spawn_complete events into session/cost
 *                        aggregates, ONLY for sessions with no
 *                        conductor-emitted spawn_complete (double-count
 *                        guard - see the Purpose section above); this is the
 *                        first source of non-zero wall_seconds AND non-zero
 *                        tokens for hook-only ad-hoc sessions.
 *                        hooks/lib/capture-gap.js detectCaptureGap() is
 *                        ALREADY a live consumer of two of this unit's
 *                        fields TODAY, not merely "expected to be" one -
 *                        its skeptic-with-findings trigger reads
 *                        `data.findings_count`/`data.signed_off` directly
 *                        off a `spawn_complete` event (any source, hook or
 *                        conductor-emitted) to decide whether a Skeptic
 *                        completion is learning-worthy (round-1 shipped
 *                        this field's own module manifest correctly, three
 *                        lines above this paragraph in that version's
 *                        text, while this Downstream-consumers section
 *                        still claimed the opposite - corrected here, M5).
 *                        Before this unit, that branch was structurally
 *                        dead for any hook-emitted row (hook payloads never
 *                        carried calibration data at all); it is live now.
 *                        `bin/ds-calibrate` (DS-178 unit B, not yet built
 *                        as of this unit) is expected to add its own
 *                        density-report consumer of `agent_source`/
 *                        `model`/`unit_key`/`iteration`/`findings_count`/
 *                        `signed_off`/`findings_parse_ambiguous`/
 *                        `diff_lines`/`calibration_note` - that consumer
 *                        does not exist yet, but `capture-gap.js`'s does.
 *
 * Failure modes: Fully fail-open, mirroring hooks/pre-tool-use-spawn-emit.js.
 *                Entire body wrapped in try/catch; ALWAYS process.exit(0).
 *                Any fs error, parse error, or missing field is silently
 *                swallowed. NEVER writes to stdout. NEVER denies (advisory
 *                telemetry only). The SubagentStop payload's own
 *                `session_id`/`cwd`/`agent_id` fields ARE empirically
 *                verified (DS-178, direct measurement against 4,237 live
 *                `.meta.json` sidecars and their paired transcripts on the
 *                machine this fix was built on) - `session_id`/`cwd` are
 *                read with a typeof guard and null fallback as before, but
 *                `tool_use_id` is now KNOWN, not merely suspected, to be
 *                unreliable (measured null on 612/612 real payloads) and
 *                is retained only as a last-resort fallback input, never
 *                the primary pairing key - see the Pairing paragraph above
 *                for the sidecar-based replacement. Sidecar
 *                resolution/parsing failure (missing file, invalid JSON,
 *                empty file, wrong shape) degrades gracefully at TWO
 *                independent layers - readSidecar()'s own internal
 *                guards, and the outer try/catch around its call site in
 *                run() - to a null sidecar, which in turn degrades pairing
 *                to the FIFO fallback and `agent` resolution to the
 *                matched spawn_start's own label or `"unknown"`; neither
 *                ever blocks emission of the completion signal itself
 *                (both layers verified by executed mutation, DS-178).
 *
 *                **Token resolution (post-DS-160 addition).** `data.tokens`
 *                (`{input, output, cache_creation, cache_read}`, summed
 *                across the subagent's own transcript JSONL) is populated
 *                when the transcript can be found and read; it is ABSENT
 *                (never zero-filled) when unresolvable - a zero that looks
 *                like a measurement is the exact failure mode this addition
 *                removes. The transcript path is resolved the same way
 *                bin/ds-parse-subagent-usage resolves it: under the active
 *                harness config dir (hooks/lib/config-dir.js
 *                resolveClaudeConfigDir(), NOT a hardcoded ~/.claude - see
 *                that module's header for the measured root cause this
 *                fixes), primary construction from `cwd`+`session_id`+
 *                `agent_id`, falling back to a bounded scan (first
 *                MAX_PROJECT_DIRS_SCAN entries of
 *                `readdirSync(configDir/projects)`) when the primary path
 *                does not exist. Requires `agent_id` (best-effort,
 *                harness-supplied - see the field read above); when the
 *                harness omits it, or the transcript FILE cannot be
 *                located, `data.tokens_note` is
 *                `"unavailable (transcript not found)"`. When the
 *                transcript IS located but yields zero assistant-turn
 *                records contributing at least one usable NUMERIC usage
 *                field (round-2 fix: this is the same note for an empty
 *                file, a wholly malformed/non-JSONL file, and a genuinely
 *                turn-less transcript alike - scanTranscript() tracks
 *                whether ANY record actually parsed and never treats a
 *                successful-but-vacuous read as a real zero measurement;
 *                round-3 fix: "parsed" now means at least one usage field
 *                that is a real, non-negative number - a record whose
 *                `usage` is present but `{}`, or carries only non-numeric
 *                values, no longer counts as parsed either, closing the
 *                same fabrication class one step over: previously such a
 *                transcript silently emitted a {0,0,0,0} `tokens` object
 *                with no note. A negative usage value is treated as
 *                unusable - never summed, and does not count toward "this
 *                record parsed" - since a negative token count cannot be a
 *                real measurement and silently adding it would corrupt the
 *                total in the other direction),
 *                `data.tokens_note` is
 *                `"unavailable (transcript unreadable)"`, and no `tokens`
 *                key is emitted either way. A transcript at or above
 *                MAX_TRANSCRIPT_BYTES (20 MiB) is SKIPPED entirely
 *                (`data.tokens_note: "skipped (transcript too large)"`) -
 *                never partial-summed, same never-fabricate principle as
 *                the `wall_seconds` sanity-cap treatment above. `tokens`
 *                and `tokens_note` are mutually exclusive on a given event.
 *
 *                **Known, documented blemish (round-3): partial sums are
 *                not flagged.** When a transcript contains a mix of
 *                well-formed assistant-usage lines and malformed/truncated
 *                lines (e.g. a transcript captured mid-write at the moment
 *                the harness process stopped), scanTranscript()
 *                silently skips the malformed lines and sums only the
 *                lines that parsed - `data.tokens` is emitted with no
 *                `tokens_note` disclosing that some lines were dropped.
 *                This is accepted, not fixed, for the same reason as the
 *                pairing TOCTOU documented below: this file is
 *                telemetry-only, fail-open, and advisory, and adding a
 *                third mutually-exclusive-with-nothing state (tokens AND a
 *                disclosure note together) would require re-deriving the
 *                "mutually exclusive" invariant this doc-comment and every
 *                consumer currently relies on. A partial sum is a
 *                data-quality blemish (undercounting, never overcounting,
 *                since only cleanly-parsed lines contribute), not a
 *                fabricated measurement - it differs from the cases this
 *                function otherwise guards against in that a real subset of
 *                the true total is genuinely present in what is reported.
 *
 *                No serialization between concurrent SubagentStop
 *                invocations (Skeptic finding, Minor): if two subagents in
 *                the same session complete close enough together that their
 *                hook invocations overlap, both can read events.jsonl before
 *                either has appended its own spawn_complete, and both can
 *                independently select the SAME unmatched spawn_start as
 *                their match (a TOCTOU race on the pairedIds exclusion set).
 *                The result is double-pairing: two spawn_complete records
 *                both claiming the same paired_spawn_id, one of which is
 *                therefore wrong. This is accepted, not mitigated, for two
 *                reasons: (1) this file is telemetry-only, fail-open, and
 *                advisory - a mispaired wall_seconds is a data-quality
 *                blemish, not a correctness or safety issue, and (2) actually
 *                closing the race would require either a file lock around
 *                the read-match-append sequence (adds latency and a new
 *                failure mode to a hook that currently cannot block or deny)
 *                or a re-read-and-recheck-pairedIds step immediately before
 *                the append (narrows the window but cannot close it without
 *                a lock, since the check-then-append is still not atomic).
 *                Neither is judged worth the added complexity for a rare,
 *                low-severity race in an advisory-only signal.
 *
 * Performance: Token resolution adds, once per SubagentStop invocation (not
 *              per events.jsonl line): at most one fs.statSync (primary
 *              transcript path), an optional bounded readdirSync scan
 *              (first MAX_PROJECT_DIRS_SCAN entries under
 *              configDir/projects, only on primary-path miss), and one
 *              synchronous fs.readFileSync of the resolved transcript,
 *              size-capped at MAX_TRANSCRIPT_BYTES (20 MiB) - a transcript
 *              at or above that size is skipped entirely rather than read.
 *              This stays inside the hook's overall 5s timeout
 *              (.claude/install.sh) alongside the rest of this hook's work.
 *
 *              The events.jsonl scan itself is bounded by
 *              hooks/lib/stdin-guard.js's read path (same as
 *              hooks/pre-tool-use-spawn-emit.js). The events.jsonl scan is
 *              bounded on BOTH axes, independent of overall file size:
 *              readRecentEvents() first fs.statSync()s the file and, when it
 *              exceeds MAX_TAIL_BYTES, opens an fd and reads only the last
 *              MAX_TAIL_BYTES bytes (fs.readSync at a computed offset, not a
 *              full fs.readFileSync) before splitting into lines and further
 *              capping at MAX_SCAN_LINES lines. events.jsonl is a
 *              cross-session, append-only, multi-writer file (this hook is
 *              itself one of the writers) with NO size cap or rotation (see
 *              content/references/events-log.md "Atomicity" - "Records are
 *              not size-bounded") - it is NOT scoped to ~50KB per session in
 *              practice (a prior version of this comment claimed otherwise;
 *              that claim was false - this repo's own events.jsonl was
 *              observed at 2.4MB, and it grows unboundedly over the file's
 *              lifetime). Bounding the read protects this hook, which runs on
 *              every subagent COMPLETION (a much higher-frequency call site
 *              than "once per session"), from an O(file size) read cost.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { readStdinGuarded } = require('./lib/stdin-guard.js');
const { resolveClaudeConfigDir } = require('./lib/config-dir.js');
const { resolveAgenticCwd } = require('./lib/repo-root.js');

// Timeout for the best-effort `git diff --shortstat` subprocess used to
// resolve `data.diff_lines` (M2) - mirrors the bounded-subprocess pattern
// hooks/lib/capture-gap.js already uses for its own git diff call. A hang
// or slow git invocation must never delay emitting the completion signal
// beyond this window.
const DIFF_SHORTSTAT_TIMEOUT_MS = 3000;

// Bounds the readdirSync fallback scan when the primary transcript path
// (constructed from cwd's project hash) does not exist - mirrors
// bin/ds-parse-subagent-usage's glob fallback but bounded on directory
// COUNT rather than left as an unbounded glob, matching this file's
// existing MAX_SCAN_LINES/MAX_TAIL_BYTES bounding discipline. readdirSync's
// entry order is unspecified, so any bound short of "every project dir"
// leaves SOME machine's tail unreachable on a primary-path miss; this fails
// SAFE either way (a miss emits `data.tokens_note`, never a wrong number),
// but round-2 raised the bound from 200 to 1000 after a real dev machine
// was observed with 251 entries under ~/.claude/projects - comfortably
// above the old bound and not comfortably below a plausible future one.
const MAX_PROJECT_DIRS_SCAN = 1000;

// A transcript at or above this size is SKIPPED entirely (never
// partial-summed) - see the token-resolution doc-comment note above.
const MAX_TRANSCRIPT_BYTES = 20 * 1024 * 1024;

/**
 * Claude Code's cwd->project-hash substitution scheme: every '/' becomes
 * '-'. Mirrors bin/ds-parse-subagent-usage's _project_hash_from_cwd().
 */
function projectHashFromCwd(cwd) {
  return String(cwd).replace(/\//g, '-');
}

/**
 * Resolve a subagent-scoped file's path under <configDir>/projects/, or
 * null when unresolvable. Shared by resolveTranscriptPath() (the `.jsonl`
 * transcript) and resolveSidecarPath() (the DS-178 `.meta.json` sidecar) -
 * both files live in the SAME directory (<configDir>/projects/
 * <projectHash(cwd)>/<sessionId>/subagents/), differing only in filename.
 * Requires both sessionId and agentId (the harness-supplied SubagentStop
 * agent_id, best-effort - see the field read in run()); without agentId
 * there is no way to select which file under a session belongs to THIS
 * subagent, so this function does not guess.
 *
 * Primary: <configDir>/projects/<projectHash(cwd)>/<sessionId>/subagents/
 *          <filename>
 * Fallback: the same filename under the first MAX_PROJECT_DIRS_SCAN
 *           entries of readdirSync(<configDir>/projects) - bounded scan,
 *           not an unbounded glob.
 */
function resolveSubagentFile(configDir, cwd, sessionId, agentId, filename) {
  if (!sessionId || !agentId) return null;

  const projectHash = projectHashFromCwd(cwd);
  const primary = path.join(
    configDir, 'projects', projectHash, sessionId, 'subagents', filename
  );
  try {
    if (fs.statSync(primary).isFile()) return primary;
  } catch (_) { /* fall through to bounded scan */ }

  const projectsDir = path.join(configDir, 'projects');
  let entries;
  try {
    entries = fs.readdirSync(projectsDir);
  } catch (_) {
    return null;
  }
  const bounded = entries.slice(0, MAX_PROJECT_DIRS_SCAN);
  for (const entry of bounded) {
    const candidate = path.join(projectsDir, entry, sessionId, 'subagents', filename);
    try {
      if (fs.statSync(candidate).isFile()) return candidate;
    } catch (_) { /* continue scanning */ }
  }
  return null;
}

/** Resolve the subagent's own transcript path (`.jsonl`) - see
 * resolveSubagentFile() for the shared resolution algorithm. */
function resolveTranscriptPath(configDir, cwd, sessionId, agentId) {
  return resolveSubagentFile(configDir, cwd, sessionId, agentId, `agent-${agentId}.jsonl`);
}

/** Resolve the subagent's own sidecar path (`.meta.json`, DS-178) - the
 * SAME directory and naming convention as the transcript, verified
 * independently against 4,237 live sidecars on this machine before this
 * fix was built: 100% carry `agentType`, 97.9% carry `toolUseId`, ~6%
 * carry `model`. See resolveSubagentFile() for the shared algorithm. */
function resolveSidecarPath(configDir, cwd, sessionId, agentId) {
  return resolveSubagentFile(configDir, cwd, sessionId, agentId, `agent-${agentId}.meta.json`);
}

/**
 * Read and parse the subagent's `.meta.json` sidecar, or return null when
 * unresolvable, unreadable, empty, or malformed JSON (never throws, never
 * blocks event emission). Returns `{toolUseId, agentType, model}` where
 * each field is the sidecar's own value (string) or null when absent/blank
 * - a successfully-parsed sidecar missing a field yields null for that
 * field, not a null return for the whole object; only a missing/unreadable
 * FILE, or content that fails to parse as a JSON object, returns null
 * overall.
 */
function readSidecar(configDir, cwd, sessionId, agentId) {
  const sidecarPath = resolveSidecarPath(configDir, cwd, sessionId, agentId);
  if (!sidecarPath) return null;

  let raw;
  try {
    raw = fs.readFileSync(sidecarPath, 'utf8');
  } catch (_) {
    return null;
  }
  if (!raw || !raw.trim()) return null;

  let obj;
  try {
    obj = JSON.parse(raw);
  } catch (_) {
    return null;
  }
  if (!obj || typeof obj !== 'object') return null;

  const toolUseId = (typeof obj.toolUseId === 'string' && obj.toolUseId.trim())
    ? obj.toolUseId.trim() : null;
  const agentType = (typeof obj.agentType === 'string' && obj.agentType.trim())
    ? obj.agentType.trim() : null;
  const model = (typeof obj.model === 'string' && obj.model.trim())
    ? obj.model.trim() : null;
  return { toolUseId, agentType, model };
}

/**
 * Sum token usage across all assistant turns in a transcript JSONL, or
 * return a descriptive note when unresolvable. Never returns a zero-filled
 * tokens object as a stand-in for "unresolved" - a real zero (genuinely no
 * assistant turns yet) and "we could not read this" are kept distinct by
 * tracking whether at least one assistant record ACTUALLY contributed a
 * usable numeric usage field, not merely whether a `usage` object was
 * present or the file opened without throwing. Round-2 fix: a prior version
 * returned the untouched {0,0,0,0} accumulator as a "success" whenever the
 * file was 0 bytes or wholly unparseable JSONL, which is indistinguishable
 * downstream from a real zero-token measurement - exactly the fabrication
 * this function exists to prevent. Round-3 fix: a prior version counted a
 * record as "parsed" whenever a `usage` OBJECT existed, regardless of
 * whether any field inside it was a real number - so a transcript whose
 * assistant records all carried `usage: {}` (or only non-numeric usage
 * values) silently produced the same {0,0,0,0}-with-no-note fabrication one
 * step over. A record now counts as parsed only when it contributes at
 * least one usable numeric usage field; a negative usage value is treated
 * as unusable (never summed, does not count toward "parsed") rather than
 * silently summed as-is. Malformed/truncated lines mixed with otherwise-
 * valid lines are silently skipped and NOT flagged - see the "Known,
 * documented blemish" note in this module's header doc-comment.
 *
 * Returns { tokens: {input,output,cache_creation,cache_read}, note: null }
 * when at least one assistant record contributed a usable numeric usage
 * field, or { tokens: null, note: <string> } when tokens could not be
 * determined (file missing, oversized, or found but yielding zero usable
 * fields).
 *
 * DS-178 unit A extends this SAME single pass (no extra file opens) to also
 * extract:
 *   - `model`: the first non-blank `message.model` seen on an assistant
 *     record. Independent of the token-parsing outcome - a record whose
 *     `usage` is absent/unusable can still carry a usable `model`.
 *   - `attributionAgent`: the first non-blank top-level `attributionAgent`
 *     field seen on ANY record (not assistant-only - measured present on
 *     every record type in a live transcript). This is a CROSS-CHECK input
 *     against the sidecar/pairing-derived `agent` field - never emitted
 *     under its own name, but run() (round-2 fix, m1) DOES emit
 *     `data.agent_note` when this value disagrees with the resolved
 *     `agent`, a case previously computed here and then silently
 *     discarded (dead code - the value was extracted but never read by
 *     any caller).
 *   - `firstTimestamp`: the first non-blank top-level `timestamp` field
 *     seen on any record - reserved, like `attributionAgent`, as raw
 *     forensic material rather than something this unit acts on; not
 *     emitted into the event.
 *   - `firstUserText` (round-2 addition, M2): the text of the FIRST
 *     `type === "user"` record - the subagent's own original spawn prompt,
 *     which is where the "Diff under review:" line
 *     `content/references/skeptic-protocol.md` Section 4.5 mandates lives.
 *     Used by `resolveDiffLines()` below to derive `data.diff_lines` for a
 *     Skeptic completion; never itself emitted into the event.
 * `model`/`modelNote` follow the exact same mutual-exclusion and
 * never-fabricate discipline as `tokens`/`tokensNote`, using the SAME
 * skip/not-found/unreadable notes (they are read from the same transcript
 * in the same pass, so the same failure necessarily affects both).
 */
function scanTranscript(transcriptPath) {
  const notFound = {
    tokens: null, tokensNote: 'unavailable (transcript not found)',
    model: null, modelNote: 'unavailable (transcript not found)',
    attributionAgent: null, firstTimestamp: null, firstUserText: null,
  };
  const tooLarge = {
    tokens: null, tokensNote: 'skipped (transcript too large)',
    model: null, modelNote: 'skipped (transcript too large)',
    attributionAgent: null, firstTimestamp: null, firstUserText: null,
  };

  let stat;
  try {
    stat = fs.statSync(transcriptPath);
  } catch (_) {
    return notFound;
  }
  if (!stat.isFile()) {
    return notFound;
  }
  if (stat.size >= MAX_TRANSCRIPT_BYTES) {
    return tooLarge;
  }

  let raw;
  try {
    raw = fs.readFileSync(transcriptPath, 'utf8');
  } catch (_) {
    return notFound;
  }

  const tokens = { input: 0, output: 0, cache_creation: 0, cache_read: 0 };
  // Maps the tokens accumulator key to the raw usage field name. A record
  // is only counted as "parsed" (see doc-comment above) when at least one
  // of these fields is a real, non-negative number.
  const USAGE_FIELDS = [
    ['input', 'input_tokens'],
    ['output', 'output_tokens'],
    ['cache_creation', 'cache_creation_input_tokens'],
    ['cache_read', 'cache_read_input_tokens'],
  ];
  let parsedCount = 0;
  let model = null;
  let attributionAgent = null;
  let firstTimestamp = null;
  let firstUserText = null;
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try { obj = JSON.parse(trimmed); } catch (_) { continue; }
    if (!obj || typeof obj !== 'object') continue;

    if (firstTimestamp === null && typeof obj.timestamp === 'string' && obj.timestamp.trim()) {
      firstTimestamp = obj.timestamp.trim();
    }
    if (attributionAgent === null && typeof obj.attributionAgent === 'string' && obj.attributionAgent.trim()) {
      attributionAgent = obj.attributionAgent.trim();
    }
    if (firstUserText === null && obj.type === 'user') {
      const text = extractAssistantText(obj.message);
      if (text) firstUserText = text;
    }

    if (obj.type !== 'assistant') continue;
    const message = obj.message;
    if (model === null && message && typeof message.model === 'string' && message.model.trim()) {
      model = message.model.trim();
    }
    const usage = message && message.usage;
    if (!usage || typeof usage !== 'object') continue;
    let usableFieldFound = false;
    for (const [key, rawKey] of USAGE_FIELDS) {
      const val = usage[rawKey];
      if (val === undefined || val === null) continue;
      const n = Number(val);
      // Non-numeric (NaN) and negative values are unusable: never summed,
      // and never counted toward this record having "parsed". A negative
      // token count cannot be a real measurement; silently summing it would
      // corrupt the total in the opposite direction from fabrication.
      if (!Number.isFinite(n) || n < 0) continue;
      tokens[key] += n;
      usableFieldFound = true;
    }
    if (usableFieldFound) parsedCount += 1;
  }

  const tokensResult = parsedCount === 0
    // File opened and read fine, but nothing usable parsed out of it - an
    // empty file, wholly malformed JSONL, and a genuinely turn-less
    // transcript are all indistinguishable from "we could not determine
    // this" from the caller's perspective, and must never be reported as
    // a real zero-token measurement.
    ? { tokens: null, tokensNote: 'unavailable (transcript unreadable)' }
    : { tokens, tokensNote: null };
  const modelResult = model === null
    ? { model: null, modelNote: 'unavailable (transcript unreadable)' }
    : { model, modelNote: null };

  return { ...tokensResult, ...modelResult, attributionAgent, firstTimestamp, firstUserText };
}

/**
 * Extract the text content of an assistant-role transcript record, or ''
 * when the message carries no text block(s). `message.content` is either a
 * raw string or an array of typed content blocks (measured on live
 * transcripts); only `{type:"text", text:"..."}` blocks contribute -
 * `thinking` blocks and tool-use/tool-result blocks are intentionally
 * excluded, since the sign-off format is always plain text.
 */
function extractAssistantText(message) {
  if (!message || typeof message !== 'object') return '';
  const content = message.content;
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  const parts = [];
  for (const block of content) {
    if (block && typeof block === 'object' && block.type === 'text' && typeof block.text === 'string') {
      parts.push(block.text);
    }
  }
  return parts.join('\n');
}

// Matches a "Findings:" line per content/agents/skeptic.md's mandated
// sign-off format ("Findings: Critical: N, Major: N, Minor: N" or
// "Findings: No findings."), optionally bold-wrapped, anywhere in the text
// (multiline, global) - collects EVERY occurrence so the caller can apply
// the last-line tie-break (see parseSkepticSignoff's doc-comment).
const _FINDINGS_LINE_RE = /^[ \t]*(?:\*\*)?Findings:.*$/gm;
const _FINDINGS_COUNTS_RE = /Findings:\s*(?:\*\*)?\s*Critical:\s*(\d+)\s*,\s*Major:\s*(\d+)\s*,\s*Minor:\s*(\d+)/;
const _FINDINGS_NONE_RE = /Findings:\s*(?:\*\*)?\s*No findings\.?/i;
// The two mandated verdict literals (content/agents/skeptic.md "Sign-off
// format"): "No unresolved Critical or Major findings. Sign-off granted."
// and "Sign-off withheld. The following must be resolved:". Matching the
// short literal substring, not the full sentence, is deliberate - the
// preceding clause is prose, not part of the format contract.
const _SIGNOFF_GRANTED_LITERAL = 'Sign-off granted.';
const _SIGNOFF_WITHHELD_LITERAL = 'Sign-off withheld.';

/**
 * Parse the LAST assistant message in a Skeptic transcript for the
 * mandated sign-off format (content/agents/skeptic.md "Sign-off format")
 * and return calibration fields, or a single `calibrationNote` explaining
 * why none could be extracted. Deliberately scoped to the LAST assistant
 * message only - a transcript's EARLIER message carrying the verbatim
 * sign-off template text (a decoy: e.g. the spawn prompt itself, echoed
 * back, or an intermediate draft) must never be mistaken for the actual
 * verdict.
 *
 * Multi-`Findings:` tie-break: when more than one `Findings:` line appears
 * within that last message, the LAST one wins and `findingsParseAmbiguous:
 * true` is set alongside the parsed counts (measured frequency ~2-3%; a
 * separate boolean, never folded into `calibrationNote` - those two fields
 * are not mutually exclusive with each other).
 *
 * Both a `Findings:` line (either the `Critical: N, Major: N, Minor: N`
 * form or the `No findings.` form, mapping to three explicit zeros - never
 * to absent) AND one of the two verdict literals must be present in that
 * last message, or this returns `{ calibrationNote: <string> }` with no
 * `findingsCount`/`signedOff` at all - never a partial/guessed result.
 *
 * Returns:
 *   { findingsCount: {critical,major,minor}, signedOff: bool,
 *     findingsParseAmbiguous?: true }
 *   or
 *   { calibrationNote: <string> }
 */
function parseSkepticSignoff(transcriptPath) {
  let stat;
  try {
    stat = fs.statSync(transcriptPath);
  } catch (_) {
    return { calibrationNote: 'unavailable (transcript not found)' };
  }
  if (!stat.isFile()) {
    return { calibrationNote: 'unavailable (transcript not found)' };
  }
  if (stat.size >= MAX_TRANSCRIPT_BYTES) {
    return { calibrationNote: 'skipped (transcript too large)' };
  }

  let raw;
  try {
    raw = fs.readFileSync(transcriptPath, 'utf8');
  } catch (_) {
    return { calibrationNote: 'unavailable (transcript not found)' };
  }

  let lastAssistantText = null;
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try { obj = JSON.parse(trimmed); } catch (_) { continue; }
    if (!obj || obj.type !== 'assistant') continue;
    const text = extractAssistantText(obj.message);
    if (text) lastAssistantText = text;
  }

  if (!lastAssistantText) {
    return { calibrationNote: 'unavailable (no sign-off found in transcript)' };
  }

  const findingsMatches = lastAssistantText.match(_FINDINGS_LINE_RE);
  if (!findingsMatches || findingsMatches.length === 0) {
    return { calibrationNote: 'unavailable (no sign-off found in transcript)' };
  }
  const findingsParseAmbiguous = findingsMatches.length > 1;
  const lastFindingsLine = findingsMatches[findingsMatches.length - 1];

  let findingsCount = null;
  const countsMatch = lastFindingsLine.match(_FINDINGS_COUNTS_RE);
  if (countsMatch) {
    findingsCount = {
      critical: Number(countsMatch[1]),
      major: Number(countsMatch[2]),
      minor: Number(countsMatch[3]),
    };
  } else if (_FINDINGS_NONE_RE.test(lastFindingsLine)) {
    findingsCount = { critical: 0, major: 0, minor: 0 };
  } else {
    return { calibrationNote: 'unavailable (no sign-off found in transcript)' };
  }

  // Tie-break (round-2 fix, m5): use the LAST occurrence of either verdict
  // literal, not "withheld always wins whenever both are present." A
  // Skeptic transcript can legitimately contain both literals in the same
  // last message - content/agents/skeptic.md's own sign-off-format section
  // quotes both templates verbatim, and a Skeptic reviewing that file (or
  // any file that reproduces the format contract) scored signed_off:false
  // even on a real "granted" verdict under the prior first-match logic.
  // The verdict is whichever literal actually appears LAST in the text,
  // matching the same "last one wins" convention already used for the
  // multi-`Findings:` tie-break above.
  const lastWithheldIdx = lastAssistantText.lastIndexOf(_SIGNOFF_WITHHELD_LITERAL);
  const lastGrantedIdx = lastAssistantText.lastIndexOf(_SIGNOFF_GRANTED_LITERAL);
  let signedOff;
  if (lastWithheldIdx === -1 && lastGrantedIdx === -1) {
    return { calibrationNote: 'unavailable (no sign-off found in transcript)' };
  } else if (lastGrantedIdx > lastWithheldIdx) {
    signedOff = true;
  } else {
    signedOff = false;
  }

  const result = { findingsCount, signedOff };
  if (findingsParseAmbiguous) result.findingsParseAmbiguous = true;
  return result;
}

// Matches a "Diff under review:" line per content/references/skeptic-
// protocol.md Section 4.5's `## Global-context inputs` block (item 6) -
// mirrors hooks/enforce-skeptic-round-cap.py's `_DIFF_UNDER_REVIEW_RE`
// (same bullet/numbering/bold-markup coverage; kept as a SEPARATE regex,
// not a shared module, since one is Python and one is JS). Used only to
// resolve `data.diff_lines` (M2) - never for unit-key derivation, which
// stays exclusively the round-cap hook's responsibility.
const _DIFF_UNDER_REVIEW_JS_RE = /^[ \t]*(?:[-*][ \t]*)?(?:\d+\.[ \t]*)?\*{0,2}Diff under review\*{0,2}:\*{0,2}[ \t]*([^\s*][^\n]*)$/im;
// Matches a `<ref1>..<ref2>` / `<ref1>...<ref2>` range, with an optional
// leading "git diff ", anchored at the start of the (already-stripped)
// value - mirrors the round-cap hook's `_DIFF_RANGE_RE`.
const _DIFF_RANGE_JS_RE = /^(?:git diff[ \t]+)?([A-Za-z0-9._/-]+)[ \t]*(\.{2,3})[ \t]*([A-Za-z0-9._/-]+)/i;
const _SHORTSTAT_INSERTIONS_RE = /(\d+) insertion/;
const _SHORTSTAT_DELETIONS_RE = /(\d+) deletion/;

/**
 * Resolve `data.diff_lines` (M2) for a Skeptic completion: a best-effort
 * `git diff --shortstat <range>` against the range named in the "Diff
 * under review:" line of the subagent's OWN spawn prompt (the first
 * `type === "user"` transcript record, per `scanTranscript()`'s
 * `firstUserText`). Genuinely not derivable from the SubagentStop payload
 * alone - the payload carries no diff-range or line-count field of its
 * own, only the spawn's completion signal - so this reconstructs the
 * range from the same field the round-cap hook already depends on for
 * unit identity, then measures it directly with git rather than trusting
 * any conductor-reported number.
 *
 * Returns `{ diffLines: <int>, diffLinesNote: null }` on a resolved
 * measurement (including a genuine 0, e.g. an empty diff - a real
 * measurement, not a fabricated stand-in), or
 * `{ diffLines: null, diffLinesNote: <string> }` when unresolvable at any
 * step: no prompt text, no "Diff under review:" line, no recognizable
 * `ref1..ref2` range in it (e.g. a `<key> | <diff detail>` value whose
 * detail is free-form prose or a file-path list, not a range), or the
 * `git diff` subprocess itself fails (non-git cwd, refs no longer
 * resolvable - e.g. a feature branch already deleted post-merge by the
 * time SubagentStop fires - non-zero exit, or timeout). Never throws;
 * mutually exclusive with `diffLines` on every path, matching the
 * `tokens`/`tokensNote` and `model`/`modelNote` discipline elsewhere in
 * this file.
 */
function resolveDiffLines(cwd, promptText) {
  const NOTE_NO_PROMPT = 'unavailable (no spawn prompt found in transcript)';
  const NOTE_NO_RANGE = 'unavailable (no diff range found in spawn prompt)';
  const NOTE_GIT_FAILED = 'unavailable (git diff resolution failed)';

  if (!promptText) return { diffLines: null, diffLinesNote: NOTE_NO_PROMPT };

  const lineMatch = _DIFF_UNDER_REVIEW_JS_RE.exec(promptText);
  if (!lineMatch) return { diffLines: null, diffLinesNote: NOTE_NO_RANGE };

  let value = lineMatch[1].trim();
  // DS-180 `<key> | <diff detail>` form: the range, if present, lives in
  // the detail half, not the key half.
  if (value.indexOf('|') !== -1) {
    value = value.split('|').slice(1).join('|').trim();
  }
  value = value.replace(/^`+|`+$/g, '').trim();

  const rangeMatch = _DIFF_RANGE_JS_RE.exec(value);
  if (!rangeMatch) return { diffLines: null, diffLinesNote: NOTE_NO_RANGE };
  const rangeArg = `${rangeMatch[1]}${rangeMatch[2]}${rangeMatch[3]}`;

  let output;
  try {
    output = execFileSync('git', ['diff', '--shortstat', rangeArg], {
      cwd, timeout: DIFF_SHORTSTAT_TIMEOUT_MS, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
    });
  } catch (_) {
    return { diffLines: null, diffLinesNote: NOTE_GIT_FAILED };
  }

  const insMatch = _SHORTSTAT_INSERTIONS_RE.exec(output || '');
  const delMatch = _SHORTSTAT_DELETIONS_RE.exec(output || '');
  const insertions = insMatch ? Number(insMatch[1]) : 0;
  const deletions = delMatch ? Number(delMatch[1]) : 0;
  // An empty `--shortstat` output (no files changed) is a genuine 0, not a
  // resolution failure - the git command itself succeeded.
  return { diffLines: insertions + deletions, diffLinesNote: null };
}

/**
 * O(1) lookup of a completed Skeptic spawn's round-cap state, via the
 * `.agentic/skeptic-tuid-index.json` index that hooks/enforce-skeptic-
 * round-cap.py maintains (DS-178 unit A). No directory scan and no
 * fallback bound: an index miss or an absent index file returns null
 * outright - the caller (run(), below) treats a null return as a
 * best-effort omission of `unit_key`/`iteration`, NOT as something that
 * needs its own explanatory note (this function's own contract carries no
 * note; that is deliberate - see the calibration-fields comment in run())
 * - rather than scanning `.agentic/` for `skeptic-round-*.json` files. An
 * earlier design proposed exactly that scan, capped at 500 files, which is
 * a growth cliff on an unpruned directory and was rejected in favor of
 * this index.
 *
 * Round-2 fix (M3): each index entry now carries a PINNED `iteration` -
 * the round number the spawn was actually allowed at, recorded by the
 * round-cap hook AT SPAWN TIME (`{"unit_key": ..., "iteration": ...}`) -
 * rather than this function re-reading the unit's LIVE round-state file
 * for `round_count` at SubagentStop time. The live-read was wrong for any
 * out-of-order completion: the unit's round count can have advanced (or,
 * with fingerprint coalescing, can still be mid-round) by the time a
 * particular spawn's SubagentStop fires, so the reported `iteration`
 * silently described the WRONG round - confidently, with no note. A
 * pre-round-2 index entry is still a bare `unit_key` STRING (legacy
 * shape) - this function tolerates that shape and falls back to the old
 * live-read behavior for it only, so an existing index is not
 * invalidated; it self-heals to the pinned shape as spawns complete and
 * write fresh entries.
 *
 * Returns { unitKey, iteration } on a full hit (a pinned-shape index
 * entry with a positive integer `iteration`, or - legacy fallback only -
 * an index entry resolving to a unit whose state file parses with a
 * positive numeric `round_count`), or null on ANY miss along that chain.
 * `iteration <= 0` is always treated as a miss (m2): the round-cap hook
 * never persists `round_count: 0` on an allowed spawn, so a 0 can only
 * come from a legacy/hand-edited state file and reporting it verbatim
 * would be a zero that looks like a real measurement.
 */
function readRoundState(agenticDir, toolUseId) {
  if (!toolUseId) return null;

  const indexPath = path.join(agenticDir, 'skeptic-tuid-index.json');
  let index;
  try {
    index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));
  } catch (_) {
    return null;
  }
  if (!index || typeof index !== 'object') return null;

  const entry = index[toolUseId];
  let unitKey = null;
  let pinnedIteration = null;
  if (typeof entry === 'string' && entry) {
    // Legacy (pre-round-2) shape: bare unit_key string, no pinned
    // iteration - falls through to the live-read below.
    unitKey = entry;
  } else if (entry && typeof entry === 'object' && typeof entry.unit_key === 'string' && entry.unit_key) {
    unitKey = entry.unit_key;
    pinnedIteration = typeof entry.iteration === 'number' ? entry.iteration : null;
  }
  if (!unitKey) return null;

  if (pinnedIteration !== null && pinnedIteration > 0) {
    return { unitKey, iteration: pinnedIteration };
  }

  // Legacy fallback: no pinned iteration available (a pre-round-2 index
  // entry, or a pinned-but-non-positive value) - re-read the unit's
  // current state file, same behavior as before this fix.
  const statePath = path.join(agenticDir, `skeptic-round-${unitKey}.json`);
  let state;
  try {
    state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
  } catch (_) {
    return null;
  }
  if (!state || typeof state !== 'object') return null;

  const rawIteration = typeof state.round_count === 'number' ? state.round_count : null;
  if (rawIteration === null || rawIteration <= 0) return null;

  return { unitKey, iteration: rawIteration };
}

const MAX_SCAN_LINES = 5000;
// Bounds the raw byte read regardless of events.jsonl's total size (see
// Performance note above - the file has no size cap or rotation). 2MB is
// generously above what MAX_SCAN_LINES worth of JSONL lines will ever need.
const MAX_TAIL_BYTES = 2 * 1024 * 1024;

/**
 * Parse the tail of events.jsonl (bounded to MAX_TAIL_BYTES raw bytes, then
 * further bounded to MAX_SCAN_LINES lines) into an array of parsed JSON
 * objects, skipping malformed lines. Reads at most MAX_TAIL_BYTES from disk
 * regardless of the file's total size - never a full fs.readFileSync of an
 * unbounded, cross-session, append-only file.
 */
function readRecentEvents(eventsPath) {
  let stat;
  try { stat = fs.statSync(eventsPath); } catch (_) { return []; }
  const size = stat.size;
  if (size === 0) return [];

  let raw;
  let truncatedHead = false;
  try {
    if (size <= MAX_TAIL_BYTES) {
      raw = fs.readFileSync(eventsPath, 'utf8');
    } else {
      const fd = fs.openSync(eventsPath, 'r');
      try {
        const start = size - MAX_TAIL_BYTES;
        const buf = Buffer.alloc(MAX_TAIL_BYTES);
        // fs.readSync's return value is the ACTUAL bytes read, which can be
        // less than requested (e.g. the file was concurrently truncated
        // between the stat() above and this read - events.jsonl is
        // append-only by protocol but this hook does not assume that
        // holds under every failure mode). Buffer.alloc zero-fills, so
        // ignoring bytesRead and stringifying the whole buffer would splice
        // NUL padding onto the END of the read - which is the NEWEST data
        // (the read starts partway through the file and reads toward EOF),
        // silently corrupting the very lines this hook most needs to parse
        // correctly. Slice to bytesRead before decoding.
        const bytesRead = fs.readSync(fd, buf, 0, MAX_TAIL_BYTES, start);
        raw = buf.subarray(0, bytesRead).toString('utf8');
        truncatedHead = true;
      } finally {
        fs.closeSync(fd);
      }
    }
  } catch (_) { return []; }

  if (!raw.trim()) return [];
  let lines = raw.split('\n').filter(l => l.trim());
  // When we only read a tail window, the FIRST line of that window may be a
  // truncated fragment of a longer line that started before the window -
  // drop it explicitly rather than rely on JSON.parse's try/catch to skip
  // a corrupt partial object (which it would, but dropping it up front
  // avoids treating a merely-truncated valid line as "malformed").
  if (truncatedHead && lines.length > 0) {
    lines = lines.slice(1);
  }
  const tail = lines.length > MAX_SCAN_LINES ? lines.slice(-MAX_SCAN_LINES) : lines;
  const out = [];
  for (const line of tail) {
    try { out.push(JSON.parse(line)); } catch (_) { /* skip malformed */ }
  }
  return out;
}

/**
 * Find the best-effort matching spawn_start for this SubagentStop, and
 * return { spawnId, startTs, agent } or null when nothing matches.
 *
 * Matching preference order:
 *   1. Exact data.tool_use_id match (when both sides carry one).
 *   2. FIFO: oldest unmatched hook-emitted spawn_start for this session_uuid,
 *      oldest first (candidates are in file order already, since
 *      events.jsonl is append-only).
 * "Unmatched" excludes any spawn_id already referenced by a prior
 * spawn_complete's data.paired_spawn_id in the scanned window.
 *
 * Session scoping is REQUIRED, not best-effort: a candidate is only eligible
 * when this SubagentStop's sessionId AND the candidate spawn_start's
 * data.session_uuid are BOTH present and equal. Prior to this fix, a null
 * sessionId (or a candidate with no session_uuid) short-circuited the
 * session filter entirely (`if (sessionId && d.session_uuid && ...)`),
 * allowing FIFO to pair across sessions - and across months, once nothing
 * ahead of it in the scan window carried a session_uuid at all. When either
 * side is missing a session id, this function degrades to unpaired (returns
 * null) rather than guessing.
 */
function findMatch(events, sessionId, toolUseId) {
  if (!sessionId) return null;

  const pairedIds = new Set();
  for (const ev of events) {
    if (ev && ev.event === 'spawn_complete') {
      const d = ev.data || {};
      if (d.paired_spawn_id) pairedIds.add(d.paired_spawn_id);
    }
  }

  const candidates = [];
  for (const ev of events) {
    if (!ev || ev.event !== 'spawn_start') continue;
    const d = ev.data || {};
    if (d.source !== 'hook') continue;
    if (!d.spawn_id || pairedIds.has(d.spawn_id)) continue;
    // Session scoping is mandatory: both sides must carry a session id and
    // they must match. A candidate with no session_uuid is never eligible.
    if (!d.session_uuid || d.session_uuid !== sessionId) continue;
    candidates.push({ spawnId: d.spawn_id, startTs: ev.ts, agent: ev.agent, toolUseId: d.tool_use_id || null });
  }

  if (candidates.length === 0) return null;

  if (toolUseId) {
    const exact = candidates.find(c => c.toolUseId === toolUseId);
    if (exact) return exact;
  }

  // FIFO fallback: candidates are in file order (oldest first) already,
  // since events.jsonl is append-only.
  return candidates[0];
}

// Sanity ceiling on wall_seconds: any pairing that would produce a duration
// beyond this is almost certainly a stale/mismatched pair (e.g. a spawn_start
// that was never cleaned up across an interrupted session) rather than a
// genuine 24h+ subagent run. Rather than reject the pairing outright (the
// completion signal itself is still real and should not be lost, and
// paired_spawn_id is still useful for forensics), the event is marked
// data.suspect:true with data.wall_seconds:null - NOT a fabricated ceiling
// value. A round-2 Skeptic fix: an earlier version of this ceiling clamped
// wall_seconds to 86400 instead of nulling it, which silently injected a
// false 24h duration into consumer aggregates (hooks/stop-context.js
// scanSessionAggregate, bin/ds-cost) for every suspect pairing - worse than
// the unbounded figure it replaced, since it was indistinguishable from a
// real measurement. Consumers already treat wall_seconds:null as a 0
// contribution (Number(null)||0), which is the correct behavior for a
// suspect pairing: count the spawn, contribute nothing to its duration.
// 86400 = 24 hours, generously above any real subagent run.
const MAX_SANE_WALL_SECONDS = 86400;

/**
 * Main entry point. Reads SubagentStop payload from stdin, emits a best-effort
 * spawn_complete event to events.jsonl, always exits 0.
 */
async function run() {
  try {
    const raw = await readStdinGuarded();
    let payload;
    try { payload = JSON.parse(raw); } catch (_) { process.exit(0); }

    const cwd = (payload && typeof payload.cwd === 'string' && payload.cwd.trim())
      ? payload.cwd.trim()
      : null;
    if (!cwd) process.exit(0);

    const sessionId = (payload && typeof payload.session_id === 'string' && payload.session_id.trim())
      ? payload.session_id.trim()
      : null;
    // Best-effort, and measured (DS-178) to be null on 612/612 real
    // SubagentStop payloads - the SubagentStop payload shape does not
    // reliably carry this field. Kept as a fallback input only; the
    // authoritative source is now the `.meta.json` sidecar's `toolUseId`
    // (see sidecarToolUseId below).
    const payloadToolUseId = (payload && typeof payload.tool_use_id === 'string' && payload.tool_use_id.trim())
      ? payload.tool_use_id.trim()
      : null;
    // Best-effort: the subagent's own identity, if the harness threads it
    // through to SubagentStop (mirrors the agent_id convention documented in
    // hooks/enforce-orchestrator-singularity.py). Required for BOTH the
    // transcript and the DS-178 sidecar resolution (same directory).
    const agentId = (payload && typeof payload.agent_id === 'string' && payload.agent_id.trim())
      ? payload.agent_id.trim()
      : null;

    const agenticDir = path.join(resolveAgenticCwd(cwd), '.agentic');
    fs.mkdirSync(agenticDir, { recursive: true });
    const eventsPath = path.join(agenticDir, 'events.jsonl');

    // DS-178: resolve the sidecar FIRST - it is the authoritative source
    // for both the pairing key (toolUseId) and the agent label
    // (agentType), replacing the SubagentStop payload's own (measured
    // always-null) tool_use_id. Wrapped independently and fail-open:
    // sidecar resolution/parsing failure must never block the completion
    // signal, same discipline as the pre-existing token resolution below.
    let sidecar = null;
    let configDir = null;
    try {
      configDir = resolveClaudeConfigDir();
      sidecar = readSidecar(configDir, cwd, sessionId, agentId);
    } catch (_) {
      sidecar = null;
    }
    const sidecarToolUseId = (sidecar && sidecar.toolUseId) ? sidecar.toolUseId : null;
    // Pairing precedence (DS-178): sidecar toolUseId exact match, then the
    // pre-existing FIFO fallback, then unpaired. findMatch()'s own
    // exact-match-then-FIFO logic already implements this once given the
    // right toolUseId to match against - the fix is sourcing that value
    // from the sidecar (97.9% present) instead of the broken payload
    // field. payloadToolUseId is retained only as a last-resort input in
    // case a future harness version does populate it.
    const matchToolUseId = sidecarToolUseId || payloadToolUseId;

    const events = readRecentEvents(eventsPath);
    const match = findMatch(events, sessionId, matchToolUseId);

    // agent precedence (DS-178): sidecar agentType -> matched start's agent
    // -> "unknown". Deliberately NOT a new `agent_type` sibling field (see
    // this hook's module manifest) - this populates the EXISTING `agent`
    // field with the corrected value. agent_source (round-2 fix, M1)
    // records the provenance of THIS LABEL specifically - which of the two
    // precedence tiers actually supplied `agentName` - not which tier
    // resolved the pairing match. Those are two different questions: a
    // sidecar can carry a `toolUseId` with no `agentType` (pairs via
    // sidecar, but the label falls through to the matched start), or carry
    // an `agentType` with no `toolUseId` (labels via sidecar, but pairs via
    // FIFO) - a tier-of-pairing definition reports the wrong provenance in
    // both cases, verified by execution pre-fix. `agentSource` is computed
    // from the exact same branches that set `agentName`, so the two can
    // never disagree.
    let agentName = 'unknown';
    let agentSource;
    if (sidecar && sidecar.agentType) {
      agentName = sidecar.agentType;
      agentSource = 'sidecar';
    } else if (match && match.agent) {
      agentName = match.agent;
      agentSource = 'paired_start';
    } else {
      agentSource = 'unknown';
    }

    const nowIso = new Date().toISOString();
    let wallSeconds = null;
    let pairedSpawnId = null;
    let suspect = false;
    if (match) {
      pairedSpawnId = match.spawnId;
      const startMs = Date.parse(match.startTs);
      const nowMs = Date.parse(nowIso);
      if (!Number.isNaN(startMs) && !Number.isNaN(nowMs) && nowMs >= startMs) {
        wallSeconds = Number(((nowMs - startMs) / 1000).toFixed(3));
        // Sanity ceiling: null out (never fabricate a ceiling value) and
        // flag rather than trust a pairing that implies an implausibly
        // long-running spawn (see MAX_SANE_WALL_SECONDS comment above
        // findMatch).
        if (wallSeconds > MAX_SANE_WALL_SECONDS) {
          wallSeconds = null;
          suspect = true;
        }
      }
    }

    // Transcript resolution + single-pass scan: tokens, model,
    // attributionAgent (cross-check only, never emitted), firstTimestamp
    // (reserved, never emitted). tokens/model are populated ONLY on
    // success; their *_note is populated ONLY on failure - never both, and
    // never a fabricated stand-in for "unresolved" (see scanTranscript's
    // doc-comment).
    let tokens = null;
    let tokensNote = null;
    let model = null;
    let modelNote = null;
    let transcriptPath = null;
    let firstUserText = null;
    let attributionAgent = null;
    try {
      const resolvedConfigDir = configDir || resolveClaudeConfigDir();
      transcriptPath = resolveTranscriptPath(resolvedConfigDir, cwd, sessionId, agentId);
      if (transcriptPath) {
        const scanResult = scanTranscript(transcriptPath);
        tokens = scanResult.tokens;
        tokensNote = scanResult.tokensNote;
        firstUserText = scanResult.firstUserText;
        attributionAgent = scanResult.attributionAgent;
        // model precedence (DS-178): sidecar model -> transcript
        // message.model -> absent + model_note. The sidecar carries
        // `model` on only ~6-8% of real sidecars, so the transcript is the
        // usual source; both are genuinely independent measurements of
        // the same fact.
        if (sidecar && sidecar.model) {
          model = sidecar.model;
        } else {
          model = scanResult.model;
          modelNote = scanResult.modelNote;
        }
      } else {
        tokensNote = 'unavailable (transcript not found)';
        if (sidecar && sidecar.model) {
          model = sidecar.model;
        } else {
          modelNote = 'unavailable (transcript not found)';
        }
      }
    } catch (_) {
      // Transcript resolution/scan must never block emitting the
      // completion signal itself - fall through with whatever notes are
      // already set, defaulting any still-unset one.
      tokensNote = tokensNote || 'unavailable (transcript not found)';
      if (!(sidecar && sidecar.model) && model === null) {
        modelNote = modelNote || 'unavailable (transcript not found)';
      }
    }

    // Calibration fields (DS-178 unit A/round-2): only meaningful for a
    // Skeptic spawn - readRoundState()/parseSkepticSignoff()/
    // resolveDiffLines() are all specifically about the Skeptic round-cap,
    // sign-off format, and reviewed-diff size. Never attempted for any
    // other agent (not a "miss" in that case - simply not applicable).
    //
    // Round-2 fix (M3): a `readRoundState()` tuid-index miss now ALSO
    // contributes to `calibration_note`, naming the miss - the plan's own
    // step 8 mandates "emit neither [unit_key/iteration] plus a
    // calibration_note naming the miss," which the round-1 cut disclosed
    // skipping on the (rejected) grounds that it matched
    // `paired_spawn_id`'s silent-omission treatment. `calibration_note` is
    // a single SHARED field across all three calibration misses (tuid
    // index, sign-off parse, diff-range resolution) rather than one note
    // per miss - when more than one miss occurs on the same completion,
    // each contributes its own labeled clause, joined with "; ", so no
    // miss is silently dropped by another miss's note overwriting it.
    let calibrationFields = {};
    const calibrationNoteParts = [];
    if (agentName === 'skeptic') {
      try {
        const roundState = readRoundState(agenticDir, matchToolUseId);
        if (roundState) {
          calibrationFields.unit_key = roundState.unitKey;
          calibrationFields.iteration = roundState.iteration;
        } else {
          calibrationNoteParts.push('unit_key/iteration: unavailable (tuid-index miss)');
        }

        const signoff = transcriptPath
          ? parseSkepticSignoff(transcriptPath)
          : { calibrationNote: 'unavailable (transcript not found)' };
        if (Object.prototype.hasOwnProperty.call(signoff, 'findingsCount')) {
          calibrationFields.findings_count = signoff.findingsCount;
          calibrationFields.signed_off = signoff.signedOff;
          if (signoff.findingsParseAmbiguous) calibrationFields.findings_parse_ambiguous = true;
        } else {
          calibrationNoteParts.push(`findings_count/signed_off: ${signoff.calibrationNote}`);
        }

        // diff_lines (M2): resolved from the spawn's own prompt text, only
        // attempted for a Skeptic spawn (same scope as the other two
        // calibration fields above).
        const diffResult = resolveDiffLines(cwd, firstUserText);
        if (diffResult.diffLines !== null) {
          calibrationFields.diff_lines = diffResult.diffLines;
        } else {
          calibrationNoteParts.push(`diff_lines: ${diffResult.diffLinesNote}`);
        }
      } catch (_) {
        // Calibration resolution must never block emitting the completion
        // signal itself.
        calibrationFields = {};
        calibrationNoteParts.length = 0;
        calibrationNoteParts.push('unavailable (calibration resolution error)');
      }
    }
    const calibrationNote = calibrationNoteParts.length ? calibrationNoteParts.join('; ') : null;

    // agent_note (round-2 fix, m1): plan step 4's cross-check between the
    // sidecar/pairing-resolved `agent` and the transcript's own
    // `attributionAgent` field (the harness's own per-record agent
    // stamp - see scanTranscript()'s doc-comment) was previously computed
    // and silently discarded (dead code: `attributionAgent` was extracted
    // but never read anywhere in run()). A disagreement is forensically
    // useful precisely because it can indicate a pairing/sidecar
    // resolution bug independent of this hook's own logic. Only emitted
    // when BOTH sides carry a real value and they differ - never a note on
    // a merely-absent attributionAgent (that transcript field's own
    // absence has no bearing on whether the resolved `agent` is correct).
    let agentNote = null;
    if (attributionAgent && agentName !== 'unknown' && attributionAgent !== agentName) {
      agentNote = `attributionAgent ("${attributionAgent}") disagrees with resolved agent ("${agentName}")`;
    }

    const event = {
      ts: nowIso,
      phase: 'hook',
      event: 'spawn_complete',
      agent: agentName,
      task_id: null,
      data: {
        source: 'hook',
        session_uuid: sessionId || null,
        tool_use_id: matchToolUseId,
        agent_id: agentId,
        agent_source: agentSource,
        ...(agentNote ? { agent_note: agentNote } : {}),
        paired_spawn_id: pairedSpawnId,
        wall_seconds: wallSeconds,
        suspect: suspect,
        ...(tokens ? { tokens } : {}),
        ...(tokensNote ? { tokens_note: tokensNote } : {}),
        ...(model ? { model } : {}),
        ...(modelNote ? { model_note: modelNote } : {}),
        ...calibrationFields,
        ...(calibrationNote ? { calibration_note: calibrationNote } : {}),
      },
    };
    fs.appendFileSync(eventsPath, JSON.stringify(event) + '\n', 'utf8');

    process.exit(0);
  } catch (_) {
    // Fully fail-open: any unexpected error -> silent exit 0.
    process.exit(0);
  }
}

run().catch(() => process.exit(0));
