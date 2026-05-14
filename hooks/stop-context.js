#!/usr/bin/env node

/**
 * Purpose: Reads the Claude Code Stop hook JSON payload from stdin and writes
 *          session context to disk so the next session's Workers have lightweight
 *          context about what was happening. Also marks any active orchestration
 *          loop as interrupted so the next session can offer to resume.
 *
 * Public API: run() — invoked immediately at module load via run() call at
 *             bottom of file. Not imported; executed as a CLI script by the
 *             Claude Code Stop hook. Internal helpers: writeLoopState(cwd),
 *             writeBatchState(cwd, sessionId), writeSessionTotal(cwd, sessionId).
 *
 * Upstream deps: Node built-ins only (fs, path, os, child_process). No npm
 *                dependencies. Reads from stdin (fd 0). Reads/writes
 *                ~/.claude/projects/[hash]/context.md,
 *                [cwd]/.agentic/loop-state.json, and
 *                [cwd]/.agentic/batch-state.json.
 *
 * Downstream consumers: Claude Code Stop hook (configured in
 *                        ~/.claude/settings.json or project .claude/settings.json).
 *                        Output files are read by Worker agents at session start.
 *
 * Failure modes: All failures are silent (process.exit(0)). Four independent
 *                write paths: (1) context.md write is best-effort; any fs error
 *                is swallowed and the file may not be written. (2) loop-state.json
 *                write is also best-effort; any fs error is swallowed independently
 *                of path (1). (3) events.jsonl write is best-effort; any fs error
 *                is swallowed independently of paths (1) and (2). The append
 *                failure model is identical to context.md - the next session
 *                can re-derive totals from per-spawn events if needed.
 *                (4) writeBatchState writes interrupted-status to
 *                .agentic/batch-state.json on session exit; aborts silently on
 *                session_id mismatch with the file's owner, on missing file, or
 *                on parse error. Best-effort silent-fail; failure of
 *                writeBatchState does not block writeSessionTotal.
 *                All four paths are independent - a failure in one does not
 *                affect the others. The 10-minute implicit-interrupt heuristic
 *                handles missed loop-state writes. cwd values with path
 *                traversal components are rejected for the loop-state and
 *                batch-state writes (defence in depth).
 *
 * Performance: ~5-20 ms typical; one git status subprocess call (5 s timeout).
 *              Synchronous I/O throughout; runs as a short-lived CLI process.
 */

/**
 * Claude Code Stop Hook — Session Context Writer
 *
 * Reads the Stop hook JSON payload from stdin and writes a minimal context.md
 * file to ~/.claude/projects/[hash]/ so that the next session's Workers have
 * lightweight context about what was happening.
 *
 * Design goals:
 *  - Silent failure: any error exits 0, nothing written to stderr
 *  - No external dependencies: only Node built-ins
 *  - Fast: no LLM call, pure text extraction
 *  - /wrap coexistence: if context.md was written by /wrap (detected by
 *    "# Session Context\n*Written by /wrap" at the file start), the Stop hook
 *    appends a "Session Activity" block rather than overwriting. Any previous
 *    activity block is replaced, not accumulated - most recent session only.
 *    /wrap content is preserved indefinitely; only another /wrap run replaces
 *    the whole file. The Stop hook is the fallback for sessions where /wrap
 *    was never run.
 *
 * Output path: ~/.claude/projects/[hash]/context.md
 *   where hash = cwd with every '/' replaced by '-' (leading '-' is kept)
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

/**
 * Write interrupted status to loop-state.json if an active loop exists.
 * Called from ALL exit paths so the loop-state write is never skipped.
 * Silent failure: any error is swallowed independently of the context write.
 * @param {string} cwd - Verified project directory (already traversal-checked by caller).
 */
