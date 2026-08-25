## Writing Style

Never use em dashes (--). Use a regular hyphen (-) instead in all generated text, copy, comments, documentation, and commit messages.

## Project Structure Convention

`AGENTS.md` is the canonical project-instructions file across Claude Code, Codex, Cursor, and other tools. Claude Code reads it via a `CLAUDE.md` containing `@AGENTS.md` and `@MEMORY.md` import lines. Always structure projects with a lean root `AGENTS.md` and deeper context in subdirectory `AGENTS.md` files co-located with the code they describe.

- **Root `AGENTS.md`** - one-paragraph summary, resolved architecture decisions, cross-cutting conventions, repo structure map. Keep it under ~40 lines. This limit applies to project root AGENTS.md files. The global `~/.claude/CLAUDE.md` is exempt.
- **Subdirectory `AGENTS.md`** (e.g. `backend/AGENTS.md`, `contracts/AGENTS.md`) - loaded only when working in that directory. Can be as detailed as needed without polluting other contexts. Detail here means durable conventions and decisions; step-by-step procedures follow the runbook rule below.
- **Runbooks live in separate files, not inline.** Step-by-step procedures (build/run steps, multi-command how-tos, gotcha catalogs) do not belong inline in any AGENTS.md - the file is auto-loaded into every session working in its directory, so a 20-line procedure taxes every unrelated session there. Put the procedure in its own doc scoped to the deepest directory it applies to (e.g. `<dir>/docs/local-run.md`) and leave a one-line pointer in that AGENTS.md (`- Local build + open: see docs/local-run.md`). Mechanical trigger: more than ~10 lines of procedure content in an AGENTS.md (aggregate across the file) means externalize and link. This is the same "read on trigger" pattern the methodology uses for its own reference docs.
- **`.claude/settings.json`** - project-scoped MCP servers and shared config (safe to commit).
- **`.claude/settings.local.json`** - secrets and local env values (always gitignored).

When starting a new project, run `/ds-init-project` to scaffold this structure automatically.

## Session Context and Memory

**Session startup:** Read `.agentic/context.md` as the first action of every session - standalone, never in parallel with other tool calls.

**Meta-divergence sweep at session start.** After reading `.agentic/context.md`, the conductor sweeps `.agentic/events.jsonl` for `meta_review_complete` events whose `original_task_id` is not present in `.agentic/.meta-divergence-surfaced`. For each such event with non-empty `data.divergence.critical_missed` or `data.divergence.major_missed`, emit at the next user-facing turn boundary:

```
META-DIVERGENCE: meta-Skeptic identified [Critical|Major] '<finding-title>' that original Skeptic missed on <task_id>. Original sign-off stands; review recommended before merging.
[phase: meta-divergence-critical]
```

Then append `original_task_id` to the tracker file. The sweep is a standalone scan - not parallel with other startup tool calls. Tracker file format is one `original_task_id` per line, append-only, matching `/ds-init-project` Step 9's `.agentic/*` umbrella ignore (not individually enumerated - see `content/project-scaffolding.yml`). File-absent equals empty set. This catches divergences whose meta-Skeptic completed asynchronously after the originating session ended.

**Pagination (vicious loop defense):** The sweep MUST NOT read the full `.agentic/events.jsonl` on every boot. It reads only events with `ts` strictly greater than the timestamp stored in `.agentic/.meta-divergence-last-sweep` (ISO8601 UTC, single line, file-absent = first run). On first run (no tracker file), the scan is capped to the most recent 100 lines of the events file. After the sweep completes, the conductor writes the current ISO8601 UTC timestamp to the tracker file (atomic: tmp + `mv`). This prevents the vicious loop where growing telemetry consumes ever more context on every session start. See `content/references/skeptic-protocol.md` Section 14 "Session-start sweep pagination" for the full procedure.

