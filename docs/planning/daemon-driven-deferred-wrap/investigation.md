# Investigation: PR #184 surface for daemon-driven `/wrap` evolution

*Produced by investigator, 2026-06-12. Input to the Architect. Read-only map of the current implementation; reference-dense by design.*

## Summary

PR #184 is implemented across four load-bearing surfaces: (1) the Node Stop hook `hooks/stop-context.js` (marker staging + lock-aware spillover + suppression), (2) `content/commands/wrap.md` (async-by-default dispatch + deferred-enrichment data model + SessionStart auto-enrichment conductor protocol), (3) `content/agents/wrap-enrichment.md` (draft-formatter agent), (4) `.opencode/plugins/session-context.ts` (OpenCode mirror). **There is no SessionEnd hook today, and SessionStart is NOT wired by any install script** - the single largest structural gap. The in-session async enrichment to REMOVE lives in `wrap.md` Step 0c + the SessionStart protocol + the `wrap-enrichment` agent; the synchronous pipeline to PRESERVE is the `--sync`/"Enrichment Pipeline" body. The marker (`stageWrapPending`, stop-context.js:806-816) is missing `branch`, `head_sha`, a `ready` status, and a daemon-distinct claim field.

## Item 1 - hooks/stop-context.js deferred-wrap functions (signatures verbatim)

- `wrapLockHeld(cwd)` - :671-674. `fs.existsSync(path.join(cwd,'.agentic','wrap.lock'))`; lock is a DIRECTORY (atomic mkdir); fail-open false on error.
- `appendSpilloverRecord(cwd, record)` - :685-694. Appends one JSONL line to `.agentic/.stop-deferred-activity.jsonl`. Record shape (:1001-1009): `{schema_version:1, ts, session_id, recent_focus[], paths_referenced[], uncommitted[], tools_used[]}`.
- `writeContextMdOrSpill(cwd, outputPath, projectDir, body, spilloverRecord)` - :752-769. Lock-aware context.md write; if locked -> spill; else mkdir then RE-CHECK `wrapLockHeld` immediately before `writeFileSync` (TOCTOU mitigation); spill if now locked. Called at :1067 (wrap-coexistence) and :1136 (normal).
- `readLastWrap(cwd)` - :704-713. Reads single-line `.agentic/.last-wrap`, returns trimmed session_id or null.
- `liveMarkerExists(cwd)` - :725-735. True only when marker `status === 'pending' || 'in_progress'`.
- `stageWrapPending(cwd, sessionId, scan)` - :788-827. Atomic tmp+rename. Suppression (all must pass): `readLastWrap !== sessionId` (:795), `!liveMarkerExists` (:798), substantive activity `uncommittedCount>=1 || pathsReferencedCount>=1 || recentFocusCount>=1` (:801-804) + traversal guard. **Fields written (:806-816):** `schema_version:1, session_id, staged_at, status:'pending', claimed_by:null, claimed_at:null, attempts:0, project_root:cwd, last_error:null`.
- Identity-nudge `appendIdentityNudgeToContextMd(repoRoot)` (:404-418) is a context.md writer -> deferred while locked; gated at :1108/:1184 by `!identity && !wrapLockHeld(cwd)`; sentinel `~/.agentic/.identity-nudged` consumed atomically so deferral re-fires rather than loses.
- Manifest declares **nine** write paths (path 9 = spillover). Per-turn flow: `run()` at :829/:1213 - parse stdin -> extract cwd/session_id/transcript (:849-856) -> scans -> build spillover record/scan -> coexistence path (:1041-1067) or normal `writeContextMdOrSpill` (:1136) -> writeLoopState/writeBatchState/writeSessionTotal/identity gate/removeLearningsAgentSession/`stageWrapPending` (:1208) -> exit 0.

## Item 2 - Marker schema (implemented vs Brief-required)