function writeLoopState(cwd) {
  // M3: Reject cwd values with traversal components before any path join.
  // path.resolve normalizes '..' segments; if the result differs from the
  // input, cwd was not a clean absolute path and could escape the project dir.
  const resolvedCwd = path.resolve(cwd);
  if (resolvedCwd !== cwd) {
    // cwd contains traversal components - skip loop-state write silently.
    return;
  }

  try {
    const loopStatePath = path.join(cwd, '.agentic', 'loop-state.json');
    if (fs.existsSync(loopStatePath)) {
      const loopState = JSON.parse(fs.readFileSync(loopStatePath, 'utf-8'));
      if (loopState.status === 'active') {
        loopState.status = 'interrupted';
        loopState.interrupted_at = new Date().toISOString();
        loopState.interrupt_reason = 'unknown'; // cannot distinguish rate_limit vs crash at hook time
        const tmpPath = loopStatePath + '.tmp';
        fs.writeFileSync(tmpPath, JSON.stringify(loopState, null, 2));
        fs.renameSync(tmpPath, loopStatePath);
      }
    }
  } catch (_) {
    // Silent failure - the 10-minute implicit-interrupt heuristic handles missed writes
  }
}

/**
 * Write interrupted status to batch-state.json if an active batch exists AND
 * the file is owned by the current session. Mirrors writeLoopState but with
 * an additional session_id ownership check (the Stop hook must not steal
 * another session's batch state). Silent failure: any error swallowed.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid from the Stop payload.
 */
function writeBatchState(cwd, sessionId) {
  // Reject cwd values with traversal components before any path join.
  const resolvedCwd = path.resolve(cwd);
  if (resolvedCwd !== cwd) {
    return;
  }

  try {
    const batchStatePath = path.join(cwd, '.agentic', 'batch-state.json');
    if (!fs.existsSync(batchStatePath)) return;
    const batchState = JSON.parse(fs.readFileSync(batchStatePath, 'utf-8'));

    // Ownership check: do not steal another session's batch state.
    // If the file's session_id is a non-empty string and does not match the
    // current session, abort silently.
    if (typeof batchState.session_id === 'string'
        && batchState.session_id.length > 0
        && batchState.session_id !== sessionId) {
      return;
    }

    if (batchState.status !== 'active') return;

    const nowIso = new Date().toISOString();
    batchState.status = 'interrupted';
    batchState.interrupted_at = nowIso;
    batchState.interrupt_reason = 'unknown';
    batchState.updated_at = nowIso;

    const tmpPath = batchStatePath + '.tmp';
    fs.writeFileSync(tmpPath, JSON.stringify(batchState, null, 2));
    fs.renameSync(tmpPath, batchStatePath);
  } catch (_) {
    // Silent failure - best-effort write; resume-time logic tolerates absent mark.
  }
}

/**
 * Append a single session_total event to .agentic/events.jsonl summing
 * spawn_complete + conductor_direct events for the current session.
 * Best-effort: any fs / parse failure is swallowed silently.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid from the Stop payload.
 */