**Skill-candidate sweep at session start.** After the meta-divergence sweep, the conductor checks `.agentic/skill-candidates.md` for entries. Each entry begins with a `## <domain>` heading (the unique key); its `**Status:**` field is either `open` or `dismissed`. For each entry whose `**Status:**` is `open` AND whose domain is NOT present in `.agentic/.skill-candidates-surfaced`, emit at the next user-facing turn boundary:

```
SKILL-CANDIDATE: domain '<domain>' has accumulated <count> occurrences - consider creating a skill (suggested artifact: <suggestedArtifact>). Run /ds-skill-candidates for the full backlog.
[phase: skill-candidate]
```

Then append the domain (the `## <domain>` heading value, without the `## ` prefix) to `.agentic/.skill-candidates-surfaced` (atomic tmp + `mv`, one domain per line, file-absent = empty set, gitignored). File-absent for `.agentic/skill-candidates.md` = no-op. The sweep is non-blocking: emitting the notice never gates any conductor action. Only entries with `**Status:** open` trigger the notice; entries with `**Status:** dismissed` are skipped.

**Pagination (skill-candidate sweep):** The sweep reads only entries whose `**Last seen:**` date is strictly greater than the date stored in `.agentic/.skill-candidates-last-sweep` (ISO8601 UTC, single line, file-absent = first run). On first run (no tracker file), all open un-surfaced entries are candidates. After the sweep completes, the conductor writes the current ISO8601 UTC timestamp to `.agentic/.skill-candidates-last-sweep` (atomic: tmp + `mv`). This mirrors the meta-divergence pagination discipline and prevents re-scanning the full backlog on every session start.

**Pending-merge sweep at session start.** Runs at session start, after the skill-candidate sweep. Skip when any of: `TRACKER == none`; the `pending_merge_sweep` config toggle is `false`; fewer than 60 minutes have elapsed since the last sweep (the throttle); `.agentic/ticket-ledger.jsonl` is absent or unreadable; or the candidate set is empty after exclusions. Otherwise runs `/ds-ticket-status-sync --pending-merge`, tracked via `.agentic/.pending-merge-last-sweep` (throttle timestamp) and `.agentic/pending-merge-state.jsonl` (sweep state). See `content/commands/ds-ticket-status-sync.md` §Pending-merge sweep for the procedure. This sweep emits no first-user-turn notice and does not add to the stacked-notice count at `:89` - it prints only when a transition actually fires.

**Knowledge-strand sweep.** Runs at session start after the pending-merge sweep; read-only (no worktree/branch/write/fetch). Checks the same five-file set as `/ds-wrap` Part G for uncommitted changes versus `origin/<BASE_BRANCH>`, honoring `knowledge_commit_exclude` so an operator-excluded file is never surfaced; emits a non-blocking `KNOWLEDGE-STRAND:` notice pointing at `/ds-wrap` when found. See `content/references/conventions-detail.md` §Session-Start Sweeps for notice format, gating rules, tracker-key derivation, and pagination rationale.

**Session context.** **The read contract is unchanged: read `.agentic/context.md` as the first action of every session.** How it is produced changed: the Stop hook writes this session's own `.agentic/context.d/<session_id>.md` shard after every agent turn, and `.agentic/context.md` is then recomposed as a DERIVED ROLLUP of `.agentic/_wrap.md` (the curated region) plus the shard set. Nothing writes `context.md` directly any more - a direct write is discarded by the next turn's recomposition. Writers are session-keyed so concurrent sessions cannot clobber each other, and because the rollup is derivable a lost update self-heals on the next turn rather than losing data. (Legacy fallback: `~/.claude/projects/[hash]/context.md` - used only when `.agentic/context.md` does not exist.) `/ds-wrap` is available for richer on-demand summarization; it writes `_wrap.md`. Update `MEMORY.md` (root `<cwd>/MEMORY.md`) at the end of any session where stable facts were learned. Close the session cleanly so the Stop hook can finish writing `context.md`: in the terminal CLI, use `/exit` rather than ctrl+c; in the desktop or web app, just close the window or tab normally rather than force-quitting.

