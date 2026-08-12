/**
 * Purpose: OpenCode plugin that writes this session's `.agentic/context.d/`
 *          activity shard and recomposes the derived `.agentic/context.md`
 *          rollup on every busy->idle transition (`session.idle`), runs full
 *          Stop-hook-equivalent finalization (loop-state, batch-state,
 *          session_total, shard + rollup) once per session when the user invokes
 *          `/ds-wrap` (`command.executed`), and emits a skill-load instruction
 *          on `session.created` when `skill_auto_load: true` is set in
 *          `~/.config/opencode/agentic-engineering.json`.
 *
 * Public API: SessionContextPlugin — exported plugin function for OpenCode.
 *
 * Upstream deps: Bun runtime APIs ($, Bun.file, Bun.write). Node built-in
 *                path. Node fs/promises (appendFile, rename). OpenCode SDK
 *                client (client.app.log, client.session.prompt).
 *
 * Downstream consumers: OpenCode plugin system (loaded from
 *                        ~/.config/opencode/plugins/ or .opencode/plugins/).
 *
 * Failure modes: Silent failure on every write path. Per-process
 *                deduplication guard (global Symbol) prevents double
 *                handling when OpenCode loads the plugin from multiple
 *                discovery paths or fans out bus events twice. The plugin
 *                uses two distinct OpenCode dispatch mechanisms:
 *                  1. Direct trigger hook `tool.execute.after` — invoked by
 *                     name with (input, output) by the runtime's `trigger`
 *                     dispatcher. Used to accumulate file paths and tools.
 *                  2. Generic `event` hook — invoked for EVERY bus event
 *                     (session.idle, command.executed, session.created,
 *                     session.compacted, etc.); the handler discriminates
 *                     by `event.type` internally. Bus events read their data
 *                     from `event.properties`, not from a top-level
 *                     destructure.
 *                session.created fires once per session; the handler reads
 *                `~/.config/opencode/agentic-engineering.json` for
 *                `skill_auto_load` and emits a skill-load instruction prompt
 *                when true. Missing config or a prompt failure is logged and
 *                swallowed.
 *                session.idle does the shard write + rollup recompose only — no
 *                loop-state, batch-state, or events.jsonl writes happen there.
 *                Finalization writes (loop-state, batch-state,
 *                events.jsonl) run only on /ds-wrap completion via
 *                command.executed and are independent and best-effort: a
 *                failure in one does not affect the others. writeLoopState now
 *                carries the same session_id ownership check as
 *                writeBatchState (absence/null/empty session_id on disk
 *                proceeds; only a positively-differing session_id skips),
 *                mirroring hooks/lib/state-mark.js markInterrupted's polarity
 *                on the Claude Code side. This plugin's cadence is UNCHANGED
 *                by that addition: it already fires this write once per
 *                session on command.executed, not once per turn, so it never
 *                had the Claude Stop hook's per-turn-interrupt bug. A
 *                diagnostic session.prompt (noreply: true) fires once on
 *                /ds-wrap. The prompt is fire-and-forget (no await) so it
 *                cannot block the handler even if delivery hangs. cwd values
 *                with path-traversal components are rejected by all three
 *                writers (defence in depth). The per-session-once invariant
 *                for session_total relies on the user invoking /ds-wrap;
 *                OpenCode does not expose a guaranteed shutdown hook from
 *                plugins.
 *                SHARD MODEL (DS-107): this plugin no longer writes
 *                `.agentic/context.md` directly. It writes
 *                `.agentic/context.d/<session_id>.md` (session-private, so
 *                concurrent writers cannot collide) and then recomposes
 *                `context.md` as a PURE FUNCTION of (`_wrap.md`, shard set).
 *                It was moved into scope for that change specifically because it
 *                was the only unported adapter that ACTIVELY DESTROYED state:
 *                the retired refreshWrapActivityBlock recognised the /ds-wrap
 *                header, sliced at the FIRST `## Session Activity` sentinel, and
 *                wrote back exactly ONE block - on an N-session rollup that
 *                destroys N-1 sessions' activity. Every other unported adapter
 *                merely overwrites, and its content is recovered as
 *                `_foreign.md`. The rollup write is deliberately LOCK-FREE:
 *                because the file is derivable, a lost update self-heals on the
 *                next turn instead of losing data. Do not add a lock check.
 *                SECOND INTENTIONAL PARALLEL IMPLEMENTATION: the shard/rollup
 *                composer below duplicates hooks/lib/context-rollup.js for the
 *                same reason writeLoopState duplicates state-mark.js - this is a
 *                standalone Bun plugin loaded from ~/.config/opencode/plugins/
 *                where the repo's hooks/ tree is not reachable. THE TWO MUST
 *                CHANGE TOGETHER IN THE SAME PR; nothing mechanical enforces it,
 *                and `check-adapter-sync` cannot see this file at all (it is
 *                hand-authored and regenerated by no build script).
 *                WHAT MUST STAY IN SYNC IS THE NORMATIVE PROCEDURE, NOT JUST THE
 *                CONSTANTS. Scoping this note to the constants alone is how the
 *                first version of this port shipped WITHOUT stripDerivedBlocks
 *                and seeded `_wrap.md` verbatim, making derived cruft permanent.
 *                The list, non-exhaustive by intent - when in doubt, diff the
 *                two files:
 *                  - constants ACTIVITY_SENTINEL, DERIVED_MARKER,
 *                    ACTIVITY_REGION_SIGNATURES, DERIVED_NOTICE_SIGNATURES
 *                  - findActivityRegionIndex (LAST signature-matched sentinel)
 *                  - stripDerivedBlocks (activity regions marked OR unmarked,
 *                    plus the one-time notices, dropped not re-emitted)
 *                  - the migration discriminator and the byte-exact lines 1-2 rule
 *                  - foreign-preservation classification
 *                  - ABORT-BEFORE-OVERWRITE on a failed seed or preservation write
 *                  - shard ordering (mtime DESC, session_id ASC) and retention
 *                INTENTIONAL PARALLEL IMPLEMENTATION: writeLoopState's
 *                candidate resolution (resolveLoopStateCandidates) duplicates
 *                the expansion rules of hooks/lib/state-mark.js's
 *                _resolveCandidates - the per-ticket keyed
 *                `.agentic/loop-state-<LOOP_KEY>.json` siblings newest-mtime-first
 *                capped at 100, plus the ALWAYS-present legacy
 *                `.agentic/loop-state.json`. This plugin deliberately does NOT
 *                `require` that lib: it is a standalone Bun plugin loaded from
 *                ~/.config/opencode/plugins/ where the repo's hooks/ tree is
 *                not reachable. The duplication is therefore accepted, and
 *                THE TWO MUST CHANGE TOGETHER IN THE SAME PR - nothing
 *                mechanical enforces it. Any change to the candidate rules in
 *                hooks/lib/state-mark.js must be mirrored here and vice versa.
 *
 * Performance: ~5-20 ms typical on session.idle (one git status subprocess);
 *              slightly heavier on /ds-wrap completion (multiple writes, one
 *              full-file read+parse of events.jsonl for the session_total
 *              rollup, one .agentic/ readdir plus one stat per keyed
 *              loop-state candidate, capped at 100). The generic `event` hook fires for every bus event
 *              in the session (potentially hundreds per session); the
 *              unmatched-type early-return must stay cheap (a single
 *              property read and three string comparisons, no allocations,
 *              no logs).
 */

