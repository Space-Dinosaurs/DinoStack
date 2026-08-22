---
description: "/ds-wrap-deferred - Non-Interactive Single-Pass Session Enrichment"
agent: build
---
# /ds-wrap-deferred - Non-Interactive Single-Pass Session Enrichment

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

> Operators/maintainers: see `hooks/wrap-deferred.README.md` for enabling and configuring the daemon, the runtime state it owns, how to stop/reset it, the security model, and the rollback procedure.

This command is invoked by the deferred-wrap daemon (`hooks/wrap-daemon.js`), not directly by users. The daemon resumes a cleanly-ended session headlessly (`claude --resume <id> -p "/ds-wrap-deferred"` with `AGENTIC_WRAP_DAEMON=1`) and runs this command in the MAIN project directory. It is the non-interactive counterpart of `/ds-wrap`: where `/ds-wrap` is an interactive, multi-pass, Skeptic-reviewed pipeline that a human drives, `/ds-wrap-deferred` is a single headless model pass that writes good-faith enrichment of the same three targets with NO prompts and NO subagents, then exits.

**The interactive `/ds-wrap` provably hangs headlessly** on its first human-decision point (a stale-lock prompt). `/ds-wrap-deferred` exists so the daemon can finalize forgotten wraps unattended. Manual `/ds-wrap --sync` remains the full-fidelity path; users never invoke `/ds-wrap-deferred` themselves.

## Non-interactive contract (binding)

`/ds-wrap-deferred` MUST satisfy all of these on every path:

- **Never prompts.** No question, no confirmation, no escalation-to-user is ever emitted. There is no human at the other end of a daemon-resumed session. On ANY ambiguity, blocker, contention, or drift: write what it can safely write, exit cleanly, NEVER ask.
- **One model pass.** A single in-session pass surveys the resumed transcript and live state, then writes. No iteration loop, no re-route, no re-draft.
- **No subagents.** Spawns nothing. Specifically OMITTED versus `/ds-wrap`: the draft Worker, the Skeptic (both the Steps 2-3 draft review and the Step 4 hand-authored on-disk Skeptic), Part E compression, `/ds-cleanup-worktrees`, the `gh pr` open-PR enumeration and its Open-PR deferral passes, the scaffold-migration pre-flight, the no-active-Workers pre-flight, and the drift-requires-input prompt. The conductor of the resumed session performs the survey and the writes inline itself.
- **Always reaches a terminal state.** Every path ends in either a write-or-clean-exit. There is no hang, no wait-loop, no blocking.
- **Marker `done` is NOT transitioned here.** The daemon owns the per-session marker lifecycle: it claimed the marker to `in_progress` before spawning this command, and it transitions the marker to a retained `done` tombstone (stamped `wrapped_at`; reaped by the janitor after ttl) ONLY after this headless process exits 0. `/ds-wrap-deferred` does NOT touch `.agentic/wrap/pending-<session_id>.json` at all. If `/ds-wrap-deferred` cannot write a target, it still exits cleanly (the daemon counts the attempt); it never marks itself done or gave_up.

## Inputs

- **The resumed transcript** - the conversation of the ended session, reloaded by `claude --resume`. This is the primary source for Recent Focus, next steps, files touched, stable facts, AND any git-state detail (uncommitted changes, recent commits, branch, stashes) the ended session described in its conversation.
- **Live file state in the main project dir** - read-only reads of: the existing `.agentic/_wrap.md` (the curated context file - **not** `.agentic/context.md`, which is a derived rollup recomposed from `_wrap.md` plus the per-session shards in `.agentic/context.d/`; writing it directly is discarded on the next Stop turn), `.agentic/memory.md` (the staging area this path writes), root `MEMORY.md` (**read-only** - dedup target, never written here; see Step 3), root and track `AGENTS.md` files (merge targets); and `.agentic/learnings.md` (read-only - so a proposed memory entry is not re-derived from a fact already captured as a structured learning).