- Produced today: `schema_version, session_id, staged_at, status, claimed_by, claimed_at, attempts, project_root, last_error`. Status enum `pending|in_progress|done|gave_up` (wrap.md:108,116). NORMATIVE schema = wrap.md:102-118.
- **MISSING vs Brief:** `branch` and `head_sha` (daemon builds worktree from recorded commit - without `head_sha` it cannot). `ready` status value absent (SessionEnd "finalize" implies `pending -> ready` transition not currently written). Claim fields are session-claim semantics; daemon needs daemon-owner/claim distinction (e.g. `claimed_by` = daemon PID/instance) so a daemon claim is not confused with a session claim. **Net additions:** `branch`, `head_sha`, `ready` status (+ the SessionEnd finalize transition), daemon-vs-session claim ownership.

## Item 3 - session-start-version-check.sh + detached-spawn precedent

- The marker NOTICE is NOT in this script; it only handles version-update. SessionStart backlog-drain + marker notice today is **conductor protocol** (wrap.md:11-31), not a hook. Script drains stdin (`cat >/dev/null`, :24), calls `hooks/lib/version-check-core.sh`, emits `{systemMessage, suppressOutput:true}`; does NOT capture cwd.
- **Detached-spawn precedent (the daemon must follow): `hooks/lib/version-check-core.sh:87-104` (`maybe_refresh()`):**
```
  nohup bash -c '
    repo="$1"; cache="$2"
    git -C "$repo" fetch --quiet origin >/dev/null 2>&1 || exit 0
    ...
  ' _ "$ae_repo_dir" "$CACHE_FILE" </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
```
Pattern: `nohup bash -c '...' _ <args> </dev/null >/dev/null 2>&1 &` then `disown`. Comment (:87-88): "All three standard fds are redirected so the parent never waits on an inherited pipe." TTL-throttle (:60-85) is the "launch only when needed" precedent.

## Item 4 - wrap.md async structure (REMOVE vs PRESERVE)

- Step 0a (:134-144) stages the marker before Step 0 (default + --sync). Step 0b (:146-151) routes (zero/light inline; standard async). Step 0c (:153-159) in-session async dispatch fork: Default dispatches Enrichment Pipeline `run_in_background:true` + returns (:155); `--sync` inline blocking (:157); same-session coalesce (:159).
- "Enrichment Pipeline" (:161-180): draft Worker (Step 1) -> Skeptic (2-3) -> Part A/B/C (4) -> Part E compression -> Step 6. Narrow Part-A-only lock (:165).
- Part A (:416-455 context.md merge under lock), Part B (:457-467 memory.md), Part C (:469-493 AGENTS.md), Part E (:495-566 compression), Step 6 (:572-589 terminal marker transition: done+unlink on success; gave_up on attempts>=3).
- **REMOVE:** (i) SessionStart auto-enrichment section (:11-31, spawns in-session pipeline at :25); (ii) Step 0b standard-async routing (:146-151) + Step 0c Default-async branch/dispatch/confirmation (:153-156); (iii) same-session coalesce (:159); (iv) `run_in_background:true` preamble directive (:163); (v) Step 6 async-run confirmation (:585) + give-up-assumes-background (:579); flip async-default framing (:136) to sync.
- **PRESERVE (make manual default):** entire --sync pipeline (Step 0 :181-212, Step 0.5 :214-250, Steps 1-4 :252-493, Part E :495-566, Step 5 :568-570, Step 6 sync branch :584), pre-flight lock acquire (:74-95), lock-release-on-every-exit (:87-94). RETAIN+repurpose the Deferred-enrichment data model (:98-130) and Step 0a staging (:134-144) - consumer is now the daemon.
- **Marker-staging guard (Brief :33):** Step 0a stages unconditionally today. Gate behind `(adapter==Claude) AND deferred_wrap_daemon==true`; else run exactly as today (sync, no marker, no daemon). Guard at top of Step 0a (:134).

## Item 5 - wrap-enrichment.md (REMOVE)

Role (:63-83): the conversation-independent draft half; returns three JSON drafts; writes/spawns nothing. Spawned by SessionStart auto-enrichment + async `/wrap` (both removed). Since the daemon resumes the real session and runs the FULL `/wrap` (its own Step 1 draft Worker), the separate bundle-formatter is obsoleted. DELETE (Brief :14).

