# /wrap — On-Demand Session Context Enrichment

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Use when you want a richer context file than the auto-hook provides — e.g. before handing off complex in-progress work to a future session.

The Stop hook auto-writes `<cwd>/.agentic/context.md` after every turn with raw session data. `/wrap` merges with or rewrites that file with a structured, human-curated version when detail matters. It is also the ongoing counterpart to `/init-project`: where `/init-project` scaffolds the AGENTS.md hierarchy, `/wrap` populates it — filling in root and subdirectory AGENTS.md files with decisions, conventions, stack details, and gotchas learned during sessions.

**Relationship to `wrap-ticket`.** `/wrap` is the on-demand richer session-summarization tool that targets AGENTS.md, MEMORY.md, and `.agentic/context.md` across an entire session and uses Skeptic review. The per-ticket Phase 11b `wrap-ticket` agent (see `content/agents/wrap-ticket.md`) is a constrained automated subset that fires on every PR opened by `/implement-ticket` — it appends to MEMORY.md, decisions.md, and `.agentic/context.md` only, never touches AGENTS.md, and runs without Skeptic. They write to overlapping files (MEMORY.md, context.md) but at non-overlapping cadences (per-ticket vs per-session); both follow append-discipline so the concurrent-write hazard is bounded. `wrap-ticket` and `/wrap` MUST NOT run concurrently — both acquire `.agentic/wrap.lock`. If `/wrap` is invoked while `wrap-ticket` holds the lock, `/wrap` waits per the standard lock-wait protocol below; if `wrap-ticket` is invoked while `/wrap` holds the lock, `wrap-ticket` skips with `skipped_reason: "wrap-lock-contention"` and proceeds without learnings capture (Phase 11b is non-blocking).

## SessionStart auto-enrichment (conductor protocol)

This is a conductor protocol that runs at session start, not a step in the on-demand `/wrap` flow and not a separate agent. It completes the deferred enrichment that a prior session staged but did not finish. (A one-line pointer belongs in METHODOLOGY.md §Session Context and Memory: "On session start, after reading `.agentic/context.md`, run the SessionStart auto-enrichment + drain sweep in `content/commands/wrap.md`.")

**On session start, after reading `.agentic/context.md`:**

1. **Drain-temp sweep (fail-open).** Run `rm -f .agentic/.stop-deferred-activity.jsonl.draining.*` to clean any spillover-drain temp file leaked by a crash between the rename and unlink steps of a prior Part A drain. This is best-effort; ignore any error and continue.

2. **Marker check + claim.** Read `.agentic/wrap-pending.json`. Claim and run enrichment when EITHER:
   - `status: pending`, OR
   - `status: in_progress` AND `claimed_at` is older than the staleness window AND `.agentic/wrap.lock` is absent (the prior claimant crashed or stalled).

   To claim, atomically (tmp + rename) set `status: in_progress`, `claimed_by: <this session_id>`, `claimed_at: <now, ISO8601 UTC>`, and increment `attempts` by 1. `attempts` increments at claim time (before enrichment begins) so a crash mid-enrichment still counts toward the give-up budget. If `attempts` would reach 3 or more, do NOT claim for a normal run: set `status: gave_up`, `last_error: <short reason>`, retain the marker, and surface the manual-`/wrap` notice (see Step 6 give-up branch). Do NOT claim a marker already `status: done`/`gave_up`.

3. **Run the Enrichment Pipeline in the background.** Dispatch the same Enrichment Pipeline that `/wrap` runs (draft Worker -> conductor arranges Skeptic -> inline Part A/B/C writes -> Part E compression -> Step 6 terminal transition), all with `run_in_background: true`. Stay responsive to the user's prompts while it runs - the conductor does not block on it.

4. **Terminal transition** is handled by the pipeline's Step 6 (marker `status: done` then unlink on full success; `gave_up` retained on `attempts >= 3`).

**Staleness window: 60 minutes (advisory).** A claim of an `in_progress` marker is allowed only when `claimed_at` is older than 60 minutes AND `wrap.lock` is absent. This is intentionally WIDER than the 30-minute `wrap.lock` staleness heuristic above, because a background enrichment can legitimately run longer than a single lock-held window (the lock is held only in the brief Part A window; the rest of the pipeline runs unlocked and may take minutes). The window is advisory, not a correctness invariant: a too-eager reclaim only causes a duplicate run, which idempotency makes wasteful-not-corrupting.

**Idempotency is the correctness guarantee.** Two sessions racing to claim the same marker is tolerated - the loser also runs, and idempotency (context.md merge dedups via the Recent-Focus `session_id`+`staged_at` dedup rule; `.agentic/memory.md`/`AGENTS.md` are single-writer and their dedup passes are idempotent; root `MEMORY.md`/`.agentic/learnings.md` are append-dedup) makes the double-run wasteful but never corrupting. `claimed_at` + the staleness window exist only to make that race rare.

## Your job (main agent)

**Pre-flight scaffold-accuracy check** (runs BEFORE Step 0). `/init-project` is the canonical scaffolding spec; /wrap uses it as the reference for "what this project should look like." Check for drift and auto-migrate the critical items inline:

1. **CLAUDE.md → AGENTS.md migration** (per-file, recursive through tracks). For each `CLAUDE.md` in the project (root + every track directory) where a sibling `AGENTS.md` does not already exist:
   - `cp <dir>/CLAUDE.md <dir>/AGENTS.md` to preserve content.
   - Overwrite `<dir>/CLAUDE.md` with the single line `@AGENTS.md` so Claude Code transparently loads the new file.
   - Skip directories where `AGENTS.md` already exists (leave `CLAUDE.md` untouched).

2. **`.claude/` → `.agentic/` session state migration.** If `<cwd>/.claude/context.md` exists and `<cwd>/.agentic/context.md` does not:
   - `mkdir -p <cwd>/.agentic`
   - `mv <cwd>/.claude/context.md <cwd>/.agentic/context.md`
   - Same for `<cwd>/.claude/memory.md` and `<cwd>/.claude/memory/` (the auto-memory dir).
   - Redo symlinks in `~/.claude/projects/[hash]/` to point at the new `.agentic/` paths.

3. **Legacy config migration (`.claude/<name>.md` → `.agentic/<name>.md`)** — for each of `qa.md`, `deploy.md`, `findings.md`, `tracking.md`, `learnings.md`:
   - **Both paths exist on disk**: do NOT migrate. Log a drift warning in the wrap run output (e.g. "Drift (both .claude/findings.md and .agentic/findings.md exist - skipping auto-migration; resolve manually via /init-project)"), and add a bullet under the context.md "Watch Out For" section naming the conflicting files. Skip to the next name.
   - **Only legacy `.claude/<name>.md` exists**: first, run `git status --porcelain` to check working-tree cleanliness. If there are staged or unstaged changes, do NOT migrate - log a drift note ("Skipped migration of legacy .claude/<name>.md: working tree dirty. Commit or stash, then re-run /wrap or /init-project.") and add a Watch Out For bullet. If the working tree is clean, migrate: `git mv .claude/<name>.md .agentic/<name>.md`. Log the move to the wrap run output only.
   - **Only `.agentic/<name>.md` exists**: no action.
   - **Neither exists**: no action at this step - the missing-stub creation below handles creation.

4. **Missing-stub creation.** If any of `.agentic/tracking.md`, `.agentic/deploy.md` (only when release signals detected), or `.agentic/learnings.md` is missing (checked via resolver: `.agentic/<name>.md` preferred, legacy `.claude/<name>.md` fallback), create a stub at `.agentic/<name>.md` per the template in `/init-project` Steps 6a-6d. For `.agentic/learnings.md`, use the template from `/init-project` Step 8 (unconditional — always create).

