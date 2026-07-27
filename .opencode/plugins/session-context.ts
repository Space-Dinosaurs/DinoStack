/**
 * Purpose: OpenCode plugin that refreshes .agentic/context.md on every
 *          busy->idle transition (`session.idle`), runs full Stop-hook-
 *          equivalent finalization (loop-state, batch-state, session_total,
 *          activity-block refresh) once per session when the user invokes
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
 *                session.idle does context.md refresh only — no loop-state,
 *                batch-state, or events.jsonl writes happen there.
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

  /**
   * Refresh the activity block on a /ds-wrap-authored context.md.
   * Returns true if the file existed and was a /ds-wrap-authored file (whether
   * the append succeeded or not), false if no /ds-wrap file was present.
   */
  async function refreshWrapActivityBlock(
    cwd: string,
    dateStr: string,
    attribution: string,
  ): Promise<boolean> {
    const projectDir = path.join(cwd, ".agentic");
    const outputPath = path.join(projectDir, "context.md");
    try {
      const existingFile = Bun.file(outputPath);
      if (!(await existingFile.exists())) return false;
      const existing = await existingFile.text();
      if (!existing.startsWith("# Session Context\n*Written by /ds-wrap"))
        return false;

      await log(
        "info",
        "Detected /ds-wrap-generated context.md, refreshing activity block",
        {
          outputPath,
        },
      );
      const sentinelIdx = existing.indexOf(ACTIVITY_SENTINEL);
      const wrapContent =
        sentinelIdx >= 0 ? existing.slice(0, sentinelIdx) : existing.trimEnd();
      const activityBlock = await buildActivityBlock(cwd, dateStr, attribution);

      try {
        await $`mkdir -p ${projectDir}`;
        await Bun.write(outputPath, wrapContent + activityBlock);
        await log("info", "Refreshed activity block", { outputPath });
      } catch (err: any) {
        await log("warn", "Failed to refresh activity block", {
          outputPath,
          error: err.message,
        });
      }
      return true;
    } catch (err: any) {
      await log("info", "No existing /ds-wrap file or unreadable", {
        error: err.message,
      });
      return false;
    }
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
        // skill-load instruction so the model reads the agentic-engineering
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
            await log("warn", "Failed to read agentic-engineering config", {
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
                        "SKILL CHECK [agentic-engineering]: skill_auto_load=true.",
                        "Before responding to any software development request, read the agentic-engineering SKILL.md.",
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
          await log("info", "session.idle event fired", { cwd, date: dateStr });
          await log("info", "Collected session data", {
            pathCount: filePaths.size,
            toolCount: toolsUsed.size,
          });

          // --- /ds-wrap coexistence: refresh activity block if file was written by /ds-wrap ---
          const wrapHandled = await refreshWrapActivityBlock(
            cwd,
            dateStr,
            "Auto-appended by session idle plugin",
          );
          if (wrapHandled) {
            await log("info", "session.idle processing complete (wrap path)");
            return;
          }

          // --- Normal write (no /ds-wrap file present) ---
          const projectDir = path.join(cwd, ".agentic");
          const outputPath = path.join(projectDir, "context.md");

          const activityBlock = await buildActivityBlock(
            cwd,
            dateStr,
            "Auto-updated by session idle plugin",
          );

          const content = `# Session Context
*Auto-updated by session idle plugin — ${dateStr}. Overwritten each turn. Not committed to git.*
*Project: ${cwd}*

## Recent Focus
${RECENT_MESSAGES_PLACEHOLDER}

${activityBlock.slice(ACTIVITY_SENTINEL.length)}
`;

          try {
            await $`mkdir -p ${projectDir}`;
            await Bun.write(outputPath, content);
            await log("info", "Wrote context.md", { outputPath });
          } catch (err: any) {
            await log("warn", "Failed to write context.md", {
              outputPath,
              error: err.message,
            });
          }

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

          // Best-effort: refresh the activity block if context.md was
          // written by /ds-wrap. If the file is missing or lacks the wrap
          // header, skip the activity-block step but still proceed to
          // bookkeeping writes — wrap may have failed to write context.md,
          // but finalization runs anyway.
          await refreshWrapActivityBlock(
            cwd,
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