## Item 6 - Per-consumer impact table

| File | References | Change |
|---|---|---|
| `content/agents/wrap-enrichment.md` | The agent itself | DELETE (canonical source). |
| `content/references/agent-team.md:18` | Roster row | Remove row. |
| `content/commands/wrap.md:11-31` | SessionStart auto-enrichment protocol | Remove section; replace w/ daemon pointer (SessionStart launches daemon, not in-session pipeline). |
| `content/commands/wrap.md:146-159` | Step 0b/0c async dispatch+coalesce | Synchronous-default; remove async dispatch; retain gated Step 0a. |
| `content/commands/wrap.md:161-180,585` | Enrichment Pipeline run_in_background + async confirmation | Strip async; pipeline = synchronous manual `/wrap`. |
| `content/references/conductor-operating-rules.md:71-73` | §deferred-wrap carve-out (drainer="deferred-wrap enrichment"; "SessionStart enrichment protocol") | Rewrite: drainer = daemon's headless `/wrap`; consumer "next session's conductor" -> "the daemon". Update manifest (:5,:18-22,:34-38). |
| `content/references/conductor-operating-rules.md` manifest (:1-40) | Names SessionStart enrichment protocol | Re-point to daemon protocol. |
| `content/sections/02-delegation.md:142-144` | wrap-ticket/learnings pointers (NOT wrap-enrichment) | Low; verify no stale pointer. |
| `.codex/agents/wrap-enrichment.toml`, `.gemini/agents/wrap-enrichment.md`, `.opencode/agents/wrap-enrichment.md` (git-tracked) | Adapter copies | Regenerate via each build.sh (files disappear); commit deletions. |
| `.claude/agents/wrap-enrichment.md` (untracked) | Adapter copy | Disappears on rebuild; no git action. |
| `.cursor/.codex/.gemini` built copies of agent-team.md | Roster row copies | Regenerate. |
| `.claude/.codex/.cursor/.gemini/.opencode/.kimi` built copies of wrap.md | Async sections | Regenerate after source rewrite. |
| `.opencode/plugins/session-context.ts:422-536+` | OpenCode marker/spillover mirror | RETAIN as-is (Claude-only daemon; OpenCode gains NO daemon awareness; confirm no regression). |
| `docs/planning/deferred-background-wrap*` | #184 planning artifacts | Historical; no edit. |

## Item 7 - SessionEnd hook + wiring

- **No SessionEnd hook exists today.** All `SessionEnd` matches are Gemini-adapter (`.gemini/hooks/stop-context-gemini.js:4`, ADAPTERS.md:23) or docs. Claude context-save uses the **Stop** hook.
- **Wiring:** `.claude/install.sh:295-479` writes `~/.claude/settings.json` hooks via embedded Python: `UserPromptSubmit` (:319-364), `Stop -> node {repo}/hooks/stop-context.js` (:367-407, idempotent find-or-create matcher `*`), `PreToolUse` matchers `Task` (:412-440) and `AskUserQuestion` (:443-471). Project `.claude/settings.json` is EMPTY; `.claude/settings.local.json` holds no hooks. **SessionStart is NOT wired by install.sh.**
- **New hooks must register** following the Stop-block pattern (:367-407): add `SessionEnd` key (find-or-create matcher `*`), command `node {repo}/hooks/<hook>.js`, `timeout:5`. **A `SessionStart` block must also be added** (currently absent) for both the version-check notice AND the backlog-drain daemon launch. Hooks live in `hooks/` at repo root (adapter-agnostic; ADAPTERS.md:40). Stdin fields: `payload.cwd`, `payload.session_id`, `payload.transcript` (stop-context.js:849-856).

## Item 8 - .agentic/config.json toggles

