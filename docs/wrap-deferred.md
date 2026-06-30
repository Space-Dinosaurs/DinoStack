<!--
Purpose: Operator-facing guide for the /wrap-deferred command and the
         deferred-wrap daemon. Explains what it is, how it differs from /wrap,
         when it runs, the non-interactive contract, and the security model.

Public API: Operator-facing prose. Entry point for anyone who sees the daemon
            in logs or wants to understand why a session was enriched without
            a manual /wrap call. Full daemon setup, runtime state, and security
            design live in hooks/wrap-deferred.README.md.

Upstream deps: content/commands/wrap-deferred.md (command spec);
               hooks/wrap-deferred.README.md (daemon setup and security model);
               content/commands/wrap.md (interactive counterpart).

Downstream consumers: docs site root index.

Failure modes: Stale if the non-interactive contract, omission table, or
               security model changes. Update alongside
               content/commands/wrap-deferred.md in the same change.

Performance: Standard.
-->

# /wrap-deferred

`/wrap-deferred` is the non-interactive counterpart of `/wrap`. It runs
automatically via a background daemon to finalize session enrichment when a
session ends without a manual `/wrap` call.

You do not invoke this command yourself. The daemon (`hooks/wrap-daemon.js`)
detects cleanly-ended sessions, resumes them headlessly, and runs
`/wrap-deferred` to write the same three targets as `/wrap` - session context,
memory, and AGENTS.md updates - in a single unattended pass.

The daemon setup, runtime state, stop/reset procedure, and security model
are in `hooks/wrap-deferred.README.md`. This page explains what the command
does and why it exists.

## Why it exists

The interactive `/wrap` hangs headlessly. It reaches a human-decision point
early in its pipeline (a stale-lock prompt) and waits for input that never
arrives. `/wrap-deferred` exists to close that gap: a single-pass command with
no prompts, no subagents, and no loops that the daemon can run safely without
a human at the other end.

The result: sessions that end without a manual `/wrap` still get their context,
memory, and AGENTS.md updated - just with less fidelity than the full
interactive path.

## How it differs from /wrap

The interactive `/wrap` is a multi-pass, Skeptic-reviewed pipeline. `/wrap-deferred`
is a single in-session model pass with the same write targets but fewer steps.

| `/wrap` step | `/wrap-deferred` |
|---|---|
| Draft Worker (subagent) | Omitted - conductor surveys inline |
| Skeptic review (two passes) | Omitted |
| context.md merge (Part A) | Kept |
| memory.md Open-PR deferral path | Omitted - writes directly to memory.md |
| AGENTS.md Open-PR deferral path | Omitted - writes directly to AGENTS.md |
| Part D skill-candidate signal | Omitted - Bash tool is removed in daemon context |
| Part E compression | Omitted |
| open-PR enumeration | Omitted |
| /cleanup-worktrees | Omitted |
| Marker transition to `done` | Omitted - the daemon owns this after the child exits 0 |
| Scaffold migration prompts | Omitted - detected drift becomes a "Watch Out For" bullet in context.md |

The write targets are identical: `.agentic/context.md`, `.agentic/memory.md`,
and touched-track AGENTS.md files. The content quality is lower because there
is no draft-review loop - it is a best-effort single pass.

## The non-interactive contract

`/wrap-deferred` satisfies these constraints on every execution path:

- **Never prompts.** No question, no confirmation, no escalation. Any
  ambiguity, blocker, or drift becomes a `## Watch Out For` bullet in
  context.md and the command moves on.
- **One model pass.** Surveys the resumed transcript and live file state, then
  writes. No iteration, no re-route, no re-draft.
- **No subagents.** Spawns nothing. All work happens inline in the resumed
  session.
- **Always reaches a terminal state.** Every path ends in a write or a clean
  exit. No hangs, no wait loops.
- **No git access.** The daemon launches the command with `--disallowedTools "Bash"`,
  removing the Bash tool from the session entirely. This is a deliberate
  security boundary - see below.

## The Bash removal and why it matters

The daemon launches `/wrap-deferred` with `--disallowedTools "Bash"` under
`--permission-mode bypassPermissions`. Under bypass-permissions mode,
`--allowedTools` does not constrain the tool set - it only suppresses approval
prompts. The actual boundary is `--disallowedTools "Bash"`, which removes the
Bash tool from context before the bypass step runs.

This matters because a malicious cloned repository can execute attacker code
through ordinary read-only git verbs (`core.fsmonitor` on `git status`,
`diff.external` on `git diff`, `core.pager`). Running git in a daemon context
that bypasses permissions creates an RCE path. Removing Bash closes that
vector entirely.

The consequence for the command itself: git state (uncommitted changes, recent
commits, branch, stashes) is derived from the resumed conversation transcript
when the ended session described that state, and is omitted otherwise. No
`git status`, `git log`, `git stash list`, or `git diff` runs under the daemon.
The interactive `/wrap`, which runs under normal permissions with a human
present, still reads git normally.

## What it writes

The inputs are the resumed transcript and live reads of a small set of files:
`.agentic/context.md`, `.agentic/memory.md`, root and track `AGENTS.md` files,
and `.agentic/learnings.md` (read-only, to avoid duplicating already-captured
facts).

The write sequence is fixed:

1. **Survey inline.** From the transcript and live file reads, compile: main
   task and state, files touched, errors and gotchas, next steps, stable facts,
   and which AGENTS.md files need updates.

2. **Write context.md** using the shared rolling-session-label merge algorithm.
   The daemon holds a `wrap/lock` window across this step; the child never
   touches the lock directly.

3. **Write memory.md** with append-dedup. Skip if there is nothing stable to
   record. No Open-PR deferral path - writes directly.

4. **Write AGENTS.md updates** with semantic dedup against existing content.
   Skip if nothing to add. No Open-PR deferral path - writes directly.

5. **Exit 0.** The daemon then transitions the per-session marker to `done`.

## Manual /wrap --sync is still the full-fidelity path

`/wrap-deferred` is a fallback for forgotten wraps, not a replacement. Run
`/wrap --sync` manually when the session's work matters and you want:

- Skeptic review of the draft context and memory entries.
- Open-PR deferral for memory and AGENTS.md changes that need review before
  merging.
- Skill-candidate detection (Part D).
- Part E context compression for long sessions.

The daemon enriches unattended; you enrich deliberately.

## Related references

- `hooks/wrap-deferred.README.md` - daemon setup, runtime state, stop/reset, and full security model.
- `content/commands/wrap-deferred.md` - command spec: non-interactive contract, inputs, procedure, and the full omission table vs `/wrap`.
- `content/commands/wrap.md` - interactive `/wrap` pipeline.
