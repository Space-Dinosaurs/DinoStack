# Architect Plan (v4 - FINALIZED): Daemon-Driven Deferred `/wrap`

*Produced by architect, 2026-06-12. Supersedes v3. Closes the round-2 Skeptic findings on v3 (CRITICAL-A live-resume, MAJOR-B sentinel silent no-op, MAJOR-C stuck in_progress, MINOR-D OpenCode coupling, MINOR-E format-extraction). Round-2 confirmed all 11 prior findings genuinely resolved - those are retained unchanged. Brief: `daemon-driven-deferred-wrap.md`. Investigation: `investigation.md`. Test: `headless-test-findings.md`.*

## Approach
Opt-in, Claude-Code-only, per-project Node background daemon that finalizes forgotten session wraps by headlessly resuming each *cleanly-ended* session and running a NEW, fully non-interactive, single-pass command `/wrap-deferred` - NOT the interactive `/wrap` (which the empirical test proved HANGS headlessly on its first human-decision point). `/wrap-deferred` never prompts, runs one model pass, writes context.md / `.agentic/memory.md` / AGENTS.md directly to canonical locations, exits cleanly on any ambiguity. The daemon runs IN THE MAIN PROJECT DIR (no worktree, no copy-back, no merge), acquires `wrap.lock` and AUTO-CLEARS stale locks in code (never prompting), and is bounded by timeout-and-kill.

