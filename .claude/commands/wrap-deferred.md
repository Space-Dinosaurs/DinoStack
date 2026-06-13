> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.

# /wrap-deferred - Non-Interactive Single-Pass Session Enrichment

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

This command is invoked by the deferred-wrap daemon (`hooks/wrap-daemon.js`), not directly by users. The daemon resumes a cleanly-ended session headlessly (`claude --resume <id> -p "/wrap-deferred"` with `AGENTIC_WRAP_DAEMON=1`) and runs this command in the MAIN project directory. It is the non-interactive counterpart of `/wrap`: where `/wrap` is an interactive, multi-pass, Skeptic-reviewed pipeline that a human drives, `/wrap-deferred` is a single headless model pass that writes good-faith enrichment of the same three targets with NO prompts and NO subagents, then exits.

**The interactive `/wrap` provably hangs headlessly** on its first human-decision point (a stale-lock prompt). `/wrap-deferred` exists so the daemon can finalize forgotten wraps unattended. Manual `/wrap --sync` remains the full-fidelity path; users never invoke `/wrap-deferred` themselves.

## Non-interactive contract (binding)

`/wrap-deferred` MUST satisfy all of these on every path:

- **Never prompts.** No question, no confirmation, no escalation-to-user is ever emitted. There is no human at the other end of a daemon-resumed session. On ANY ambiguity, blocker, contention, or drift: write what it can safely write, exit cleanly, NEVER ask.
- **One model pass.** A single in-session pass surveys the resumed transcript and live state, then writes. No iteration loop, no re-route, no re-draft.
- **No subagents.** Spawns nothing. Specifically OMITTED versus `/wrap`: the draft Worker, the Skeptic (both the Steps 2-3 draft review and the Step 4 hand-authored on-disk Skeptic), Part E compression, `/cleanup-worktrees`, the `gh pr` open-PR enumeration and its Open-PR deferral passes, the scaffold-migration pre-flight, the no-active-Workers pre-flight, and the drift-requires-input prompt. The conductor of the resumed session performs the survey and the writes inline itself.
- **Always reaches a terminal state.** Every path ends in either a write-or-clean-exit. There is no hang, no wait-loop, no blocking.
- **Marker `done` is NOT transitioned here.** The daemon owns the per-session marker lifecycle: it claimed the marker to `in_progress` before spawning this command, and it transitions the marker to `done` (then unlinks) ONLY after this headless process exits 0. `/wrap-deferred` does NOT touch `.agentic/wrap-pending-<session_id>.json` at all. If `/wrap-deferred` cannot write a target, it still exits cleanly (the daemon counts the attempt); it never marks itself done or gave_up.

## Inputs

- **The resumed transcript** - the conversation of the ended session, reloaded by `claude --resume`. This is the primary source for Recent Focus, next steps, files touched, stable facts, AND any git-state detail (uncommitted changes, recent commits, branch, stashes) the ended session described in its conversation.
- **Live file state in the main project dir** - read-only reads of: the existing `.agentic/context.md`, `.agentic/memory.md`, root and track `AGENTS.md` files (merge targets); and `.agentic/learnings.md` (read-only - so a proposed memory entry is not re-derived from a fact already captured as a structured learning).

**No git execution under the daemon (deliberate security boundary).** `/wrap-deferred` has NO Bash/git access: the daemon spawns it with `--disallowedTools "Bash"`, which REMOVES the `Bash` tool from the headless model's context entirely. This is intentional, not an oversight. The headless child runs under `--permission-mode bypassPermissions`, and under that mode `--allowedTools` does NOT constrain the tool set - it only suppresses approval prompts for the tools it lists, while any unlisted tool (including `Bash`) stays in context and is auto-approved by the bypass. So the file-tools allowlist (`Read,Edit,Write,Glob,Grep`) is NOT the boundary; the actual boundary is `--disallowedTools "Bash"`, which deletes `Bash` from context before the bypass-mode step runs. This matters because a malicious cloned repo's own repo-local `.git/config` executes attacker code on ordinary read-only verbs (`core.fsmonitor` on `git status`, `diff.external` on `git diff`, `core.pager`/`alias.*`/`ext::`) - running git in that context is an RCE vector. With `Bash` removed from context the deferred path can NEVER shell git. (Supplementary `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM`/`GIT_CONFIG_NOSYSTEM` env hardening neutralizes the global/system config tiers as defense-in-depth.)

Consequently the context.md git-state section (uncommitted changes, recent commits, branch, stashes) is derived from the resumed **conversation transcript** when the ended session described that state, and is **OMITTED** otherwise. Do not attempt to run `git status`, `git log`, `git stash list`, `git diff`, `git rev-parse`, or `git branch` - the tool is not granted and the attempt fails. The interactive `/wrap` - run by a human under normal (non-bypassed) permissions - still reads git normally; that path is unaffected.

The daemon enriches in the main project dir (no worktree, no copy-back, no merge), so the schema carries no `branch`/`head_sha`.

## Procedure (single pass, in this order)

**Step 1 - Survey (inline, no subagent).** From the resumed transcript and the live FILE reads above (no git - see the Inputs note), compile: the main task and its state; files touched this session (full paths); errors/gotchas/near-misses; concrete remaining next steps; tools used; stable project facts worth preserving (distinguish stable facts -> memory.md from temporary state -> context.md); the uncommitted/stashed safety-net lists ONLY when the resumed transcript described them (no `git status`/`git stash list` is run under the daemon - omit if the conversation did not surface them); the touched tracks that are candidates for AGENTS.md updates. Read `.agentic/learnings.md` so already-captured facts are not duplicated into memory.md. This is the same survey `/wrap` Step 0 performs, minus the `gh pr` open-PR enumeration (omitted - no deferral pass here) and minus all git reads (the deferred path has no Bash/git - the interactive `/wrap` keeps them).