**No git execution under the daemon (deliberate security boundary).** `/ds-wrap-deferred` has NO Bash/git access: the daemon spawns it with `--disallowedTools "Bash"`, which REMOVES the `Bash` tool from the headless model's context entirely. This is intentional, not an oversight. The headless child runs under `--permission-mode bypassPermissions`, and under that mode `--allowedTools` does NOT constrain the tool set - it only suppresses approval prompts for the tools it lists, while any unlisted tool (including `Bash`) stays in context and is auto-approved by the bypass. So the file-tools allowlist (`Read,Edit,Write,Glob,Grep`) is NOT the boundary; the actual boundary is `--disallowedTools "Bash"`, which deletes `Bash` from context before the bypass-mode step runs. This matters because a malicious cloned repo's own repo-local `.git/config` executes attacker code on ordinary read-only verbs (`core.fsmonitor` on `git status`, `diff.external` on `git diff`, `core.pager`/`alias.*`/`ext::`) - running git in that context is an RCE vector. With `Bash` removed from context the deferred path can NEVER shell git. (Supplementary `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM`/`GIT_CONFIG_NOSYSTEM` env hardening neutralizes the global/system config tiers as defense-in-depth.) Note that the deferred Write/Edit surface (`.agentic/`, `.git/hooks/`, `core.hooksPath` under `bypassPermissions`) is broad and trusted-child-only, not reviewed for adversarial input; RCE-via-read-only-git-verb is closed by `--disallowedTools "Bash"` but not every write-path risk is addressed by that boundary alone.

Consequently the curated git-state section (uncommitted changes, recent commits, branch, stashes) is derived from the resumed **conversation transcript** when the ended session described that state, and is **OMITTED** otherwise. Do not attempt to run `git status`, `git log`, `git stash list`, `git diff`, `git rev-parse`, or `git branch` - the tool is not granted and the attempt fails. The interactive `/ds-wrap` - run by a human under normal (non-bypassed) permissions - still reads git normally; that path is unaffected.

The daemon enriches in the main project dir (no worktree, no copy-back, no merge), so the schema carries no `branch`/`head_sha`.

## Procedure (single pass, in this order)

**Step 1 - Survey (inline, no subagent).** From the resumed transcript and the live FILE reads above (no git - see the Inputs note), compile: the main task and its state; files touched this session (full paths); errors/gotchas/near-misses; concrete remaining next steps; tools used; stable project facts worth preserving (distinguish stable facts -> `.agentic/memory.md` staging (promoted to root `MEMORY.md` by the next synchronous `/ds-wrap`) from temporary state -> `_wrap.md`); the uncommitted/stashed safety-net lists ONLY when the resumed transcript described them (no `git status`/`git stash list` is run under the daemon - omit if the conversation did not surface them); the touched tracks that are candidates for AGENTS.md updates. Read `.agentic/learnings.md` so already-captured facts are not duplicated into staging. This is the same survey `/ds-wrap` Step 0 performs, minus the `gh pr` open-PR enumeration (omitted - no deferral pass here) and minus all git reads (the deferred path has no Bash/git - the interactive `/ds-wrap` keeps them).

**Step 2 - Write `.agentic/_wrap.md` (Part A; the lock-guarded write - daemon holds wrap/lock for this step). Retarget only: the Part A algorithm in `content/references/wrap-context-format.md` is unchanged; it now reads and writes `_wrap.md`. Never write `.agentic/context.md` here - it is derived and the next Stop turn would discard the write.**