function writeSessionTotal(cwd, sessionId) {
  try {
    const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
    if (!fs.existsSync(eventsPath)) return;
    const raw = fs.readFileSync(eventsPath, 'utf8');
    if (!raw.trim()) return;

    const lines = raw.split('\n');
    let totalWall = 0;
    let spawnCount = 0;
    const totalTokens = { input: 0, output: 0, cache_creation: 0, cache_read: 0 };
    const byAgent = {};

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let obj;
      try { obj = JSON.parse(trimmed); } catch (_) { continue; }
      const ev = obj && obj.event;
      if (ev !== 'spawn_complete' && ev !== 'conductor_direct') continue;
      const data = (obj && obj.data) || {};
      // Filter to current session when session_uuid is present on the
      // event payload. Events without session_uuid are included
      // unconditionally (tolerant of pre-instrumentation events).
      if (sessionId && data.session_uuid && data.session_uuid !== sessionId) {
        continue;
      }
      const wall = Number(data.wall_seconds) || 0;
      totalWall += wall;
      const tokens = data.tokens || {};
      for (const k of ['input', 'output', 'cache_creation', 'cache_read']) {
        totalTokens[k] += Number(tokens[k]) || 0;
      }
      if (ev === 'spawn_complete') {
        spawnCount += 1;
        const agentName = obj.agent || 'unknown';
        if (!byAgent[agentName]) {
          byAgent[agentName] = {
            spawns: 0, wall_seconds: 0,
            tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
          };
        }
        byAgent[agentName].spawns += 1;
        byAgent[agentName].wall_seconds += wall;
        for (const k of ['input', 'output', 'cache_creation', 'cache_read']) {
          byAgent[agentName].tokens[k] += Number(tokens[k]) || 0;
        }
      }
    }

    const totalLine = JSON.stringify({
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
        session_uuid: sessionId || null,
      },
    });
    fs.appendFileSync(eventsPath, totalLine + '\n');
  } catch (_) {
    // Silent failure - consistent with context.md / loop-state.json paths.
  }
}

/**
 * Remove the learnings-agent session marker if it belongs to the current session.
 * Silent failure: any error is swallowed.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid from the Stop payload.
 */
function removeLearningsAgentSession(cwd, sessionId) {
  // Reject cwd values with traversal components before any path join.
  const resolvedCwd = path.resolve(cwd);
  if (resolvedCwd !== cwd) {
    return;
  }

  try {
    const markerPath = path.join(cwd, '.agentic', 'learnings-agent.session');
    if (!fs.existsSync(markerPath)) return;
    const raw = fs.readFileSync(markerPath, 'utf8');
    const marker = JSON.parse(raw);
    if (typeof marker.session_id === 'string' && marker.session_id === sessionId) {
      fs.unlinkSync(markerPath);
    }
  } catch (_) {
    // Silent failure
  }
}