- Read by conductor before classifying/spawning; absent file -> defaults. Documented in conventions.md:87-141 (§Project Config, "Eleven toggles"), METHODOLOGY §Risk Classification, init-project.md:829-877 (§6f), seed `content/templates/.agentic/config.json`.
- **Add `deferred_wrap_daemon` (default false) following `debugger_on_failure`:** (1) add key+default to seed template; (2) document in conventions.md §Project Config (bump count) + METHODOLOGY list; (3) add to init-project §6f seed (init-project.md:838-864) + `/agentic-status` print (:1146-1147). init-project seeds config.json (only-if-absent, never overwrite). **Template drift (pre-existing):** seed missing `commit_telemetry`, `storybook_version`, `storybook_url` that conventions.md documents - mirror or fix when adding.

## Item 9 - Adapter build

- Adapters: `.claude .codex .cursor .gemini .opencode .pi .kimi`.
- Propagation: all trace to `content/`. `.claude/build.sh:54` loops content/commands; agents are copies. `.codex/build.sh:175-335` generates TOML agents (:200) + hardlinks commands. `.opencode/build.sh:21` loops content/agents. `.gemini` md agents + toml commands. `.cursor` .mdc from rules+commands.
- **Daemon under `hooks/` is adapter-agnostic by construction** (ADAPTERS.md:40), but WIRING is per-adapter: only `.claude/install.sh` (settings.json) and `.kimi/install.sh` (config.toml `[[hooks]]`) register Claude-style hooks; `.opencode` uses session-context.ts plugin; others have own configs. **Daemon is Claude-only (Brief d9):** launched only by Claude SessionEnd/SessionStart hooks (wired only in `.claude/install.sh`), gated by `deferred_wrap_daemon`. Other adapters' builds do not loop `hooks/*.js`, so adding `hooks/<daemon>.js` + `hooks/<sessionend>.js` touches ONLY `.claude/install.sh`. The `wrap.md` core rebuilds into every adapter -> marker-staging guard MUST suppress on non-Claude.

## Item 10 - hooks/tests/ harness

- Runner: `node hooks/tests/<file>.js` (no framework). Custom `assert(cond,msg)` with counters + `process.exit(1)` on failure.
- Fake-HOME isolation: `runHook(projectDir, fakeHome, sessionId, transcript)` execs via `execSync(node ${hookScript}, {input:payload, env:{...process.env, HOME:fakeHome}, stdio:['pipe','pipe','ignore']})`. `makeTmp(prefix)` builds isolated `tmpDir/{home,project,project/.agentic,home/.agentic}`; `cleanup` rmSync.
- Fixtures inline (`EDIT_TRANSCRIPT` substantive; `READONLY_TRANSCRIPT` not). `makeWrapLock` creates lock DIR. Tmp project intentionally NOT a git repo. Existing #184 test: `hooks/tests/test-stop-context-deferred-wrap.js` (323 lines); sibling `test-stop-context-session-log.js`. Daemon/SessionEnd tests reuse this pattern: crafted payload + fake HOME, assert on-disk marker state + process side effects.

## Item 11 - wrap.lock discipline (daemon inherits)

- Acquire (wrap.md:74-85): `mkdir -p .agentic` then `mkdir .agentic/wrap.lock` (atomic). Write `.agentic/wrap.lock/owner` = two lines PID then ISO8601 UTC (`date -u +%Y-%m-%dT%H:%M:%SZ`). wrap-ticket.md:95-98 exact acquire.
- Contention (wrap.md:79-83): owner unreadable -> stale, abort w/ notice. timestamp >30min -> potentially-stale, do NOT auto-remove, tell user `rm -rf`, abort. <30min live -> wait loop poll 5s, retry mkdir, 20-min cap. No `ps -p` liveness (PID reuse; timestamp authoritative). wrap-ticket skips w/ `skipped_reason:"wrap-lock-contention"`.
- Release (wrap.md:87-94): `rm -rf .agentic/wrap.lock` mandatory on every exit. `/wrap` holds only around narrow Part-A window (released right after `.last-wrap`), Step-6 defensive release backstop.
- 30-min staleness recovers crashed `/wrap`; daemon inherits (Brief :30 also uses 30-min for dead-daemon / killed-session reclaim).

## Item 12 - Headless-resume operational notes