This step runs inside a `wrap/lock` window the daemon holds (see item (4) below). Run the shared algorithm cited in `content/references/wrap-context-format.md`: (1) the 3-step rename-first spillover drain; (2) the rolling-session-label merge write (file-absent / non-/ds-wrap / merge branches, duplicate-claim dedup, 1-to-10 label rolling window, per-section merge rules) - the merged write begins with the pinned header prefix `# Session Context\n*Written by /ds-wrap`; (3) write `.agentic/wrap/last-wrap` = this `session_id`; (4) the lock is acquired and released by the daemon, not this child - the daemon calls `acquireWrapLock` before spawning and `releaseWrapLock` after the child exits (success or failure); the child never touches the lock. (`clearProvablyStaleWrapLock` is the daemon's crash-backstop only: it clears the lock if the daemon itself died after acquiring but before releasing; under normal operation it is not the release path.)

**Step 3 - Write `.agentic/memory.md` (Part B; no lock, no Open-PR deferral).**

Skip if there are no stable facts to record. Otherwise apply the shared Part B append-dedup from `/ds-wrap`: read the existing `.agentic/memory.md`; for each proposed stable-fact entry, skip it if the same fact is already captured in `.agentic/memory.md` OR in root `MEMORY.md` (read-only above) OR as a structured learning in `.agentic/learnings.md` (semantic dedup, not string match); supersede an existing `.agentic/memory.md` entry in place when the new entry corrects or updates the same topic; otherwise append. Entry format `- **YYYY-MM-DD:** [what was decided and why]` using today's date. There is NO Open-PR deferral pass and NO `.agentic/memory-pending.md` routing - write directly to `.agentic/memory.md`. **This path NEVER writes root `MEMORY.md`** - no Skeptic and no Part E compression run here; promotion of staged entries into root `MEMORY.md` happens only at the next synchronous `/ds-wrap` (Part B step 0, the staging drain).

**Step 4 - Write AGENTS.md updates (Part C; no lock, no Open-PR deferral).**

Skip if there are no AGENTS.md additions. Otherwise apply the shared Part C from `/ds-wrap`: for each touched track's AGENTS.md, append only genuinely-new, session-derived bullets (semantic dedup against existing content); create a minimal stub for a touched directory that has no AGENTS.md and apply the additions into it; apply any `Update:` corrections in place. Root AGENTS.md focuses on `## Decisions` and `## Conventions`; subdir AGENTS.md on `## Stack` / `## Key Conventions` / track-relevant categories. There is NO Open-PR deferral pass and NO `.agentic/agents-md-pending.md` routing - write directly to the AGENTS.md files. Do NOT run the pre-AGENTS.md three-way split (that requires user confirmation `/ds-wrap` cannot provide headlessly either) - if a pre-AGENTS.md layout is detected, record it as a `_wrap.md` "Watch Out For" bullet instead.

**Drift is never a prompt.** Any scaffolding drift, ambiguity, or condition that the interactive `/ds-wrap` would surface to the user becomes a single `## Watch Out For` bullet in the `.agentic/_wrap.md` output (e.g. "Pre-AGENTS.md layout detected; run /ds-init-project to migrate", "Linear workspace slug not set", "both .claude/findings.md and .agentic/findings.md exist - resolve manually"). `/ds-wrap-deferred` writes the bullet and moves on; it does not pause, migrate destructively, or ask.

**Exit.** After the writes (or after a clean early exit because the lock could not be acquired, or because the survey found nothing substantive to write), exit. Exit 0 on a successful pass. Do NOT transition the marker - the daemon transitions it to `done` after observing exit 0.

## Omitted versus `/ds-wrap` (explicit)

| `/ds-wrap` step | `/ds-wrap-deferred` |
|---|---|
| no-active-Workers pre-flight | omitted (daemon already serialized) |
| scaffold-migration pre-flight (CLAUDE.md->AGENTS.md, legacy `.claude/*` moves) | omitted; detected drift -> `_wrap.md` "Watch Out For" bullet |
| lock wait-loop + stale-lock prompt | omitted; daemon owns the lock (acquires before spawn, releases after child exits); on contention the daemon skips the drain tick (idle self-exit) - the child never handles lock contention |
| draft Worker (Step 1) | omitted; conductor surveys inline |
| Skeptic (Steps 2-3 draft review) | omitted |
| Step 4 hand-authored on-disk Skeptic | omitted |
| Part A curated merge (now targets `_wrap.md`) | KEPT (cites `wrap-context-format.md`) |
| Part B Open-PR deferral / memory-pending.md | omitted; direct append-dedup to memory.md |
| Part B target | `.agentic/memory.md` (staging), NOT root `MEMORY.md` - no Skeptic and no Part E on this path |
| Part C Open-PR deferral / agents-md-pending.md | omitted; direct write to AGENTS.md |
| Part D skill-candidate wrap-time signal | omitted; `--disallowedTools "Bash"` removes the Bash tool from the daemon child's context, so no `node` shell-out is possible. Daemon-completed sessions do not contribute the wrap-time skill-candidate signal. |
| Part E compression | omitted - `.agentic/memory.md`, the one Part E target this daemon path writes, is picked up and curated by the next synchronous `/ds-wrap` Part E gate check (`wrap-ticket`'s own gate check only covers root `MEMORY.md`, a file this daemon path never writes), never curated in-daemon here |
| `gh pr` open-PR enumeration | omitted |
| staging-overflow signal | when `.agentic/memory.md` holds more than 9 entries (3 x the drain cap, `bin/tests/drain_model.py` `CAP = 3`) at the end of Step 3, emit a `_wrap.md` "Watch Out For" bullet: "staging holds <N> entries - run /ds-wrap to drain them into MEMORY.md." This is the only human-reaching signal for a daemon-only project, which never runs a synchronous wrap. |
| Step 5 `/ds-cleanup-worktrees` | omitted |
| Step 6 terminal marker transition | omitted; daemon owns `done` |
| Part F tracker status reconciliation | omitted; daemon has no Bash and spawns nothing |
| drift-requires-input prompt | omitted; drift -> `_wrap.md` "Watch Out For" bullet |