import path from 'path';
import { appendFile, rename, readdir, stat } from 'fs/promises';
import type { Plugin } from "@opencode-ai/plugin";

interface ToolExecuteArgs {
  file_path?: string;
  path?: string;
  command?: string;
}

const ACTIVITY_SENTINEL = '\n\n---\n\n## Session Activity\n';

/**
 * Written in the ACTIVITY-REGION header, immediately after the sentinel, and
 * NEVER in the file header. Placement is load-bearing: this plugin's own former
 * strip-and-append PRESERVED the file header while replacing the activity
 * region, so a header marker would survive a foreign write, the composer would
 * conclude "this is mine", skip foreign-preservation, and destroy that writer's
 * block. Must stay byte-identical to DERIVED_MARKER in hooks/lib/context-rollup.js.
 */
const DERIVED_MARKER = '<!-- agentic:derived-activity-region v1 -->';

/** Matches SHARD_RETENTION in hooks/lib/context-rollup.js. */
const SHARD_RETENTION = 10;

/** Shard-name fallback when OpenCode gives the idle event no sessionID. */
const FALLBACK_SHARD_ID = 'opencode-session';

/**
 * Signatures identifying the text after a sentinel as a DERIVED activity region
 * rather than curated prose that merely QUOTES the sentinel bytes. Must stay in
 * sync with ACTIVITY_REGION_SIGNATURES in hooks/lib/context-rollup.js.
 */
const ACTIVITY_REGION_SIGNATURES = [
  '<!-- agentic:derived-activity-region',
  '*Derived from .agentic/context.d/',
  '*Auto-appended by Stop hook',
  '*Auto-appended by session idle plugin',
  '*Auto-appended by /ds-wrap finalization',
  '*Auto-updated by session idle plugin',
  '### Recent Messages',
];

/**
 * Leading text of the machine-DERIVED one-time notices that must be stripped
 * from a body before it is seeded into the curated `_wrap.md`. Must stay in sync
 * with DERIVED_NOTICE_SIGNATURES in hooks/lib/context-rollup.js.
 */
const DERIVED_NOTICE_SIGNATURES = [
  'CAPTURE-GAP:',
  '[dinostack] No developer identity set.',
  'WRAP-LOCK-STUCK:',
  '[scaffolding-sync] WARNING:',
];

