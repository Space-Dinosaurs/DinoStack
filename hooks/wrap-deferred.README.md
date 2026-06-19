# Deferred `/wrap` daemon - operator runbook

Operator/maintainer home for the deferred-`/wrap` daemon. For code-level invariants
read the module manifests at the top of `hooks/wrap-daemon.js`, `hooks/lib/wrap-marker.js`,
and `hooks/stop-context.js` - this file does not restate them.

## What it is / when it runs

An opt-in, Claude-only, out-of-session daemon that finalizes forgotten session wraps.
When a session ends cleanly without a manual `/wrap`, the SessionEnd hook stages a
`ready` marker; a per-project background daemon (`hooks/wrap-daemon.js`) drains that
queue by headlessly resuming each session and running a non-interactive single-pass
`/wrap-deferred` enrichment in the main project dir. It is inert by default and never
runs unless the master toggle is on. The interactive synchronous `/wrap` is untouched
by this subsystem.

## How to enable & configure

The feature is gated behind one master toggle in `.agentic/config.json`:

- `deferred_wrap_daemon` - boolean, default `false`. The master switch. When `false`
  (the default) no daemon spawns and no marker is staged; synchronous `/wrap` is
  byte-identical to a build without this feature.

The five tuning params are consulted ONLY when `deferred_wrap_daemon` is `true`:

| Key | Default | Meaning |
|---|---|---|
| `deferred_wrap_idle_minutes` | `15` | Minutes of session idle before a session is eligible for an out-of-session wrap; also the daemon's self-exit idle window. |
| `deferred_wrap_heartbeat_seconds` | `120` | Interval at which the daemon writes a liveness heartbeat while processing a job. |
| `deferred_wrap_timeout_minutes` | `10` | Maximum minutes a single headless child may run before the daemon kills it. |
| `deferred_wrap_inprogress_reclaim_minutes` | `30` | Minutes after which an `in_progress` job with a stale heartbeat is reclaimed and re-queued. |
| `deferred_wrap_pending_ttl_days` | `7` | Days a `pending` marker is retained before the janitor expires it. |

All six keys are optional; an absent key takes its default. Leaving the file unchanged
keeps the feature off.

## What state it owns

All runtime artifacts live under `[cwd]/.agentic/wrap/` and are gitignored (covered by
the `.agentic/` umbrella in a consumer project). `hooks/lib/wrap-marker.js` is the single
source of truth for these paths:

| Path | What it is |
|---|---|
| `pending-<session_id>.json` | Per-session marker (the state machine: `pending` -> `ready` -> `in_progress` -> `done`/`gave_up`). |
| `last-wrap` | Single-slot sentinel recording the last-wrapped session id. |
| `lock` (a DIRECTORY) | The wrap lock the daemon holds around each child spawn. |
| `lock/owner` | The lock owner record (`{ pid, ts }`). |
| `daemon.pid` | PID-file singleton; one daemon per project. |
| `daemon.log` | Bounded operator log (rotates to `daemon.log.1` at ~2 MB). |
| `daemon-auth-failed` | One-time notice written when `claude auth status` fails. |
| `claude-host` | Self-healing sentinel marking a Claude host; gates Step 0a staging. |
| `heartbeats/<session_id>` | Per-job liveness mtime touched while draining. |
| `deferred-activity.jsonl` | Append-only deferred-activity record. |

`.agentic/config.json` stays at the `.agentic/` top level - it is project-wide methodology
config, not a wrap artifact, and is never placed under `.agentic/wrap/`.

## How to stop / reset it

**Stop (primary):** set `deferred_wrap_daemon: false` in `.agentic/config.json`. This
stops every daemon spawn and all marker staging immediately, with zero effect on
synchronous `/wrap`. No code change is needed.

**Reset / cleanup:** the `.agentic/wrap/` runtime files are gitignored and safe to remove
when no daemon is running:

```
rm -rf .agentic/wrap/
```

Do this only while the daemon is stopped. The daemon enforces a `daemon.pid` singleton
(O_EXCL): a second daemon refuses to start while a live one owns the file. A stale pid
(the recorded PID is dead) is reclaimed automatically on the next start - a fresh daemon
detects the dead owner and takes over the pid file. Deleting `daemon.pid` by hand is not
required for a normal restart.

## Security model (plain terms)