**Knowledge-file routing (three distinct stores):**
- `<cwd>/MEMORY.md` - canonical durable facts; committed (exception: see conventions-detail.md); loaded at session start via the `@MEMORY.md` import in the project root `CLAUDE.md`; written by `/ds-wrap` (Part B promotion, capped 3/run, plus a one-time migration stub seed), wrap-ticket, `/ds-memory-update`.
- `.agentic/memory.md` - deferred-wrap daemon staging; written exclusively by the daemon (`/ds-wrap-deferred` Step 3); `/ds-wrap` only reads and drains it (Part B), never writes it; gitignored; NOT auto-injected; NOT the same as root `MEMORY.md`.
- `.agentic/learnings.md` - structured fix-pattern learnings; committed; written by `learning-extractor` (mechanically) and `learnings-agent` (mandatory triggers, conductor-spawned).

**Per-developer session log:** `.agentic/session-log/<developer_id>.jsonl` - per-developer session rollup written by the Stop hook. Committed to git via the `.agentic/session-log/` carve-out in `.gitignore` when `commit_telemetry: true` (default) and identity is confirmed; the commit happens at `/ds-implement-ticket` Phase 8 as a SEPARATE commit on the PR branch. Teammates receive it on pull after squash merge. See `content/references/events-log.md` "Per-developer session log". Aggregated via `ds-cost team`.

**Identity setup.** `ds-identity auto` derives a provisional global GitHub handle; `init <handle>` sets one manually. `--scope project` stores a gitignored repo identity; `--scope profile` stores an active harness-profile identity. Effective identity uses confirmation-first project > profile > global ordering. Full paths, profile bindings, and routing contract: `content/commands/ds-identity.md`.

**Conductor first-user-turn provisional-confirm.** When the preflight resolves a `provisional: true` effective identity, the conductor substitutes the winning scope (`global`, `profile`, or `project`) and surfaces the following notice at its first user-facing turn - non-blocking, analogous to the meta-divergence notice:

```
IDENTITY: tracking handle '<handle>' auto-derived (provisional) - confirm or correct.
Telemetry is buffered (not lost) until confirmed.
  Confirm: ds-identity confirm --scope <scope>
  Correct: ds-identity init <handle> --force --scope <scope>
```

Profile commands use the active config binding; add `--profile-dir <dir>` only when absent. The notice re-surfaces until confirmation. Buffered telemetry is tagged with the winning `identity_scope`; confirmation flushes only that scope, leaving nonmatching records buffered. See `content/commands/ds-identity.md`.

**Deprecated-preset first-user-turn notice.** When the preflight (Step 1 in `content/sections/01-activation-preflight.md`) finds a legacy session-wide `preset` key present at either scope - `~/.claude/agentic-engineering.json` `preset:` or an `agentic-engineering-preset:` marker line - the conductor surfaces one of the two notices below at its first user-facing turn, non-blocking, analogous to the meta-divergence and identity-provisional-confirm notices. Fire on PRESENCE of the key regardless of whether it wins resolution; use the first template when the legacy preset won at that scope, the second when it was present but overridden by a `profile` elsewhere in the precedence chain:

```
# Legacy preset WON resolution at this scope:
DEPRECATED: preset key '{value}' ({scope}) resolved to profile={resolved}; migrate by setting
profile={resolved} directly - preset support will be removed after the deprecation window.

# Legacy preset PRESENT but did NOT win (coexistence / cross-scope override):
DEPRECATED: preset key '{value}' ({scope}) is present but NOT used - effective profile is
'{effective}' (source: {source}). Remove the stale preset key/marker - it has no effect and
will be rejected after the deprecation window.
```

One of 5 stacked first-user-turn notices in this section (meta-divergence, skill-candidate, identity-provisional-confirm, deprecated-preset, knowledge-strand); ordering among the five is immaterial.

**Telemetry is BUFFERED, not lost.** While identity is unconfirmed (provisional or absent), the Stop hook writes session telemetry to a pending buffer (`~/.agentic/session-log/.pending/<uuid>.json`) rather than directly to the session log. Pending sessions are flushed and attributed when `ds-identity confirm` (or `init --force`) runs. No session is silently dropped.

