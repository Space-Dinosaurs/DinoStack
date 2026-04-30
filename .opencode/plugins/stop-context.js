/**
 * Purpose: OpenCode plugin that writes session context to disk when the session
 *          becomes idle, so the next session has lightweight context about what
 *          was happening. Also marks active orchestration loops as interrupted.
 *
 * Public API: StopContextPlugin — exported plugin function for OpenCode.
 *
 * Upstream deps: Bun runtime APIs ($, Bun.file, Bun.write). No npm deps.
 *
 * Downstream consumers: OpenCode plugin system (loaded from
 *                        ~/.config/opencode/plugins/ or .opencode/plugins/).
 *
 * Failure modes: Silent failure on all errors. Context write and loop-state write
 *                are independent — one failing does not affect the other.
 *
 * Performance: ~5-20 ms typical; one git status subprocess call.
 */

export const StopContextPlugin = async ({ directory, $ }) => {
  const recentMessages = [];
  const filePaths = new Set();
  const toolsUsed = new Set();
  const MAX_MESSAGES = 10;

  return {
    "message.updated": async ({ message }) => {
      if (message.role !== 'user') return;

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
    },

    "tool.execute.after": async ({ tool, args }) => {
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

    "session.idle": async () => {
      const cwd = directory || process.cwd();
      const dateStr = new Date().toISOString().slice(0, 10);

      // Detect uncommitted changes via git status --porcelain
      const uncommittedFiles = [];
      try {
        const result = await $`git status --porcelain`.text();
        for (const line of result.split('\n')) {
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

      const recentFocus = recentMessages.slice(-3).map(m => {
        const truncated = m.length > 150 ? m.slice(0, 147) + '...' : m;
        return '- ' + truncated.replace(/\n/g, ' ');
      }).join('\n') || '(no user messages captured)';

      const pathsReferenced = filePaths.size > 0
        ? [...filePaths].sort().map(p => '- ' + p).join('\n')
        : '(none detected)';

      const toolsLine = [...toolsUsed].sort().join(', ') || '(none recorded)';

      const uncommittedChangesLines = uncommittedFiles.length > 0
        ? uncommittedFiles.map(({ statusCode, filePath }) => `- ${statusCode} ${filePath}`).join('\n')
        : '(working tree clean)';

      const projectDir = `${cwd}/.agentic`;
      const outputPath = `${projectDir}/context.md`;

      // --- /wrap coexistence: append activity block if file was written by /wrap ---
      try {
        const existingFile = Bun.file(outputPath);
        if (await existingFile.exists()) {
          const existing = await existingFile.text();
          if (existing.startsWith('# Session Context\n*Written by /wrap')) {
            // Strip any previous Session Activity block (sentinel marks its start).
            const ACTIVITY_SENTINEL = '\n\n---\n\n## Session Activity\n';
            const sentinelIdx = existing.indexOf(ACTIVITY_SENTINEL);
            const wrapContent = sentinelIdx >= 0
              ? existing.slice(0, sentinelIdx)
              : existing.trimEnd();

            // Build and append the fresh activity block.
            const activityBlock = `${ACTIVITY_SENTINEL}*Auto-appended by session idle plugin — ${dateStr}. Replaced each session.*

### Recent Messages
${recentFocus}

### Paths Referenced
${pathsReferenced}

### Uncommitted Changes
${uncommittedChangesLines}

### Tools Used
${toolsLine}
`;

            try {
              await $`mkdir -p ${projectDir}`;
              await Bun.write(outputPath, wrapContent + activityBlock);
            } catch (_) {
              // Silent failure
            }

            // Write loop-state on ALL exit paths, including the wrap-coexistence path.
            try {
              const loopStatePath = `${cwd}/.agentic/loop-state.json`;
              const loopStateFile = Bun.file(loopStatePath);
              if (await loopStateFile.exists()) {
                const loopState = await loopStateFile.json();
                if (loopState.status === 'active') {
                  loopState.status = 'interrupted';
                  loopState.interrupted_at = new Date().toISOString();
                  loopState.interrupt_reason = 'unknown';
                  await Bun.write(loopStatePath, JSON.stringify(loopState, null, 2));
                }
              }
            } catch (_) {
              // Silent failure
            }

            return;
          }
        }
      } catch (_) {
        // File does not exist or is unreadable - proceed to write normally.
      }

      // --- Normal write (no /wrap file present) ---
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
      } catch (_) {
        // Silent failure
      }

      // Write interrupted status to loop-state.json if an active loop exists
      try {
        const loopStatePath = `${cwd}/.agentic/loop-state.json`;
        const loopStateFile = Bun.file(loopStatePath);
        if (await loopStateFile.exists()) {
          const loopState = await loopStateFile.json();
          if (loopState.status === 'active') {
            loopState.status = 'interrupted';
            loopState.interrupted_at = new Date().toISOString();
            loopState.interrupt_reason = 'unknown';
            await Bun.write(loopStatePath, JSON.stringify(loopState, null, 2));
          }
        }
      } catch (_) {
        // Silent failure — the 10-minute implicit-interrupt heuristic handles missed writes
      }
    }
  };
};