The headless child runs under `--permission-mode bypassPermissions`. Under that mode the
`--allowedTools` allowlist does NOT constrain the tool set - it only suppresses approval
prompts for the tools it lists; unlisted tools stay in context and auto-approve. The
actual boundary is `--disallowedTools Bash`, which REMOVES `Bash` from the model's context
before the bypass step runs.

What this does and does not buy you:

- **Closes RCE-via-read-only-git-verb DURING the drain.** A malicious cloned repo ships its
  own repo-local `.git/config`, which git reads on every invocation. Execution hooks there
  fire on ordinary read-only verbs (`core.fsmonitor` on `git status`, `diff.external` on
  `git diff`, `core.pager`/`alias.*`/`ext::`). With `Bash` removed from context the child
  can never shell git, so those vectors never fire while the daemon drains.
- **Does NOT stop the child from PLANTING code that runs later.** The deferred Write/Edit
  surface (`.agentic/`, `AGENTS.md`, `memory.md`, and similar) is broad, trusted-child-only,
  and unreviewed for adversarial input by design (there is no Skeptic on the deferred pass).
  A child could write a hook, a `.git/hooks/` script, or a `core.hooksPath` target that runs
  on a later git command. The boundary closes execution DURING the drain, not all future
  execution. State the accurate claim: the child "can't run code during the drain", not
  "can't run code".

Defense-in-depth layered on top:

- `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_SYSTEM=/dev/null`, `GIT_CONFIG_NOSYSTEM=1` in
  every spawned child env, neutralizing the global/system git config tiers.
- `AGENTIC_WRAP_DAEMON=1` exported to the child as a loop-guard: every marker transition
  and launch entry point no-ops under the guard, so the child's own Stop/SessionEnd cannot
  stage a new marker and trigger an infinite re-wrap.
- Symlink hardening on the lock and log paths (`O_NOFOLLOW` open, `lstat` no-follow guards
  on the `lock` directory and its `owner` leaf), so a planted symlink cannot redirect a
  write or be read through.

## Rollback

- **Primary (config-only, instant):** flip `deferred_wrap_daemon: false`. The daemon stops,
  Step 0a stages nothing, synchronous `/wrap` is unaffected. This is the intended rollback
  for any behavioral problem found in the field - no code revert needed.
- **Code defect:** `git revert` the offending commit, regenerate adapters (run each
  `*/build.sh`), and remove the gitignored runtime files (`rm -rf .agentic/wrap/`) on any
  project where the daemon ran. Each unit writes a disjoint file set, so a single-commit
  revert is self-contained.

Because the feature is opt-in and inert when off, there is no urgent rollback pressure: a
half-landed or suspected-bad daemon is harmless until the toggle is on.

## Risk register (condensed)

| Risk | Mitigation |
|---|---|
| **Live-resume corruption** - the daemon resumes a still-live session and interleaves its transcript. | The sole `pending` -> `ready` transition is SessionEnd's terminal-reason `finalizeReady`; there is NO stale-sweep. The daemon claims ONLY `ready` markers; `reclaimAbandonedInProgress` never touches `pending`, so a live/idle session cannot be resumed. |
| **Infinite re-wrap loop** - the child's own `/wrap-deferred` stages a new marker. | `AGENTIC_WRAP_DAEMON=1` loop-guard no-ops every marker/launch entry point in the child; the `last-wrap` sentinel is a secondary backstop. |
| **Marker-state regression** - a late Stop downgrades `ready` -> `pending`, losing the finalize. | `stagePending` suppresses staging when a marker is already `ready`/`pending`/`in_progress`; `finalizeReady` never downgrades. |
| **Silent feature no-op** - an existing install lacks the `claude-host` sentinel, so Step 0a never stages. | Self-healing sentinel: SessionStart writes `claude-host` create-if-absent on every start; the install drop is a belt-and-suspenders second writer. |
| **Off-Claude / toggle-off behavior change** - `/wrap` not byte-identical when the feature is inactive. | Step 0a is gated on the `claude-host` sentinel + the toggle + the non-guard condition; an off-Claude host has no sentinel and stages nothing. |
| **Doc / intent drift** - toggle counts, manifests, and carve-outs go stale. | Config keys and counts are kept in sync in `content/rules/conventions.md`; module manifests are updated with the code; adapter regen is verified by the build gate. |