**TEAM dimension.** `ds-cost team` aggregates all `.agentic/session-log/*.jsonl` files found locally. Session-logs are committed to git via the Phase 8 telemetry commit (when `commit_telemetry: true` and identity is confirmed), so `team` reflects sessions from any developer whose telemetry has landed on the current branch via pull after merge.

**MEMORY.md** is loaded at session start via the `@MEMORY.md` import in the project root `CLAUDE.md` (added by `/ds-init-project`). It stores stable facts learned about the project - architecture, key file paths, user preferences, recurring solutions. Include rationale with each entry ("chose X because Y"). Rules:
- Before adding an entry, check if it supersedes an existing one and update it in place (adjust the date)
- Remove entries that are no longer true
- Do not duplicate what is already in `AGENTS.md`
- Session-specific state (current task, next steps) belongs in `context.md`, not here
- Entry format: `- **YYYY-MM-DD:** [what and why, in one sentence]`

Read `content/references/conventions-detail.md` §The Intent Layer for the artifact list, intent-debt concept, Project Overview Layer, Project Config (`.agentic/config.json`) toggle catalog, and Ubiquitous Language (`glossary.md`).

## Git Workflow

**Conductor never edits shippable artifacts directly - including Trivial one-line changes.** Every shippable change is delegated to a worktree-isolated `engineer` branched from `origin/main`. The conductor edits only exempt artifacts in its own checkout. Worktrees are exclusively for subagents.

**Shippable/exempt classifier (4-rule precedence, first match wins):**
1. `.agentic/**` -> EXEMPT (conductor sole-writer).
2. begins `docs/planning/` -> EXEMPT (Briefs/Plans/ADRs/planning subdirs). ALL other docs SHIPPABLE, by name: `docs/research/`, `docs/_archive/`, `docs/overview/`, `docs/technical/`, `docs/images/`, `docs/slides/`, file `docs/index.html` (Vercel `outputDirectory: docs`).
3. conductor-direct PRINT/DECISION/RESOLVER-EXECUTION -> EXEMPT. **A conductor-direct session-context write under this exemption targets `.agentic/_wrap.md`, NEVER `.agentic/context.md`.** `context.md` is a derived rollup recomposed from `_wrap.md` plus the per-session shards on every turn, so a direct write to it is silently discarded by the next Stop turn - the exemption would quietly lose the conductor's edit.
4. any other tracked-file write -> SHIPPABLE -> delegate to worktree-isolated engineer (Trivial: no Skeptic/no brief; Elevated: full Worker+Skeptic).

**Mechanical backstop (Claude Code, DinoStack checkout only).** A PreToolUse hook (`hooks/enforce-shippable-edit.py`) mechanically enforces this classifier for the conductor: it matches Write/Edit/MultiEdit, and denies a conductor-direct edit (agent_id absent) to a shippable file inside the repo. Exempt: `.agentic/**`, `docs/planning/**`, the instruction-layer basenames `AGENTS.md`/`MEMORY.md`/`CLAUDE.md` at any depth (the sanctioned `/wrap` conductor-write path), and paths outside the repo. Fail-open on any error. Kill-switch: `AE_SHIPPABLE_GUARD_DISABLE=1`. Residual: conductor hand-edits to the instruction-layer files made OUTSIDE `/wrap` are mechanically unguarded by design - that workflow trades the backstop for `/wrap`'s own internal Skeptic review.

**Base branch resolution** - resolve `BASE_BRANCH` in this order and cache the result for the session:
1. **Explicit declaration wins.** If the project declares a base/integration branch via a `BASE_BRANCH:` line in `AGENTS.md`, use it. Highest priority.
2. Else if a local `develop` branch exists - use `develop`.
3. Else if a local `development` branch exists - use `development`.
4. Else (no declaration and neither `develop` nor `development` exists locally) - prompt the user: no `develop`/`development` integration branch found - use `main` (falling back to `master`), or set up a develop-based workflow? Offer `main` as the recommended default; recommending `main` here does not contradict the develop-first default - it is the safe, reversible choice precisely because no develop-based flow exists yet. Do NOT auto-create any branch.
5. On decline / main preference - resolve `main` (fall back to `master` if `main` does not exist). Cache the resolved value as `BASE_BRANCH` for the session.

