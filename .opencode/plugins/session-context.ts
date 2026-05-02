/**
 * Purpose: OpenCode plugin that refreshes .agentic/context.md on every
 *          busy->idle transition (`session.idle`), and runs full Stop-hook-
 *          equivalent finalization (loop-state, batch-state, session_total,
 *          activity-block refresh) once per session when the user invokes
 *          `/wrap` (`command.executed`). Surfaces a TUI toast on /wrap.
 *
 * Public API: SessionContextPlugin — exported plugin function for OpenCode.
 *
 * Upstream deps: Bun runtime APIs ($, Bun.file, Bun.write). Node built-in
 *                path. Node fs/promises (appendFile, rename). OpenCode SDK
 *                client (client.app.log, client.tui.showToast).
 *
 * Downstream consumers: OpenCode plugin system (loaded from
 *                        ~/.config/opencode/plugins/ or .opencode/plugins/).
 *
 * Failure modes: Silent failure on every write path. The plugin uses two
 *                distinct OpenCode dispatch mechanisms:
 *                  1. Direct trigger hook `tool.execute.after` — invoked by
 *                     name with (input, output) by the runtime's `trigger`
 *                     dispatcher. Used to accumulate file paths and tools.
 *                  2. Generic `event` hook — invoked for EVERY bus event
 *                     (session.idle, message.updated, command.executed,
 *                     session.created, session.compacted, etc.); the
 *                     handler discriminates by `event.type` internally.
 *                     Bus events read their data from `event.properties`,
 *                     not from a top-level destructure.
 *                NOTE: an earlier version of this plugin registered
 *                `'session.idle'`, `'message.updated'`, and
 *                `'command.executed'` as top-level hook keys. The OpenCode
 *                runtime never looks those up — bus events only flow
 *                through the generic `event` hook — so all three handlers
 *                were dead code. This commit fixes that dispatch bug.
 *                session.idle does context.md refresh only — no loop-state,
 *                batch-state, or events.jsonl writes happen there.
 *                Finalization writes (loop-state, batch-state,
 *                events.jsonl) run only on /wrap completion via
 *                command.executed and are independent and best-effort: a
 *                failure in one does not affect the others. TUI toast
 *                failure falls back to a structured log line. cwd values
 *                with path-traversal components are rejected by all three
 *                writers (defence in depth). The per-session-once
 *                invariant for session_total relies on the user invoking
 *                /wrap; OpenCode does not expose a guaranteed shutdown
 *                hook from plugins.
 *
 * Performance: ~5-20 ms typical on session.idle (one git status subprocess);
 *              slightly heavier on /wrap completion (multiple writes, one
 *              full-file read+parse of events.jsonl for the session_total
 *              rollup, plus one TUI toast HTTP call). The generic `event`
 *              hook fires for every bus event in the session (potentially
 *              hundreds per session); the unmatched-type early-return must
 *              stay cheap (a single property read and three string
 *              comparisons, no allocations, no logs).
 */

import path from 'path';
import { appendFile, rename } from 'fs/promises';

interface PluginContext {
  directory: string;
  $: any;
  client: {
    app: {
      log: (payload: {
        body: {
          service: string;
          level: 'debug' | 'info' | 'warn' | 'error';
          message: string;
          extra?: Record<string, any>;
        };
      }) => Promise<void>;
    };
    tui: {
      showToast: (payload: {
        body: {
          title?: string;
          message: string;
          variant: 'info' | 'success' | 'warning' | 'error';
          duration?: number;
        };
      }) => Promise<unknown>;
    };
  };
}

interface Message {
  role: string;
  content: string | Array<{ type: string; text?: string }>;
}

interface ToolExecuteArgs {
  file_path?: string;
  path?: string;
  command?: string;
}

const ACTIVITY_SENTINEL = '\n\n---\n\n## Session Activity\n';

