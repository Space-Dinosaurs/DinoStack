#!/usr/bin/env node

/**
 * Purpose: R1 deterministic gate for DS-178 unit A - "Every hook
 *          spawn_complete with a resolvable sidecar carries `agent` equal
 *          to that spawn's `subagent_type`, verified against the sidecar
 *          oracle on a live re-run of the shipped script." This is that
 *          script: it enumerates REAL `.meta.json` sidecar files already
 *          on this machine (the "sidecar oracle" - each file directly
 *          states its own `agentType`, ground truth independent of the
 *          hook under test), copies each one's RAW CONTENT (unmodified)
 *          into a fresh throwaway `<tmp configDir>/projects/<hash>/
 *          <sessionId>/subagents/agent-<agentId>.meta.json` whose
 *          directory layout the hook's own `resolveSubagentFile()`
 *          expects, runs the REAL shipped hook against a synthetic
 *          SubagentStop payload pointing at that throwaway location, and
 *          asserts the emitted `spawn_complete`'s `agent` equals the
 *          sidecar's own `agentType`. Never touches the real
 *          `~/.claude/projects` tree - every run uses fresh, isolated
 *          throwaway directories, only the sidecar CONTENT is real.
 *          Bounded (SAMPLE_LIMIT sidecars, directory-walk order) - not a
 *          full sweep of an unbounded, ever-growing directory.
 *
 *          Round-3 fix (M1): the sandbox now ALSO seeds a decoy
 *          `spawn_start` in the fresh `events.jsonl` before invoking the
 *          hook, carrying a deliberately wrong `agent` label
 *          (DECOY_WRONG_AGENT) and, when the sidecar itself carries a
 *          `toolUseId`, the SAME `tool_use_id` (so the decoy wins an exact
 *          pairing match rather than merely sitting in the FIFO queue).
 *          Without this decoy, the sidecar was the ONLY possible label
 *          source in the sandbox by construction, so an inverted
 *          precedence (paired spawn_start wins over sidecar) could never
 *          be caught - PASS: 60, MISMATCH: 0 either way. With the decoy
 *          present, correct precedence (sidecar wins) still emits the
 *          oracle's real agentType; inverted precedence emits
 *          DECOY_WRONG_AGENT, which mismatches the oracle on every
 *          checked sidecar.
 *
 * Public API: CLI only - `node scripts/verify-spawn-attribution-contract.js
 *             [--limit N]`. Prints a PASS/FAIL count per sidecar and a
 *             summary line; exits 1 if any sidecar with a real `agentType`
 *             produced a mismatched `agent`.
 *
 * Upstream deps: Node built-ins only (fs, path, os, child_process).
 *                hooks/lib/config-dir.js (resolveClaudeConfigDir) - reads
 *                sidecar CONTENT from the real config dir this resolves
 *                to on this machine, but never writes there.
 *
 * Downstream consumers: `content/references/events-log.md`'s "Hook-emitted
 *                        calibration fields (DS-178 unit A)" bullet names
 *                        this script and states when to run it live
 *                        (before any change to findMatch()'s pairing
 *                        precedence or the sidecar-vs-paired-start label
 *                        precedence in hooks/subagent-stop-spawn-emit.js).
 *                        Not wired into CI - the sidecar oracle only
 *                        exists on a machine with real prior sessions, so
 *                        this cannot run in a fresh CI checkout.
 *
 * Failure modes: A sidecar with no `agentType` (or unreadable/malformed)
 *                is SKIPPED, not counted as a failure - it carries no
 *                oracle value. A sidecar whose synthetic re-run produced
 *                no `spawn_complete` at all is reported as an ERROR,
 *                distinct from a MISMATCH (the hook ran and emitted a
 *                value that disagrees with the oracle).
 *
 * Performance: One subprocess (the real hook) plus a few sync fs calls
 *              per sampled sidecar.
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const { resolveClaudeConfigDir } = require('../hooks/lib/config-dir.js');

const hookPath = path.resolve(__dirname, '..', 'hooks', 'subagent-stop-spawn-emit.js');

// Round-3 fix (M1): deliberately wrong label seeded into the decoy
// spawn_start so a mismatch is unambiguous (never a real agent name).
const DECOY_WRONG_AGENT = 'decoy-wrong-agent-DO-NOT-MATCH';

function parseArgs(argv) {
  let limit = 500;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--limit' && argv[i + 1]) {
      limit = Number(argv[i + 1]);
      i++;
    }
  }
  return { limit };
}

/** Walk each project/session's subagents/ dir under <configDir>/projects/
 * for `agent-*.meta.json` files, returning their paths, capped at `limit`. */
function findSidecarPaths(configDir, limit) {
  const projectsDir = path.join(configDir, 'projects');
  const out = [];
  let projectDirs;
  try {
    projectDirs = fs.readdirSync(projectsDir);
  } catch (_) {
    return out;
  }
  for (const projectHashDir of projectDirs) {
    const projectPath = path.join(projectsDir, projectHashDir);
    let sessionDirs;
    try {
      sessionDirs = fs.readdirSync(projectPath);
    } catch (_) {
      continue;
    }
    for (const sessionId of sessionDirs) {
      const subagentsDir = path.join(projectPath, sessionId, 'subagents');
      let files;
      try {
        files = fs.readdirSync(subagentsDir);
      } catch (_) {
        continue;
      }
      for (const f of files) {
        if (/^agent-.+\.meta\.json$/.test(f)) {
          out.push(path.join(subagentsDir, f));
          if (out.length >= limit) return out;
        }
      }
    }
  }
  return out;
}