**Conductor preflight** - run this checklist ONCE at session start. Do not skip it when the user issues a direct command; commands are goals, not overrides for workflow hygiene. Cache the resolved base branch in-context for the session; do not re-run the full preflight before every subagent spawn. Re-run only if the user explicitly switches branches or after 30+ minutes of idle time.
1. What branch is the working tree on? (`git branch --show-current`)
2. Does this branch already contain unrelated commits? If yes, start fresh from the base branch (resolve it per **Base branch resolution** above) before proceeding.
3. Are there uncommitted changes? If so, do they belong to the current task? Stash or commit unrelated work before proceeding.
4. When was `origin` last fetched? Run `git fetch origin` if it has been more than a few minutes.
5. Resolve the base branch per **Base branch resolution** above and cache it as `BASE_BRANCH` for the session. Resolution is lazy only in its interactive step: the declaration / `develop` / `development` checks (steps 1-3) are non-interactive and may run here at session start, but step 4's prompt is deferred until `BASE_BRANCH` is first needed for a shippable operation (spawning an engineer, creating a worktree, opening a PR, or starting fresh from the base branch per step 2). A purely read-only session therefore never triggers the prompt. The prompt is a sanctioned stop-and-ask (an explicit command directive per the delegation Exception clause) exempt from the default-and-proceed protocol; surface it with `main` as the recommended default per the AskUserQuestion precondition.
6. **When step 5 resolved `BASE_BRANCH` non-interactively**, run `ds-base-sync "$REPO" "$BASE_BRANCH"` (PATH-guarded, non-blocking on any exit). Skip silently otherwise. See `content/references/base-branch-sync.md` §Call sites.
7. Run worktree prune and the branch prune (see `content/references/worktree-lifecycle.md` §Session-start prune script and §Branch prune) - both run ONCE at session start.

**Subagent worktrees:** Each parallel subagent gets its own worktree, branched from the conductor's current branch. Worktrees are created at `.agentic/worktrees/<branch-name>` under the project root (already gitignored via `/ds-init-project` Step 9's `.agentic/*` umbrella ignore (not individually enumerated - see `content/project-scaffolding.yml`)). The conductor merges each subagent branch back after sign-off and removes the worktree.

```bash
# Create a subagent worktree:
git worktree add .agentic/worktrees/<branch-name> -b <branch-name> HEAD

# Remove after merge:
git worktree remove .agentic/worktrees/<branch-name>
git branch -d <branch-name>
```

**Branch naming:** `feature/<name>`, `fix/<name>`, `chore/<name>`.

**Merging:** After Skeptic sign-off, subagent branches merge back into the conductor's current branch. The conductor's branch (not the individual subagent branch) then opens a PR into `main`. PRs are required regardless of whether other sessions are active - they make in-flight work visible and force explicit conflict resolution.

**Merge-time tracker writeback.** When an agent merges a PR **outside** `/ds-implement-ticket` Phase 12's auto-merge block (that block owns its own writeback decision at site W7 and MUST NOT also fire this rule), and `gh pr merge` exits 0, and the agent knows **both** the ticket ID and the merged PR number, immediately run `/ds-ticket-status-sync <TICKET_ID> --pr <PR_NUMBER> --no-confirm`. A `gh pr merge --auto` call exiting 0 means QUEUED, not merged, and does NOT trigger this rule. If either the ticket ID or the PR number is unknown, do nothing here - the automatic backstop is the session-start `--pending-merge` sweep, and `/ds-ticket-status-sync --all` remains available on operator invocation. Soft-fail: a failure logs one line and never blocks the merge or any following step. `TRACKER == none` is a silent no-op. This does not change what state is written - the transition target is still `$TRACKER_STATE_DEV_COMPLETE`; AE still never writes the terminal `TRACKER_STATE_DONE` at any site.