**The single correctness invariant (hardened in v4): a `pending` marker becomes `ready` ONLY via a genuine `SessionEnd` with a terminal reason.** No SessionStart stale-sweep (v3's MAJOR-2 sweep REMOVED - CRITICAL-A): an idle-open session is indistinguishable from a killed one by heartbeat, so promoting on staleness could resume a live session. Three safe defenses: (1) per-session marker state machine with `ready`-non-stageable (MAJOR-3); (2) loop-guard env var; (3) daemon-startup reclaim of markers a dead *daemon* abandoned in `in_progress` (MAJOR-C) - acts only on daemon-claimed markers, never `pending`.

## Binding constraints
Route content/** + hooks/** via /update-agentic-engineering; DCO -s; regen ALL adapters + commit built-copy deletions; hooks fail-open (exit 0) no added Stop-latency; no nested subagent spawns; daemon Claude-only (wired only in .claude/install.sh); `/wrap` byte-identical off-Claude / toggle-off / under daemon-guard.

## Data model

### Per-session marker (MAJOR-5): `.agentic/wrap-pending-<session_id>.json`, schema_version 3
Fields: `schema_version:3, session_id, staged_at (immutable, FIFO key), status (pending|ready|in_progress|done|gave_up), claimed_by, claimed_kind (session|daemon|null), claimed_at, attempts (0..3), project_root, last_error`. Dropped vs v2: `branch`, `head_sha` (no worktree; enrichment conversation-driven, git-state reflects live tree per committed-only d2). Lib: `markerPath(cwd,sessionId)`, `listReadyMarkers(cwd)` (glob wrap-pending-*.json, status===ready, sort staged_at asc), `listInProgressMarkers(cwd)`.

### State machine - NO SWEEP (CRITICAL-A)
```
absent --stagePending(Stop,every turn)--> pending
       --finalizeReady(SessionEnd,terminal reason)--> ready   [ONLY pending->ready transition]
       --claimMarker(daemon)--> in_progress
       --transitionDone--> done(unlink)
       --reclaimAbandonedInProgress(daemon startup)--> ready   [in_progress->ready; daemon-claimed+dead-PID only; MAJOR-C]
       --fail x3--> gave_up
```
The ONLY `pending->ready` transition is `finalizeReady` in the SessionEnd hook on a terminal reason. No `staleSweep`, no `wrap-stale-sweep.js`. An OPEN, IDLE session leaves a `pending` marker, never daemon-claimable -> the daemon can never resume a live/idle session. Manual `/wrap` Step 0a stages `pending`, claims `claimed_kind:session`, runs sync to `done`.

**MAJOR-3 - `ready` non-stageable.** `stagePending` proceeds ONLY when this session's marker is absent/done/gave_up; pending/ready/in_progress all suppress. `finalizeReady` writes `ready` only from pending/absent (no-downgrade). A late Stop after finalize finds `ready` and no-ops. Correctness boundary = `ready` + per-marker idempotency; daemon acts ONLY on `ready`.

**MAJOR-C - `in_progress` reclaim is daemon-internal, not a sweep.** `reclaimAbandonedInProgress` (daemon startup) resets `in_progress->ready` ONLY for markers with `claimed_kind:daemon` AND dead `claimed_by` PID AND `claimed_at` stale. Never touches `pending`; never promotes a live-session marker -> does not reintroduce CRITICAL-A.

### Loop-guard (KEEP): `AGENTIC_WRAP_DAEMON=1`
Daemon's headless `/wrap-deferred` still fires Stop+SessionEnd (+SessionStart on resume). Daemon exports the env var into the child; these no-op when set: (i) Stop stagePending, (ii) SessionEnd finalizeReady+launch, (iii) SessionStart guarded launch, (iv) `/wrap-deferred`+`/wrap` Step 0a staging. The self-healing sentinel write is intentionally UNGUARDED (harmless true fact). Secondary backstop: `.last-wrap`=session_id. Guard test asserts no-op on: Stop stagePending, SessionEnd finalize+launch, SessionStart launch, Step-0a staging (sweep entry point gone).

### Heartbeat (KEEP - pure wastefulness defense; feeds NO sweep)
`.agentic/.heartbeats/`; Stop touches `.agentic/.heartbeats/<session_id>` (mtime) per turn (local fs, no git/network). Daemon, before claiming a `ready` marker, defers+retries if mtime younger than fresh window (~120s). Missing = safe to claim. In v4 it never feeds a sweep and never gates pending->ready; sole job is to defer on a `ready` marker whose session still emits turns. SessionEnd + transitionDone unlink it.

### Artifacts
- `.agentic/wrap-daemon.pid` - singleton (openSync 'wx' O_EXCL; PID+ISO8601; reclaim ts>30min AND process.kill(pid,0) dead).
- `.agentic/wrap-daemon-auth-failed` - one-time fail-loud notice (claude auth status non-zero); surfaced next SessionStart.
- `.agentic/.claude-host` - **(MAJOR-1 + MAJOR-B) self-healing Claude-only sentinel.** Written by BOTH `.claude/install.sh` (belt) AND the SessionStart hook create-if-absent every start (suspenders) - existing installs get it next Claude session without re-running install.sh.
Unchanged: `.last-wrap`, `.stop-deferred-activity.jsonl`, `wrap.lock`, pinned `# Session Context\n*Written by /wrap` header.

**MAJOR-B self-healing sentinel:** existing installs won't re-run install.sh -> under v3 no sentinel -> Step 0a never stages -> silent no-op for the entire existing user base. v4: SessionStart hook (Claude-only, since only .claude/install.sh wires SessionStart) writes `.agentic/.claude-host` create-if-absent every start, idempotent fail-open. install.sh drop KEPT for fresh installs. Write is NOT guard-suppressed (writing a true fact is harmless; it only gates Step-0a staging, itself guard-suppressed).

## API contracts (binding)

### `hooks/lib/wrap-marker.js` (NEW CommonJS; single source of truth). Atomic, fail-open.
- Paths: `markerPath(cwd,sessionId)`, `lastWrapPath/wrapLockPath/wrapLockOwnerPath/daemonPidPath/authFailedPath/claudeHostPath(cwd)`, `heartbeatPath(cwd,sessionId)`.
- Reads (unguarded): `readMarker`, `listReadyMarkers`, `listInProgressMarkers` (NEW), `liveMarkerForSession`, `readLastWrap`, `wrapLockHeld`, `wrapLockStale(cwd,staleMs)`, `heartbeatFresh`, `isClaudeHost`.
- Sentinel write (NEW MAJOR-B, UNGUARDED fail-open): `ensureClaudeHost(cwd)` - create-if-absent (openSync 'wx'; swallow EEXIST + all fs errors). Idempotent. Called by SessionStart hook + install.sh.
- Loop-guard: `daemonGuardActive()` -> `process.env.AGENTIC_WRAP_DAEMON==='1'`.
- Transitions (NO-OP under guard): `writeMarker`, `stagePending` (suppress ready/pending/in_progress + .last-wrap + substantive), `finalizeReady(cwd,sessionId)` (**pending|absent->ready ONLY; sole pending->ready; no-op otherwise; no branch/sha**), `claimMarker(cwd,sessionId,owner,kind,staleMs)->marker|null`, `transitionDone`, `transitionGaveUp`.
- Reclaim (NEW MAJOR-C, daemon-internal): `reclaimAbandonedInProgress(cwd, staleMs) -> {reclaimed:[], gaveUp:[]}`. Scans `listInProgressMarkers`. Reset to `ready` IFF `claimed_kind==='daemon'` AND `claimed_at` older than staleMs AND `claimed_by` PID dead (`process.kill(pid,0)` ESRCH=dead; EPERM=alive->skip). If `attempts>=3` -> `transitionGaveUp` (last_error:"reclaimed-after-max-attempts"). NEVER touches non-daemon-claimed, non-in_progress, or `pending` markers. Idempotent re-wrap safe (context.md dedup-merge). Fail-open per marker.
- Lock: `acquireWrapLock(cwd,owner,staleMs)` (mkdir O_EXCL; on fail if `wrapLockStale(cwd,30*60*1000)` -> rm -rf + retry once; else false; NEVER prompts), `releaseWrapLock` (rm -rf idempotent).
- Heartbeat: `touchHeartbeat` (no-op under guard), `removeHeartbeat`.

**Cross-language (MAJOR-5 + MINOR-D):** lib canonical; stop-context.js requires it. The marker's ONLY consumer is now the Claude daemon (in-session enrichment consumer removed); daemon is Claude-only -> on OpenCode the marker has no reader. **`.opencode/plugins/session-context.ts` REMOVES marker-staging** (reverts #184 marker-staging on OpenCode; keeps context.md/spillover mirroring). No cross-language per-session contract on OpenCode; no "OpenCode markers rely on a Claude sweep" dead path.

### `content/commands/wrap-deferred.md` (NEW - non-interactive single-pass enrichment)
Never prompts. One pass. No subagents (no draft-Worker/Skeptic/compression/`/cleanup-worktrees`/`gh pr`). On ambiguity: write what it safely can, exit clean, NEVER ask. Inputs: resumed transcript + live state. Outputs (direct, canonical, main dir): (1) `.agentic/context.md` via shared Part A merge (only write touching wrap.lock, narrow Part-A); (2) `.agentic/memory.md` via shared Part B append-dedup; (3) AGENTS.md via shared Part C. Omitted: Part E compression, Skeptic, /cleanup-worktrees, Open-PR deferral, scaffold-migration pre-flight, drift-requires-input (drift -> a context.md "Watch Out For" bullet). Lock: `acquireWrapLock` around Part-A; `releaseWrapLock` every exit; can't acquire -> spill + exit clean. Marker `done` owned by daemon, not the command. Cites `content/references/wrap-context-format.md`.

**Shared-formatting (MINOR-E):** NEW `content/references/wrap-context-format.md` = normative home of pinned header prefix, Part A rolling-label merge (wrap.md:430-455), `.last-wrap` contract, spillover-drain 3-step rename. Both `/wrap` Part A and `/wrap-deferred` CITE it. Behavior-preserving extraction verified by a golden-file test (interactive `/wrap` Part A output byte-identical pre/post extraction, 5-label fixture). Reference declares consumers in its opening note.

### `hooks/wrap-daemon.js` (`node hooks/wrap-daemon.js <project_root>`)
Startup: (1) traversal guard; (2) exit0 if `daemonGuardActive()`; (3) singleton O_EXCL (reclaim stale PID file); (4) **`reclaimAbandonedInProgress(cwd,staleMs)` - MAJOR-C - reset daemon-abandoned in_progress (dead PID) to ready / gave_up; log;** (5) auth pre-flight `claude auth status` (non-zero -> write authFailedPath, no attempts++, exit). FIFO over `listReadyMarkers` (staged_at asc): (1) heartbeatFresh -> defer+continue; (2) claimMarker(...,'daemon',...) -> null skips; (3) main dir; (4) spawn `claude --resume <id> -p "/wrap-deferred" --permission-mode bypassPermissions --allowedTools "Read,Edit,Write,Glob,Grep,Bash(git *)" --max-turns <N>` with `AGENTIC_WRAP_DAEMON=1` child env, cwd=project root, timeout-and-kill (default 10min) -> on timeout kill child+group, attempts+++last_error:timeout; optional stream-json watch; no `--bare`; (5) exit0 -> transitionDone; (6) non-zero/timeout -> attempts++; >=3 -> transitionGaveUp. NO worktree/copy-back/merge. Idle self-exit ~15min. Crash recovery: daemon dies between child-exit-0 and transitionDone -> marker stranded in_progress -> NEXT startup's reclaim resets it (MAJOR-C).

### `hooks/session-end-wrap.js` (SessionEnd)
stdin `{session_id,transcript_path,cwd,hook_event_name:"SessionEnd",reason}`. exit0 if guard. finalize to `ready` on terminal reasons {clear,logout,prompt_input_exit,bypass_permissions_disabled,other}; `reason:"resume"` -> NO finalize (no sweep -> stays `pending` permanently, NOT auto-wrapped, manual `/wrap` recovers - Known Limitations). `finalizeReady(cwd,session_id)` (sole pending->ready); `removeHeartbeat`; launch daemon detached (toggle true). exit0 always.

### `hooks/session-start-wrap.sh` (SessionStart)
(v3 `wrap-stale-sweep.js` DELETED - CRITICAL-A; no sweep step.) (a) version-check notice; (b) surface auth-failed; (c) **self-heal sentinel: `ensureClaudeHost(cwd)` create-if-absent, idempotent fail-open, UNCONDITIONAL (not guard-suppressed) - MAJOR-B**; (d) launch daemon detached (toggle true), guarded `[ "$AGENTIC_WRAP_DAEMON" = "1" ]` -> skip.

### `/wrap` Step 0a guard (MAJOR-1 - NO CLAUDECODE)
`if [ -f "$cwd/.agentic/.claude-host" ] && [ "$AGENTIC_WRAP_DAEMON" != "1" ] && <deferred_wrap_daemon toggle true>; then <stage per-session pending marker>; fi`. Sentinel now reliably present on every Claude host (install drop + SessionStart self-heal - MAJOR-B). Off-Claude (no SessionStart ever runs -> no sentinel)/toggle-off/under-guard -> stage nothing, `/wrap` byte-identical.

## Unit DAG
v3->v4: `wrap-stale-sweep.js` GONE (CRITICAL-A); no sweep step; SessionStart self-heals sentinel (MAJOR-B); daemon startup reclaim (MAJOR-C); OpenCode change is now a REMOVAL (MINOR-D); golden format test added (MINOR-E).

- **U1** marker lib + per-session schema v3 + wrap.md NORMATIVE schema. NEW `hooks/lib/wrap-marker.js` (incl. `reclaimAbandonedInProgress`, `listInProgressMarkers`, `ensureClaudeHost`; `finalizeReady` sole pending->ready); MODIFY stop-context.js (helpers->lib+require; per-turn touchHeartbeat; suppression ready/pending/in_progress MAJOR-3; per-session staging); MODIFY wrap.md:102-118 schema; UPDATE stop-context.js manifest (count+heartbeat; remove liveMarkerExists). Elevated. Deps: none. Manifest REQUIRED on lib.
- **U-WDEF** NEW `content/commands/wrap-deferred.md` + NEW `content/references/wrap-context-format.md` (extract; declare consumers); MODIFY wrap.md Part A to CITE ref (golden test proves byte-identity). Elevated. Deps: U1 (soft).
- **U2** NEW `hooks/session-end-wrap.js` (finalize terminal reason; resume no-finalize; NO sweep). `wrap-stale-sweep.js` NOT created. Elevated. Deps: U1. Manifest REQUIRED.
- **U3** NEW `hooks/wrap-daemon.js` (main-dir; **startup reclaimAbandonedInProgress MAJOR-C**; **startup bounded `pending`-marker janitor: DELETE (never promote) `pending` markers older than `deferred_wrap_pending_ttl_days` (default 7) - MINOR-1; delete-only so it cannot reintroduce CRITICAL-A**; auth pre-flight; FIFO; heartbeat defer; acquireWrapLock auto-stale-clear; spawn `/wrap-deferred` + timeout-kill; transitionDone/GaveUp). Elevated (highest blast radius). Deps: U1, U-WDEF. Manifest REQUIRED. (Janitor adds lib API `cleanStalePending(cwd, ttlMs)` - delete-only, never status-mutate.)
- **U4** MODIFY `.claude/install.sh` (+SessionEnd, +SessionStart, KEEP .claude-host drop - belt MAJOR-B); NEW `hooks/session-start-wrap.sh` (notice + auth-failed + **self-heal ensureClaudeHost MAJOR-B** + guarded launch; NO sweep); MODIFY session-start-version-check.sh:12-13 docstring. Elevated. Deps: U2, U3. Manifest REQUIRED on the new shell hook.
- **U5** MODIFY wrap.md: remove async (:11-31, :146-159, :163, :585/:579); flip :136 sync-default; gate Step 0a on .claude-host sentinel. Elevated. Deps: U1.
- **U6** DELETE `content/agents/wrap-enrichment.md`; MODIFY agent-team.md (remove row); rewrite conductor-operating-rules.md:67-73 + manifest:1-41; verify 02-delegation.md:142-144. UPDATE conductor-operating-rules.md manifest. Elevated. Deps: U5.
- **U7** tests: EXTEND test-stop-context-deferred-wrap.js; NEW test-session-end-wrap.js, test-wrap-daemon.js, NEW test-wrap-marker-reclaim.js (MAJOR-C), NEW test-wrap-context-format-golden.js (MINOR-E). NO test-wrap-stale-sweep.js (gone). Elevated. Deps: U1,U2,U3,U-WDEF.
- **U8** config + doc-sync: MODIFY templates/.agentic/config.json (+deferred_wrap_daemon:false, +idle_minutes:15, +heartbeat_seconds:120, +timeout_minutes:10, **+inprogress_reclaim_minutes:30** [replaces stale_sweep_minutes], **+deferred_wrap_pending_ttl_days:7** [MINOR-1 janitor]; FIX drift +commit_telemetry/+storybook_version/+storybook_url); conventions.md §Project Config (count+keys); **04-risk-classification.md:71-83 (MAJOR-4)**; METHODOLOGY list; init-project §6f; /agentic-status print. Elevated. Deps: none.
- **U9** MODIFY `.opencode/plugins/session-context.ts` (**REMOVE marker-staging; MINOR-D**); run each adapter build.sh; commit deletions of `.codex/.gemini/.opencode` wrap-enrichment copies; regenerate built wrap.md/NEW wrap-deferred.md/NEW wrap-context-format.md/agent-team.md/conductor-operating-rules.md/04-risk-classification.md/config across 7 adapters; verify built 04-risk count (MAJOR-4); **verify NO built wrap-stale-sweep.js anywhere (CRITICAL-A)**. Elevated. Deps: U-WDEF,U5,U6,U8 (orchestration-planner correction: U9 regenerates built wrap-deferred.md/wrap-context-format.md from U-WDEF).

Manifest reminders: U1 updates stop-context.js manifest; U6 updates conductor-operating-rules.md manifest; NEW source files (wrap-marker.js, session-end-wrap.js, wrap-daemon.js, session-start-wrap.sh) require manifest headers.

## Per-consumer impact table
| consumer_file:line | passes_arg? | compensating? | current | new |
|---|---|---|---|---|
| stop-context.js:788-827 stageWrapPending | yes | yes (lib+guard) | inline single-file v1 | lib; per-session v3 pending; ready/pending/in_progress suppress (MAJOR-3); no-op under guard; touch heartbeat/turn |
| stop-context.js:671-735 helpers | n/a | yes (moved) | local helpers | re-exported; liveMarkerForSession replaces liveMarkerExists |
| stop-context.js:22-25,49 manifest | n/a | n/a | "Nine write paths"; liveMarkerExists | UPDATED count(+heartbeat); liveMarkerExists removed (Minor-1) |
| hooks/session-end-wrap.js (NEW) | yes | yes (lib+guard) | n/a | finalize terminal reason ONLY (sole pending->ready); resume no-finalize; no sweep |
| hooks/wrap-daemon.js (NEW) | yes | yes (lib+guard) | n/a | startup reclaim (MAJOR-C); FIFO listReadyMarkers; claim/done/gaveUp |
| hooks/session-start-wrap.sh (NEW) | yes | yes (fail-open) | n/a | self-heal sentinel (MAJOR-B, unguarded); guarded launch; NO sweep (CRITICAL-A) |
| .opencode/plugins/session-context.ts:496-569 | n/a | n/a (REMOVED) | single-file v1 marker-staging (#184) | marker-staging REMOVED (MINOR-D); pre-#184; keeps context/spillover mirror |
| wrap.md:102-118 schema | n/a | n/a | single-file v1 | per-session v3; branch/head_sha dropped |
| wrap.md:134-159,585 | n/a | yes (sentinel guard) | async-default | sync-default; Step 0a gated on .claude-host (reliable, MAJOR-B) |
| wrap.md:416-455 Part A | n/a | yes (cite ref + golden) | inlines merge algo | cites wrap-context-format.md; byte-unchanged (MINOR-E) |
| content/agents/wrap-enrichment.md | n/a | n/a | draft-formatter agent | DELETED |
| agent-team.md roster row | n/a | n/a | wrap-enrichment row | removed |
| conductor-operating-rules.md:67-73 + manifest:1-41 | n/a | n/a | drainer=in-session/next conductor | rewritten: drainer=daemon /wrap-deferred; manifest re-pointed |
| 04-risk-classification.md:71-83 | n/a | n/a | "eleven" + 11 list | bumped count + new toggle (MAJOR-4) |
| 02-delegation.md:5 | n/a | n/a | enforce-background-spawn | verify-only UNAFFECTED (Minor-3) |
| templates/.agentic/config.json | n/a | n/a | 9 keys, drift | +5 daemon (incl inprogress_reclaim_minutes; stale_sweep_minutes GONE) +3 drift-fix |
| .codex/.gemini/.opencode wrap-enrichment copies | n/a | n/a | adapter copies | regen->deleted; commit deletions |
| built wrap.md/wrap-deferred.md/wrap-context-format.md/agent-team/conductor-rules/04-risk x7 | n/a | n/a | async/old roster/old count | regenerated; verify NO wrap-stale-sweep.js (CRITICAL-A) |

## Risk + rollback seeds
- **U1 (marker lib, highest structural):** regression breaks Stop every turn. Mitigation: fail-open; extend #184 suite before merge; guard no-ops pure. Rollback: revert U1 (self-contained); v1->v3 harmless.
- **U3 (daemon, highest behavioral):** hung headless wedges; auth silent-drop; resume a live session. Mitigation: timeout-and-kill; auth pre-flight+fail-loud; ready-only + no-sweep (CRITICAL-A) + reclaim-never-touches-pending (MAJOR-C) + heartbeat defer. Rollback: opt-in default false - toggle off stops all spawns; revert U3+U4 removes daemon path, sync `/wrap` untouched.
- **U5 (wrap.md):** malformed sentinel guard. Mitigation: reliable self-healing sentinel; explicit off-Claude/toggle-off byte-identical test. Rollback: revert restores async-default; FEATURE rollback is the toggle.

## Round-2 finding -> resolution map
- **CRITICAL-A (live-resume via stale-sweep): RESOLVED by DROPPING the sweep.** wrap-stale-sweep.js + SessionStart sweep step DELETED; sole pending->ready is SessionEnd finalizeReady on a terminal reason; idle-open session's `pending` marker is never daemon-claimable. Trade documented: kill-without-SessionEnd / reason:resume sessions are NOT auto-wrapped (manual /wrap recovers).
- **MAJOR-B (sentinel silent no-op for existing installs): RESOLVED by self-healing sentinel.** SessionStart hook writes `.claude-host` create-if-absent every start; install.sh drop kept (belt). Unguarded write (harmless true fact).
- **MAJOR-C (stuck in_progress after daemon crash): RESOLVED by daemon-startup reclaim.** `reclaimAbandonedInProgress` resets daemon-claimed dead-PID stale in_progress to ready (or gave_up at attempts>=3); never touches pending; new config key inprogress_reclaim_minutes; new test.
- **MINOR-D (OpenCode coupling): RESOLVED by removing OpenCode's consumerless marker-staging** (reverts #184 on OpenCode; keeps context/spillover mirror).
- **MINOR-E (format-extraction): RESOLVED by golden-file byte-identity test** for `/wrap` Part A across the extraction.

## QA criteria
```yaml
qa_criteria:
  qa_skip: pure-backend-library
  qa_skip_rationale: >-
    No browser UI. Node daemon + Claude Code hooks + methodology markdown; verified
    by hooks/tests, G-AUTH real-run, G-E2E manual.
  viewport: [desktop]
  scenarios: []
  manual_smoke: >-
    G-E2E: S1 edit + clean exit -> SessionEnd finalizes per-session ready -> daemon
    resumes S1 headlessly in MAIN dir + runs non-interactive /wrap-deferred (auto-clears
    stale wrap.lock, no prompt) -> 3 docs written in place -> marker cleared; S2 responsive;
    late Stop after finalize does NOT regress ready->pending (MAJOR-3); daemon killed mid-wrap
    -> next startup reclaims in_progress to ready and re-wraps (MAJOR-C); existing install (no
    install.sh re-run) -> first SessionStart self-heals .claude-host + feature activates (MAJOR-B);
    OpenCode stages NO marker (MINOR-D); kill-without-SessionEnd / reason:resume NOT auto-wrapped
    (manual /wrap recovery, CRITICAL-A limitation); manual /wrap blocks to completion; toggle-off
    + non-Claude -> no marker.
```

## Verification gates
- **G-AUTH (real-run):** detached no-TTY `claude --resume <id> -p "/wrap-deferred"` inherits authed creds without prompting (defensive either way; operator -p test corroborates).
- **G-HEADLESS: SATISFIED** by the operator test + non-interactive redesign.
- **G-CLAUDECODE (non-blocking):** confirm CLAUDECODE in a `/wrap` bash on Claude / absent off-Claude; v4 ships on the sentinel regardless.
- **G-SELFHEAL (MAJOR-B):** existing install, no prior install.sh re-run, no pre-existing sentinel -> first Claude SessionStart creates it; sentinel NOT created off-Claude.
- **G-NOSWEEP (CRITICAL-A):** wrap-stale-sweep.js does not exist; SessionStart makes no sweep call; a `pending` marker for an idle-open/resume-ended session never reaches `ready` without a terminal SessionEnd (cross-checked across 7 built adapters).
- **G-E2E (two-session+daemon+crash, manual):** full smoke incl. MAJOR-C crash-then-reclaim + MAJOR-B existing-install self-heal.
- **Unit tests:** (1) finalize writes ready (no branch/sha); (2) reason:resume no-finalize, stays pending (no promotion); (3) a stale `pending` is NEVER auto-promoted to ready by any path (CRITICAL-A); (4) Stop refresh + .last-wrap suppression; (5) late Stop after finalize no regress (MAJOR-3); (6) liveMarkerForSession; (7) daemon singleton; (8) idle self-exit; (9) FIFO by staged_at; (10) acquireWrapLock auto-clears stale / defers on fresh; (11) toggle OFF -> no launch; (12) non-Claude -> no marker; (13) loop-guard no-ops all entry points; (14) heartbeat defer/claim; (15) auth pre-flight -> authFailed + no attempt; (16) timeout-kill -> attempts+timeout; (17) `/wrap-deferred` never emits a prompt; (18) per-session marker isolation; (19) reclaimAbandonedInProgress resets daemon-claimed dead-PID stale to ready, does NOT touch session-claimed / live-PID / fresh / pending, gave_up at attempts>=3 (MAJOR-C); (20) self-healing sentinel creates when absent, no-ops present, fail-open, not guard-suppressed (MAJOR-B); (21) golden-file Part A byte-identity (MINOR-E).
- **Build/lint:** all adapter builds; lint; 3 tracked wrap-enrichment copies deleted; no orphaned async sections; no built wrap-stale-sweep.js (CRITICAL-A); 04-risk count correct (MAJOR-4); OpenCode stages no marker (MINOR-D).

## Known limitations
- **CRITICAL-A trade (Brief reconciliation):** a session killed without SessionEnd, or ended via `reason:resume`, leaves its marker permanently `pending` and is NOT auto-wrapped - manual `/wrap` recovers. Narrows Brief success #2 ("killed and detected via marker staleness... wrapped automatically") to "a cleanly-ended session is auto-wrapped; an abnormally-terminated one needs manual `/wrap`." Brief's "staleness/reclaim recovers a session killed without SessionEnd" narrows to "reclaim recovers a dead daemon's abandoned in_progress marker (MAJOR-C), not a killed live session's pending marker." Deliberate documented trade vs a live-resume Critical.
- G-AUTH detached keychain still empirical (defensive; -p test corroborates).
- `/wrap-deferred` single-pass (no Skeptic/compression); manual `/wrap` full-fidelity (Brief amendment).
- Compacted sessions wrap on compacted transcript; committed-only (git-state = live tree at enrichment).
- OpenCode stages NO marker (MINOR-D); pre-#184 behavior; no Claude-sweep dead path.
- MAJOR-C re-wrap idempotency relies on context.md dedup-merge (covered by golden + FIFO + reclaim tests).

## Open Questions
None.