export const SessionContextPlugin: Plugin = async ({
  directory,
  $,
  client,
}) => {
  const log = async (
    level: "debug" | "info" | "warn" | "error",
    message: string,
    extra: Record<string, any> = {},
  ) => {
    try {
      await client.app.log({
        body: { service: "ae-session-context", level, message, extra },
      });
    } catch (_) {
      // Silent fallback if logging itself fails
    }
  };

  await log("info", "Plugin loaded", { directory: directory || null });

  const filePaths = new Set<string>();
  const toolsUsed = new Set<string>();
  const RECENT_MESSAGES_PLACEHOLDER =
    "(user-message capture unavailable on OpenCode — see plugin manifest)";

  // Per-process deduplication: OpenCode may load the plugin twice (global +
  // project-local discovery paths) or fan out bus events twice. Use a global
  // symbol so only the first instance handles events.
  const PLUGIN_INSTANCE_KEY = Symbol.for("ae-session-context:instance");
  if ((globalThis as any)[PLUGIN_INSTANCE_KEY]) {
    await log("info", "Plugin instance already active, skipping duplicate");
    return {} as any;
  }
  (globalThis as any)[PLUGIN_INSTANCE_KEY] = true;

  /**
   * Aggregate spawn_complete + conductor_direct events from events.jsonl for
   * the current session and append a session_total rollup. Mirrors
   * hooks/stop-context.js writeSessionTotal. Silent failure on every error path.
   */
  async function writeSessionTotal(cwd: string, sessionID: string | null) {
    // M4: Reject cwd values with traversal components before any path join.
    const resolvedCwd = path.resolve(cwd);
    if (resolvedCwd !== cwd) {
      await log(
        "warn",
        "Skipping session_total write: cwd contains traversal components",
        { cwd },
      );
      return;
    }

    const eventsPath = path.join(cwd, ".agentic", "events.jsonl");
    try {
      const eventsFile = Bun.file(eventsPath);
      if (!(await eventsFile.exists())) return;
      const raw = await eventsFile.text();
      if (!raw.trim()) return;

      const lines = raw.split("\n");
      let totalWall = 0;
      let spawnCount = 0;
      const totalTokens: {
        input: number;
        output: number;
        cache_creation: number;
        cache_read: number;
      } = {
        input: 0,
        output: 0,
        cache_creation: 0,
        cache_read: 0,
      };
      const byAgent: Record<
        string,
        {
          spawns: number;
          wall_seconds: number;
          tokens: {
            input: number;
            output: number;
            cache_creation: number;
            cache_read: number;
          };
        }
      > = {};
      const tokenKeys = [
        "input",
        "output",
        "cache_creation",
        "cache_read",
      ] as const;

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        let obj: any;
        try {
          obj = JSON.parse(trimmed);
        } catch (_) {
          continue;
        }
        const ev = obj && obj.event;
        if (ev !== "spawn_complete" && ev !== "conductor_direct") continue;
        const data = (obj && obj.data) || {};
        // Filter to current session when session_uuid is present on the
        // event payload. Events without session_uuid are included
        // unconditionally (tolerant of pre-instrumentation events).
        if (sessionID && data.session_uuid && data.session_uuid !== sessionID) {
          continue;
        }
        const wall = Number(data.wall_seconds) || 0;
        totalWall += wall;
        const tokens = data.tokens || {};
        for (const k of tokenKeys) {
          totalTokens[k] += Number(tokens[k]) || 0;
        }
        if (ev === "spawn_complete") {
          spawnCount += 1;
          const agentName = (obj && obj.agent) || "unknown";
          if (!byAgent[agentName]) {
            byAgent[agentName] = {
              spawns: 0,
              wall_seconds: 0,
              tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
            };
          }
          byAgent[agentName].spawns += 1;
          byAgent[agentName].wall_seconds += wall;
          for (const k of tokenKeys) {
            byAgent[agentName].tokens[k] += Number(tokens[k]) || 0;
          }
        }
      }

      const event = {
        ts: new Date().toISOString(),
        phase: "session_end",
        event: "session_total",
        agent: null,
        task_id: null,
        data: {
          wall_seconds: Number(totalWall.toFixed(3)),
          tokens: totalTokens,
          spawn_count: spawnCount,
          by_agent: byAgent,
          session_uuid: sessionID || null,
        },
      };
      // C3: Use fs/promises.appendFile rather than read-modify-write so
      // concurrent writers cannot lose lines.
      await appendFile(eventsPath, JSON.stringify(event) + "\n");
      await log("info", "Appended session_total", {
        eventsPath,
        spawn_count: spawnCount,
        wall_seconds: Number(totalWall.toFixed(3)),
      });
    } catch (err: any) {
      await log("warn", "Failed to write session_total", {
        eventsPath,
        error: err.message,
      });
    }
  }

  /** Maximum keyed loop-state candidates processed per call, newest-mtime-first. */
  const KEYED_CANDIDATE_CAP = 100;

  /** A per-ticket keyed loop-state sibling: `.agentic/loop-state-<LOOP_KEY>.json`. */
  const KEYED_LOOP_STATE_RE = /^loop-state-.+\.json$/;

  /**
   * Resolve every loop-state candidate under [cwd]/.agentic: the per-ticket
   * keyed siblings `loop-state-<LOOP_KEY>.json` newest-mtime-first (capped at
   * KEYED_CANDIDATE_CAP), then the LEGACY `loop-state.json`.
   *
   * The legacy path is ALWAYS returned, even when the directory read fails, so
   * legacy detection can never be lost to an unreadable .agentic/. `.tmp`
   * staging files and non-.json entries never match the regex.
   *
   * This is an intentional parallel implementation of
   * hooks/lib/state-mark.js's _resolveCandidates - see the plugin manifest.
   */
  async function resolveLoopStateCandidates(cwd: string): Promise<string[]> {
    const agenticDir = path.join(cwd, ".agentic");
    const legacyPath = path.join(agenticDir, "loop-state.json");

    let entries: string[] = [];
    try {
      entries = await readdir(agenticDir);
    } catch {
      return [legacyPath]; // fail open - legacy detection survives regardless
    }

    const keyed: Array<{ p: string; mtimeMs: number }> = [];
    for (const name of entries) {
      if (name === "loop-state.json" || !KEYED_LOOP_STATE_RE.test(name)) continue;
      const p = path.join(agenticDir, name);
      // Per-candidate traversal check: a resolved candidate must be a DIRECT
      // child of .agentic/ (guard (c) - the key is always wrapped in the fixed
      // `loop-state-` / `.json` affixes, so it can never be a path component).
      if (path.dirname(path.resolve(p)) !== path.resolve(agenticDir)) continue;
      let mtimeMs = 0;
      try {
        mtimeMs = (await stat(p)).mtimeMs;
      } catch { /* raced away between readdir and stat - sorts oldest */ }
      keyed.push({ p, mtimeMs });
    }
    keyed.sort((a, b) => b.mtimeMs - a.mtimeMs);

    return [...keyed.slice(0, KEYED_CANDIDATE_CAP).map((k) => k.p), legacyPath];
  }

  /**
   * Write interrupted status to every loop-state candidate that holds an
   * active loop AND is owned by the current session. Candidates are the
   * per-ticket keyed `.agentic/loop-state-<LOOP_KEY>.json` siblings plus the
   * legacy `.agentic/loop-state.json` (see resolveLoopStateCandidates). Mirrors
   * the batch-state ownership check below and hooks/lib/state-mark.js
   * markInterrupted's polarity, applied PER CANDIDATE:
   * absence/null/empty session_id on disk PROCEEDS (self-owned); only a
   * positively-DIFFERING session_id skips (owned by another session). Because
   * the predicate is per candidate, a failure or foreign owner on one file
   * never skips the others.
   * M1: Atomic tmp+rename so a crash mid-write cannot leave the file
   * partially written and unparseable on next session resume.
   * M4: Reject cwd values with traversal components before any path join, and
   * re-assert per candidate that it is a direct child of .agentic/.
   *
   * This plugin fires this write once per session on command.executed
   * (`/ds-wrap`), NOT on every turn, so it does not have the Claude Stop
   * hook's per-turn-interrupt bug and its cadence is unchanged by this pass.
   */
  async function writeLoopState(cwd: string, sessionID: string | null) {
    const resolvedCwd = path.resolve(cwd);
    if (resolvedCwd !== cwd) {
      await log(
        "warn",
        "Skipping loop-state write: cwd contains traversal components",
        { cwd },
      );
      return;
    }

    const candidates = await resolveLoopStateCandidates(cwd);
    let found = 0;

    for (const loopStatePath of candidates) {
      try {
        const loopStateFile = Bun.file(loopStatePath);
        if (!(await loopStateFile.exists())) continue;
        found++;
        const loopState: any = await loopStateFile.json();

        // Ownership check: do not steal another session's loop state.
        if (
          typeof loopState.session_id === "string" &&
          loopState.session_id.length > 0 &&
          loopState.session_id !== sessionID
        ) {
          await log(
            "info",
            "Skipping loop-state write: owned by another session",
            {
              loopStatePath,
              owner: loopState.session_id,
              current: sessionID,
            },
          );
          continue;
        }

        if (loopState.status === "active") {
          loopState.status = "interrupted";
          loopState.interrupted_at = new Date().toISOString();
          // Mirrors Claude Stop hook behavior: 'unknown' is the only writable value
          // from a session-exit context (we can't distinguish rate-limit vs crash here).
          // Future explicit-cancel paths should set richer reasons before this writer fires.
          loopState.interrupt_reason = "unknown";
          const tmpPath = loopStatePath + ".tmp";
          await Bun.write(tmpPath, JSON.stringify(loopState, null, 2));
          await rename(tmpPath, loopStatePath);
          await log("info", "Marked active loop-state as interrupted", {
            loopStatePath,
          });
        } else {
          await log("info", "loop-state exists but not active", {
            loopStatePath,
            status: loopState.status,
          });
        }
      } catch (err: any) {
        // Fail open PER CANDIDATE - one unparseable file must not skip the rest.
        await log("warn", "Failed to write loop-state", {
          loopStatePath,
          error: err.message,
        });
      }
    }

    if (found === 0) {
      await log("info", "No loop-state file found", {
        agenticDir: path.join(cwd, ".agentic"),
      });
    }
  }

  /**
   * Write interrupted status to batch-state.json if an active batch exists
   * AND the file is owned by the current session. Mirrors the Stop hook
   * (hooks/stop-context.js writeBatchState) including the session_id
   * ownership check — the plugin must not steal another session's batch
   * state. Silent failure on every error path.
   */
  async function writeBatchState(cwd: string, sessionID: string | null) {
    const resolvedCwd = path.resolve(cwd);
    if (resolvedCwd !== cwd) {
      await log(
        "warn",
        "Skipping batch-state write: cwd contains traversal components",
        { cwd },
      );
      return;
    }

    const batchStatePath = path.join(cwd, ".agentic", "batch-state.json");
    try {
      const batchStateFile = Bun.file(batchStatePath);
      if (!(await batchStateFile.exists())) {
        await log("info", "No batch-state.json found", { batchStatePath });
        return;
      }
      const batchState: any = await batchStateFile.json();

      // Ownership check: do not steal another session's batch state.
      if (
        typeof batchState.session_id === "string" &&
        batchState.session_id.length > 0 &&
        batchState.session_id !== sessionID
      ) {
        await log(
          "info",
          "Skipping batch-state write: owned by another session",
          {
            batchStatePath,
            owner: batchState.session_id,
            current: sessionID,
          },
        );
        return;
      }

      if (batchState.status !== "active") {
        await log("info", "batch-state exists but not active", {
          batchStatePath,
          status: batchState.status,
        });
        return;
      }

      const nowIso = new Date().toISOString();
      batchState.status = "interrupted";
      batchState.interrupted_at = nowIso;
      batchState.interrupt_reason = "unknown";
      batchState.updated_at = nowIso;

      const tmpPath = batchStatePath + ".tmp";
      await Bun.write(tmpPath, JSON.stringify(batchState, null, 2));
      await rename(tmpPath, batchStatePath);
      await log("info", "Marked active batch-state as interrupted", {
        batchStatePath,
      });
    } catch (err: any) {
      await log("warn", "Failed to write batch-state", {
        batchStatePath,
        error: err.message,
      });
    }
  }

  /**
   * Build the activity block markdown from accumulated in-memory state plus
   * a fresh git status read. Returns the full block including the leading
   * sentinel. Used by both the session.idle handler and the /ds-wrap
   * finalization path.
   */
  async function buildActivityBlock(
    cwd: string,
    dateStr: string,
    attribution: string,
  ): Promise<string> {
    // Detect uncommitted changes via git status --porcelain
    const uncommittedFiles: Array<{ statusCode: string; filePath: string }> =
      [];
    try {
      const result = await $`git status --porcelain`.text();
      for (const line of result.split("\n")) {
        if (!line.trim()) continue;
        const statusCode = line.slice(0, 2).trim();
        const filePath = line.slice(3).trim();
        if (statusCode && !statusCode.includes("?") && filePath) {
          uncommittedFiles.push({ statusCode, filePath });
        }
      }
      await log("info", "git status completed", {
        trackedChanges: uncommittedFiles.length,
      });
    } catch (err: any) {
      await log("warn", "git status failed", { error: err.message });
    }
    const uncommittedFilesLimited = uncommittedFiles.slice(0, 30);

    const recentFocus = RECENT_MESSAGES_PLACEHOLDER;

    const pathsReferenced =
      filePaths.size > 0
        ? [...filePaths]
            .sort()
            .map((p) => "- " + p)
            .join("\n")
        : "(none detected)";

    const toolsLine = [...toolsUsed].sort().join(", ") || "(none recorded)";

    const uncommittedChangesLines =
      uncommittedFilesLimited.length > 0
        ? uncommittedFilesLimited
            .map(({ statusCode, filePath }) => `- ${statusCode} ${filePath}`)
            .join("\n")
        : "(working tree clean)";

    return `${ACTIVITY_SENTINEL}*${attribution} — ${dateStr}. Replaced each session.*

### Recent Messages
${recentFocus}

### Paths Referenced
${pathsReferenced}

### Uncommitted Changes
${uncommittedChangesLines}

### Tools Used
${toolsLine}
`;
  }

  // -------------------------------------------------------------------------
  // Shard + derived rollup (DS-107). See the SHARD MODEL note in the manifest.
  // -------------------------------------------------------------------------

  /** Sanitize a session id for use as a shard filename (no traversal, no separators). */
  function safeShardId(sessionID: string | null): string {
    const raw = (sessionID || "").trim();
    if (!raw || raw.includes("/") || raw.includes("\\") || raw.includes(".."))
      return FALLBACK_SHARD_ID;
    return raw;
  }

  /** True when the text after a sentinel looks like a derived activity region. */
  function looksLikeActivityRegion(after: string): boolean {
    const head = after.slice(0, 400);
    return ACTIVITY_REGION_SIGNATURES.some((sig) => head.includes(sig));
  }

  /**
   * Index of the activity region's opening sentinel, or -1.
   *
   * Scans for the LAST signature-matched sentinel, never the first. The activity
   * region is always the file tail, and a curated body that QUOTES the sentinel
   * bytes would otherwise be sliced in half - which in steady state makes the
   * remainder look foreign and rewrites _foreign.md every single turn.
   */
  function findActivityRegionIndex(text: string): number {
    if (!text) return -1;
    let idx = text.lastIndexOf(ACTIVITY_SENTINEL);
    while (idx >= 0) {
      if (looksLikeActivityRegion(text.slice(idx + ACTIVITY_SENTINEL.length)))
        return idx;
      idx = idx > 0 ? text.lastIndexOf(ACTIVITY_SENTINEL, idx - 1) : -1;
    }
    return -1;
  }

  function secondLine(text: string): string {
    const nl = text.indexOf("\n");
    if (nl < 0) return "";
    const rest = text.slice(nl + 1);
    const nl2 = rest.indexOf("\n");
    return nl2 < 0 ? rest : rest.slice(0, nl2);
  }

  /**
   * Remove machine-DERIVED content from a body about to be seeded into the
   * curated `_wrap.md`. Port of stripDerivedBlocks in hooks/lib/context-rollup.js
   * - the NORMATIVE procedure, not just the constants, must stay in sync.
   *
   * Omitting this (the original form of this port) seeded the prefix VERBATIM,
   * so pre-sentinel capture-gap and identity-nudge notices, and any earlier
   * unmarked activity region, persisted permanently into the curated file. That
   * cruft is IMMORTAL: `_wrap.md` is only ever merge-written by /ds-wrap Part A,
   * and the strip-and-append path that used to clear it is deleted. It is
   * reachable in any mixed Claude+OpenCode repo - whichever harness migrates
   * first determines the seed - and a pre-sentinel CAPTURE-GAP block is exactly
   * the shape the live incident's wedged `context.md` had.
   *
   * Two classes are removed: any activity region (MARKED OR UNMARKED - unmarked
   * is what every legacy writer produces), and the one-time derived notices.
   * Stripped blocks are DROPPED, not re-emitted: both notice families are
   * sentinel-gated and their sentinels are already consumed.
   *
   * Content that merely QUOTES a sentinel is preserved - see
   * findActivityRegionIndex.
   */
  function stripDerivedBlocks(text: string): string {
    if (!text) return "";
    let out = text;

    // 1. Activity regions, last-first, until none remain.
    for (;;) {
      const i = findActivityRegionIndex(out);
      if (i < 0) break;
      out = out.slice(0, i);
    }

    // 2. Derived one-time notices: each written as `\n---\n<TEXT...>`, running
    //    to the next `---` fence, the next top-level heading, or end of body.
    const lines = out.split("\n");
    const kept: string[] = [];
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].trim() !== "---") {
        kept.push(lines[i]);
        continue;
      }
      let j = i + 1;
      while (j < lines.length && !lines[j].trim()) j++;
      const isNotice =
        j < lines.length &&
        DERIVED_NOTICE_SIGNATURES.some((sig) => lines[j].startsWith(sig));
      if (!isNotice) {
        kept.push(lines[i]);
        continue;
      }
      let k = j;
      while (
        k < lines.length &&
        lines[k].trim() !== "---" &&
        !lines[k].startsWith("## ")
      ) {
        k++;
      }
      i = k - 1;
    }

    return kept.join("\n").replace(/\s+$/, "");
  }

  async function readIfPresent(p: string): Promise<string | null> {
    try {
      const f = Bun.file(p);
      if (!(await f.exists())) return null;
      return await f.text();
    } catch (_) {
      return null;
    }
  }

  /**
   * Write this session's shard. SESSION-PRIVATE, so concurrent writers never
   * collide and no lock is needed.
   */
  async function writeShard(
    cwd: string,
    sessionID: string | null,
    body: string,
  ): Promise<void> {
    const shardDir = path.join(cwd, ".agentic", "context.d");
    const target = path.join(shardDir, safeShardId(sessionID) + ".md");
    const tmp = `${target}.tmp.${process.pid}.${Math.random().toString(36).slice(2, 10)}`;
    try {
      await $`mkdir -p ${shardDir}`;
      await Bun.write(tmp, body);
      await rename(tmp, target);
      await log("info", "Wrote context shard", { target });
    } catch (err: any) {
      await log("warn", "Failed to write context shard", {
        target,
        error: err.message,
      });
    }
  }

  /**
   * Regenerate .agentic/context.md from .agentic/_wrap.md plus the shard set.
   *
   * DELIBERATELY LOCK-FREE, and NOT a strip-and-append. The retired
   * refreshWrapActivityBlock sliced at the FIRST sentinel and wrote back exactly
   * one block, destroying every other session's activity on an N-session rollup;
   * this plugin was the only unported adapter that ACTIVELY stripped accumulated
   * multi-session state rather than merely overwriting. The rollup is now a pure
   * function of its inputs, so a lost update self-heals on the next turn.
   *
   * Emits NO timestamp of its own - two regens over an unchanged shard set must
   * be byte-identical, which is what licenses writing without a lock.
   */
  async function regenerateRollup(cwd: string): Promise<void> {
    const projectDir = path.join(cwd, ".agentic");
    const outputPath = path.join(projectDir, "context.md");
    const curatedPath = path.join(projectDir, "_wrap.md");
    const foreignPath = path.join(projectDir, "_foreign.md");
    const shardDir = path.join(projectDir, "context.d");

    try {
      const curated = await readIfPresent(curatedPath);
      const head =
        curated && curated.trim()
          ? curated.replace(/\s+$/, "")
          : [
              "# Session Context",
              "*Derived rollup - regenerated from .agentic/context.d/ on every turn. Not committed to git.*",
              `*Project: ${cwd}*`,
            ].join("\n");

      // Migration: seed _wrap.md from a pre-existing curated context.md so the
      // next /ds-wrap takes its MERGE branch (its algorithm overwrites any file
      // whose SECOND LINE does not begin `*Written by /ds-wrap`, so lines 1-2
      // must stay byte-exact) rather than the fresh-write branch, which would
      // destroy the 10-slot rolling label window.
      const existing = await readIfPresent(outputPath);
      if (
        curated === null &&
        existing !== null &&
        existing.trim() &&
        !existing.includes(DERIVED_MARKER)
      ) {
        const i = findActivityRegionIndex(existing);
        const prefix = i >= 0 ? existing.slice(0, i) : existing;
        if (secondLine(prefix).startsWith("*Written by /ds-wrap")) {
          try {
            // stripDerivedBlocks, NOT a verbatim seed: derived cruft in the
            // curated file is unclearable (see that function's doc).
            await Bun.write(curatedPath, stripDerivedBlocks(prefix) + "\n");
            await log("info", "Migrated curated context.md into _wrap.md", { curatedPath });
          } catch (err: any) {
            // ABORT-BEFORE-OVERWRITE. `context.md` is the ONLY surviving copy of
            // the curated body until this write lands, and migration is guarded
            // by the derived marker so it never retries once a marked rollup is
            // written. Falling through would destroy it permanently. Returning
            // leaves the old file in place so the NEXT turn retries.
            // Recursing here would ALSO spin forever: the retry would find
            // `_wrap.md` still absent and take this same branch again.
            await log("warn", "Migration seed failed - aborting rollup write to avoid destroying context.md", {
              curatedPath,
              error: err?.message,
            });
            return;
          }
          return regenerateRollup(cwd); // recompose with the seed in place
        }
      }

      // Foreign preservation: an UNMARKED region (or an unmarked whole-file
      // write from an unported adapter) is someone else's content. Preserve it
      // once before rebuilding rather than assuming it is ours.
      if (existing !== null && existing.trim() && !existing.includes(DERIVED_MARKER)) {
        const i = findActivityRegionIndex(existing);
        const foreign =
          i >= 0
            ? existing.slice(i)
            : secondLine(existing).startsWith("*Written by /ds-wrap") ||
                existing.replace(/\s+$/, "") === head.replace(/\s+$/, "")
              ? null
              : existing;
        if (foreign) {
          try {
            await appendFile(foreignPath, `\n---\n${foreign.replace(/\s+$/, "")}\n`, "utf8");
            await log("info", "Preserved non-derived context.md as _foreign.md", { foreignPath });
          } catch (err: any) {
            // ABORT-BEFORE-OVERWRITE, same rule as the migration seed above: the
            // unported adapter's block lives only in `context.md` until this
            // append lands, and the rollup write below is a wholesale overwrite.
            await log("warn", "Foreign preservation failed - aborting rollup write to avoid destroying context.md", {
              foreignPath,
              error: err?.message,
            });
            return;
          }
        }
      }

      // Snapshot the shard set: (mtime DESC, session_id ASC). The secondary key
      // is mandatory - retention keeps only the N most recent, so an mtime tie
      // changes both the order AND which shard is dropped.
      let names: string[] = [];
      try {
        names = await readdir(shardDir);
      } catch (_) {
        names = [];
      }
      const shards: Array<{ id: string; p: string; mtime: number }> = [];
      for (const name of names) {
        if (!name.endsWith(".md")) continue;
        const p = path.join(shardDir, name);
        try {
          const st = await stat(p);
          if (!st.isFile()) continue;
          shards.push({ id: name.slice(0, -3), p, mtime: st.mtimeMs });
        } catch (_) { /* vanished mid-scan */ }
      }
      shards.sort((a, b) => (b.mtime - a.mtime) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));

      const blocks: string[] = [];
      for (const s of shards.slice(0, SHARD_RETENTION)) {
        const body = await readIfPresent(s.p);
        if (!body || !body.trim()) continue;
        blocks.push(`### Session ${s.id}\n\n${body.replace(/\s+$/, "")}`);
      }

      if (blocks.length === 0 && curated === null) return; // nothing to say

      let content = head;
      if (blocks.length > 0) {
        content +=
          ACTIVITY_SENTINEL +
          DERIVED_MARKER +
          "\n*Derived from .agentic/context.d/ - " +
          blocks.length +
          " session shard(s). Do not edit; regenerated every turn.*\n\n" +
          blocks.join("\n\n---\n\n");
      }
      content += "\n";

      await $`mkdir -p ${projectDir}`;
      await Bun.write(outputPath, content);
      await log("info", "Regenerated context.md rollup", {
        outputPath,
        shards: blocks.length,
      });
    } catch (err: any) {
      await log("warn", "Failed to regenerate context.md rollup", {
        outputPath,
        error: err.message,
      });
    }
  }

  /**
   * Write this session's activity shard and recompose the derived rollup.
   * Replaces the retired refreshWrapActivityBlock + whole-file-write pair.
   */
  async function writeContextShardAndRollup(
    cwd: string,
    sessionID: string | null,
    dateStr: string,
    attribution: string,
  ): Promise<void> {
    const block = await buildActivityBlock(cwd, dateStr, attribution);
    // buildActivityBlock returns the block INCLUDING the leading sentinel; the
    // shard body carries no sentinel and no `## Recent Focus` (that heading names
    // curated content owned by _wrap.md, which this composer must never write).
    await writeShard(cwd, sessionID, block.slice(ACTIVITY_SENTINEL.length));
    await regenerateRollup(cwd);
  }

  return {
    "tool.execute.after": async ({
      tool,
      args,
    }: {
      tool: string;
      args?: ToolExecuteArgs;
    }) => {
      await log("info", "tool.execute.after hook fired", { tool });
      toolsUsed.add(tool);

      if (args) {
        if (typeof args.file_path === "string" && args.file_path.trim()) {
          filePaths.add(args.file_path.trim());
        }
        if (typeof args.path === "string" && args.path.trim()) {
          filePaths.add(args.path.trim());
        }

        // Extract paths from bash commands via simple heuristic
        if (tool === "bash" && typeof args.command === "string") {
          const cmd = args.command;
          const matches = cmd.match(/(?:^|\s)(\/[^\s"'\\;|&<>]+)/g);
          if (matches) {
            for (const m of matches) {
              const p = m.trim();
              if (
                p.includes(".") ||
                p.startsWith("/Users/") ||
                p.startsWith("/home/")
              ) {
                if (p.length > 4 && !p.startsWith("/.")) {
                  // Best-effort: only treat as path if 4+ slashes (typical absolute project path).
                  // Shorter paths like /repo/x.ts are intentionally skipped to reduce false positives.
                  if ((p.match(/\//g) || []).length >= 4) {
                    filePaths.add(p);
                  }
                }
              }
            }
          }
        }
      }
    },

    // The OpenCode runtime fans out EVERY bus event (session.idle,
    // message.updated, command.executed, session.created, session.compacted,
    // ...) through this single generic `event` hook. We discriminate by
    // `event.type` and read payload data from `event.properties`. Unrelated
    // event types must early-return cheaply: this hook fires hundreds of
    // times per session.
    event: async ({ event }: { event: { type: string; properties?: any } }) => {
      const type = event?.type;
      const props = event?.properties ?? {};

      if (type === "session.created") {
        // session.created fires once at session start. If skill_auto_load is
        // enabled in ~/.config/opencode/agentic-engineering.json, emit a
        // skill-load instruction so the model reads the dinostack
        // protocol before handling any software development request.
        await log("info", "session.created event handler entered");
        try {
          const configPath = path.join(
            process.env.HOME || "~",
            ".config",
            "opencode",
            "agentic-engineering.json",
          );
          let skillAutoLoad = false;
          try {
            const configFile = Bun.file(configPath);
            if (await configFile.exists()) {
              const config: any = await configFile.json();
              skillAutoLoad = config?.skill_auto_load === true;
            }
          } catch (configErr: any) {
            await log("warn", "Failed to read dinostack config", {
              configPath,
              error: configErr.message,
            });
          }

          if (skillAutoLoad) {
            await log("info", "skill_auto_load=true, emitting skill-load instruction");
            const sessionID: string | undefined = props.sessionID;
            const sid: string | null = sessionID ?? null;
            try {
              client.session.prompt({
                path: { id: sid || "" },
                body: {
                  parts: [
                    {
                      type: "text",
                      text: [
                        "SKILL CHECK [dinostack]: skill_auto_load=true.",
                        "Before responding to any software development request, read the dinostack SKILL.md.",
                        "Do not implement directly - follow the delegation and risk classification protocol in that file.",
                      ].join("\n"),
                    },
                  ],
                  noReply: true,
                },
              }).catch((err: any) => {
                log("warn", "Skill-load prompt delivery failed", {
                  error: err?.message,
                });
              });
              await log("info", "Skill-load instruction emitted");
            } catch (promptErr: any) {
              await log("warn", "Failed to emit skill-load instruction", {
                error: promptErr.message,
              });
            }
          } else {
            await log("info", "skill_auto_load not set, skipping skill-load instruction");
          }
        } catch (err: any) {
          await log("warn", "session.created handler crashed", {
            error: err.message || String(err),
          });
        }
        return;
      }

      if (type === "session.idle") {
        // session.idle fires per busy->idle transition (every turn), NOT
        // once per session. This branch is intentionally limited to
        // context.md refresh; loop-state / batch-state / session_total
        // writes belong on /ds-wrap (see command.executed below) so they fire
        // once per session.
        await log("info", "session.idle event handler entered");

        try {
          const cwd = directory || process.cwd();
          const dateStr = new Date().toISOString().slice(0, 10);
          const idleSessionID: string | null = props.sessionID ?? null;
          await log("info", "session.idle event fired", { cwd, date: dateStr });
          await log("info", "Collected session data", {
            pathCount: filePaths.size,
            toolCount: toolsUsed.size,
          });

          // ONE path for both cases. The former two-branch structure -
          // strip-and-append onto a /ds-wrap file, else whole-file overwrite -
          // is retired: the first destroyed every session's activity but the
          // most recent, and the second clobbered concurrent writers wholesale.
          await writeContextShardAndRollup(
            cwd,
            idleSessionID,
            dateStr,
            "Auto-updated by session idle plugin",
          );

          await log("info", "session.idle processing complete");
        } catch (err: any) {
          await log("error", "session.idle handler crashed", {
            error: err.message || String(err),
          });
        }
        return;
      }

      if (type === "command.executed") {
        // /ds-wrap is the once-per-session finalization trigger. The bare
        // command name is "ds-wrap" (no leading slash). Other commands are
        // ignored.
        const name: string | undefined = props.name;
        if (name !== "ds-wrap") return;

        // Normalize sessionID to match the writers' string|null contract.
        const sessionID: string | undefined = props.sessionID;
        const sid: string | null = sessionID ?? null;

        await log(
          "info",
          "command.executed: /ds-wrap detected, running finalization",
          {
            sessionID: sid,
          },
        );

        try {
          const cwd = directory || process.cwd();
          const dateStr = new Date().toISOString().slice(0, 10);

          // Best-effort: write this session's shard and recompose the rollup.
          // No header sniffing and no early return - the composer handles the
          // /ds-wrap-authored, adapter-authored, and fresh-file cases uniformly,
          // so finalization runs regardless of what context.md currently holds.
          await writeContextShardAndRollup(
            cwd,
            sid,
            dateStr,
            "Auto-appended by /ds-wrap finalization",
          );

          // The three finalization writes are independent and best-effort.
          await writeLoopState(cwd, sid);
          await writeBatchState(cwd, sid);
          await writeSessionTotal(cwd, sid);

          // Surface a session prompt so the user knows the session was
          // finalized and should be ended cleanly. Prompt failure falls
          // back to a log.
          try {
            client.session.prompt({
              path: { id: sid || "" },
              body: {
                parts: [
                  {
                    type: "text",
                    text: "Session context written. Start a new session to continue with fresh context.",
                  },
                ],
                noReply: true,
              },
            }).catch(() => {});
            await log("info", "Session finalized via /ds-wrap (prompt shown)");
          } catch (err: any) {
            await log(
              "info",
              "Session finalized via /ds-wrap (prompt unavailable)",
              {
                error: err.message,
              },
            );
          }
        } catch (err: any) {
          await log("error", "command.executed handler crashed", {
            error: err.message || String(err),
          });
        }
        return;
      }

      // All other event types: silent ignore. The `event` hook fires for
      // every bus event; unrelated types must return cheaply.
      // Debug-only: helps observability when we add new branches in the
      // future. Uncomment if you need to see what bus events are flowing.
      // await log('debug', 'event hook fired (unhandled type)', { type });
    },
  };
};