**Cleanup:** Remove worktrees after the subagent branch is merged or the task is explicitly closed. Do not leave stale worktrees. Between tasks there should be no active subagent worktrees.

**Commit each fix immediately during testing.** Never accumulate uncommitted changes during live testing sessions. After each validated fix: commit, PR, merge, pull - then start the next fix. Do not batch multiple unrelated fixes. **Exception - Implicit Trivial batching:** a series of individually-Trivial-classified tweaks to the same surface may share one draft PR across multiple pushes instead of a fresh commit-PR-merge-pull cycle per tweak; the pre-spawn continuation judgment (see `content/references/worktree-lifecycle.md` §Implicit Trivial batching: open the PR at first push) is the discriminator that decides whether a given tweak continues an open batch or starts a new one - the file-overlap scope test that runs on return is rare-miss verification only, never the batching decision itself. Genuinely distinct fixes - unrelated files, unrelated intent, a topic switch - still follow the full commit-PR-merge-pull cycle per fix; "related" is defined by that same continuation judgment, not by file adjacency.

**DCO sign-off when the repo enforces it.** When the target repo enforces DCO - a DCO / Signed-off-by CI check exists, or CONTRIBUTING requires sign-off - commit with `git commit -s` so the `Signed-off-by:` trailer is present and matches the commit author email; without it the DCO check fails and the commit must be amended. This is conditional: only sign off when the repo enforces it, not universally for every repo. The dinostack repo itself enforces a DCO check, so commits to it require `-s`.

**Multi-session support:** Multiple Claude Code sessions can work on different features simultaneously. Each session operates on its own branch. Isolation worktrees are additionally protected across sessions by the harness itself: Claude Code locks (`git worktree lock`) each isolation worktree while its agent is running, so git refuses the non-force removal and branch-deletion commands this methodology uses against it from any concurrent session; the lock releases when the agent finishes. This coordination is harness behavior (see Claude Code's own worktree documentation), not a mechanism the conductor or methodology adds.

**Temp-file ownership.** Agents that write temp files are responsible for deleting them in teardown. If a downstream phase consumes the temp files, the consuming phase deletes the originals after consumption.

**Superseding an open PR's work means close + rebase, never bundle.** If your branch's work makes another open PR's commits unnecessary or subsumed, close that PR citing the superseding one and rebase your branch clean of its commits - do not merge or cherry-pick the superseded PR's commits into your own branch. A branch whose history contains another open PR's head commit is exactly the pattern an advisory review-rigor CI check flags where configured; treat the flag as confirmation to close + rebase, not to proceed. This applies to superseding only - see the rework-rounds bullet immediately below for the same-approach case.

**Rework rounds on an open PR stay on the same PR - push fix commits to the existing branch, do not close and reopen.** Rework (round-N fix, same implementation approach already on the open PR - a Skeptic finding, CI failure, or review comment resolved by a surgical edit that builds on top of the existing branch tip) is a distinct git-workflow class from superseding (a wholesale replacement of the PR's approach, where the old commits become dead weight rather than a foundation - still close + rebase per the bullet above). Test: if the fix commit builds on top of the existing branch tip and addresses specific findings against it, it is rework; if the new work discards the prior round's approach outright, it is superseding. See `content/references/worktree-lifecycle.md` §Round-N rework mechanic for the round-N branching and recovery procedure.

## Context Economy

Read `content/references/conventions-detail.md` §Context Economy for context-window discipline rules (no duplicate file contents, minimal diffs, no verbatim tool output, structured blocks over prose) and multi-developer coordination guidance.

## External Comment Discipline

Read `content/references/conventions-detail.md` §External Comment Discipline for rules on PR bodies, review comments, commit messages, ticket descriptions, and other external-facing artifacts (lead with result, bullets over prose, evidence beats description, no marketing voice).