**Step 2 - Write `.agentic/context.md` (Part A; the only lock-touching write).**

Acquire `wrap.lock` around the NARROW Part-A window only, exactly as `/wrap` Part A does, and run the shared algorithm cited in `content/references/wrap-context-format.md`: (1) the 3-step rename-first spillover drain; (2) the rolling-session-label merge write (file-absent / non-/wrap / merge branches, duplicate-claim dedup, 1-to-5 label rolling window, per-section merge rules) - the merged write begins with the pinned header prefix `# Session Context\n*Written by /wrap`; (3) write `.agentic/.last-wrap` = this `session_id`; (4) release the lock (`rm -rf .agentic/wrap.lock`) as the last action.

**Lock handling is non-interactive (no wait-loop, no prompt).** Acquire the lock via `acquireWrapLock` (from `hooks/lib/wrap-marker.js`), which auto-clears a stale lock (>30 min) in code without prompting. If the lock STILL cannot be acquired after the auto-stale-clear (a live `/wrap` or `wrap-ticket` holds it), do NOT wait and do NOT prompt: instead append this session's would-be context.md activity to the spillover log `.agentic/.stop-deferred-activity.jsonl` (the same JSONL the Stop hook spills to under contention, per `content/references/wrap-context-format.md`) and exit cleanly. The live lock-holder's drain folds the spilled record into context.md on its next Part-A window. Release the lock on EVERY exit path that acquired it.

**Step 3 - Write `.agentic/memory.md` (Part B; no lock, no Open-PR deferral).**

Skip if there are no stable facts to record. Otherwise apply the shared Part B append-dedup from `/wrap`: read the existing `.agentic/memory.md`; for each proposed stable-fact entry, skip it if the same fact is already captured in `.agentic/memory.md` OR as a structured learning in `.agentic/learnings.md` (semantic dedup, not string match); supersede an existing entry in place when the new entry corrects or updates the same topic; otherwise append. Entry format `- **YYYY-MM-DD:** [what was decided and why]` using today's date. There is NO Open-PR deferral pass and NO `.agentic/memory-pending.md` routing - write directly to `.agentic/memory.md`.

**Step 4 - Write AGENTS.md updates (Part C; no lock, no Open-PR deferral).**

Skip if there are no AGENTS.md additions. Otherwise apply the shared Part C from `/wrap`: for each touched track's AGENTS.md, append only genuinely-new, session-derived bullets (semantic dedup against existing content); create a minimal stub for a touched directory that has no AGENTS.md and apply the additions into it; apply any `Update:` corrections in place. Root AGENTS.md focuses on `## Decisions` and `## Conventions`; subdir AGENTS.md on `## Stack` / `## Key Conventions` / track-relevant categories. There is NO Open-PR deferral pass and NO `.agentic/agents-md-pending.md` routing - write directly to the AGENTS.md files. Do NOT run the pre-AGENTS.md three-way split (that requires user confirmation `/wrap` cannot provide headlessly either) - if a pre-AGENTS.md layout is detected, record it as a context.md "Watch Out For" bullet instead.

**Drift is never a prompt.** Any scaffolding drift, ambiguity, or condition that the interactive `/wrap` would surface to the user becomes a single `## Watch Out For` bullet in the `.agentic/context.md` output (e.g. "Pre-AGENTS.md layout detected; run /init-project to migrate", "Linear workspace slug not set", "both .claude/findings.md and .agentic/findings.md exist - resolve manually"). `/wrap-deferred` writes the bullet and moves on; it does not pause, migrate destructively, or ask.

**Exit.** After the writes (or after a clean early exit because the lock could not be acquired, or because the survey found nothing substantive to write), exit. Exit 0 on a successful pass. Do NOT transition the marker - the daemon transitions it to `done` after observing exit 0.

## Omitted versus `/wrap` (explicit)

| `/wrap` step | `/wrap-deferred` |
|---|---|
| no-active-Workers pre-flight | omitted (daemon already serialized) |
| scaffold-migration pre-flight (CLAUDE.md->AGENTS.md, legacy `.claude/*` moves) | omitted; detected drift -> context.md "Watch Out For" bullet |
| lock wait-loop + stale-lock prompt | omitted; auto-stale-clear in code, else spill + clean exit |
| draft Worker (Step 1) | omitted; conductor surveys inline |
| Skeptic (Steps 2-3 draft review) | omitted |
| Step 4 hand-authored on-disk Skeptic | omitted |
| Part A context.md merge | KEPT (cites `wrap-context-format.md`) |
| Part B Open-PR deferral / memory-pending.md | omitted; direct append-dedup to memory.md |
| Part C Open-PR deferral / agents-md-pending.md | omitted; direct write to AGENTS.md |
| Part E compression | omitted |
| `gh pr` open-PR enumeration | omitted |
| Step 5 `/cleanup-worktrees` | omitted |
| Step 6 terminal marker transition | omitted; daemon owns `done` |
| drift-requires-input prompt | omitted; drift -> context.md "Watch Out For" bullet |
