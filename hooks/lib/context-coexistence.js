'use strict';

/**
 * Purpose: Pure serializers for preserving /wrap-authored context while adding
 *          the latest automated session activity block.
 *
 * Public API: WRAP_HEADER_PREFIX, ACTIVITY_SENTINEL,
 *             mergeAutomatedContext(existing, fallback, activityBlock).
 *
 * Upstream deps: none.
 *
 * Downstream consumers: context-safe I/O adapters for Claude, Codex, and
 *                       OpenCode context writers.
 *
 * Failure modes: rejects non-string inputs. It performs no I/O and is safe to
 *                retry. Existing /wrap bytes before the first exact activity
 *                sentinel are preserved byte-for-byte.
 *
 * Performance: linear in the existing context length.
 */

const WRAP_HEADER_PREFIX = '# Session Context\n*Written by /wrap';
const ACTIVITY_SENTINEL = '\n\n---\n\n## Session Activity\n';

function mergeAutomatedContext(existing, fallback, activityBlock) {
  if (typeof existing !== 'string' || typeof fallback !== 'string' || typeof activityBlock !== 'string') {
    throw new TypeError('context coexistence inputs must be strings');
  }
  if (!existing.startsWith(WRAP_HEADER_PREFIX)) return fallback;

  const sentinelIndex = existing.indexOf(ACTIVITY_SENTINEL);
  const wrapBase = sentinelIndex >= 0
    ? existing.slice(0, sentinelIndex)
    : existing.trimEnd();
  const normalizedActivity = activityBlock.startsWith(ACTIVITY_SENTINEL)
    ? activityBlock.slice(ACTIVITY_SENTINEL.length)
    : activityBlock;
  return wrapBase + ACTIVITY_SENTINEL + normalizedActivity;
}

module.exports = {
  WRAP_HEADER_PREFIX,
  ACTIVITY_SENTINEL,
  mergeAutomatedContext,
};