- Session id from Stop/SessionEnd stdin `session_id` (stop-context.js:849-856); marker records it. Daemon runs `claude --resume <session_id> "/wrap"`.
- Recorded (Brief :62, claude-code-guide 2026-06-12): `claude -p "/wrap" --resume <id>` supported non-`--bare`; resume reloads transcript; non-`--bare` uses stored creds automatically. d4 requires resume in a dedicated worktree from recorded commit (hence marker needs head_sha+branch); worktree is same-repo -> satisfies same-repo-dir constraint. **One empirical unknown:** detached no-TTY keychain inheritance - deferred to a real-run check.

## Risks / gotchas

- **TOCTOU on lock:** daemon must hold `wrap.lock` for its headless `/wrap` Part-A window or hooks firing mid-run clobber context.md (narrow lock means daemon does NOT hold the lock its whole run).
- **`pending` vs `ready`:** today `pending` = staged-awaiting-claim. Stop fires EVERY turn staging `pending`. The daemon must only resume `ready`/finalized markers, else it resumes live sessions. The SessionEnd finalize transition (who writes `ready`, when) is the load-bearing new state machine.
- **`.last-wrap` interplay:** sync `/wrap` writes `.last-wrap` after Part A; subsequent Stop suppresses re-staging. Daemon's headless `/wrap` also writes `.last-wrap` = resumed session id; session ids unique so safe - confirm.
- **Build-drift on agent removal:** wrap-enrichment has git-tracked copies in .codex/.gemini/.opencode; deleting source requires running each build.sh + committing deletions (`.codex/build.sh:335` auto-removes stale TOML).
- **config template drift (pre-existing):** seed missing commit_telemetry/storybook_version/storybook_url.
- **Empirical auth unknown:** highest-risk feasibility item; not resolvable by review; needs a one-time fail-loud notice path.
- **No SessionStart hook today:** version-check notice registration is unconfirmed; architect must resolve before adding a second SessionStart consumer.

## Gaps / unknowns (architect must resolve)

- **Where the version-check SessionStart hook registers is unconfirmed** - `.claude/install.sh` does NOT wire SessionStart (only Stop/UserPromptSubmit/PreToolUse). Could be a documented manual step, pre-existing user config, or a genuine wiring gap. Resolve before adding the daemon's SessionStart launch.
- Exact Claude Code SessionEnd payload schema (e.g. `reason`, `transcript_path`) not re-confirmed against live docs; relied on in-repo Gemini/Stop contracts. Confirm if precise fields needed.
- `.opencode/plugins/session-context.ts` read only for marker/spillover signatures (:422-536); full daemon-irrelevance rests on Claude-only decision.

## Recommended next steps (for the Architect)

1. Design the marker state machine first (add `branch`, `head_sha`, `ready`, daemon-vs-session claim; specify the SessionEnd finalize transition) - update wrap.md:102-118 NORMATIVE + stageWrapPending in lockstep.
2. Resolve the SessionStart wiring gap before adding the daemon's SessionStart launch.
3. Specify the two new repo-root hooks (`hooks/<sessionend>.js`, `hooks/<daemon>.js`) sharing util with stop-context.js; wire in `.claude/install.sh` (Stop-block pattern); fail-open; detached-spawn via version-check-core.sh pattern.
4. Gate Step 0a staging behind Claude AND `deferred_wrap_daemon`; flip command to sync-default (remove Step 0b/0c async + SessionStart auto-enrichment).
5. Delete `wrap-enrichment` (agent + roster row + carve-out rewrite) and regenerate all adapters; commit built-copy deletions.
6. Add `deferred_wrap_daemon` toggle (debugger_on_failure precedent) across template/conventions/init-project §6f/agentic-status.
7. Plan tests in test-stop-context-deferred-wrap.js style.
8. Route content/** + hooks/** via `/update-agentic-engineering`, DCO `-s`, regenerate every adapter.

## Confidence

High on the four primary surfaces (read end-to-end) and the wiring gap (verified vs install.sh + git ls-files). Medium on the exact SessionEnd payload schema and the unresolved SessionStart registration site - both flagged.