function readSidecarRaw(sidecarPath) {
  try {
    const raw = fs.readFileSync(sidecarPath, 'utf8');
    if (!raw || !raw.trim()) return null;
    const obj = JSON.parse(raw);
    if (!obj || typeof obj !== 'object') return null;
    const agentType = typeof obj.agentType === 'string' && obj.agentType.trim() ? obj.agentType.trim() : null;
    const toolUseId = typeof obj.toolUseId === 'string' && obj.toolUseId.trim() ? obj.toolUseId.trim() : null;
    return { raw, agentType, toolUseId };
  } catch (_) {
    return null;
  }
}

/** Run the REAL hook against a FRESH throwaway sandbox carrying a copy of
 * *sidecarRaw*'s content at the exact path the hook's own
 * `resolveSubagentFile()` expects, and return the emitted `spawn_complete`
 * event (or null).
 *
 * Round-3 fix (M1): also seeds a decoy `spawn_start` (agent =
 * DECOY_WRONG_AGENT) into the sandbox's own `.agentic/events.jsonl` before
 * the hook runs, so the sandbox actually discriminates between "sidecar
 * wins" and "paired spawn_start wins" instead of the sidecar being the
 * only possible label source. When *sidecarToolUseId* is present the decoy
 * carries the SAME `tool_use_id`, so it wins findMatch()'s exact-match tier
 * rather than merely sitting in the FIFO queue - the worst case for
 * catching an inverted precedence. When absent, the decoy has no
 * `tool_use_id` and is picked up by the FIFO fallback instead (still
 * discriminating, since it remains the only spawn_start candidate). */
function runHookAgainstFreshSidecar(sidecarRaw, sidecarToolUseId) {
  const sandboxCwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ds178-contract-cwd-'));
  const sandboxConfigDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ds178-contract-config-'));
  const sessionId = 'contract-session';
  const agentId = 'contractagent';
  const projectHash = String(sandboxCwd).replace(/\//g, '-');
  const subagentsDir = path.join(sandboxConfigDir, 'projects', projectHash, sessionId, 'subagents');
  fs.mkdirSync(subagentsDir, { recursive: true });
  fs.writeFileSync(path.join(subagentsDir, `agent-${agentId}.meta.json`), sidecarRaw);

  const agenticDir = path.join(sandboxCwd, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  const decoySpawnStart = {
    ts: new Date(Date.now() - 60000).toISOString(),
    phase: 'hook',
    event: 'spawn_start',
    agent: DECOY_WRONG_AGENT,
    task_id: null,
    data: {
      source: 'hook',
      session_uuid: sessionId,
      spawn_id: 'ds178-contract-decoy-spawn',
      ...(sidecarToolUseId ? { tool_use_id: sidecarToolUseId } : {}),
    },
  };
  fs.writeFileSync(path.join(agenticDir, 'events.jsonl'), JSON.stringify(decoySpawnStart) + '\n');

  const payload = {
    cwd: sandboxCwd,
    session_id: sessionId,
    agent_id: agentId,
    hook_event_name: 'SubagentStop',
  };
  const env = Object.assign({}, process.env, { CLAUDE_CONFIG_DIR: sandboxConfigDir });
  spawnSync('node', [hookPath], {
    input: JSON.stringify(payload), cwd: sandboxCwd, env, timeout: 10000, encoding: 'utf8',
  });
  const eventsPath = path.join(sandboxCwd, '.agentic', 'events.jsonl');
  let complete = null;
  try {
    const lines = fs.readFileSync(eventsPath, 'utf8').split('\n').filter(Boolean);
    for (const line of lines) {
      let obj;
      try { obj = JSON.parse(line); } catch (_) { continue; }
      if (obj && obj.event === 'spawn_complete') complete = obj;
    }
  } catch (_) { /* no events file - hook found nothing */ }
  try { fs.rmSync(sandboxCwd, { recursive: true, force: true }); } catch (_) { /* best-effort */ }
  try { fs.rmSync(sandboxConfigDir, { recursive: true, force: true }); } catch (_) { /* best-effort */ }
  return complete;
}

function main() {
  const { limit } = parseArgs(process.argv.slice(2));
  const configDir = resolveClaudeConfigDir();
  const sidecarPaths = findSidecarPaths(configDir, limit);

  let checked = 0;
  let pass = 0;
  let mismatch = 0;
  let errored = 0;
  let skippedNoAgentType = 0;

  for (const sidecarPath of sidecarPaths) {
    const sidecar = readSidecarRaw(sidecarPath);
    if (!sidecar || !sidecar.agentType) {
      skippedNoAgentType++;
      continue;
    }
    checked++;
    const complete = runHookAgainstFreshSidecar(sidecar.raw, sidecar.toolUseId);
    if (!complete) {
      errored++;
      console.error(`ERROR: no spawn_complete emitted re-running ${sidecarPath}`);
      continue;
    }
    if (complete.agent === sidecar.agentType) {
      pass++;
    } else {
      mismatch++;
      console.error(
        `MISMATCH: ${sidecarPath} oracle=${sidecar.agentType} emitted=${complete.agent} agent_source=${(complete.data || {}).agent_source}`
      );
    }
  }

  console.log(`\nSampled sidecars: ${sidecarPaths.length} (limit ${limit})`);
  console.log(`Skipped (no agentType in sidecar): ${skippedNoAgentType}`);
  console.log(`Checked (had a real oracle agentType): ${checked}`);
  console.log(`PASS: ${pass}`);
  console.log(`MISMATCH: ${mismatch}`);
  console.log(`ERROR (no spawn_complete emitted): ${errored}`);

  process.exit(mismatch > 0 ? 1 : 0);
}

main();
