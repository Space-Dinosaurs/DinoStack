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
 *          `spawn_complete` event to [primary root]/.agentic/events.jsonl on every
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
 *          DS-246 (telemetry v2, `data.telemetry_v: 2`). Supersedes the
 *          pairing, wall and token paragraphs below where they differ:
 *          - Root: rows go to the PRIMARY checkout's events.jsonl
 *            (lib/spawn-events.js), so a stop whose cwd is a linked
 *            isolation worktree is not lost with the worktree.
 *          - Internal agents: a stop with an empty or absent payload
 *            `agent_type` and no sidecar file is a harness-internal agent;
 *            it writes one `subagent_stop_internal` row and never consumes
 *            a spawn_start. Every other stop yields a spawn_complete, with
 *            `tokens_note` naming the tiers tried when no transcript
 *            resolves (resolveSubagentFiles()).
 *          - Pairing (findMatch()): exact tool_use_id over ALL this
 *            session's hook starts, paired or not, then FIFO over unpaired
 *            starts of the SAME agent type; no FIFO without a type.
 *          - Runs: every completion is one run. `run_index` = prior paired
 *            hook completions of the start + 1 (`pair_method: "resume"`
 *            for k > 1); `wall_seconds` covers this run only - from the
 *            start for run 1, from the transcript's resume boundary
 *            (`run_start_ts`) for a later run, else null plus `wall_note`.
 *          - Tokens: deduped per `message.id`, cumulative in `tokens`, this
 *            run's share in `run_tokens`, both with
 *            `cache_creation_5m`/`cache_creation_1h`. The transcript cap is
 *            MAX_TRANSCRIPT_BYTES (256 MiB), read streamed in one pass that
 *            also yields the run's last assistant text for the Skeptic and
 *            QA parses (no second read).
 *          - Model: transcript `message.model` first (never `<synthetic>`),
 *            else the sidecar alias unless `inherit`; `model_source` says
 *            which.
 *          - task_id: copied from the paired start (`task_id_source:
 *            "paired_start"`), else lib/active-ticket.js with the sidecar's
 *            `description` and `toolUseId`.
 *          - qa-engineer: `qa_result` (PASS/FAIL/PARTIAL/INCONCLUSIVE/
 *            BLOCKED) and `qa_blocking_count` from the run's last text, or
 *            `qa_result_note`.
 *          - Label: sidecar `agentType`, then payload `agent_type`
 *            (`agent_source: "payload"`), then the paired start.
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
 * Public API: run() - invoked when executed as a script (require.main ===
 *             module) by the Claude Code SubagentStop hook. Exported for
 *             in-process tests only: scanTranscript, findMatch,
 *             isInternalAgent, parseQaResult, resolveSubagentFiles.
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
 *                Writes [primary root]/.agentic/events.jsonl via appendFileSync.
 *                DS-246 additions: lib/spawn-events.js (spawnEventsPath,
 *                streamLines), lib/repo-root.js resolveMainRepoRoot,
 *                lib/active-ticket.js (resolveActiveTicket; may write its
 *                .ticket-scan-<session>.json cache under the cwd root, the
 *                same place the PreToolUse hook writes it).
 *                resolveActiveTicket and readRoundState() read the cwd
 *                root; readRoundState() then falls back to the primary root.
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
 *                        `bin/ds-calibrate` (DS-178 unit B) is now also a
 *                        live consumer: its `density` subcommand groups on
 *                        `data.unit_key` (falling back to the event's
 *                        `task_id` for pre-unit-A rows) and renders
 *                        `data.diff_lines` as `-` when absent rather than
 *                        zero-filling it, per this event's own
 *                        present-or-absent-with-`calibration_note` contract.
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
 *                MAX_TRANSCRIPT_BYTES (256 MiB) is SKIPPED entirely
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
 *              chunked streamLines read of the resolved transcript,
 *              size-capped at MAX_TRANSCRIPT_BYTES (256 MiB) - a transcript
 *              at or above that size is skipped entirely rather than read.
 *
 *              Round-3 fix (M3): two calibration-only contributors, both
 *              added by DS-178 unit A and both previously undocumented
 *              here, only run for a Skeptic completion (agentName ===
 *              "skeptic"), never for any other agent. (1)
 *              parseSkepticSignoff() parses the run's last assistant text
 *              that scanTranscript() already extracted (DS-246 removed its
 *              second read of the transcript). (2) resolveDiffLines()
 *              shells out to `git diff --shortstat` via execFileSync,
 *              bounded by DIFF_SHORTSTAT_TIMEOUT_MS (3000ms) - 60% of the
 *              hook's overall 5s timeout budget on its own, the largest
 *              single contributor in this file. Both degrade to a
 *              calibration_note clause on failure/timeout rather than
 *              blocking. Combined with the token-resolution work above,
 *              this stays inside the hook's overall 5s timeout
 *              (.claude/install.sh) alongside the rest of this hook's
 *              work, but the margin is materially thinner for a Skeptic
 *              completion than for any other agent's.
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
const { resolveAgenticCwd, resolveMainRepoRoot } = require('./lib/repo-root.js');
const { spawnEventsPath, streamLines } = require('./lib/spawn-events.js');
const { resolveActiveTicket } = require('./lib/active-ticket.js');

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
const MAX_TRANSCRIPT_BYTES = 256 * 1024 * 1024;

/**
 * Claude Code's cwd->project-hash substitution scheme: every '/' becomes
 * '-'. Mirrors bin/ds-parse-subagent-usage's _project_hash_from_cwd().
 */