export const SessionContextPlugin = async ({ directory, $, client }: PluginContext) => {
  const log = async (
    level: 'debug' | 'info' | 'warn' | 'error',
    message: string,
    extra: Record<string, any> = {}
  ) => {
    try {
      await client.app.log({
        body: { service: 'ae-session-context', level, message, extra },
      });
    } catch (_) {
      // Silent fallback if logging itself fails
    }
  };

  await log('info', 'Plugin loaded', { directory: directory || null });

  const recentMessages: string[] = [];
  const filePaths = new Set<string>();
  const toolsUsed = new Set<string>();
  const MAX_MESSAGES = 10;

  /**
   * Aggregate spawn_complete + conductor_direct events from events.jsonl for
   * the current session and append a session_total rollup. Mirrors
   * hooks/stop-context.js writeSessionTotal. Silent failure on every error path.
   */
  async function writeSessionTotal(cwd: string, sessionID: string | null) {
    // M4: Reject cwd values with traversal components before any path join.
    const resolvedCwd = path.resolve(cwd);
    if (resolvedCwd !== cwd) {
      await log('warn', 'Skipping session_total write: cwd contains traversal components', { cwd });
      return;
    }

    const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
    try {
      const eventsFile = Bun.file(eventsPath);
      if (!(await eventsFile.exists())) return;
      const raw = await eventsFile.text();
      if (!raw.trim()) return;

      const lines = raw.split('\n');
      let totalWall = 0;
      let spawnCount = 0;
      const totalTokens: { input: number; output: number; cache_creation: number; cache_read: number } = {
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
          tokens: { input: number; output: number; cache_creation: number; cache_read: number };
        }
      > = {};
      const tokenKeys = ['input', 'output', 'cache_creation', 'cache_read'] as const;

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
        if (ev !== 'spawn_complete' && ev !== 'conductor_direct') continue;
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
        if (ev === 'spawn_complete') {
          spawnCount += 1;
          const agentName = (obj && obj.agent) || 'unknown';
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
        phase: 'session_end',
        event: 'session_total',
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
      await appendFile(eventsPath, JSON.stringify(event) + '\n');
      await log('info', 'Appended session_total', {
        eventsPath,
        spawn_count: spawnCount,
        wall_seconds: Number(totalWall.toFixed(3)),
      });
    } catch (err: any) {
      await log('warn', 'Failed to write session_total', { eventsPath, error: err.message });
    }
  }

  /**
   * Write interrupted status to loop-state.json if an active loop exists.
   * M1: Atomic tmp+rename so a crash mid-write cannot leave the file
   * partially written and unparseable on next session resume.
   * M4: Reject cwd values with traversal components before any path join.
   */
  async function writeLoopState(cwd: string) {
    const resolvedCwd = path.resolve(cwd);
    if (resolvedCwd !== cwd) {
      await log('warn', 'Skipping loop-state write: cwd contains traversal components', { cwd });
      return;
    }

    const loopStatePath = path.join(cwd, '.agentic', 'loop-state.json');
    try {
      const loopStateFile = Bun.file(loopStatePath);
      if (await loopStateFile.exists()) {
        const loopState: any = await loopStateFile.json();
        if (loopState.status === 'active') {
          loopState.status = 'interrupted';
          loopState.interrupted_at = new Date().toISOString();
          loopState.interrupt_reason = 'unknown';
          const tmpPath = loopStatePath + '.tmp';
          await Bun.write(tmpPath, JSON.stringify(loopState, null, 2));
          await rename(tmpPath, loopStatePath);
          await log('info', 'Marked active loop-state as interrupted', { loopStatePath });
        } else {
          await log('info', 'loop-state exists but not active', {
            loopStatePath,
            status: loopState.status,
          });
        }
      } else {
        await log('info', 'No loop-state.json found', { loopStatePath });
      }
    } catch (err: any) {
      await log('warn', 'Failed to write loop-state', { loopStatePath, error: err.message });
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
      await log('warn', 'Skipping batch-state write: cwd contains traversal components', { cwd });
      return;
    }

    const batchStatePath = path.join(cwd, '.agentic', 'batch-state.json');
    try {
      const batchStateFile = Bun.file(batchStatePath);
      if (!(await batchStateFile.exists())) {
        await log('info', 'No batch-state.json found', { batchStatePath });
        return;
      }
      const batchState: any = await batchStateFile.json();

      // Ownership check: do not steal another session's batch state.
      if (
        typeof batchState.session_id === 'string' &&
        batchState.session_id.length > 0 &&
        batchState.session_id !== sessionID
      ) {
        await log('info', 'Skipping batch-state write: owned by another session', {
          batchStatePath,
          owner: batchState.session_id,
          current: sessionID,
        });
        return;
      }

      if (batchState.status !== 'active') {
        await log('info', 'batch-state exists but not active', {
          batchStatePath,
          status: batchState.status,
        });
        return;
      }

      const nowIso = new Date().toISOString();
      batchState.status = 'interrupted';
      batchState.interrupted_at = nowIso;
      batchState.interrupt_reason = 'unknown';
      batchState.updated_at = nowIso;

      const tmpPath = batchStatePath + '.tmp';
      await Bun.write(tmpPath, JSON.stringify(batchState, null, 2));
      await rename(tmpPath, batchStatePath);
      await log('info', 'Marked active batch-state as interrupted', { batchStatePath });
    } catch (err: any) {
      await log('warn', 'Failed to write batch-state', { batchStatePath, error: err.message });
    }
  }

  /**
   * Build the activity block markdown from accumulated in-memory state plus
   * a fresh git status read. Returns the full block including the leading
   * sentinel. Used by both the session.idle handler and the /wrap
   * finalization path.
   */
  async function buildActivityBlock(cwd: string, dateStr: string, attribution: string): Promise<string> {
    // Detect uncommitted changes via git status --porcelain
    const uncommittedFiles: Array<{ statusCode: string; filePath: string }> = [];
    try {
      const result = await $`git status --porcelain`.text();
      for (const line of result.split('\n')) {
        if (!line.trim()) continue;
        const statusCode = line.slice(0, 2).trim();
        const filePath = line.slice(3).trim();
        if (statusCode && !statusCode.includes('?') && filePath) {
          uncommittedFiles.push({ statusCode, filePath });
        }
      }
      await log('info', 'git status completed', { trackedChanges: uncommittedFiles.length });
    } catch (err: any) {
      await log('warn', 'git status failed', { error: err.message });
    }
    const uncommittedFilesLimited = uncommittedFiles.slice(0, 30);

    const recentFocus =
      recentMessages
        .slice(-3)
        .map((m) => {
          const truncated = m.length > 150 ? m.slice(0, 147) + '...' : m;
          return '- ' + truncated.replace(/\n/g, ' ');
        })
        .join('\n') || '(no user messages captured)';

    const pathsReferenced =
      filePaths.size > 0
        ? [...filePaths].sort().map((p) => '- ' + p).join('\n')
        : '(none detected)';

    const toolsLine = [...toolsUsed].sort().join(', ') || '(none recorded)';

    const uncommittedChangesLines =
      uncommittedFilesLimited.length > 0
        ? uncommittedFilesLimited
            .map(({ statusCode, filePath }) => `- ${statusCode} ${filePath}`)
            .join('\n')
        : '(working tree clean)';

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
   * Refresh the activity block on a /wrap-authored context.md.
   * Returns true if the file existed and was a /wrap-authored file (whether
   * the append succeeded or not), false if no /wrap file was present.
   */
  async function refreshWrapActivityBlock(cwd: string, dateStr: string, attribution: string): Promise<boolean> {
    const projectDir = path.join(cwd, '.agentic');
    const outputPath = path.join(projectDir, 'context.md');
    try {
      const existingFile = Bun.file(outputPath);
      if (!(await existingFile.exists())) return false;
      const existing = await existingFile.text();
      if (!existing.startsWith('# Session Context\n*Written by /wrap')) return false;

      await log('info', 'Detected /wrap-generated context.md, refreshing activity block', {
        outputPath,
      });
      const sentinelIdx = existing.indexOf(ACTIVITY_SENTINEL);
      const wrapContent = sentinelIdx >= 0 ? existing.slice(0, sentinelIdx) : existing.trimEnd();
      const activityBlock = await buildActivityBlock(cwd, dateStr, attribution);

      try {
        await $`mkdir -p ${projectDir}`;
        await Bun.write(outputPath, wrapContent + activityBlock);
        await log('info', 'Refreshed activity block', { outputPath });
      } catch (err: any) {
        await log('warn', 'Failed to refresh activity block', { outputPath, error: err.message });
      }
      return true;
    } catch (err: any) {
      await log('info', 'No existing /wrap file or unreadable', { error: err.message });
      return false;
    }
  }

  return {
    'tool.execute.after': async ({ tool, args }: { tool: string; args?: ToolExecuteArgs }) => {
      await log('info', 'tool.execute.after hook fired', { tool });
      toolsUsed.add(tool);

      if (args) {
        if (typeof args.file_path === 'string' && args.file_path.trim()) {
          filePaths.add(args.file_path.trim());
        }
        if (typeof args.path === 'string' && args.path.trim()) {
          filePaths.add(args.path.trim());
        }

        // Extract paths from bash commands via simple heuristic
        if (tool === 'bash' && typeof args.command === 'string') {
          const cmd = args.command;
          const matches = cmd.match(/(?:^|\s)(\/[^\s"'\\;|&<>]+)/g);
          if (matches) {
            for (const m of matches) {
              const p = m.trim();
              if (p.includes('.') || p.startsWith('/Users/') || p.startsWith('/home/')) {
                if (p.length > 4 && !p.startsWith('/.')) {
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

      if (type === 'message.updated') {
        const message: Message | undefined = props.message;
        if (!message || message.role !== 'user') return;
        await log('info', 'message.updated event received for user message');

        let text = '';
        if (typeof message.content === 'string') {
          text = message.content.trim();
        } else if (Array.isArray(message.content)) {
          for (const block of message.content) {
            if (block && block.type === 'text' && typeof block.text === 'string') {
              text += block.text;
            }
          }
          text = text.trim();
        }

        if (!text) return;

        recentMessages.push(text);
        if (recentMessages.length > MAX_MESSAGES) {
          recentMessages.shift();
        }
        return;
      }

      if (type === 'session.idle') {
        // session.idle fires per busy->idle transition (every turn), NOT
        // once per session. This branch is intentionally limited to
        // context.md refresh; loop-state / batch-state / session_total
        // writes belong on /wrap (see command.executed below) so they fire
        // once per session.
        await log('info', 'session.idle event handler entered');

        try {
          const cwd = directory || process.cwd();
          const dateStr = new Date().toISOString().slice(0, 10);
          await log('info', 'session.idle event fired', { cwd, date: dateStr });
          await log('info', 'Collected session data', {
            messageCount: recentMessages.length,
            pathCount: filePaths.size,
            toolCount: toolsUsed.size,
          });

          // --- /wrap coexistence: refresh activity block if file was written by /wrap ---
          const wrapHandled = await refreshWrapActivityBlock(
            cwd,
            dateStr,
            'Auto-appended by session idle plugin'
          );
          if (wrapHandled) {
            await log('info', 'session.idle processing complete (wrap path)');
            return;
          }

          // --- Normal write (no /wrap file present) ---
          const projectDir = path.join(cwd, '.agentic');
          const outputPath = path.join(projectDir, 'context.md');

          // Reuse the same git status / focus building logic as the
          // activity block, but format as a top-level context.md instead.
          const uncommittedFiles: Array<{ statusCode: string; filePath: string }> = [];
          try {
            const result = await $`git status --porcelain`.text();
            for (const line of result.split('\n')) {
              if (!line.trim()) continue;
              const statusCode = line.slice(0, 2).trim();
              const filePath = line.slice(3).trim();
              if (statusCode && !statusCode.includes('?') && filePath) {
                uncommittedFiles.push({ statusCode, filePath });
              }
            }
            await log('info', 'git status completed', { trackedChanges: uncommittedFiles.length });
          } catch (err: any) {
            await log('warn', 'git status failed', { error: err.message });
          }
          const uncommittedFilesLimited = uncommittedFiles.slice(0, 30);

          const recentFocus =
            recentMessages
              .slice(-3)
              .map((m) => {
                const truncated = m.length > 150 ? m.slice(0, 147) + '...' : m;
                return '- ' + truncated.replace(/\n/g, ' ');
              })
              .join('\n') || '(no user messages captured)';

          const pathsReferenced =
            filePaths.size > 0
              ? [...filePaths].sort().map((p) => '- ' + p).join('\n')
              : '(none detected)';

          const toolsLine = [...toolsUsed].sort().join(', ') || '(none recorded)';

          const uncommittedChangesLines =
            uncommittedFilesLimited.length > 0
              ? uncommittedFilesLimited
                  .map(({ statusCode, filePath }) => `- ${statusCode} ${filePath}`)
                  .join('\n')
              : '(working tree clean)';

          const content = `# Session Context
*Auto-updated by session idle plugin — ${dateStr}. Overwritten each turn. Not committed to git.*
*Project: ${cwd}*

## Recent Focus
${recentFocus}

## Paths Referenced
${pathsReferenced}

## Uncommitted Changes
${uncommittedChangesLines}

## Tools Used
${toolsLine}
`;

          try {
            await $`mkdir -p ${projectDir}`;
            await Bun.write(outputPath, content);
            await log('info', 'Wrote context.md', { outputPath });
          } catch (err: any) {
            await log('warn', 'Failed to write context.md', { outputPath, error: err.message });
          }

          await log('info', 'session.idle processing complete');
        } catch (err: any) {
          await log('error', 'session.idle handler crashed', {
            error: err.message || String(err),
          });
        }
        return;
      }

      if (type === 'command.executed') {
        // /wrap is the once-per-session finalization trigger. The bare
        // command name is "wrap" (no leading slash). Other commands are
        // ignored.
        const name: string | undefined = props.name;
        if (name !== 'wrap') return;

        // Normalize sessionID to match the writers' string|null contract.
        const sessionID: string | undefined = props.sessionID;
        const sid: string | null = sessionID ?? null;

        await log('info', 'command.executed: /wrap detected, running finalization', {
          sessionID: sid,
        });

        try {
          const cwd = directory || process.cwd();
          const dateStr = new Date().toISOString().slice(0, 10);

          // Best-effort: refresh the activity block if context.md was
          // written by /wrap. If the file is missing or lacks the wrap
          // header, skip the activity-block step but still proceed to
          // bookkeeping writes — wrap may have failed to write context.md,
          // but finalization runs anyway.
          await refreshWrapActivityBlock(cwd, dateStr, 'Auto-appended by /wrap finalization');

          // The three finalization writes are independent and best-effort.
          await writeLoopState(cwd);
          await writeBatchState(cwd, sid);
          await writeSessionTotal(cwd, sid);

          // Surface a TUI toast so the user knows the session was
          // finalized and should be ended cleanly. Toast failure falls
          // back to a log.
          try {
            await client.tui.showToast({
              body: {
                message:
                  'Session context written. Start a new session to continue with fresh context.',
                variant: 'info',
                duration: 8000,
              },
            });
            await log('info', 'Session finalized via /wrap (toast shown)');
          } catch (err: any) {
            await log('info', 'Session finalized via /wrap (toast unavailable)', {
              error: err.message,
            });
          }
        } catch (err: any) {
          await log('error', 'command.executed handler crashed', {
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