function run() {
  // --- 1. Read stdin ---
  let raw = '';
  try {
    raw = fs.readFileSync(0, 'utf8');
  } catch (_) {
    process.exit(0);
  }

  if (!raw.trim()) process.exit(0);

  // --- 2. Parse JSON ---
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (_) {
    process.exit(0);
  }

  // --- 3. Extract fields (all optional — guard every access) ---
  const cwd = (typeof payload.cwd === 'string' && payload.cwd.trim()) ? payload.cwd.trim() : null;
  if (!cwd) process.exit(0);

  const sessionId = (typeof payload.session_id === 'string' && payload.session_id.trim())
    ? payload.session_id.trim()
    : null;

  const transcript = Array.isArray(payload.transcript) ? payload.transcript : [];

  // --- 4. Compute output path ---
  // Write context.md to the project's .agentic/ directory. Claude Code treats
  // any .claude/ directory (project-local OR global) as a sensitive file
  // location, so writing there still triggers the permission prompt even when
  // allow rules are set. .agentic/ is the same convention already used for
  // loop-state.json and is not subject to that check.
  const projectDir = path.join(cwd, '.agentic');
  const outputPath = path.join(projectDir, 'context.md');

  // --- 5. Extract recent user messages (last 3, truncated to ~150 chars) ---
  const userMessages = [];
  for (const msg of transcript) {
    if (!msg || msg.role !== 'user') continue;
    let text = '';
    if (typeof msg.content === 'string') {
      text = msg.content.trim();
    } else if (Array.isArray(msg.content)) {
      // Concatenate all text blocks
      for (const block of msg.content) {
        if (block && block.type === 'text' && typeof block.text === 'string') {
          text += block.text;
        }
      }
      text = text.trim();
    }
    if (text) userMessages.push(text);
  }
  const recentUserMessages = userMessages.slice(-3);

  // --- 6. Extract files touched from tool calls in transcript ---
  // Note: "Paths Referenced" in the output includes both file accesses (Read/Edit/Write/MultiEdit)
  // and search directories (Glob/Grep `path` arguments). Both categories appear in the same section.
  const filePaths = new Set();
  const fileToolNames = new Set(['Read', 'Edit', 'Write', 'MultiEdit']);

  for (const msg of transcript) {
    if (!msg) continue;
    const blocks = Array.isArray(msg.content) ? msg.content : [];
    for (const block of blocks) {
      if (!block || block.type !== 'tool_use') continue;
      const name = block.name || '';
      const input = block.input || {};

      if (fileToolNames.has(name)) {
        // Read, Edit, Write, MultiEdit all use file_path
        if (typeof input.file_path === 'string' && input.file_path.trim()) {
          filePaths.add(input.file_path.trim());
        }
      } else if (name === 'Glob' || name === 'Grep') {
        // Glob and Grep use path (directory or file to search in)
        if (typeof input.path === 'string' && input.path.trim()) {
          filePaths.add(input.path.trim());
        }
      } else if (name === 'Bash' || name === 'bash') {
        // Try to extract file paths from Bash commands via simple heuristic:
        // look for arguments that look like absolute paths
        const cmd = typeof input.command === 'string' ? input.command : '';
        const matches = cmd.match(/(?:^|\s)(\/[^\s"'\\;|&<>]+)/g);
        if (matches) {
          for (const m of matches) {
            const p = m.trim();
            // Only include paths that look like files (have an extension or are in known dirs)
            if (p.includes('.') || p.startsWith('/Users/') || p.startsWith('/home/')) {
              // Skip paths that are clearly flags or short tokens
              if (p.length > 4 && !p.startsWith('/.')) {
                // Require at least /Users/name/dir/file depth (4+ slashes) to avoid
                // capturing bare directories like /Users/alice or /home/bob
                if ((p.match(/\//g) || []).length >= 4) {
                  filePaths.add(p);
                }
              }
            }
          }
        }
      }
    }
  }

  // --- 7. Extract unique tools used from transcript tool_use blocks ---
  const toolsUsedSet = new Set();
  for (const msg of transcript) {
    if (!msg) continue;
    const blocks = Array.isArray(msg.content) ? msg.content : [];
    for (const block of blocks) {
      if (block && block.type === 'tool_use' && typeof block.name === 'string' && block.name.trim()) {
        toolsUsedSet.add(block.name.trim());
      }
    }
  }
  const uniqueTools = [...toolsUsedSet].sort();

  // --- 7b. Detect uncommitted changes via git status --porcelain ---
  const uncommittedFiles = [];
  try {
    const gitStatus = execSync('git status --porcelain', { cwd, timeout: 5000, encoding: 'utf8' });
    for (const line of gitStatus.split('\n')) {
      if (!line.trim()) continue;
      const statusCode = line.slice(0, 2).trim();
      const filePath = line.slice(3).trim();
      // Only include tracked modified/added/deleted/renamed files; skip untracked (??)
      if (statusCode && !statusCode.includes('?') && filePath) {
        uncommittedFiles.push({ statusCode, filePath });
      }
    }
  } catch (_) {
    // Silent failure if git isn't available or cwd isn't a repo
  }
  const uncommittedFilesLimited = uncommittedFiles.slice(0, 30);

  // --- 8. Format content ---
  const dateStr = new Date().toISOString().slice(0, 10);

  const recentFocusLines = recentUserMessages.length > 0
    ? recentUserMessages.map(m => {
        const truncated = m.length > 150 ? m.slice(0, 147) + '...' : m;
        // Indent continuation lines to keep the list readable
        return '- ' + truncated.replace(/\n/g, ' ');
      }).join('\n')
    : '(no user messages captured)';

  const pathsReferencedLines = filePaths.size > 0
    ? [...filePaths].sort().map(p => '- ' + p).join('\n')
    : '(none detected)';

  const toolsLine = uniqueTools.length > 0
    ? uniqueTools.join(', ')
    : '(none recorded)';

  const uncommittedChangesLines = uncommittedFilesLimited.length > 0
    ? uncommittedFilesLimited.map(({ statusCode, filePath }) => `- ${statusCode} ${filePath}`).join('\n')
    : '(working tree clean)';

  const content = `# Session Context
*Auto-updated by Stop hook — ${dateStr}. Overwritten each turn. Not committed to git.*
*Project: ${cwd}*

## Recent Focus
${recentFocusLines}

## Paths Referenced
${pathsReferencedLines}

## Uncommitted Changes
${uncommittedChangesLines}

## Tools Used
${toolsLine}
`;

  // --- 9. Append/replace session activity on /wrap-authored files ---
  // If existing context.md was written by /wrap (detected by exact two-line
  // startsWith to avoid false matches from user messages in ## Recent Focus),
  // append a "Session Activity" block rather than overwriting. Any previous
  // activity block is stripped first (replace mode — most recent session only,
  // not accumulated). /wrap content is preserved; only another /wrap run
  // replaces the whole file. The Stop hook is the fallback for sessions where
  // /wrap was never run.
  try {
    const existing = fs.readFileSync(outputPath, 'utf8');
    if (existing.startsWith('# Session Context\n*Written by /wrap')) {
      // Strip any previous Session Activity block (sentinel marks its start).
      const ACTIVITY_SENTINEL = '\n\n---\n\n## Session Activity\n';
      const sentinelIdx = existing.indexOf(ACTIVITY_SENTINEL);
      const wrapContent = sentinelIdx >= 0
        ? existing.slice(0, sentinelIdx)
        : existing.trimEnd();

      // Build and append the fresh activity block.
      const activityBlock = `${ACTIVITY_SENTINEL}*Auto-appended by Stop hook — ${dateStr}. Replaced each session.*

### Recent Messages
${recentFocusLines}

### Paths Referenced
${pathsReferencedLines}

### Uncommitted Changes
${uncommittedChangesLines}

### Tools Used
${toolsLine}
`;
      try {
        fs.mkdirSync(projectDir, { recursive: true });
        fs.writeFileSync(outputPath, wrapContent + activityBlock, 'utf8');
      } catch (_) {
        // Silent failure
      }
      // M1: write loop-state on ALL exit paths, including the wrap-coexistence path.
      writeLoopState(cwd);
      // Mirror to batch-state.json (sibling envelope; ordered after loop-state
      // so per-ticket inner state is marked first, then outer batch envelope).
      writeBatchState(cwd, sessionId);
      // Write session_total to events.jsonl on this exit path too.
      writeSessionTotal(cwd, sessionId);
      removeLearningsAgentSession(cwd, sessionId);
      process.exit(0);
    }
  } catch (_) {
    // File does not exist or is unreadable - proceed to write normally.
  }

  // --- 10. Write file (silent failure on any error) ---
  try {
    fs.mkdirSync(projectDir, { recursive: true });
    fs.writeFileSync(outputPath, content, 'utf8');
  } catch (_) {
    // Silent failure
  }

  // --- 11. Write interrupted status to loop-state.json if an active loop exists ---
  // Delegated to writeLoopState() which is also called from the wrap-coexistence
  // path (section 9) so the write executes on ALL exit paths.
  writeLoopState(cwd);

  // --- 11b. Mirror interrupted status to batch-state.json if owned by this session ---
  // Independent best-effort write; ordered after loop-state so per-ticket inner
  // state is marked first, then the outer batch envelope.
  writeBatchState(cwd, sessionId);

  // --- 12. Append session_total event to .agentic/events.jsonl if present ---
  // Independent best-effort write; any failure swallowed.
  writeSessionTotal(cwd, sessionId);

  // --- 13. Remove learnings-agent session marker if owned by this session ---
  removeLearningsAgentSession(cwd, sessionId);

  process.exit(0);
}

run();