5. **Silent auto-fix for remaining drift.** /wrap is silent and hands-off. For any drift /wrap can fix without user input, fix it inline:
   - Create `docs/overview/`, `docs/technical/`, `docs/planning/`, `docs/research/` (with `.gitkeep`) if missing.
   - Create `.claude/settings.json` (`{}`) if missing.
   - Create `.claude/settings.local.json` with `autoMemoryDirectory` set to `<cwd>/.agentic/memory` if missing or if the key is not yet present (merge rule: never overwrite an existing value).
   - Create `.gitignore` entries for `.claude/settings.local.json` and the `.agentic/` runtime-artifact block (per `/init-project` Step 9) if missing.
   - **Pre-AGENTS.md layout detection (DO NOT auto-split inline).** If root `AGENTS.md` is absent AND root `CLAUDE.md` exists with more than the single-line `@AGENTS.md` pointer, do NOT attempt the Worker+Skeptic three-way split inline — that migration requires user confirmation of the proposed split, and /wrap's silent contract cannot provide one. Instead, add a "Watch Out For" entry in context.md: `Pre-AGENTS.md layout detected (CLAUDE.md has real content, no root AGENTS.md). Run /init-project to run the Worker+Skeptic split and migrate.`

6. **Drift that cannot be auto-fixed.** If any drift requires user input (e.g. Linear workspace slug, Jira base URL, confirmation of release commands, selection among multiple detected web UIs), do NOT prompt during /wrap. Instead, record a bullet under "Watch Out For" in the context.md output noting which scaffolding items are still incomplete. The user can address these later by running `/init-project` interactively. Specific drift kinds that always require user input and must be listed here:
   - **CLAUDE.md split** — the pre-AGENTS.md migration requires the user to review and accept the three-way split (AGENTS.md / residual CLAUDE.md / MEMORY.md). /wrap cannot perform this silently; it points at `/init-project`.
   - Linear workspace slug or QA assignee UUID not yet set when `## Linear` is present.
   - Jira `JIRA_BASE_URL`, `TICKET_PREFIX`, or transition name not yet set when `## Tracker` is present.
   - Release command / rollback procedure confirmation when `.agentic/deploy.md` has TODO placeholders.
   - Choice among multiple detected web UIs for `.agentic/qa.md` in a multi-track project.

All steps are silent on success. Log each migration action taken (e.g. "Migrated admin/CLAUDE.md to admin/AGENTS.md + pointer") to the wrap run output only, not as user prompts. After preflight completes, proceed to Step 0.

**Pre-flight check — no active Workers.** Before doing anything else, check whether any background Workers or subagents are currently running. If any are, stop and tell the user: "Cannot run /wrap while background tasks are active. Please wait for them to finish (or stop them) first." Do not proceed until confirmed.

**Pre-flight lock acquisition.** /wrap writes to several shared project-local files (context.md, memory.md, AGENTS.md, compression-state.json, rolling snapshots). Concurrent /wrap runs in the same project would clobber each other. Acquire a project-local lock before proceeding:

1. Ensure `<cwd>/.agentic/` exists (`mkdir -p <cwd>/.agentic`).
2. Attempt atomic acquisition: `mkdir <cwd>/.agentic/wrap.lock` (atomic on POSIX - succeeds only if the directory did not exist).
3. **If `mkdir` succeeds**, immediately write owner metadata: `<cwd>/.agentic/wrap.lock/owner` containing two lines - the current process PID and an ISO8601 UTC timestamp (e.g. `date -u +%Y-%m-%dT%H:%M:%SZ`). Proceed.
4. **If `mkdir` fails** (lock already held), attempt to read `<cwd>/.agentic/wrap.lock/owner` to get the owner PID and timestamp.
   - **If the owner file cannot be read or parsed** (file missing, unreadable, or contains no valid ISO8601 timestamp): treat as stale. Report to the user: "A /wrap lock exists at `<cwd>/.agentic/wrap.lock` but its owner file could not be read or parsed. If no /wrap run is active, remove it manually: `rm -rf <cwd>/.agentic/wrap.lock`." Then abort. Do not proceed to any subsequent step.
   - **If the timestamp is older than 30 minutes**: treat as potentially stale, but do NOT remove the lock automatically. Report to the user: "A /wrap lock exists at `<cwd>/.agentic/wrap.lock` (pid N, started at TIME) and is older than 30 minutes. If no /wrap run is active, remove it manually: `rm -rf <cwd>/.agentic/wrap.lock`." Then abort. Do not proceed to any subsequent step. Rationale: only the process that wrote the lock should remove it - auto-removal risks clobbering a live run if the 30-minute heuristic is wrong.
   - **If the timestamp is less than 30 minutes old** (live lock): wait for the lock to be released. Tell the user once: "Another /wrap run is in progress in this project (pid N, started at TIME). Waiting for it to finish..." Then enter a wait loop: every 5 seconds check whether `<cwd>/.agentic/wrap.lock` still exists (e.g. `ls <cwd>/.agentic/wrap.lock`). When the directory disappears, retry `mkdir` acquisition (step 2). If that `mkdir` succeeds, proceed normally. If it fails (another session won the race), do NOT abort - resume polling and retry on the next disappearance. Continue the loop until either (a) `mkdir` succeeds, or (b) total elapsed wait time since entering the loop exceeds **20 minutes**. On the 20-minute cap, report: "Waited 20 minutes for /wrap lock at `<cwd>/.agentic/wrap.lock` (pid N, started at TIME) without acquiring it. If no /wrap run is active, remove it manually: `rm -rf <cwd>/.agentic/wrap.lock`." Then abort.
5. Do not perform a PID liveness check (`ps -p`). PID reuse makes the check unreliable for Claude Code processes - the timestamp is the authoritative signal.

The 30-minute staleness heuristic exists because a crashed or force-killed /wrap may leave the lock dir behind. The timestamp backstop is the reliable signal; PID checks are omitted because Claude Code process hierarchies make `ps -p` results unreliable.