function projectHashFromCwd(cwd) {
  return String(cwd).replace(/\//g, '-');
}

/**
 * DS-246: resolve this subagent's transcript (`agent-<id>.jsonl`) and
 * `.meta.json` sidecar, each independently, trying in order:
 *   agent_transcript_path  - the payload's own path (sidecar = sibling)
 *   parent_session         - <dirname(payload.transcript_path)>/<sid>/subagents/
 *   cwd_hash               - <configDir>/projects/<hash(cwd)>/<sid>/subagents/
 *   main_root_hash         - the same under hash(primary checkout root)
 *   scan                   - the first MAX_PROJECT_DIRS_SCAN project dirs
 * Returns {transcriptPath, transcriptSource, sidecarPath, tried[]}; paths are
 * null when unresolved, and `tried` names every tier attempted for the
 * transcript so an unresolved row can say where it looked. Requires agentId -
 * without it there is no way to select THIS subagent's files.
 */
function resolveSubagentFiles(configDir, payload, cwd, mainRoot, sessionId, agentId) {
  const out = { transcriptPath: null, transcriptSource: null, sidecarPath: null, tried: [] };
  if (!agentId) {
    out.tried.push('agent_id missing');
    return out;
  }
  const tName = `agent-${agentId}.jsonl`;
  const sName = `agent-${agentId}.meta.json`;
  const isFile = (p) => { try { return fs.statSync(p).isFile(); } catch (_) { return false; } };

  const tiers = [];
  if (typeof payload.agent_transcript_path === 'string' && payload.agent_transcript_path.trim()) {
    const p = payload.agent_transcript_path.trim();
    tiers.push(['agent_transcript_path', path.dirname(p), p]);
  }
  if (sessionId && typeof payload.transcript_path === 'string' && payload.transcript_path.trim()) {
    tiers.push(['parent_session', path.join(path.dirname(payload.transcript_path.trim()), sessionId, 'subagents')]);
  }
  if (sessionId && configDir) {
    tiers.push(['cwd_hash', path.join(configDir, 'projects', projectHashFromCwd(cwd), sessionId, 'subagents')]);
    if (mainRoot && mainRoot !== cwd) {
      tiers.push(['main_root_hash', path.join(configDir, 'projects', projectHashFromCwd(mainRoot), sessionId, 'subagents')]);
    }
  }
  const consider = (source, dir, explicitTranscript) => {
    if (!out.transcriptPath) {
      out.tried.push(source);
      const t = explicitTranscript || path.join(dir, tName);
      if (isFile(t)) { out.transcriptPath = t; out.transcriptSource = source; }
    }
    if (!out.sidecarPath) {
      const s = explicitTranscript ? explicitTranscript.replace(/\.jsonl$/, '.meta.json') : path.join(dir, sName);
      if (s !== explicitTranscript && isFile(s)) out.sidecarPath = s;
    }
  };
  for (const [source, dir, explicit] of tiers) consider(source, dir, explicit);

  if ((!out.transcriptPath || !out.sidecarPath) && sessionId && configDir) {
    const projectsDir = path.join(configDir, 'projects');
    let entries = [];
    try { entries = fs.readdirSync(projectsDir).slice(0, MAX_PROJECT_DIRS_SCAN); } catch (_) { /* none */ }
    if (!out.transcriptPath) out.tried.push('scan');
    for (const entry of entries) {
      if (out.transcriptPath && out.sidecarPath) break;
      const dir = path.join(projectsDir, entry, sessionId, 'subagents');
      if (!out.transcriptPath && isFile(path.join(dir, tName))) {
        out.transcriptPath = path.join(dir, tName);
        out.transcriptSource = 'scan';
      }
      if (!out.sidecarPath && isFile(path.join(dir, sName))) out.sidecarPath = path.join(dir, sName);
    }
  }
  return out;
}

function nonBlank(v) {
  return (typeof v === 'string' && v.trim()) ? v.trim() : null;
}

/**
 * Read and parse a `.meta.json` sidecar, or null when absent, unreadable,
 * empty, or not a JSON object (never throws). Returns
 * `{toolUseId, agentType, model, description}`, each the sidecar's own
 * non-blank string or null.
 */
function readSidecarFile(sidecarPath) {
  if (!sidecarPath) return null;
  let obj;
  try {
    const raw = fs.readFileSync(sidecarPath, 'utf8');
    if (!raw || !raw.trim()) return null;
    obj = JSON.parse(raw);
  } catch (_) {
    return null;
  }
  if (!obj || typeof obj !== 'object') return null;
  return {
    toolUseId: nonBlank(obj.toolUseId),
    agentType: nonBlank(obj.agentType),
    model: nonBlank(obj.model),
    description: nonBlank(obj.description),
  };
}

const TOKEN_BANDS = ['input', 'output', 'cache_creation', 'cache_read', 'cache_creation_5m', 'cache_creation_1h'];

function nonNegative(v) {
  if (v === undefined || v === null) return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/**
 * Normalize one usage block to the 6 token bands, or null when it carries no
 * usable (real, non-negative) number. Negative and non-numeric values are
 * never summed. The 5m/1h split comes from `usage.cache_creation`; a block
 * without that breakdown books its cache_creation to 5m, the API default TTL.
 */
function usageBands(usage) {
  if (!usage || typeof usage !== 'object') return null;
  const bands = {
    input: nonNegative(usage.input_tokens),
    output: nonNegative(usage.output_tokens),
    cache_creation: nonNegative(usage.cache_creation_input_tokens),
    cache_read: nonNegative(usage.cache_read_input_tokens),
  };
  if (Object.values(bands).every((v) => v === null)) return null;
  const split = usage.cache_creation && typeof usage.cache_creation === 'object' ? usage.cache_creation : null;
  const fiveM = split ? nonNegative(split.ephemeral_5m_input_tokens) : null;
  const oneH = split ? nonNegative(split.ephemeral_1h_input_tokens) : null;
  const out = {};
  for (const k of ['input', 'output', 'cache_creation', 'cache_read']) out[k] = bands[k] || 0;
  if (fiveM !== null || oneH !== null) {
    out.cache_creation_5m = fiveM || 0;
    out.cache_creation_1h = oneH || 0;
  } else {
    out.cache_creation_5m = out.cache_creation;
    out.cache_creation_1h = 0;
  }
  return out;
}

function sumBands(list) {
  const total = {};
  for (const k of TOKEN_BANDS) total[k] = 0;
  for (const b of list) for (const k of TOKEN_BANDS) total[k] += b[k];
  return total;
}

function isImageOnly(content) {
  if (typeof content === 'string') return /^\s*\[Image[^\]]*\]\s*$/.test(content);
  return Array.isArray(content) && content.length > 0
    && content.every((b) => b && typeof b === 'object' && b.type === 'image');
}

function isToolResult(content) {
  return Array.isArray(content) && content.some((b) => b && typeof b === 'object' && b.type === 'tool_result');
}

function tsMs(ts) {
  const n = typeof ts === 'string' ? Date.parse(ts) : NaN;
  return Number.isNaN(n) ? null : n;
}

/**
 * DS-246: one streamed pass over a subagent transcript (capped at maxBytes,
 * default MAX_TRANSCRIPT_BYTES; a file at or above the cap is skipped whole,
 * never partial-summed).
 *
 * Tokens: chunks sharing a `message.id` repeat one usage block, so only the
 * LAST usable usage per id counts (a record without an id counts alone).
 * `tokens` is the deduped cumulative total with the 5m/1h cache split.
 *
 * Runs: `lastPriorCompleteTs` is the ts of this spawn's latest earlier paired
 * completion, or null for run 1. For a later run, `runStartTs` is the first
 * candidate boundary B where the turn-ending assistant record's ts <=
 * lastPriorCompleteTs <= B's ts. A candidate is a user record that is not a
 * tool_result, not `isCompactSummary`, not image-only, and directly follows
 * an assistant record whose stop_reason is end_turn/stop_sequence, or null on
 * a message.id with no tool_use chunk. Compaction and image-only records are
 * skipped when deciding what a record "directly follows". The index of a run is NOT derived here
 * (compaction, coordinator messages and cut-off re-prompts make transcript
 * counting unreliable); run() takes it from prior paired completions.
 * `runTokens` sums ids first seen at or after runStartTs (all ids for run 1;
 * null when a later run's boundary is not found). `lastText` is the last
 * assistant text in this run (after lastPriorCompleteTs when the boundary is
 * missing). `model` is the last `message.model` that is not `<synthetic>`.
 *
 * A negative, non-numeric or empty usage block never counts as parsed; a
 * transcript with none yields tokens null plus a note, never a zero fill.
 * `readError` is set (to the same note) only when the file itself could not
 * be read - not found, or at/above the cap.
 * Malformed lines mixed with valid ones are skipped undisclosed (the
 * documented blemish in this module's header).
 */
function scanTranscript(transcriptPath, lastPriorCompleteTs, maxBytes) {
  const cap = maxBytes || MAX_TRANSCRIPT_BYTES;
  const blank = {
    runStartTs: null, runTokens: null, lastText: null,
    attributionAgent: null, firstTimestamp: null, firstUserText: null,
  };
  const failed = (note) => ({ ...blank, tokens: null, tokensNote: note, model: null, modelNote: note, readError: note });

  let stat;
  try { stat = fs.statSync(transcriptPath); } catch (_) { return failed('unavailable (transcript not found)'); }
  if (!stat.isFile()) return failed('unavailable (transcript not found)');
  if (stat.size >= cap) return failed('skipped (transcript too large)');

  const priorMs = tsMs(lastPriorCompleteTs);
  const usageById = new Map();
  const toolUseIds = new Set();
  let noIdCounter = 0;
  let model = null;
  let attributionAgent = null;
  let firstTimestamp = null;
  let firstUserText = null;
  let prevDialog = null;
  let runStartTs = null;
  let lastText = null;

  const res = streamLines(transcriptPath, 0, (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let obj;
    try { obj = JSON.parse(trimmed); } catch (_) { return; }
    if (!obj || typeof obj !== 'object') return;
    const ts = typeof obj.timestamp === 'string' && obj.timestamp.trim() ? obj.timestamp.trim() : null;
    if (firstTimestamp === null && ts) firstTimestamp = ts;
    if (attributionAgent === null && typeof obj.attributionAgent === 'string' && obj.attributionAgent.trim()) {
      attributionAgent = obj.attributionAgent.trim();
    }
    const message = obj.message && typeof obj.message === 'object' ? obj.message : null;

    if (obj.type === 'user') {
      if (firstUserText === null) {
        const text = extractAssistantText(message);
        if (text) firstUserText = text;
      }
      const content = message ? message.content : null;
      // Compaction summaries and image-only records never start a run, and
      // are transparent: the next real user record still "follows" the turn end.
      if (obj.isCompactSummary || isImageOnly(content)) return;
      if (priorMs !== null && runStartTs === null && prevDialog && prevDialog.type === 'assistant'
          && !isToolResult(content)) {
        const pm = prevDialog.message || {};
        const ended = pm.stop_reason === 'end_turn' || pm.stop_reason === 'stop_sequence'
          || ((pm.stop_reason === null || pm.stop_reason === undefined) && !toolUseIds.has(pm.id));
        const endMs = tsMs(prevDialog.timestamp);
        const candMs = tsMs(ts);
        if (ended && endMs !== null && candMs !== null && endMs <= priorMs && priorMs <= candMs) runStartTs = ts;
      }
      prevDialog = obj;
      return;
    }
    if (obj.type !== 'assistant') return;
    prevDialog = obj;
    if (!message) return;
    const id = typeof message.id === 'string' && message.id ? message.id : `__noid_${noIdCounter++}`;
    if (Array.isArray(message.content) && message.content.some((b) => b && b.type === 'tool_use')) toolUseIds.add(id);
    if (typeof message.model === 'string' && message.model.trim() && message.model.trim() !== '<synthetic>') {
      model = message.model.trim();
    }
    const bands = usageBands(message.usage);
    if (bands) {
      const prior = usageById.get(id);
      usageById.set(id, { bands, firstSeen: prior ? prior.firstSeen : ts });
    }
    const text = extractAssistantText(message);
    if (text) {
      const scopeMs = runStartTs !== null ? tsMs(runStartTs) : priorMs;
      const recMs = tsMs(ts);
      if (scopeMs === null || recMs === null || recMs >= scopeMs) lastText = text;
    }
  }, { flushTail: true });
  if (!res) return failed('unavailable (transcript not found)');

  const all = [...usageById.values()];
  const tokens = all.length ? sumBands(all.map((u) => u.bands)) : null;
  let runTokens = null;
  if (tokens && priorMs === null) {
    runTokens = tokens;
  } else if (tokens && runStartTs !== null) {
    const startMs = tsMs(runStartTs);
    runTokens = sumBands(all.filter((u) => { const m = tsMs(u.firstSeen); return m !== null && m >= startMs; })
      .map((u) => u.bands));
  }
  return {
    tokens,
    tokensNote: tokens ? null : 'unavailable (transcript unreadable)',
    model,
    modelNote: model ? null : 'unavailable (transcript unreadable)',
    runStartTs, runTokens, lastText, attributionAgent, firstTimestamp, firstUserText, readError: null,
  };
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
// preceding clause is prose, not part of the format contract. Both the
// line-anchored regexes below and the substring fallback honour this: each
// side matches only the SHORT literal, symmetrically. An earlier revision
// made the granted side require the full two-sentence form; that silently
// made the "No unresolved ..." clause load-bearing, contradicting this
// comment and leaving a bare `Sign-off granted.` verdict line unmatched.
const _SIGNOFF_GRANTED_LITERAL = 'Sign-off granted.';
const _SIGNOFF_WITHHELD_LITERAL = 'Sign-off withheld.';
// Markers that may precede content on a line, in any combination:
// indentation, blockquote carets, an ATX heading, and a bullet or numbered
// list item. Shared by the verdict regexes AND the fence regex - a fence
// opened inside a list item or blockquote must be tracked, or every line
// after it is mis-bucketed.
const _LINE_MARKER_PREFIX = '^[ \\t]*(?:>[ \\t]*)*(?:#{1,6}[ \\t]+)?(?:(?:[-*+]|\\d+[.)])[ \\t]+)?';
// A verdict line may additionally be bold-wrapped, with or without a space
// between the `**` and the literal.
const _VERDICT_LINE_PREFIX = _LINE_MARKER_PREFIX + '(?:\\*\\*[ \\t]*)?';
// The granted verdict's mandated line opens with a prose clause ("No
// unresolved Critical or Major findings.") before the literal, where the
// withheld line opens with its literal directly. That clause is therefore
// OPTIONAL here, not required: the short literal stays the only token
// either side matches on - honouring the comment above - while the
// canonical two-sentence line and a bare `Sign-off granted.` line both
// anchor. Requiring the clause instead would leave the bare form unmatched
// and bias every ambiguous case toward withheld.
const _SIGNOFF_GRANTED_CLAUSE = '(?:No unresolved Critical or Major findings\\.[ \\t]*(?:\\*\\*)?)?';
const _SIGNOFF_GRANTED_LINE_RE = new RegExp(
  _VERDICT_LINE_PREFIX + _SIGNOFF_GRANTED_CLAUSE + 'Sign-off granted\\.');
const _SIGNOFF_WITHHELD_LINE_RE = new RegExp(_VERDICT_LINE_PREFIX + 'Sign-off withheld\\.');
// Opening/closing marker of a fenced code block (``` or ~~~), carrying the
// same marker prefixes a verdict line may carry. The marker must be the
// LAST content on the line, optionally followed by a language tag (which
// cannot itself contain a fence character). Without that end anchor an
// inline code span that opens and closes on one line - "- ```inline```
// code", "1. ```x``` y", "# ```z" - would toggle fence state, and an odd
// number of such lines mis-buckets every line after it.
const _CODE_FENCE_RE = new RegExp(
  _LINE_MARKER_PREFIX + '(?:```|~~~)[ \\t]*[A-Za-z0-9_+.-]*[ \\t]*$');

/**
 * Resolve the verdict from a Skeptic's last assistant message.
 *
 * The rule is deliberately ORDER-FREE, because document order cannot tell
 * a real verdict from a quoted one under both template shapes at once:
 * the verdict-first template (current) puts the real verdict at the TOP of
 * the block, the verdict-last template (superseded, but still emitted by
 * any agent whose adapter/skill copy has not been re-installed yet - the
 * same per-machine dormancy gap AGENTS.md documents for hook snapshots)
 * puts it at the BOTTOM. A first-wins rule mis-scores the second shape and
 * a last-wins rule mis-scores the first, so neither is usable during the
 * rollout window when both shapes coexist.
 *
 * Instead: consider only literals that BEGIN their own line, and resolve
 * in two tiers - UNFENCED lines first, then FENCED lines. Fencing does NOT
 * discriminate a decoy from a real verdict, and must not be read that way:
 * skeptic.md displays the sign-off template as a fenced block, so agents
 * routinely emit their own real block fenced. Treating "fenced" as
 * "quoted" therefore discards the dominant emission shape and silently
 * falls through to the substring rule this function exists to replace.
 * What the tiering actually buys is precedence: when a quoted template
 * excerpt and a real verdict coexist, the excerpt is nearly always the
 * fenced one, so an unfenced verdict outranks a fenced one - while a
 * wholly-fenced block still resolves, from tier 2, rather than falling
 * through.
 *
 * Within each tier, if BOTH verdicts appear, withheld wins: recording a
 * blocking review as a pass is the failure furthest from Pillar 2, so the
 * ambiguous case fails safe toward the blocking verdict.
 *
 * Two known, accepted mis-scores. Both need a line that OPENS with a
 * verdict literal; a literal appearing anywhere later on a line is
 * unaffected.
 *
 * (1) SAFE direction. Because a verdict line may be bulleted, a granted
 * block whose findings list contains a bullet that itself starts with the
 * withheld literal (e.g. "- Sign-off withheld. is still the wording in the
 * stale copy (a.md:12)") resolves withheld. A real granted review recorded
 * as blocking - noisy, but it over-reports blocking rather than
 * under-reporting it, which is the trade this function is calibrated for.
 *
 * (2) UNSAFE direction, disclosed deliberately. Because tier 1 resolves
 * before tier 2, a FENCED real withheld block loses to any UNFENCED line
 * that starts with the granted literal - e.g. a closing recap after the
 * fenced block: "Sign-off granted. would require the Major above to be
 * resolved first." That records a blocking review as a pass. It is the
 * price of tier-1 precedence, which is what makes the far more common
 * quoted-excerpt case come out right; narrowing it would need to
 * distinguish a recap from a verdict, which no line-shape rule can do.
 * Prefer withheld-wins ACROSS tiers only if this shape is ever measured
 * in the wild - it is not, today.
 *
 * Returns true (granted), false (withheld), or null (no line-anchored
 * verdict in either tier - caller falls back to the substring rule).
 */
function _resolveVerdictLineAnchored(text) {
  let inFence = false;
  const unfenced = { granted: false, withheld: false };
  const fenced = { granted: false, withheld: false };
  for (const line of text.split('\n')) {
    if (_CODE_FENCE_RE.test(line)) {
      inFence = !inFence;
      continue;
    }
    const tier = inFence ? fenced : unfenced;
    if (_SIGNOFF_WITHHELD_LINE_RE.test(line)) tier.withheld = true;
    else if (_SIGNOFF_GRANTED_LINE_RE.test(line)) tier.granted = true;
  }
  for (const tier of [unfenced, fenced]) {
    if (tier.withheld) return false;
    if (tier.granted) return true;
  }
  return null;
}

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
 * Verdict resolution is ORDER-FREE and tiered: among verdict literals that
 * begin their own line, unfenced lines are consulted first and fenced
 * lines second, withheld winning over granted within each tier. This
 * scores the verdict-first and verdict-last template shapes identically,
 * which matters while both are in the wild during adapter rollout, and
 * resolves a wholly-fenced block (the shape agents copy from skeptic.md)
 * rather than dropping it. See _resolveVerdictLineAnchored. Only when
 * neither tier yields a verdict does the older substring "last literal
 * wins" rule apply as a fallback.
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
function parseSkepticSignoff(lastAssistantText) {
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

  // Verdict resolution: see _resolveVerdictLineAnchored for the rule and
  // why it is deliberately order-free (it must score the verdict-first and
  // verdict-last template shapes correctly at the same time).
  let signedOff = _resolveVerdictLineAnchored(lastAssistantText);
  if (signedOff === null) {
    // Fallback: no line-anchored verdict in EITHER tier (e.g. a Skeptic
    // that inlined its verdict into a sentence). Retain the
    // pre-existing substring "last literal wins" behaviour rather than
    // dropping to a calibrationNote, so this stays a strict superset of
    // prior coverage.
    const lastWithheldIdx = lastAssistantText.lastIndexOf(_SIGNOFF_WITHHELD_LITERAL);
    const lastGrantedIdx = lastAssistantText.lastIndexOf(_SIGNOFF_GRANTED_LITERAL);
    if (lastWithheldIdx === -1 && lastGrantedIdx === -1) {
      return { calibrationNote: 'unavailable (no sign-off found in transcript)' };
    }
    signedOff = lastGrantedIdx > lastWithheldIdx;
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
// value. Round-4 fix (Minor): the character class includes `~` and `^`,
// ordinary git revision-suffix syntax (`<sha>~1..<sha>`, `<sha>^..<sha>`)
// that this repo's own briefs use - the pre-fix class silently rejected
// these as NOTE_NO_RANGE. Widening still cannot admit anything the
// leading-`-` option-shape guard below or execFileSync (no shell, so
// `~`/`^` carry no injection meaning) would mishandle - re-verified by
// the option-shape and injection probes in the m1 regression test after
// this change.
//
// DELIBERATELY DOES NOT mirror the round-cap hook's `_DIFF_RANGE_RE`
// (round-6 correction - round-5 M3 claimed the two "mirror" each other
// and widened the Python regex to match; that claim was false and the
// widening was reverted). This regex's only consumer is
// `resolveDiffLines()` below - a pure `diff --shortstat` line-count
// measurement with no round-cap consequence, so admitting `~`/`^` here
// is safe. The round-cap hook's `_DIFF_RANGE_RE` feeds
// `_normalize_diff_identity()`, which derives the round-cap UNIT KEY;
// admitting `~`/`^` there collapsed every `<x>~n..HEAD` / `<x>^..HEAD`
// value onto the single literal token "HEAD" regardless of `<x>`,
// colliding distinct units onto one shared round counter (measured:
// `skeptic-round-HEAD-7138a51661.json`). The two regexes have different
// jobs and must be evaluated independently against their own consumer's
// failure mode - a regex-vs-regex parity claim proves nothing about
// either consumer's decision-level behavior.
const _DIFF_RANGE_JS_RE = /^(?:git diff[ \t]+)?([A-Za-z0-9._/^~-]+)[ \t]*(\.{2,3})[ \t]*([A-Za-z0-9._/^~-]+)/i;
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
  const NOTE_OPTION_SHAPED = 'unavailable (diff range rejected: option-shaped value)';
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
  // Round-3 fix (m1): a leading `-` makes rangeArg option-shaped to git
  // (e.g. a prompt-derived "-O/etc/passwd..HEAD" value), which git would
  // otherwise consume as a flag rather than a ref - reject it before the
  // subprocess call rather than reporting a fabricated 0. No command
  // injection risk either way (execFileSync, no shell), but a
  // fabricated-0 result violates this file's own never-fabricate
  // discipline. Round-4 fix (M2 Minor): a distinct note, not NOTE_NO_RANGE
  // - a range WAS found and then rejected as option-shaped, which is a
  // different miss cause than no range being found at all; conflating the
  // two made them indistinguishable in calibration_note for any later
  // analyst, cutting against R6.
  if (rangeArg.startsWith('-')) return { diffLines: null, diffLinesNote: NOTE_OPTION_SHAPED };

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
 * silently described the WRONG round - confidently, with no note.
 *
 * Round-3 fix (m2): the legacy live-read fallback (for a pre-round-2 bare
 * `unit_key` STRING index entry, or a pinned-but-non-positive value) is
 * REMOVED, not merely narrowed. It was untested (relaxing the `> 0` guard
 * below to a bare not-null check left the calibration suite fully green,
 * since nothing exercised the pinned path with a non-positive value), and
 * it is dead in practice - `origin/main` has zero occurrences of
 * `skeptic-tuid-index` as a bare-string writer, so a bare-string entry can
 * only exist on a machine that ran the unmerged round-1 commit. Worse, if
 * it were ever live, it would silently reintroduce the exact round-1
 * wrong-round defect (a live `round_count` read at completion time can
 * describe a different round than the one this spawn actually ran at)
 * with no calibration_note disclosing the fallback occurred. Treating any
 * entry without a pinned positive integer `iteration` as a miss is
 * strictly safer and requires no state-file read of its own.
 *
 * Returns { unitKey, iteration } on a full hit (a pinned-shape index
 * entry with a positive integer `iteration`), or null on ANY miss: no
 * index, no entry for this toolUseId, a legacy bare-string entry, or a
 * pinned `iteration` that is missing, non-numeric, zero, or negative.
 * `iteration <= 0` is always treated as a miss: the round-cap hook never
 * persists `round_count: 0` on an allowed spawn, so a non-positive value
 * can only come from a hand-edited index and reporting it verbatim would
 * be a zero that looks like a real measurement.
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
  if (!entry || typeof entry !== 'object' || typeof entry.unit_key !== 'string' || !entry.unit_key) {
    // Covers: no entry, and the legacy bare-string shape (m2: no longer
    // given a live-read fallback).
    return null;
  }
  const pinnedIteration = typeof entry.iteration === 'number' ? entry.iteration : null;
  if (pinnedIteration === null || pinnedIteration <= 0) return null;

  return { unitKey: entry.unit_key, iteration: pinnedIteration };
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
 * Find the spawn_start this SubagentStop completes, or null.
 *
 * DS-246 order:
 *   1. Exact `data.tool_use_id` match over ALL of this session's hook
 *      spawn_starts, including ones already paired - a resumed agent keeps
 *      its original tool_use_id, so its k-th stop must reach the same start.
 *      pairMethod is 'resume' when that start already has paired hook
 *      completions, else 'tool_use_id'.
 *   2. Otherwise FIFO over unpaired starts whose `agent` equals agentType
 *      ('fifo_same_agent'). With no agentType there is no FIFO: an
 *      unlabelled stop is left unpaired rather than stealing another
 *      spawn's start.
 * Session scoping is REQUIRED: without a sessionId, or for a start with no
 * `data.session_uuid`, nothing matches (degrades to unpaired, never an
 * unscoped cross-session guess).
 *
 * Returns {spawnId, startTs, agent, toolUseId, taskId, pairMethod,
 * priorCompletes[]} where priorCompletes are the hook spawn_completes
 * already paired to that start - run() numbers the run from them.
 */
function findMatch(events, sessionId, toolUseId, agentType) {
  if (!sessionId) return null;

  const completesBySpawn = new Map();
  const pairedIds = new Set();
  for (const ev of events) {
    if (!ev || ev.event !== 'spawn_complete') continue;
    const d = ev.data || {};
    if (!d.paired_spawn_id) continue;
    pairedIds.add(d.paired_spawn_id);
    if (d.source !== 'hook') continue;
    if (!completesBySpawn.has(d.paired_spawn_id)) completesBySpawn.set(d.paired_spawn_id, []);
    completesBySpawn.get(d.paired_spawn_id).push(ev);
  }

  const starts = [];
  for (const ev of events) {
    if (!ev || ev.event !== 'spawn_start') continue;
    const d = ev.data || {};
    if (d.source !== 'hook' || !d.spawn_id) continue;
    if (!d.session_uuid || d.session_uuid !== sessionId) continue;
    starts.push({
      spawnId: d.spawn_id, startTs: ev.ts, agent: ev.agent, toolUseId: d.tool_use_id || null,
      taskId: typeof ev.task_id === 'string' && ev.task_id ? ev.task_id : null,
    });
  }

  const withPrior = (s, method) => {
    const priorCompletes = completesBySpawn.get(s.spawnId) || [];
    const pairMethod = method === 'tool_use_id' && priorCompletes.length ? 'resume' : method;
    return { ...s, pairMethod, priorCompletes };
  };

  if (toolUseId) {
    const exact = starts.find((s) => s.toolUseId === toolUseId);
    if (exact) return withPrior(exact, 'tool_use_id');
  }
  if (!agentType) return null;
  const fifo = starts.find((s) => !pairedIds.has(s.spawnId) && s.agent === agentType);
  return fifo ? withPrior(fifo, 'fifo_same_agent') : null;
}

/**
 * DS-246 internal-agent test: Claude Code also fires SubagentStop for its
 * own internal agents, which carry an empty or absent `agent_type` and no
 * sidecar. Those must not consume a real spawn's start. Any other stop -
 * including one with no resolvable transcript - is a real spawn. `sidecar`
 * is the resolved sidecar PATH: a sidecar file that exists but fails to
 * parse still marks a real spawn.
 */
function isInternalAgent(payload, sidecar) {
  const t = payload ? payload.agent_type : undefined;
  return (t === undefined || t === null || t === '') && !sidecar;
}

// qa-engineer's pointer return (content/agents/qa-engineer.md) opens with a
// top-level `result:` line; criteria[] entries repeat `result:` indented, so
// only an unindented line counts. BLOCKED is accepted although the pointer
// enum omits it, because the same file's "Overall result rules" define it as
// an overall result - dropping it would leave a real run unrecorded.
const _QA_RESULT_RE = /^result:[ \t]*(PASS|FAIL|PARTIAL|INCONCLUSIVE|BLOCKED)[ \t]*$/gm;
const _QA_BLOCKING_RE = /^blocking_count:[ \t]*(\d+)[ \t]*$/gm;

/**
 * Parse one qa-engineer run's last assistant text. Returns
 * {qaResult, qaBlockingCount|null} from the LAST matching top-level lines,
 * or {qaResultNote} when no result line is present.
 */
function parseQaResult(runLastText) {
  const text = typeof runLastText === 'string' ? runLastText : '';
  const results = [...text.matchAll(_QA_RESULT_RE)];
  if (!results.length) return { qaResultNote: 'unavailable (no top-level result line in run)' };
  const counts = [...text.matchAll(_QA_BLOCKING_RE)];
  return {
    qaResult: results[results.length - 1][1],
    qaBlockingCount: counts.length ? Number(counts[counts.length - 1][1]) : null,
  };
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
 * spawn_complete (or, for a harness-internal agent, subagent_stop_internal)
 * event to the primary checkout's events.jsonl, always exits 0.
 */
async function run() {
  try {
    const raw = await readStdinGuarded();
    let payload;
    try { payload = JSON.parse(raw); } catch (_) { process.exit(0); }

    const cwd = nonBlank(payload && payload.cwd);
    if (!cwd) process.exit(0);
    const sessionId = nonBlank(payload.session_id);
    // Measured (DS-178) null on 612/612 real SubagentStop payloads; kept as a
    // last-resort pairing input behind the sidecar's own toolUseId.
    const payloadToolUseId = nonBlank(payload.tool_use_id);
    const agentId = nonBlank(payload.agent_id);

    const mainRoot = resolveMainRepoRoot(cwd).root;
    const eventsPath = spawnEventsPath(cwd);
    const agenticDir = path.dirname(eventsPath);
    fs.mkdirSync(agenticDir, { recursive: true });
    const nowIso = new Date().toISOString();
    const append = (event) => fs.appendFileSync(eventsPath, JSON.stringify(event) + '\n', 'utf8');

    let files = { transcriptPath: null, transcriptSource: null, sidecarPath: null, tried: [] };
    let sidecar = null;
    let configDir = null;
    try {
      configDir = resolveClaudeConfigDir();
      files = resolveSubagentFiles(configDir, payload, cwd, mainRoot, sessionId, agentId);
      sidecar = readSidecarFile(files.sidecarPath);
    } catch (_) {
      sidecar = null;
    }

    if (isInternalAgent(payload, files.sidecarPath)) {
      append({
        ts: nowIso, phase: 'hook', event: 'subagent_stop_internal', agent: null, task_id: null,
        data: {
          source: 'hook', telemetry_v: 2, session_uuid: sessionId, agent_id: agentId,
          reason: payload.agent_type === '' ? 'agent_type empty, no sidecar' : 'agent_type absent, no sidecar',
        },
      });
      process.exit(0);
    }

    const payloadAgentType = nonBlank(payload.agent_type);
    const matchToolUseId = (sidecar && sidecar.toolUseId) || payloadToolUseId;
    // Label precedence: sidecar agentType -> payload agent_type -> matched
    // start's agent -> "unknown"; agent_source names whichever supplied it.
    const labelType = (sidecar && sidecar.agentType) || payloadAgentType;
    const match = findMatch(readRecentEvents(eventsPath), sessionId, matchToolUseId, labelType);

    let agentName = 'unknown';
    let agentSource = 'unknown';
    if (sidecar && sidecar.agentType) {
      agentName = sidecar.agentType;
      agentSource = 'sidecar';
    } else if (payloadAgentType) {
      agentName = payloadAgentType;
      agentSource = 'payload';
    } else if (match && match.agent) {
      agentName = match.agent;
      agentSource = 'paired_start';
    }

    const priorCompletes = match ? match.priorCompletes : [];
    const runIndex = match ? priorCompletes.length + 1 : null;
    const lastPriorCompleteTs = priorCompletes.reduce(
      (acc, ev) => ((typeof ev.ts === 'string' && (!acc || ev.ts > acc)) ? ev.ts : acc), null);

    let scan = null;
    let tokensNote = null;
    try {
      if (files.transcriptPath) {
        scan = scanTranscript(files.transcriptPath, lastPriorCompleteTs);
        tokensNote = scan.tokensNote;
      } else {
        tokensNote = `unavailable (transcript not found; tried: ${files.tried.join(', ') || 'none'})`;
      }
    } catch (_) {
      scan = null;
      tokensNote = 'unavailable (transcript scan error)';
    }

    let model = null;
    let modelSource = null;
    let modelNote = null;
    if (scan && scan.model) {
      model = scan.model;
      modelSource = 'transcript';
    } else if (sidecar && sidecar.model && sidecar.model !== 'inherit') {
      model = sidecar.model;
      modelSource = 'sidecar_alias';
    } else {
      modelNote = (scan && scan.modelNote) || tokensNote;
    }

    // Wall covers THIS run only: run 1 from the spawn_start, a later run from
    // its resume boundary in the transcript (idle time between runs excluded).
    let runStartTs = null;
    let wallSeconds = null;
    let wallNote = null;
    let suspect = false;
    if (match) {
      if (runIndex === 1) {
        runStartTs = match.startTs;
      } else if (scan && scan.runStartTs) {
        runStartTs = scan.runStartTs;
      } else {
        wallNote = files.transcriptPath
          ? 'unavailable (resume boundary not found in transcript)'
          : 'unavailable (transcript not found)';
      }
      const startMs = runStartTs ? Date.parse(runStartTs) : NaN;
      const nowMs = Date.parse(nowIso);
      if (!Number.isNaN(startMs) && nowMs >= startMs) {
        wallSeconds = Number(((nowMs - startMs) / 1000).toFixed(3));
        if (wallSeconds > MAX_SANE_WALL_SECONDS) {
          wallSeconds = null;
          suspect = true;
        }
      }
    }

    const cwdAgenticDir = path.join(resolveAgenticCwd(cwd), '.agentic');
    let ticket;
    if (match && match.taskId) {
      ticket = { ticketId: match.taskId, source: 'paired_start', note: null };
    } else {
      ticket = resolveActiveTicket({
        agenticDir: cwdAgenticDir,
        sessionId,
        transcriptPath: nonBlank(payload.transcript_path),
        toolUseId: matchToolUseId,
        spawnDescription: sidecar ? sidecar.description : '',
      });
    }

    // Calibration fields: Skeptic only. calibration_note is one shared field;
    // each miss contributes its own labelled clause, joined with "; ".
    let calibrationFields = {};
    const calibrationNoteParts = [];
    if (agentName === 'skeptic') {
      try {
        const roundState = readRoundState(cwdAgenticDir, matchToolUseId)
          || readRoundState(agenticDir, matchToolUseId);
        if (roundState) {
          calibrationFields.unit_key = roundState.unitKey;
          calibrationFields.iteration = roundState.iteration;
        } else {
          calibrationNoteParts.push('unit_key/iteration: unavailable (tuid-index miss)');
        }

        let signoff;
        if (!files.transcriptPath || !scan) signoff = { calibrationNote: 'unavailable (transcript not found)' };
        else if (scan.readError) signoff = { calibrationNote: scan.readError };
        else signoff = parseSkepticSignoff(scan.lastText);
        if (Object.prototype.hasOwnProperty.call(signoff, 'findingsCount')) {
          calibrationFields.findings_count = signoff.findingsCount;
          calibrationFields.signed_off = signoff.signedOff;
          if (signoff.findingsParseAmbiguous) calibrationFields.findings_parse_ambiguous = true;
        } else {
          calibrationNoteParts.push(`findings_count/signed_off: ${signoff.calibrationNote}`);
        }

        const diffResult = resolveDiffLines(cwd, scan ? scan.firstUserText : null);
        if (diffResult.diffLines !== null) {
          calibrationFields.diff_lines = diffResult.diffLines;
        } else {
          calibrationNoteParts.push(`diff_lines: ${diffResult.diffLinesNote}`);
        }
      } catch (_) {
        calibrationFields = {};
        calibrationNoteParts.length = 0;
        calibrationNoteParts.push('unavailable (calibration resolution error)');
      }
    }
    const calibrationNote = calibrationNoteParts.length ? calibrationNoteParts.join('; ') : null;

    let qaFields = {};
    if (agentName === 'qa-engineer') {
      const qa = scan && scan.lastText ? parseQaResult(scan.lastText)
        : { qaResultNote: tokensNote || 'unavailable (no assistant text in run)' };
      qaFields = qa.qaResult
        ? { qa_result: qa.qaResult, ...(qa.qaBlockingCount !== null ? { qa_blocking_count: qa.qaBlockingCount } : {}) }
        : { qa_result_note: qa.qaResultNote };
    }

    // Cross-check (DS-178 m1): the transcript's own attributionAgent stamp
    // disagreeing with the resolved label can reveal a pairing/sidecar bug.
    const attributionAgent = scan ? scan.attributionAgent : null;
    const agentNote = (attributionAgent && agentName !== 'unknown' && attributionAgent !== agentName)
      ? `attributionAgent ("${attributionAgent}") disagrees with resolved agent ("${agentName}")`
      : null;

    const tokens = scan && scan.tokens ? scan.tokens : null;
    const runTokens = scan && scan.runTokens ? scan.runTokens : null;
    append({
      ts: nowIso,
      phase: 'hook',
      event: 'spawn_complete',
      agent: agentName,
      task_id: ticket.ticketId,
      data: {
        source: 'hook',
        telemetry_v: 2,
        session_uuid: sessionId,
        tool_use_id: matchToolUseId,
        agent_id: agentId,
        agent_source: agentSource,
        ...(agentNote ? { agent_note: agentNote } : {}),
        task_id_source: ticket.source,
        ...(ticket.note ? { task_id_note: ticket.note } : {}),
        paired_spawn_id: match ? match.spawnId : null,
        pair_method: match ? match.pairMethod : null,
        run_index: runIndex,
        run_start_ts: runStartTs,
        wall_seconds: wallSeconds,
        ...(wallNote ? { wall_note: wallNote } : {}),
        suspect,
        transcript_source: files.transcriptSource,
        ...(tokens ? { tokens } : { tokens_note: tokensNote || 'unavailable (transcript unreadable)' }),
        ...(runTokens ? { run_tokens: runTokens } : {}),
        ...(model ? { model, model_source: modelSource } : { model_note: modelNote || 'unavailable (transcript unreadable)' }),
        ...qaFields,
        ...calibrationFields,
        ...(calibrationNote ? { calibration_note: calibrationNote } : {}),
      },
    });

    process.exit(0);
  } catch (_) {
    // Fully fail-open: any unexpected error -> silent exit 0.
    process.exit(0);
  }
}

if (require.main === module) {
  run().catch(() => process.exit(0));
}

module.exports = { scanTranscript, findMatch, isInternalAgent, parseQaResult, resolveSubagentFiles };