**Lock release is mandatory on every exit path.** Because the lock is now held only around the narrow Part A `context.md` window (see the Enrichment Pipeline "Lock strategy"), in the common case it is acquired and released entirely within Part A. The lock dir MUST be removed (`rm -rf <cwd>/.agentic/wrap.lock`) before any path that holds it returns or exits, on ALL of:
- completion of the Part A `context.md` write (the lock's normal release point, immediately after writing `.agentic/.last-wrap`);
- successful completion at Step 6 (defensive release - a no-op if Part A already released);
- escalation to the user at Step 3 (format re-invocation limit or contested finding) - release only if the lock is currently held;
- compression failure or escalation at Part E - Part E holds no lock, but release defensively if held from a prior Part A;
- any user-abort path (e.g. drift requiring input, Skeptic scope bail) - release only if held.

If /wrap aborts before the lock is acquired (e.g. at the active-Workers check above, before Part A, or because a live or stale lock was detected and the command aborted without acquiring), no lock was acquired and no release is needed.

**Pre-flight path check:** Confirm `<cwd>/.agentic/` exists or can be created. The /wrap skill now writes project-local under `<cwd>/.agentic/` instead of the legacy `~/.claude/projects/[hash]/` hashed directories. No disambiguation needed - one canonical location per project.

## Deferred-enrichment data model

This section is the single source of truth for the on-disk artifacts that drive async-by-default `/wrap` and SessionStart auto-enrichment. Every other unit (the Stop hook `hooks/stop-context.js`, the OpenCode plugin `.opencode/plugins/session-context.ts`, and the conductor's SessionStart auto-enrichment protocol below) references the schemas here by exact field name; none restate field semantics divergently. Field names below are NORMATIVE. All writes are atomic (tmp + rename) and umbrella-ignored by `.agentic/*`.

**1. `.agentic/wrap-pending.json` (the enrichment marker).** Staged when a session has substantive un-wrapped work, so the next session in that project completes enrichment idempotently. Schema:

    {
      "schema_version": 1,
      "session_id": "<uuid of the session that staged the marker>",
      "staged_at": "<ISO8601 UTC, immutable>",
      "status": "pending | in_progress | done | gave_up",
      "claimed_by": "<uuid of the session currently running enrichment, or null>",
      "claimed_at": "<ISO8601 UTC of last claim, or null>",
      "attempts": "<int, 0..3>",
      "project_root": "<absolute cwd>",
      "last_error": "<short string or null>"
    }

- `status` lifecycle: `pending` (staged, unclaimed) -> `in_progress` (claimed, enrichment running) -> `done` (completed; marker then unlinked) | `gave_up` (`attempts >= 3`; marker retained with a manual-`/wrap` notice).
- `staged_at` is immutable. `claimed_at` plus a staleness window are a wastefulness reducer, not a correctness invariant (see Lock strategy in the Enrichment Pipeline below) - they make a double-claim rare, never impossible; idempotency is what makes a double-run safe.
- `attempts` increments at claim time, before enrichment begins, so a crash mid-enrichment still counts toward the give-up budget.

**2. `.agentic/.last-wrap` (the wrap-recency sentinel).** A single line containing the `session_id` of the session whose `/wrap` (sync or background enrichment) last successfully wrote `context.md`. Atomic write. This sentinel fully replaces any header-date parsing - no site parses the `context.md` header date to decide "was this session wrapped." Consumers: (a) the Stop hook's marker-staging suppression (do not stage a marker if the current `session_id` equals `.last-wrap`), and (b) the OpenCode plugin's equivalent suppression. It is written ONLY after a successful Part A `context.md` write - never staged early (writing it during Step 0a would suppress this very session's own recovery marker).

**3. `.agentic/.stop-deferred-activity.jsonl` (the spillover log).** Append-only JSONL, one record per Stop-hook (or OpenCode-idle) invocation that found `wrap.lock` held and therefore skipped its `context.md` write. Drained into the `context.md` activity block by the enrichment flow during its Part A write (atomic three-step drain, see the Enrichment Pipeline below). Record schema:

    {"schema_version": 1, "ts": "<ISO8601 UTC>", "session_id": "<uuid>", "recent_focus": ["<msg>"], "paths_referenced": ["<path>"], "uncommitted": ["<status code + path>"], "tools_used": ["<tool>"]}

**Pinned header prefix (NORMATIVE).** Exactly one byte-exact prefix is the contract between writer and matcher:

    # Session Context\n*Written by /wrap

This is what `hooks/stop-context.js:788` and `.opencode/plugins/session-context.ts:449` test via `startsWith`, and what every `/wrap` Output-1 / merge write must emit as its first two lines. The on-disk header date is a UTC calendar date (`date -u +%Y-%m-%d`); the header STRING does NOT contain the "UTC" literal - it stays `*Written by /wrap on YYYY-MM-DD. ...` exactly as the Output-1 template (Step 1) reads. The matcher only tests the pinned prefix (which stops before the date), so the date format and the absence of the "UTC" literal are both compatible. The Part A merge rule (the "(merged context)" header rewrite) appends after the date and is outside the pinned prefix - it stays. The rolling-session-label merge (Part A) is preserved unchanged.

Tell the user: "Writing enriched session context — I'll let you know when it's done."

**Step 0a — Stage the resume safety-net** (runs BEFORE Step 0; default and `--sync` paths both run it).

`/wrap` is async by default: it returns control within seconds and finishes enrichment in the background. Because an async run can exit before its Part A `context.md` write completes, stage a recovery marker first so the next session in this project can complete enrichment idempotently if this one is interrupted.

Stage `<cwd>/.agentic/wrap-pending.json` (atomic tmp + rename) per the schema in the Deferred-enrichment data model section, with:

- `schema_version: 1`, `session_id: <this session_id>`, `staged_at: <now, ISO8601 UTC>`, `status: "pending"`, `claimed_by: null`, `claimed_at: null`, `attempts: 0`, `project_root: <absolute cwd>`, `last_error: null`.

If a live marker already exists for this project (status `pending` or `in_progress`), do NOT overwrite it - this session will claim and run it via the Enrichment Pipeline rather than staging a second one. A marker with `status: done`/`gave_up` is not live; overwrite it.

**Step 0a does NOT write `.agentic/.last-wrap`.** `.last-wrap` is written only after a successful Part A `context.md` write (see the Enrichment Pipeline, Part A). Writing it here would suppress this very session's own recovery marker on the next Stop-hook fire.

**Step 0b — Route early (light / zero-substance run inline; standard goes async).**

Run the Step 0.5 routing decision now, before any async dispatch, using the raw data the conductor already holds in context (compile a quick survey per Step 0 if needed to make the call). Routing is unchanged from today - only its position moved earlier so the dispatch decision in Step 0c can use it:

- **Zero-substance** or **light** path: run INLINE and synchronously per their procedures in Step 0.5 (they are already cheap - no draft Worker, no Skeptic, or a single inline draft). Do NOT defer these. On a zero-substance run there is nothing to enrich, so unlink the Step 0a marker (`status: done` then unlink) as part of the zero-substance procedure. On a light run, after the inline Part A `context.md` write completes and `.last-wrap` is updated, unlink the Step 0a marker.
- **Standard** path: proceed to Step 0c (async dispatch). Only the standard path runs the full draft -> Skeptic -> Part B/C/E Enrichment Pipeline, and only it benefits from running in the background.

**Step 0c — Async dispatch (default) or synchronous fallback (`--sync`).**

**Default (async).** The Step 0a marker is already staged. Dispatch the Enrichment Pipeline (below) to run in the background within the conductor's session: spawn each pipeline agent with `run_in_background: true`, return control to the user immediately with a one-line staging confirmation ("Session context staging started; enrichment is running in the background and will finish shortly. Marker: `.agentic/wrap-pending.json`."), and stay responsive to further prompts. The pipeline drives itself to completion and performs the terminal marker transition (Step 6).

**`--sync`.** When the user invokes `/wrap --sync`, skip async dispatch and run the Enrichment Pipeline inline and blocking - today's fully-synchronous behavior, byte-for-byte. The same narrow Part-A lock window applies; the only difference from the default is that the conductor does not return control until Step 6 completes.

**Same-session coalesce.** If a background enrichment is already in-flight for THIS session (the conductor knows it dispatched one in Step 0c that has not yet reached its Step 6 terminal transition), a fresh manual `/wrap` (default or `--sync`) does NOT launch a second pipeline. It coalesces with a one-line notice: "Background enrichment already running for this session; it will complete shortly." This is safe because the narrow Part-A-only lock means a second run would in nearly all cases find the lock free and race the first run's context.md merge; coalescing avoids the wasted double-run entirely. (A duplicate run across DIFFERENT sessions is still tolerated by idempotency - see the Enrichment Pipeline.)

**Enrichment Pipeline** (invoked by `--sync`, by the default async dispatch in Step 0c, and by the next-session auto-trigger in the SessionStart auto-enrichment protocol).

The pipeline is the body formerly numbered Steps 1-4 + Part E. It runs as: draft Worker (Step 1) -> conductor arranges a fresh Skeptic (Steps 2-3) -> inline writes (Step 4 Parts A-C) -> compression (Part E) -> terminal marker transition (Step 6). Each agent spawn in the pipeline sets `run_in_background: true`. When the pipeline is dispatched async, the conductor orchestrates these background spawns while staying responsive; when invoked via `--sync` it runs the same spawns and blocks until Step 6.

**Lock strategy (CRITICAL - narrow Part-A-only hold).** Acquire `<cwd>/.agentic/wrap.lock` (per the Pre-flight lock acquisition protocol above) ONLY around the Part A `context.md` read-merge-write window - NOT around the whole flow. The draft Worker, the Skeptic, Part B (`.agentic/memory.md`), Part C (`AGENTS.md`), and Part E compression all run with NO lock held, because those files are single-writer (`/wrap` only) and cannot be clobbered by another actor. `context.md` is the sole genuinely-contended document (the Stop hook and the OpenCode plugin also write it); the narrow lock serializes only the enrichment's `context.md` write against those two hooks, which are lock-aware (they skip + spill while the lock is held). Correctness everywhere else rests on idempotency, not on holding the lock.

Inside the Part A locked window, in this exact order:

1. **Atomic spillover drain** (three steps; rename-first prevents loss of a record a hook appended just before the lock was observed):
   - `rename(.agentic/.stop-deferred-activity.jsonl -> .agentic/.stop-deferred-activity.jsonl.draining.<pid>)`. Atomic. Any hook append after this rename creates a fresh `.stop-deferred-activity.jsonl` belonging to the next drain - not lost.
   - Read the renamed copy's records and fold them into the `context.md` activity block (each record carries its own `session_id`, preserving cross-session provenance; the block header reflects the enrichment session).
   - `unlink(.agentic/.stop-deferred-activity.jsonl.draining.<pid>)`.
2. **Rolling-session-label merge write** of `.agentic/context.md` (the existing Part A logic, unchanged - see Part A below).
3. **Write `.agentic/.last-wrap`** = this session's `session_id` (atomic).
4. **Release the lock** (`rm -rf .agentic/wrap.lock`) as the last action of the window.

**Recent-Focus dedup rule (idempotency for a duplicate claim).** Key the folded Recent-Focus draft by the marker's `session_id` + `staged_at`. Before appending the new draft under a fresh session label in the rolling-label merge (Part A), check whether a draft for this same `session_id`+`staged_at` has already been folded under an existing label. If it has (a re-run of the same marker, e.g. two sessions both claimed it), SKIP the append rather than adding a duplicate label. This makes the rolling-label merge idempotent on a duplicate claim - a second enrichment of the same marker produces no second label - satisfying the idempotency guarantee (a duplicate run is wasteful, not corrupting).

**Part E invariant (explicit).** Part E compresses ONLY `.agentic/memory.md` (the Part B target) and `[cwd]/CLAUDE.md`. Part E NEVER touches `context.md` - `context.md` is written exclusively by Part A and is never a compression target.

**Step 0 — Compile session data** (inline, no subagent needed).

Survey the current conversation and note down:
- The main task and its current state (done? blocked? in progress?)
- All files touched or created this session (from tool call history — be specific: full paths)
- Any errors, gotchas, or near-misses that surfaced
- Specific remaining next steps (file paths, branch names, commands, open PRs — concrete enough to act on without re-reading the chat)
- Tools used during the session
- Stable project facts worth preserving: setup commands that don't change, persistent project-wide gotchas or quirks, architectural decisions made, recurring patterns or conventions established. Distinguish these from temporary state (current task, files touched this session) - stable facts will go into memory.md, temporary state into context.md only.
- Identify the project root (absolute cwd).
- Check for and read: the root `AGENTS.md` (if it exists), and any `[track]/AGENTS.md` files in subdirectories that had files touched this session. Record their full current content — this will be passed to the Worker as a dedicated field so it can avoid duplicating what is already captured.
- **Migrate `.claude/compression-state.json` → `.agentic/compression-state.json`** if `.claude/compression-state.json` exists AND `.agentic/compression-state.json` does NOT exist: `mv <cwd>/.claude/compression-state.json <cwd>/.agentic/compression-state.json`. Log the move to the wrap run output only.
- **Read `.agentic/compression-state.json`** if it exists in the project. Record its full current content — this will be passed to Part E later to determine whether compression is needed for each target.
- **Read `.agentic/learnings.md`** if it exists in the project. Record its full current content — this will be passed to the draft Worker in Step 1 so it does not re-derive facts already captured by `learnings-agent`.
- Note which tracks (subdirectories) had files touched this session — these are candidates for AGENTS.md updates.
- **Check for missing AGENTS.md files:** For each directory that had files touched this session, check whether an AGENTS.md file exists in that directory. Skip generated/artifact directories (`node_modules`, `.next`, `dist`, `out`, `build`, `.expo`, `.turbo`, `coverage`, `.cache`, `__pycache__`, `.git`). For each non-generated directory missing an AGENTS.md, note it as a **new AGENTS.md candidate** and include it explicitly in the raw data passed to the draft Worker. The Worker will propose content for these new files; the conductor will create them automatically without asking the user.
- **Run `git status --porcelain` and `git stash list`** to capture uncommitted changes and stashes. If there are uncommitted tracked files (M, A, D - not ??), list them explicitly. This is critical for preventing work loss across sessions - if the user asked to commit and files were missed, this is the safety net.
- **Note specialist agent outputs** — if `perf-analyst`, `release-orchestrator`, or `dependency-auditor` ran this session, capture their key findings: stable facts (confirmed hotspots with measurements, release version and tag, known CVEs) belong in memory.md entries; session-scoped issues (a partial deploy, a perf regression under investigation, an unresolved dependency conflict) belong in Watch Out For.
- **Note Trivial commits** — if any commits this session were classified Trivial, include them in "files touched" and "next steps" as normal. Trivial commits produce no Skeptic artifact and no adversarial brief - do not flag their absence as a gap. Only note the commit SHA and what changed.
- **Note task-state summary** - if `.agentic/tasks.jsonl` exists and contains entries with the current `session_id`, include in the session wrap summary: final task status counts (N done, N blocked, N failed, N abandoned). Do NOT copy task entries into MEMORY.md - they are already durable in the file.
- **Note loop-state summary** — if `.agentic/loop-state.json` exists: if `status=active`, note in the wrap summary that an incomplete loop was active when `/wrap` ran (the conductor should investigate before ending the session); if `status=interrupted`, note a pending resume is available (the next `/implement-ticket` invocation will offer to resume). The wrap command does NOT delete or modify `loop-state.json` - that is the user's choice (resume vs fresh-start). Do NOT copy loop state details into MEMORY.md or context.md beyond the one-line status note.
- **Enumerate open PRs targeting the conductor's current branch.** /wrap writes AGENTS.md and memory.md additions onto the conductor's current branch (typically `main`). If those additions cite file paths or feature keys that live on branches with open PRs not yet merged, the doc additions will land on the target branch describing files/keys that do not yet exist there. Capture the open-PR set now so Step 1 can defer such additions:

  ```bash
  CURRENT_BRANCH=$(git -C $REPO branch --show-current)
  gh pr list --state open --base "$CURRENT_BRANCH" --json number,headRefName,files \
    --jq '.[] | {n: .number, branch: .headRefName, files: [.files[].path]}'
  ```

  Record the resulting `{pr_number, head_branch, modified_files[]}` set as the **open-PR overlap set**. If `gh` is unavailable or returns an error, log "open-PR overlap check skipped (gh unavailable)" to the wrap run output and pass an empty set forward — the deferral logic becomes a no-op rather than blocking the run. The set is supplied to the draft Worker as a dedicated field (see Step 1) so it can flag deferral candidates; the conductor enforces deferral at write time in Step 4.

This raw data is what the draft Worker will format. The Worker is a fresh agent with no session memory, so if you don't supply the details here, they won't appear in the output.

**Step 0.5 - Route to light, zero-substance, or standard path.**

This is the routing decision invoked early by Step 0b (the procedures below are unchanged; only their invocation point moved earlier so async dispatch in Step 0c can use the routing result). Inspect what Outputs 2 and 3 would contain based on the raw data already compiled in Step 0. Do not spawn anything yet. The standard path is the only path that goes async (Step 0c); light and zero-substance run inline per Step 0b.

**Zero-substance path** - triggers when ALL of the following hold:
- Output 2 (memory entries) would be "None"
- Output 3 (AGENTS.md updates) would be "None" for every file AND no new AGENTS.md candidates exist
- No specialist agent (`perf-analyst`, `release-orchestrator`, `dependency-auditor`) ran with session-scoped issues to capture
- The session had effectively no file activity worth preserving in context.md: no uncommitted tracked changes, no new stashes, no files touched beyond reads, no meaningful next steps to record. The conductor should judge - if the only meaningful session output is "answered a question", it is zero-substance.

Zero-substance procedure:
- Do NOT write context.md (the Stop hook already writes a raw context file after every turn - running /wrap on a zero-substance session duplicates that work with a hand-curated version of nothing)
- Skip Steps 1-3 entirely (no Worker, no Skeptic)
- Skip Step 4 Parts A, B, C entirely
- Skip Part E (nothing changed, nothing to compress)
- Still run Step 5 (worktree cleanup) - that is always useful
- Step 6 confirmation must say: "zero-substance path - nothing new to capture this session; ran worktree cleanup only"

**Light path** - triggers when the zero-substance conditions do NOT all hold BUT ALL of the following hold:
- Output 2 (memory entries) would be "None" - STRICT: even a single memory entry routes to standard path
- Output 3 (AGENTS.md updates) would be "None" for every file AND no new AGENTS.md candidates exist
- No specialist agent ran with session-scoped issues to capture

Light path procedure (replaces Steps 1-3; preserves parts of Step 4):
1. Main agent drafts context.md inline from the Step 0 raw data, following the Output 1 structure exactly. No Worker, no Skeptic.
2. Skip Step 1 (draft Worker) and Steps 2-3 (Skeptic + sign-off validation).
3. Proceed to Step 4 Part A with the inline draft.
4. Skip Part B (memory.md - input is None), Part C (AGENTS.md - input is None).
5. Skip Part E entirely (nothing changed, nothing to compress).
6. Run Step 5 (worktree cleanup) as normal.
7. Step 6 confirmation must say: "light path (no stable facts or AGENTS.md updates to review this session)".

**Escape hatch for light path:** If, while drafting context.md inline, the main agent notices something it wants the Skeptic to review - ambiguous next-step wording, uncertainty about whether a fact is stable or temporary, unfamiliar territory in the raw data - it must abandon the light path and fall back to the standard path. The light path is for cases where there is genuinely nothing worth an adversarial pass.

**Escape hatch for zero-substance path:** If the conductor has ANY uncertainty about whether the session is truly zero-substance - for example, the user asked a question whose answer feels architecturally significant, or an implicit decision was made without writing anything down - it must abandon the zero-substance path and use the light or standard path instead. When in doubt, do not use the zero-substance path.

**Standard path** - triggers when neither of the above applies (i.e. at least one of Outputs 2/3 has real content, OR a specialist agent ran with session-scoped issues). Proceed to Step 1 unchanged.

**Step 1 — Spawn a draft Worker** (background, general-purpose):

---
You are a Worker agent. Format the raw session data below into three outputs. Replace all placeholders with real content from the data provided. If a section genuinely has nothing to say, write the word "None" — never leave brackets or template text.

**Raw session data:**
[paste your Step 0 notes here verbatim — this covers the task, files touched, errors, next steps, tools used, and stable facts. Do NOT embed existing AGENTS.md file contents here; those go in the dedicated field below.]

**Existing learnings:**
[Paste the full current content of `.agentic/learnings.md` read in Step 0, clearly labeled. If the file was not found, write "None." The Worker must check whether a proposed memory entry is already captured here as a structured learning before proposing it.]

**Existing AGENTS.md file contents:**
[For each AGENTS.md file read in Step 0, paste its full current content here, clearly labeled with its absolute path, e.g.:

File: /Users/alice/myapp/AGENTS.md
Content:
<full file content>

File: /Users/alice/myapp/backend/AGENTS.md
Content:
<full file content>

If no AGENTS.md files were found, write "None."]

**Open-PR overlap set:**
[paste the `{pr_number, head_branch, modified_files[]}` entries captured in Step 0, or "None" if no open PRs target the conductor's current branch / the check was skipped. The conductor will use this to defer doc additions whose cited paths overlap an open PR — but you should still flag candidates so the conductor's deferral pass has hints.]

**Output 1 — context.md draft**

Produce this exact structure. Include only temporary session state here (current task, files touched, recent errors, next steps). Do not include stable project facts in this file - those belong in Output 2.

    # Session Context
    *Written by /wrap on YYYY-MM-DD. Preserved by Stop hook. Not committed to git.*
    *Project: [absolute cwd]*

    ## Recent Focus
    [1–3 sentences: what was being worked on when /wrap was invoked]

    ## Current Task / Next Steps
    [Specific next steps: file paths, branch names, open PRs, exact commands. Concrete enough to act on without reading the chat history.]

    ## Key File Paths
    [Files touched or created this session that the next session will care about]

    ## Uncommitted Changes
    [Output of `git status --porcelain` for tracked files only (M/A/D/R, not ??). If working tree is clean, write "(working tree clean)". If there are uncommitted files, list each with its status prefix. This section is a safety net - if the user asked to commit all changes and files appear here, they were missed.]

    ## Stashes
    [Output of `git stash list`, or "(no stashes)" if empty. Stashes may contain work from previous sessions that was never committed.]

    ## Watch Out For
    [Session-specific issues, errors, or near-misses from this session only. Stable/recurring project quirks do not belong here - those go in memory.md. Or: None.]

    ## Tools Used
    [Comma-separated list of unique tools used this session]

**Output 2 — memory.md entries**

Review the raw session data for stable project facts: setup commands that don't change, persistent project-wide gotchas or quirks, architectural decisions, recurring patterns, project conventions. For each stable fact, produce one entry in this format:

`- **YYYY-MM-DD:** [what was decided and why this approach was chosen - alternatives considered may be noted as supporting context, in one to two sentences]`

Use today's date for all entries. If there are no stable facts to record, write "None."

Before proposing a memory entry, check the **Existing learnings** field above. If the same fact is already captured as a structured learning entry (same pattern, same gotcha, same architectural decision), skip it. Do not duplicate content between `.agentic/learnings.md` and `.agentic/memory.md` — they serve different purposes (structured fix-patterns vs. session-synthesized stable facts), but the underlying fact should only be recorded once.

Stable = true every session, not just this one. Temporary = only relevant right now (current task, files touched this session).

For architectural and technology decisions especially: the entry must clearly state why the chosen approach was selected on its own merits. Alternatives considered and their rejection reasons are useful supporting context but are secondary - the positive reasoning for the choice is the primary requirement. A future session asking "should we reconsider X?" should find the answer in the entry without re-researching it.

**Deferral hint:** If an entry's substance depends on file paths, feature keys, or symbols that appear in the Open-PR overlap set above (i.e. the fact only becomes true once an unmerged PR lands), append the marker `[defer-pr: <pr_number>]` to the end of the entry text. The conductor uses this hint plus its own path cross-reference to route the entry to `.agentic/memory-pending.md` instead of `.agentic/memory.md`.

**Output 3 — AGENTS.md updates**

For each AGENTS.md file whose current content was provided in the "Existing AGENTS.md file contents" field above, produce proposed additions only - not a full rewrite. Use that existing content as your baseline: do not propose content already present there.

Format each proposed update as:

    File: [full path to AGENTS.md]
    Section: [section name, e.g. "## Decisions", "## Conventions", "## Stack", "## Key Conventions"]
    Add:
    - [bullet point to add]
    - [another bullet if needed]

If a section doesn't exist in the target file yet but should be added, indicate:

    File: [full path to AGENTS.md]
    New section: [section name]
    Content:
    [section content]

If content in an existing entry should be corrected or superseded, indicate:

    File: [full path to AGENTS.md]
    Section: [section name]
    Update: [existing text] → [replacement text]

Rules:
- Only propose content that was actually established or learned in this session. Do not hallucinate or infer.
- Do not duplicate content already present in the existing AGENTS.md (check against the "Existing AGENTS.md file contents" field provided above).
- Do not contradict existing content without flagging it as an Update.
- For root AGENTS.md: focus on `## Decisions` (resolved architecture decisions as brief bullets) and `## Conventions` (patterns and rules the project follows).
- For subdir AGENTS.md: focus on `## Stack`, `## Key Conventions`, and any new relevant categories (Commands, Schema, Flows, Gotchas) that emerged this session.
- Quality directive: lean and curated. No verbose rationale paragraphs, no outdated entries, no conflicting information. Brief, actionable bullets only.
- If nothing new for a particular file, write "None" for that file.
- If no AGENTS.md files were found in the project, write "None."
- **Deferral hint:** if a proposed addition cites a file path, directory, or feature key that appears in the Open-PR overlap set above (i.e. the addition describes something that only exists on an unmerged branch), append the marker `[defer-pr: <pr_number>]` to the end of each affected bullet or section content. The conductor uses this hint plus its own path cross-reference to route the addition to `.agentic/agents-md-pending.md` instead of applying it now.

**New AGENTS.md files:** For any touched directory explicitly noted as a "new AGENTS.md candidate" in the raw session data (i.e. the directory had files touched but has no existing AGENTS.md), propose creating a new file. Use this format:

    File: [full path to new AGENTS.md]
    New file: true
    Content:
    # [Directory name]

    [One sentence description of what this directory contains, based on the session data.]

    ## Stack
    [Key technologies from package.json or inferred from file types touched - bullet list]

    ## Key Conventions
    [Conventions observed from the session - bullet list. If none observed, omit this section.]

    ## Gotchas
    [Any gotchas or sharp edges encountered - bullet list. If none, omit this section.]

This is automatic - do not ask the user. Populate sections from session context and any package.json content included in the session data.

Return all three outputs clearly labeled. Do not write to disk.

---

**Step 2 — When the draft Worker returns, spawn a fresh Skeptic** (background, general-purpose, never resumed).

Scope constraint: the Skeptic reviews only the accuracy and completeness of the context file and the AGENTS.md updates. Its findings must only trigger context file or AGENTS.md rewrites - never code changes, bug fixes, or any development work. If the Skeptic notes that the context file describes pending work that is already complete (or vice versa), the fix is to update the wording to reflect reality accurately.

Provide the draft, the existing AGENTS.md file contents from Step 0, and this adversarial brief. **Omit any section below whose corresponding Output is "None"** - always keep the Output 1 (context.md accuracy) review as the baseline pass; drop the memory-review language if Output 2 is "None"; drop the AGENTS.md-review paragraph if Output 3 is "None". The full brief below is the "all outputs present" case:

> "Is this context file accurate and actionable? Check each section: Does Recent Focus correctly describe what was actually happening — or is it vague, generic, or wrong? Are the Next Steps specific enough to act on without reading the chat history (file paths, commands, branch names)? Are Key File Paths complete — is anything relevant omitted? Does Watch Out For capture real gotchas, or is it empty when it shouldn't be? Is any section still template text rather than real content?"
>
> "Also review the proposed AGENTS.md updates (Output 3): Is each proposed addition actually derived from this session's work - or is it generic, hallucinated, or already present in the existing file content provided? Is any content going to the wrong file (project-wide content should go to root; track-specific content should go to the track subdir)? Are updates lean - brief bullets only, no verbose rationale? Does any proposed addition contradict or duplicate existing entries in the same file?"

Require this statement before sign-off: "Active search: I have applied the adversarial brief and actively searched for Critical and Major findings."

**Step 3 — Validate sign-off format.**

A valid sign-off requires all four elements: (a) "Reviewed:", (b) "Findings:", (c) "Active search:", (d) "No unresolved Critical or Major findings. Sign-off granted." If any element is missing, spawn a new Skeptic with format instructions (not a new re-route round). Limit: 3 format re-invocations, then escalate to the user.

If Critical or Major findings remain: spawn a new draft Worker with the original draft and findings, get a revised draft, then spawn a fresh Skeptic (Step 2). Repeat until sign-off. If the same finding is contested across 2+ re-routes without resolution, escalate to the user.

**Step 4 — Write to disk** (main agent, inline — do NOT delegate to a subagent).

Background subagents cannot reliably get Write/Edit permissions. The main agent must perform all writes directly. Invoking /wrap implies permission to write these files.

**Mandatory Skeptic on hand-authored output.** If the conductor authored any of the final outputs inline — for example, after a draft Worker hallucination, after a re-route loop hit its limit, after a light-path escape hatch fell back to the standard path mid-flight, or any other case where the conductor bypassed the Worker → Skeptic chain in Steps 1–3 — the conductor MUST spawn a fresh Skeptic on the on-disk files BEFORE releasing the lock in Step 6. The conductor's escape hatch from Worker iteration does NOT exempt the outputs from Skeptic review; that loophole is closed. The Skeptic in this case reads the on-disk files directly (`.agentic/context.md`, `.agentic/memory.md`, any AGENTS.md files updated, plus any deferred-write files at `.agentic/memory-pending.md` and `.agentic/agents-md-pending.md`) and applies the same adversarial brief from Step 2 (with the same scope constraint — the Skeptic's findings only trigger doc rewrites, never code changes). If the Skeptic raises Critical or Major findings, the conductor revises the on-disk files inline and re-spawns a fresh Skeptic until sign-off, subject to the same 3-re-route limit; on cap exhaustion, escalate to the user with the open findings.

**Project directory:** [absolute cwd]

**Output path (context.md):** `<cwd>/.agentic/context.md`. Project-local. The file lives next to the code it describes and is gate-free (no sensitive-file check). The Stop hook writes to the same path. Create the `<cwd>/.agentic/` directory if it does not exist.

**Memory path (memory.md):** `<cwd>/.agentic/memory.md`. Same directory as context.md.

**Migration note:** Earlier versions of this skill wrote to `~/.claude/projects/[hash]/{context,memory}.md`. If those files exist for the current project but the project-local files do not, copy them once into `<cwd>/.agentic/` before merging. Symlinks at the old hashed location pointing at the new project paths are acceptable - they preserve any platform mechanism that auto-loads from the legacy path while keeping writes gate-free.

**Part A — Write context.md**

**Lock window (NORMATIVE).** Part A is the ONLY part of the flow that holds `wrap.lock`. Acquire the lock immediately before step 1 below, perform the atomic spillover drain (Enrichment Pipeline, step 1) -> the read-merge-write below -> write `.agentic/.last-wrap` = this `session_id`, then release the lock as the last action. Parts B, C, and E run with no lock held. See the Enrichment Pipeline "Lock strategy" above for the full ordering. The merged write below always begins with the pinned header prefix `# Session Context\n*Written by /wrap` (the matcher contract); no site parses the header date.

1. Use the Read tool to attempt to read the file at the output path computed above.

2. **If the file does not exist** (Read returns a file-not-found error): write the new draft content directly to the output path. Return: "Wrote fresh context to [path] (no existing file)."

3. **If the file exists but is empty, or its second line does not begin with `*Written by /wrap`**: the existing file was written by the Stop hook or another source and cannot be meaningfully merged. Write the new draft content directly, overwriting the existing file. Return: "Wrote fresh context to [path] (replaced non-/wrap file)."

4. **If the file exists and its second line begins with `*Written by /wrap`** (i.e. it was produced by a previous `/wrap` run): proceed to the merge step below.

Note: "second line" means the literal second line of the file. A `/wrap`-produced file always starts with `# Session Context` on line 1 and `*Written by /wrap on ...` on line 2.

**Merge step:**

**Duplicate-claim dedup (idempotency).** Before assigning a new session label below, apply the Recent-Focus dedup rule from the Enrichment Pipeline: key the new draft by the marker's `session_id` + `staged_at`; if a draft for this same `session_id`+`staged_at` has already been folded under an existing label (a re-run of the same marker across two sessions), SKIP the append entirely - do not add a new label, do not roll the window. The rest of Part A (Part B/C/E gating, `.last-wrap` write) still proceeds. This makes a duplicate enrichment of the same marker wasteful but non-corrupting.

First, check how many session labels are already present in the existing file's Recent Focus section.

- **Five labels present (`[Session A]` through `[Session E]`)**: apply a rolling-window merge. Discard the `[Session A]` content from Recent Focus, relabel `[Session B]` as `[Session A]`, `[Session C]` as `[Session B]`, `[Session D]` as `[Session C]`, `[Session E]` as `[Session D]`, and use the new draft as `[Session E]`. For all other sections (Current Task / Next Steps, Key File Paths, Watch Out For, Tools Used), treat the full existing content as the prior session and apply the standard merge rules below.

- **Four labels present (`[Session A]` through `[Session D]`)**: label the new draft entry `[Session E]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Three labels present (`[Session A]`, `[Session B]`, `[Session C]`)**: label the new draft entry `[Session D]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Two labels present (`[Session A]` and `[Session B]`)**: label the new draft entry `[Session C]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Single unlabeled Recent Focus** (standard case - first merge): label the existing entry `[Session A]` and the new draft entry `[Session B]`, each on its own paragraph.

**Merge rules (existing file = prior session(s), new draft = newest session):**

- **Header line** (`*Written by /wrap...`): replace with a new line using today's date and the note "(merged context)". Keep the `*Project:` line from the new draft.
- **Recent Focus**: apply the labeling logic above.
- **Current Task / Next Steps**: combine all items from both. Remove exact duplicate lines. Keep all non-duplicate items.
- **Key File Paths**: union both lists. Remove exact duplicate lines.
- **Watch Out For**: union both lists. Remove exact duplicate lines. If one had "None" and the other has real entries, use only the real entries.
- **Tools Used**: combine both comma-separated lists, split by comma, trim whitespace, deduplicate, re-join as a single comma-separated list.

Write the merged result to disk. Return: "Merged context written to [path] (combined sessions)."

**Part B — Write memory.md**

Skip Part B entirely if the memory entries input above is "None".

**Open-PR deferral pass (run BEFORE the read/merge steps below).** For each proposed memory entry, cross-reference the file paths, directory paths, and feature keys cited in the entry against the Open-PR overlap set captured in Step 0. An entry is **post-merge-deferred** if any cited path or key appears in the `modified_files[]` list of any open PR, OR the Worker tagged the entry with `[defer-pr: <pr_number>]`. Strip the marker from the entry text and route the entry to `<cwd>/.agentic/memory-pending.md` (append-only; create the file if missing) under a heading `## Pending PR #<pr_number> (<head_branch>)`. Non-deferred entries continue to the steps below. The pending file is plain markdown — a follow-up doc PR after the source PRs merge can move entries from `.agentic/memory-pending.md` into `.agentic/memory.md`. Rationale: docs land on the conductor's branch (typically `main`) before source PRs merge; without deferral, memory.md describes paths or keys that do not yet exist on the target branch.

1. Use the Read tool to attempt to read the file at the memory.md path.

2. **If the file does not exist**: write all non-deferred entries directly as a markdown list. Return: "Wrote fresh memory to [path] (N entries written, M deferred to memory-pending.md)."

3. **If the file exists**: read its content. For each non-deferred entry, check whether the same fact is already captured — not just as an exact string match, but semantically (same architectural decision, same gotcha, same command). Also check `.agentic/learnings.md` (read in Step 0): if the same fact is captured as a structured learning entry, skip the new memory entry. If an existing entry covers the same fact, skip the new entry. If the new entry supersedes an existing one (same topic but updated or corrected), replace the existing entry in place with the new one. Otherwise append the new entry. Write the merged result. Return: "Updated memory at [path] (N entries added, M entries superseded, K deferred to memory-pending.md)."

**Part C — Write AGENTS.md updates**

Skip Part C entirely if the AGENTS.md updates input above is "None" or all files within it are marked "None".

**Open-PR deferral pass (run BEFORE iterating files).** For each proposed `Add:`, `New section:`, `New file: true`, and `Update:` block, cross-reference the file paths, directory paths, and feature keys cited in the proposed content against the Open-PR overlap set captured in Step 0. A block is **post-merge-deferred** if any cited path or key appears in the `modified_files[]` list of any open PR, OR the Worker tagged the block with `[defer-pr: <pr_number>]`. Strip the marker from the block content and route the deferred block to `<cwd>/.agentic/agents-md-pending.md` (append-only; create the file if missing) under a heading `## Pending PR #<pr_number> (<head_branch>) — <target AGENTS.md path>`. Non-deferred blocks continue through the per-file write below. A follow-up doc PR after the source PRs merge can move entries from `.agentic/agents-md-pending.md` into the actual AGENTS.md files. Rationale: docs land on the conductor's branch (typically `main`) before source PRs merge; without deferral, AGENTS.md describes paths or keys that do not yet exist on the target branch — exactly the failure mode that historically produced Critical findings during /wrap Skeptic review.

For each file with non-deferred updates:

1. Use the Read tool to attempt to read the current file content.

2. **If the file does not exist** (Read returns a file-not-found error): create a minimal stub appropriate for the file type, then continue to steps 3-6 to apply the proposed updates into it.
   - **Subdirectory AGENTS.md** (any path that is not the project root's AGENTS.md - i.e. the file is not at `[cwd]/AGENTS.md`): create a stub with `# [directory name]` as the H1 (derive from the parent directory of the file path), a `## Stack` section header, and a `## Key Conventions` section header.
   - **Root AGENTS.md** (the file is at `[cwd]/AGENTS.md`): create a stub with `# [project name]` as the H1 (derive from the cwd directory name), a `## Decisions` section header, and a `## Conventions` section header.
   If the draft Worker proposed a complete `New file: true` block with content, use that content as the starting file instead of the minimal stub.
   After creating the stub or new file, proceed with steps 3-6 to apply the proposed updates into it. Return: "Created and updated AGENTS.md at [path] (N additions)."

3. For each `Add:` update: locate the target section. Append the new bullet(s) at the end of that section, before the next `##` heading (or at end of file if it's the last section). Do not duplicate any bullet already present (check semantically, not just string match).

4. For each `New section:` update: insert the new section after the last existing section in the file, maintaining the document's natural flow (decisions and conventions before gotchas; stack and key conventions before less-common categories). Do not blindly append without regard to the existing structure.

5. For each `Update:` update: find the existing text and replace it with the replacement text.

6. Write the updated file to disk.

Return: "Updated AGENTS.md at [path] (N additions, M updates)" for each file written, or "Skipped [path] (nothing to add)" if all proposed additions were already present.

**Part E — Compress always-loaded memory files**

Skip Part E entirely if Parts B and C both reported no changes (no new memory entries, no AGENTS.md updates). Nothing changed this session - no need to recompress. Part A always writes context.md and is not a signal of session-meaningful change.

**Targets (INVARIANT):**
- The `memory.md` file written by Part B (same absolute path computed in Step 4).
- `[cwd]/CLAUDE.md` if it exists at the project root.

Part E compresses ONLY these two targets. Part E NEVER touches `.agentic/context.md` - context.md is written exclusively by Part A (under the narrow lock) and is never a compression input or output. Part E runs with no lock held (both targets are single-writer `/wrap`).

Skip any target that does not exist.

**State file:** `[cwd]/.agentic/compression-state.json`. Schema:

    {
      "targets": {
        "<absolute path>": {
          "last_compressed_size_bytes": <int>,
          "last_compressed_at": "<YYYY-MM-DD>",
          "original_backup_path": "<absolute path to FILE.original.md>",
          "rolling_snapshots": ["<absolute path to FILE.pre-YYYY-MM-DD-HHMMSS.md>", ...]
        }
      }
    }

If the file does not exist, treat all targets as never-compressed.

**Gate:** For each target, compute current file size in bytes. Compress only if:
- (a) No prior entry exists for this target AND current size > 2000 bytes, or
- (b) A prior entry exists AND current size >= 1.5 * `last_compressed_size_bytes`.

Otherwise skip that target silently.

**For each target that passes the gate:**

1. Spawn a dedicated background Worker (general-purpose) with this brief verbatim:

   > You are a compression Worker. Rewrite the file content below into a token-dense form suitable for an LLM to read on every session start. Hard constraints, no exceptions:
   > - Preserve every technical fact, decision, gotcha, and rationale. If you are not certain a phrase is filler, keep it.
   > - Never alter: file paths, absolute or relative; shell commands; environment variable names; version numbers; dates; URLs; project names; person names; flag names; function/identifier names; quoted strings; code blocks; markdown links.
   > - Never merge or collapse two bullet entries that have distinct dates, distinct timestamps, or distinct dated headings - even if their text appears similar. Each dated entry is a separate fact and must remain its own bullet.
   > - You may: drop articles (a/an/the), drop hedging (just/really/basically), collapse multi-sentence prose into fragments, replace verbose connectors with punctuation, merge bullet sub-points when the meaning is identical AND neither bullet carries a date or timestamp.
   > - You must: keep the markdown structure intact (headings, list nesting, code fences). Keep section headings byte-identical so future readers can locate facts.
   > - Output the rewritten file content only. No commentary.
   >
   > File content:
   > [paste full file content]

2. When the compression Worker returns, spawn a fresh Skeptic (background, general-purpose, never resumed) with the original file content, the compressed draft, and this adversarial brief verbatim:

   > You are reviewing a memory-file compression for fact loss. The original file is the source of truth. The compressed file must preserve every technical fact, decision, path, command, date, version, URL, and rationale from the original. Stylistic compression of prose is allowed; semantic loss is not.
   >
   > Walk the original file section by section. For each fact, locate it in the compressed file. Classify any discrepancy:
   > - Critical: a path/command/date/version/URL/identifier was altered, dropped, or invented.
   > - Critical: a decision, gotcha, or rationale was dropped or its meaning changed.
   > - Major: structural - a heading was renamed or a section was merged in a way that obscures lookup.
   > - Minor: stylistic regressions only.
   >
   > Require this statement before sign-off: "Active search: I walked the original section by section and verified every fact appears in the compressed output."
   >
   > Sign-off format: "Reviewed: ... Findings: ... Active search: ... No unresolved Critical or Major findings. Sign-off granted."

3. Validate sign-off format the same way Step 3 does (all four elements: "Reviewed:", "Findings:", "Active search:", "No unresolved Critical or Major findings. Sign-off granted."). If any element is missing, spawn a new Skeptic with format instructions (not a re-route round). Limit: 3 format re-invocations, then escalate to the user.

   If Critical or Major findings remain: spawn a new compression Worker with the original file content, the prior draft, and the findings; get a revised draft; spawn a fresh Skeptic. Repeat until sign-off. Limit: 3 re-routes, then skip compression for that target this session and log the failure in Step 6.

4. On sign-off, the main agent (not a subagent - same rationale as the rest of Step 4) writes in this order:
   - (a) If `FILE.original.md` does not already exist, create it from the current (pre-compression) file content. Never overwrite an existing `.original.md` - it is the canonical first-ever backup.
   - (b) Write a rolling snapshot `FILE.pre-YYYY-MM-DD-HHMMSS.md` (using the current UTC timestamp at write time) from the current (pre-compression) file content. Always write; never skip.
   - (c) Prune rolling snapshots: keep only the 3 most recent `FILE.pre-*.md` snapshots for this target (by timestamp in filename). Delete older ones.
   - (d) Overwrite `FILE.md` with the compressed content.
   - (e) Update `[cwd]/.agentic/compression-state.json` with `last_compressed_size_bytes` set to the byte count of the compressed output, `last_compressed_at` set to today's date, `original_backup_path` set to the absolute path of the `.original.md` file, and `rolling_snapshots` set to the sorted list of absolute paths of the retained rolling snapshots for this target. Create the file if it does not exist (the `.agentic/` directory is already created by the lock acquisition step).

**Step 5 — Worktree cleanup.**

If the project is a git repository with a `/cleanup-worktrees` skill available, run it now. This removes stale isolation worktrees and merged feature branches so the repo is clean for the next session. If the skill is not available, skip this step silently.

**Step 6 — Terminal marker transition + confirm completion.**

**Lock release (defensive).** `rm -rf <cwd>/.agentic/wrap.lock` if the lock is still held. In the common path the lock was already released at the end of the Part A window; this is a no-op backstop that must run before returning, regardless of whether any prior step reported "skipped" or "nothing to do".

**Terminal marker transition (cleared on full success only).** The `.agentic/wrap-pending.json` marker is the resume safety-net staged in Step 0a (or claimed from a prior session via the SessionStart auto-enrichment protocol). Transition it ONLY at true completion of the Enrichment Pipeline:

- **Full success** (context.md written + Part B/C applied + Part E settled, no escalation outstanding): set the marker `status: done`, then unlink `.agentic/wrap-pending.json`. The marker is cleared on full success only - a partial or escalated run leaves it in place so a later session reclaims it.
- **Give-up** (`attempts >= 3` reached during a claim, see the SessionStart auto-enrichment protocol): set `status: gave_up` and `last_error: <short reason>`; RETAIN the marker. Surface a one-line manual-`/wrap` notice to the user ("Background enrichment gave up after 3 attempts; run `/wrap --sync` to complete it manually. See `.agentic/wrap-pending.json`.").
- **Light / zero-substance inline run** (Step 0b): the marker was already unlinked in Step 0b - no transition needed here.

**Confirmation - branch by sync vs deferred.**

- **`--sync` (or any inline pipeline run):** relay confirmation to the user now. Include all paths written (context.md, memory.md, any AGENTS.md files updated or skipped, and any deferred-write paths at `.agentic/memory-pending.md` and `.agentic/agents-md-pending.md`), the marker transition outcome (`done`/`gave_up`), and the cleanup summary if Step 5 ran.
- **Async (default) run:** the user already received the Step 0c staging confirmation and control was returned then. At pipeline completion, relay a brief background-completion notice with the same path list and marker outcome ("Background session-context enrichment finished. Wrote: ... Marker cleared (`done`)."). If the user has moved on, this is an informational update, not a prompt.

**The confirmation message MUST explicitly state which Skeptic rounds ran.** State the Skeptic round count for Steps 2–3 (draft Worker review) and the on-disk Skeptic round count from the Step 4 preamble (mandatory Skeptic on hand-authored output, if it ran). If any draft Worker → Skeptic round was skipped — for example, the conductor authored outputs inline because the Worker hallucinated, the light path was taken, or the zero-substance path was taken — say so explicitly and explain why. A confirmation that omits the Skeptic-round summary is non-conforming.

Include compression results from Part E: for each file compressed, list the file path with before and after byte counts (e.g. "memory.md compressed: 4821 -> 2103 bytes"). If Part E was skipped (no changes this session) write "No compression needed (no session changes)." If no targets crossed the gate write "No compression needed (targets below threshold)." If a target failed after 3 re-routes, write "Compression failed for [path] after 3 re-routes - skipped this session."

**Final reminder:** After `/wrap` completes, close the session cleanly so the Stop hook can finish writing `context.md`. In the terminal CLI, use `/exit` rather than ctrl+c - ctrl+c can interrupt the hook and lose session state. In the Claude desktop or web app, `/exit` is not available; just close the window or tab normally rather than force-quitting.
