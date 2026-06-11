# Architect Plan: Deferred / Background `/wrap`

*Governs Brief `docs/planning/deferred-background-wrap.md`. Plan-tier. Persisted 2026-06-11 — SIMPLIFIED revision after the file-identity Critical. Lock strategy: minimal (context.md-only Part-A hold); correctness rests on idempotency, not on a whole-flow lock.*

## Approach

Make `/wrap` return control within seconds by staging a resume safety-net and running enrichment in the background; stage a `.agentic/wrap-pending.json` marker for sessions that exit un-wrapped so the next session in that project completes enrichment idempotently. The central concurrency decision, re-derived against correct file identities, is that **`.agentic/context.md` is the only shared document this feature genuinely contends on** — so the lock is held only around the conductor's actual context.md write window in Part A (the narrow hold), and **enrichment correctness rests on idempotency** (context.md merge dedups; every other written file is single-writer or append-dedup), with the marker's `claimed_at`/staleness fields used only to *reduce wasteful double-runs*, never as a correctness-critical invariant. This collapses the prior whole-flow-hold design: the F3 `memory.md`-interleave hazard that motivated it does not exist, because the file the prior plan thought two writers contended on was a conflation of two different files.

## Codebase context

Verified against the current tree. **The two memory files are different files and the prior plan conflated them — this is the load-bearing correction:**

- **`.agentic/memory.md` (lowercase, project-local).** The Part B write target (`wrap.md:308` "Memory path: `<cwd>/.agentic/memory.md`") and the Part E compression target (`wrap.md:392`, "the `memory.md` file written by Part B"). **Written ONLY by `/wrap`.** It does not appear in any other agent's allowed-files list. It does not exist on disk yet (created on first standard-path `/wrap`). **Single-writer (/wrap).** No cross-writer lock is needed to protect it, and nothing can interleave with Part E's compression of it.
- **`MEMORY.md` (uppercase, project root, ~6.6 KB on disk).** Written by `learnings-agent` (`learnings-agent.md:188` — its allowed-files list is exactly `.agentic/learnings.md` + project-root `MEMORY.md`) and by `wrap-ticket` (`wrap-ticket.md:162`, max 3 entries). **Both writers append-with-dedup.** It is **never a compression target** — Part E never touches it. learnings-agent today acquires **no lock**; wrap-ticket acquires `wrap.lock`. This file's concurrent-append situation is **exactly today's** and is **not worsened by this feature** — the new background flow writes `.agentic/memory.md`, not `MEMORY.md`.

The "F3 memory.md interleave" hazard that drove the prior Option-B whole-flow hold **does not exist** once these are separated. Part E compresses `.agentic/memory.md`, which only `/wrap` writes — nothing can interleave. And root `MEMORY.md` is append-dedup and never compressed, so a concurrent learnings-agent/wrap-ticket append is the pre-existing, already-tolerated situation. **Consequence: U8 (learnings-agent lock-awareness) and MAJOR-3's `.agentic/memory-pending-learnings.md` buffer are both deleted** — they only existed to defend the phantom.

Remaining real surfaces:

- **`hooks/stop-context.js`** is one unlocked `context.md` writer on Claude Code. The `/wrap` coexistence branch is at lines 786-869: the matcher is `existing.startsWith('# Session Context\n*Written by /wrap')` (line 788), the activity-block append writes at 811-816, and `writeLoopState`/`writeBatchState`/`writeSessionTotal`/identity-gate/`removeLearningsAgentSession` all run on this exit path (817-868). The normal (non-wrap) write is at 875-880, with header `# Session Context\n*Auto-updated by Stop hook` emitted at 761-762. All paths are silent-fail (`process.exit(0)`); one `git status` subprocess at 723 (5 s timeout). The module manifest (lines 3-75) enumerates **eight** independent write paths and must be updated.
- **`.opencode/plugins/session-context.ts`** is the second unlocked `context.md` writer. It hardcodes the same matcher at line 449 and writes context.md at line 466 (`refreshWrapActivityBlock` `/wrap`-coexistence path, reached from both `session.idle` and `command.executed`) and at line 657 (`session.idle` normal write). **Critically (drives MAJOR-1):** the three finalization writes `writeLoopState`/`writeBatchState`/`writeSessionTotal` run **ONLY** in the `command.executed` branch (lines 710-712), deliberately per-session-once; the `session.idle` branch (607-673) does context.md **only**. The manifest (lines 1-61) states this invariant explicitly (lines 38-51).
- **`content/commands/wrap.md`** holds the lock protocol. Pre-flight acquisition is Steps 1-5 (lines 52-63), atomic `mkdir <cwd>/.agentic/wrap.lock` + an `owner` file (PID + ISO8601 UTC, line 56); mandatory release on every exit path is 65-72; the 30-minute staleness heuristic is line 59. Output-1 on-disk header template is line 180 (`*Written by /wrap on YYYY-MM-DD. Preserved by Stop hook. Not committed to git.*` — **no "UTC" literal**). Part A merge logic (the `*Written by /wrap` second-line check + rolling-session-label merge + header rewrite at 340) is 312-347. Part B (`.agentic/memory.md`) is 349-359; Part E compression is 387-456 with targets **only `.agentic/memory.md` + `[cwd]/CLAUDE.md`** (391-394) — context.md is never a compression target. Step 6 release is line 464.
- **`content/agents/wrap-ticket.md`** acquires the same `wrap.lock` (lines 90-103); on contention it returns `skipped_reason: "wrap-lock-contention"` immediately (105-117). Its only context.md touch is a **`## Recent Focus` append** (lines 184-193) gated behind that same lock. **Re-evaluation result: wrap-ticket's sole shared-doc contention is on context.md, and it is already serialized by `wrap.lock`. With the narrow Part-A-only hold, wrap-ticket's existing soft-skip (`skipped_reason`) is sufficient. U7 (deferral) is DELETED.**
- **`content/agents/learnings-agent.md`** writes `.agentic/learnings.md` + optional root `MEMORY.md` (128-142). Neither is a `/wrap` target and neither is contended by this feature. **No change to this agent. U8 DELETED.**
- **`content/references/conductor-operating-rules.md`** §wrap-ticket writer carve-out (line 58) already correctly distinguishes root `MEMORY.md` from `/wrap`'s paths. Only the context.md-writer enumeration needs extending (name the OpenCode plugin as the second unlocked writer); the carve-out must NOT be edited to imply any new `MEMORY.md` serialization.
- **`.gitignore`** uses the `.agentic/*` umbrella (line 24) with explicit negations only for `config.json`, `findings.md`, `qa-regressions.md`. Every new `.agentic/` file here is umbrella-covered — **no gitignore edit required**.
- Adapter build scripts exist for all four surfaces; the new `wrap-enrichment` agent and the refactored `wrap.md` must be regenerated.
- `hooks/tests/` is the Brief's named unit-coverage home.

## Data model

Two new on-disk artifacts (down from three — the learnings buffer is gone). **Canonical schema for both lives in a new "## Deferred-enrichment data model" section in `content/commands/wrap.md`, inserted after the lock-protocol block (~line 63).** All other files reference that section; none restate field semantics divergently. Field names below are normative. All writes are atomic (tmp + rename) and umbrella-ignored.

**1. `.agentic/wrap-pending.json` (the enrichment marker).**

```json
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
```

- `status` lifecycle: `pending` (staged, unclaimed) -> `in_progress` (claimed, enrichment running) -> `done` (completed; marker then unlinked) | `gave_up` (`attempts >= 3`; marker retained with a manual-`/wrap` notice).
- `claimed_at` + a staleness window are a **wastefulness reducer, not a correctness invariant** — see Lock strategy. `staged_at` is immutable.
- `attempts` increments at claim time, before enrichment begins, so a crash mid-enrichment still counts.

**2. `.agentic/.last-wrap` (the wrap-recency sentinel).** Single line: the `session_id` of the session whose `/wrap` (sync or background enrichment) last successfully wrote context.md. Atomic write. **Fully replaces any header-date parsing** — no site parses the header date to decide "was this wrapped." Consumers: (a) Stop-hook marker-staging suppression (do not stage if current `session_id` == `.last-wrap`), and (b) the OpenCode plugin's equivalent suppression.

**3. `.agentic/.stop-deferred-activity.jsonl` (the spillover log).** Append-only JSONL, one record per Stop-hook (or OpenCode-idle) invocation that found `wrap.lock` held and therefore skipped its context.md write. Drained into the context.md activity block by the enrichment flow at its context.md write. Record schema:

```json
{"schema_version": 1, "ts": "<ISO8601 UTC>", "session_id": "<uuid>", "recent_focus": ["<msg>"], "paths_referenced": ["<path>"], "uncommitted": ["<status code + path>"], "tools_used": ["<tool>"]}
```

**Pinned header prefix (F4, normative).** Exactly one byte-exact prefix is the contract between writer and matcher:

```
# Session Context\n*Written by /wrap
```

This is what `stop-context.js:788` and `session-context.ts:449` test via `startsWith`, and what every `/wrap` Output-1 / merge write must emit as its first two lines. The on-disk header date is a UTC calendar date (`date -u +%Y-%m-%d`); the header **string does not contain the "UTC" literal** — it stays `*Written by /wrap on YYYY-MM-DD. ...` exactly as line 180 reads today. The matcher only tests the pinned prefix (which stops before the date), so date format and the absence of "UTC" are both compatible. The Part A merge rule at line 340 ("(merged context)") appends after the date and is outside the pinned prefix — it stays. The rolling-session-label merge (lines 326-347) is preserved unchanged.

## API / interface design

These are binding contracts. Workers implement them exactly.

**Stop-hook lock-aware context.md write (Node, `hooks/stop-context.js`).** Before both context.md write paths, the hook checks lock presence with a single `fs.existsSync` — no subprocess, fail-open:

```js
function wrapLockHeld(cwd) {
  try { return fs.existsSync(path.join(cwd, '.agentic', 'wrap.lock')); }
  catch (_) { return false; }   // fail-open: treat unreadable as not-held
}
```

When `wrapLockHeld(cwd)` is true: the hook **skips both context.md write paths** (the wrap-coexistence append at 811-816 and the normal write at 875-880) and instead appends one spillover record to `.agentic/.stop-deferred-activity.jsonl` (append-only, fail-open). **All other Stop-hook writes still fire on every exit path** — `writeLoopState`, `writeBatchState`, `writeSessionTotal`, the identity gate, and `removeLearningsAgentSession` are independent of context.md and must continue. The spillover record is built from the already-extracted `recentUserMessages`, `filePaths`, `uncommittedFiles`, and `uniqueTools` (no new git calls).

**Marker-staging contract (Node, `hooks/stop-context.js`).** After the context.md decision, stage a `.agentic/wrap-pending.json` marker (atomic tmp+rename) **only when all of**: (a) no live marker exists (none, or one with `status: done`/`gave_up`), AND (b) the current `session_id` does **not** match `.agentic/.last-wrap`, AND (c) the session had substantive activity (>=1 uncommitted tracked file OR >=1 non-read file path referenced OR a non-empty recent-focus). Staging is fail-open and never blocks exit. The hook does not run enrichment — it only stages.

**SessionStart auto-enrichment contract (conductor).** On session start, after reading `.agentic/context.md`, the conductor checks for `.agentic/wrap-pending.json`. If present with `status: pending`, OR `status: in_progress` with stale `claimed_at` AND `wrap.lock` absent, the conductor claims it and runs background enrichment — the same draft -> Skeptic -> inline-write -> compression flow `/wrap` runs today — while staying responsive to user prompts.

**`/wrap` async/sync flag (conductor, `content/commands/wrap.md`).** Default `/wrap` stages the safety-net (Step 0a) then runs enrichment in the background and returns control within seconds. `/wrap --sync` preserves today's fully-blocking pipeline byte-for-byte. The Step 0-6 body is unchanged; only the wrapper (when it returns to the user, and the lock-hold span) changes.

**`finalize(cwd, sessionId)` refactor (OpenCode plugin) — SCOPED to context.md only (MAJOR-1 fix).** Factor **only** the context.md lock-aware branch (the new `wrapLockHeld` check + skip-or-write + spillover) into a shared helper called from both `session.idle` and `command.executed`. The three finalization writes (`writeLoopState`/`writeBatchState`/`writeSessionTotal`, lines 710-712) **stay on `command.executed` exclusively** — they are per-session-once and a per-turn `session.idle` invocation would corrupt loop-state/batch-state/events on every turn. **Do not claim "byte-identical finalize across both paths."** The shared surface is the context.md write decision only.

## Lock strategy: minimal (context.md-only Part-A hold)

**Decision: hold `wrap.lock` only around the conductor's actual context.md write window in Part A.** Acquire immediately before the Part A read-merge-write of `.agentic/context.md`; release immediately after the context.md write completes. Do not hold across the draft/Skeptic/compression stages.

**Why this is correct — context.md is the only genuinely-contended doc, and idempotency covers the rest:**

- **context.md** is written by three actors: the background enrichment (Part A), the new session's Stop hook, and the OpenCode plugin. This is the one real race. The narrow lock serializes the enrichment's context.md write against the two hooks; the hooks are lock-aware (skip + spill while held), so no concurrent context.md write can clobber the merge, and the spilled records are folded in when the enrichment writes.
- **`.agentic/memory.md`** (Part B + Part E) and **`[cwd]/CLAUDE.md`** (Part E) and **`AGENTS.md`** (Part C) are **single-writer (/wrap)**. No other actor writes them. No cross-writer lock is needed.
- **root `MEMORY.md`** is pre-existing append-dedup (learnings-agent + wrap-ticket), uncompressed, untouched by this feature. Its concurrency posture is unchanged.

**Idempotency is the correctness guarantee.** A duplicate enrichment of the same marker is **wasteful, not corrupting**: context.md merge dedups (Part A union/dedup rules at 342-345); `.agentic/memory.md`/`AGENTS.md` writes are single-writer and the Part B/Part C dedup passes are idempotent; root `MEMORY.md` and `.agentic/learnings.md` are append-dedup. The narrow lock serializes the context.md *writes* so two enrichments cannot clobber the file mid-merge; everything else converges regardless of run count.

### Race-free walkthrough

1. **Claim (best-effort, reduces double-runs).** Conductor reads the marker. If `status: pending`, OR (`in_progress` AND `claimed_at` older than the staleness window AND `wrap.lock` absent), it sets `status: in_progress`, `claimed_by: <our session_id>`, `claimed_at: <now>`, `attempts: attempts+1` (atomic tmp+rename) and proceeds. **Two sessions racing to claim the same marker is tolerated** — the loser also runs, and idempotency makes the double-run wasteful but safe. `claimed_at` + the staleness window exist to make that race *rare*, not impossible.

2. **Background stages run with no lock held.** Draft Worker -> conductor arranges Skeptic -> inline writes (Part B `.agentic/memory.md`, Part C `AGENTS.md` — all single-writer) -> Part E compression Worker -> compression Skeptic. Because these touch only single-writer files, no lock is needed.

3. **context.md write (the one locked window, Part A).** The conductor `mkdir .agentic/wrap.lock` (atomic; on failure another `/wrap`/wrap-ticket holds it — wait per the existing lock-wait protocol). Write `wrap.lock/owner` (PID + ISO8601 UTC). Then: drain `.stop-deferred-activity.jsonl` (atomic three-step below), read-merge-write `.agentic/context.md` (existing Part A rolling-label merge), update `.last-wrap` to our `session_id`. Release the lock (`rm -rf .agentic/wrap.lock`) as the last action of the window. The hold is the duration of one read+merge+write, not the whole flow.

4. **Terminal marker transition.** On success: set marker `status: done` and unlink it. On `attempts >= 3`: set `status: gave_up`, retain the marker with a manual-`/wrap` notice. (`--sync` follows the same Part A locked window inline.)

**Atomic spillover drain (at the context.md write, inside the held lock).** "Read inside the held lock" alone is unsafe because lock-held is exactly when a lock-aware hook *might* have appended just before the lock was observed; the three-step rename-first cut prevents loss:

1. `rename(.agentic/.stop-deferred-activity.jsonl -> .agentic/.stop-deferred-activity.jsonl.draining.<pid>)`. Atomic. Any hook append after this rename creates a fresh `.stop-deferred-activity.jsonl` for the next drain — not lost, belongs to the next owner.
2. Read and fold the renamed copy's records into the context.md activity block.
3. `unlink(.agentic/.stop-deferred-activity.jsonl.draining.<pid>)`.

A session-start sweep `rm -f .agentic/.stop-deferred-activity.jsonl.draining.*` (fail-open) cleans any temp file leaked by a crash between rename and unlink. **Cross-session spillover attribution note:** spilled records carry the *spilling* session's `session_id`, and the draining enrichment folds them into its own activity block under the enrichment session's header — the activity block is a union of recent sessions' activity, so cross-session attribution is expected and the per-record `session_id` preserves provenance.

**Same-session manual `/wrap` during a background enrichment (MAJOR-2).** Because the lock is held only during the brief Part A window (not the whole flow), a same-session manual `/wrap`/`--sync` issued while the session's own background enrichment is running will, in the vast majority of cases, find the lock free (the enrichment is in its lock-free draft/Skeptic/compression stages) and proceed; if it happens to land in the enrichment's brief Part A window, the existing lock-wait protocol (wrap.md:60) waits the short duration and proceeds. The conductor SHOULD additionally short-circuit: if a background enrichment is in-flight for this session (the conductor knows it spawned one), a manual `/wrap` coalesces with a one-line "background enrichment already running for this session; it will complete shortly" notice rather than launching a second pipeline. This makes the tiny residual window a non-issue.

## Implementation steps

Ordered by dependency. **U1 gates U2-U4** (canonical schemas before any writer references them). **U6 depends on U2-U4** (OpenCode plugin mirrors schemas + lock-aware branch). **U9 is last** (adapter regeneration). All `content/**` and `hooks/**` edits route through `/update-agentic-engineering`; commits are DCO-signed (`-s`); no nested subagent spawns; hooks fail-open.

**Prior units DELETED in this revision (with reasons):**
- **Old U7 (wrap-ticket deferral)** — DELETED. wrap-ticket's only shared-doc contention is context.md, already serialized by `wrap.lock`; with the narrow hold its existing `skipped_reason: "wrap-lock-contention"` soft-skip is sufficient. No Phase 11b change needed.
- **Old U8 (learnings-agent lock-aware MEMORY.md append + `.agentic/memory-pending-learnings.md` buffer)** — DELETED. learnings-agent writes root `MEMORY.md` (append-dedup) and `.agentic/learnings.md`, neither of which is a `/wrap` target or a compression input. No torn read exists. This also dissolves MAJOR-3 (no buffer file, no fold-on-follow-up-session machinery).
- **Whole-flow continuous hold + per-stage `wrap.lock/owner`/`claimed_at` refresh** — DELETED from the lock strategy. The lock is held only in the Part A window; `claimed_at` is set once at claim and is advisory.
- **"Part E re-reads `memory.md` before compressing" defense-in-depth** — DELETED. `.agentic/memory.md` is single-writer; nothing can append to it mid-flow.

**U1 — Canonical data-model + pinned-header section (`content/commands/wrap.md`).** Insert "## Deferred-enrichment data model" after the lock-protocol block (~line 63) defining the two schemas (`wrap-pending.json`, `.last-wrap`) plus `.stop-deferred-activity.jsonl` and the pinned header prefix, verbatim as Data model above. Single source of truth referenced by all other units. *wrap.md is a command spec, not a manifested source module — no manifest header.*

**U2 — Stop-hook lock-aware context.md skip + spillover (`hooks/stop-context.js`).** Add `wrapLockHeld(cwd)` (single `fs.existsSync`, fail-open). Guard both context.md write paths (811-816, 875-880): when held, skip and append one spillover record (fail-open). Leave all other writes firing unconditionally. **Update the module manifest (lines 3-75):** the eight-write-path enumeration becomes nine (add the spillover path); the failure-modes block notes the lock-aware skip and the `.last-wrap`/`wrap-pending.json` interactions. *Manifest update mandatory — the "eight independent write paths" claim would otherwise go stale (Major).*

**U3 — Stop-hook marker staging + `.last-wrap` suppression (`hooks/stop-context.js`).** Add atomic `wrap-pending.json` staging per the marker-staging contract; add the `.last-wrap` read. Fail-open; never blocks exit. Reflect in the manifest (do the U2 + U3 manifest edits in one pass). *Minor (manifest accuracy): confirm the final write-path count reflects BOTH the U2 spillover append and the U3 marker-staging write, and that the failure-modes block names both, so the updated count (the manifest's "eight independent write paths" claim) does not itself go stale.*

**U4 — `/wrap` async default + `--sync` + Step 0a safety-net + narrow Part-A lock + atomic drain (`content/commands/wrap.md`).** Add "Step 0a — Stage resume safety-net" before Step 0 that **stages the `wrap-pending.json` marker** (status `pending`, this `session_id`) — this is the "resume safety-net" the Brief means, so an async `/wrap` that exits before Part A still leaves a recovery marker for the next session. **Step 0a does NOT write `.last-wrap`** — `.last-wrap` is written only after a successful Part A context.md write (consistent with the Data model and walkthrough step 3; writing it early would suppress this very session's recovery marker). Define the default async path: stage the marker, spawn enrichment in background, return to user within seconds; run draft/Skeptic/Part B/Part C/Part E **with no lock held** (single-writer files); **acquire `wrap.lock` only around the Part A context.md read-merge-write window**, perform the atomic three-step spillover drain inside that window, write context.md, then update `.last-wrap`, then release the lock. State the **explicit invariant: Part E writes only `.agentic/memory.md` + `[cwd]/CLAUDE.md`, never context.md** (verified, 391-394). Preserve the Part A rolling-session-label merge and the line-340 header rewrite; emit the pinned prefix; confirm no residual header-date parsing remains. `--sync` keeps today's blocking pipeline with the same narrow Part-A lock window. Specify the same-session coalesce behavior (MAJOR-2): if a background enrichment is in-flight for this session, a manual `/wrap` coalesces with a notice rather than launching a second pipeline. **Specify a Recent-Focus dedup rule for the duplicate-enrichment case (idempotency, MAJOR):** key the folded Recent-Focus draft by the marker's `session_id`+`staged_at`; if a re-run of the same marker finds its draft already folded under a session label (the rolling-label merge at `wrap.md:326-336` otherwise appends without deduping a re-run), skip the append rather than adding a new label. This makes the rolling-label merge idempotent on a duplicate claim and satisfies the QA idempotency check below.

**U5 — SessionStart auto-enrichment + drain-temp sweep (conductor protocol, `content/commands/wrap.md` + one-line METHODOLOGY §Session Context pointer if needed).** Add the SessionStart marker-check-and-claim flow: claim when `status: pending` OR (`in_progress` AND stale `claimed_at` AND `wrap.lock` absent); set `in_progress`/`claimed_by`/`claimed_at`, increment `attempts`; run background enrichment; stay responsive. Add the session-start sweep `rm -f .agentic/.stop-deferred-activity.jsonl.draining.*` (fail-open). Note idempotency as the correctness guarantee (a duplicate claim/run is wasteful, not corrupting). Conductor protocol prose, not a new agent.

**U6 (FUNCTIONAL) — OpenCode plugin lock-aware skip + spillover + `.last-wrap` suppression + SCOPED `finalize()` refactor (`.opencode/plugins/session-context.ts`).** Functional code change. Add `wrapLockHeld(cwd)` (Bun `Bun.file(...).exists()` on `.agentic/wrap.lock`, fail-open). Gate both context.md write sites (line 466 `refreshWrapActivityBlock`, line 657 `session.idle` normal write): when held, skip and append a spillover record to `.agentic/.stop-deferred-activity.jsonl`. Add `.last-wrap`-based marker-staging suppression mirroring U3. **Factor ONLY the context.md lock-aware decision into a shared helper called from both `session.idle` and `command.executed`; keep `writeLoopState`/`writeBatchState`/`writeSessionTotal` on `command.executed` exclusively (lines 710-712) — they remain per-session-once. Do NOT make them fire on `session.idle`.** Update the plugin manifest (lines 1-61): new writer enumeration + lock-aware behavior; the per-session-once invariant for the three finalization writes is **unchanged** and must stay accurate. Keep the reciprocal "keep in sync with hooks/stop-context.js" comment as an addition. *`.opencode/plugins/` is adapter source, not `content/**` — editable directly, but treat as Elevated since it mirrors hook behavior.*

**U7 — `wrap-enrichment` background agent (`content/agents/wrap-enrichment.md`, NEW).** A general-purpose-style agent encapsulating the draft -> (conductor arranges Skeptic) -> inline-write -> compression body so SessionStart and async `/wrap` share one definition. **New non-trivial module — manifest header recommended** (documented spawn-input contract, side-effecting file writes). Does **not** spawn subagents (the conductor arranges Skeptic per the no-nested-spawn constraint).

**U8 — conductor-operating-rules prose reconciliation (`content/references/conductor-operating-rules.md`).** Extend the §wrap-ticket writer carve-out (line 58) to name **both** the Node Stop hook and the OpenCode plugin as lock-aware context.md writers and correct any "the one unlocked context.md writer" claim. **Do NOT alter the `MEMORY.md` serialization language** — root `MEMORY.md` is unchanged by this feature; the carve-out's existing distinction between root `MEMORY.md` and `/wrap`'s paths is correct and load-bearing. No learnings-agent or wrap-ticket-deferral change is described (those units are deleted). Update this file's own manifest (lines 1-30) if downstream-consumers/failure-modes change.

**U9 — Adapter regeneration (build scripts).** Run `.claude/build.sh`, `.codex/build.sh`, `.cursor/build.sh`, `.opencode/build.sh` to emit the new `wrap-enrichment` agent and the refactored `wrap.md` across all adapter surfaces. Verify methodology lint/build green. **Last unit.**

### Per-consumer impact table

The trigger fires: the pinned header prefix `# Session Context\n*Written by /wrap` is a shared behavioral contract. Fresh enumeration of all matchers/emitters of that contract:

| `consumer_file:line` | `passes_relevant_arg?` | `uses_compensating_pattern?` | `current_behavior` | `new_behavior` |
|---|---|---|---|---|
| `hooks/stop-context.js:788` | matcher `startsWith('# Session Context\n*Written by /wrap')` | no | appends activity block on match; always writes context.md | skips context.md write + spills when `wrap.lock` held; matcher prefix unchanged |
| `hooks/stop-context.js:761` | emits `# Session Context\n*Auto-updated by Stop hook` (non-wrap) | n/a | normal write path | gated by `wrapLockHeld` -> spill instead when held |
| `content/commands/wrap.md:180` | emits `*Written by /wrap on YYYY-MM-DD.` (Output-1 template) | no | on-disk header | unchanged string; Step 0a stages the `wrap-pending.json` marker; `.last-wrap` written only after the Part A context.md write |
| `content/commands/wrap.md:318,320,322,340` | Part A `*Written by /wrap` second-line check + merge rewrite | no | merge vs overwrite decision; "(merged context)" rewrite | pinned prefix preserved; Part A wrapped in narrow `wrap.lock` window; no header-date parse |
| `.opencode/plugins/session-context.ts:449` | matcher `startsWith("# Session Context\n*Written by /wrap")` | no | refresh activity block on match; unlocked write | gated by `wrapLockHeld` -> spill when held (U6) |
| `.opencode/plugins/session-context.ts:646` | emits `# Session Context\n*Auto-updated by session idle plugin` (non-wrap) | n/a | unlocked normal write | gated by `wrapLockHeld` -> spill when held (U6) |
| `content/agents/wrap-ticket.md:186-193` | reads/appends `## Recent Focus` of context.md (no header emit) | append-discipline + dedup + `wrap.lock` | per-ticket append, lock-gated | **unchanged** — already serialized by `wrap.lock`; narrow Part-A hold leaves its soft-skip sufficient (no U7-deferral) |

Matcher count: 2 (`stop-context.js:788`, `session-context.ts:449`). Header-emitter count: 3 (`stop-context.js:761`, `wrap.md:180`, `session-context.ts:646`). The Part A merge site reads but does not emit the prefix divergently. wrap-ticket reads/appends `## Recent Focus` only and emits no header. No other importer of the contract exists. **Note: root `MEMORY.md` writers (`learnings-agent.md:188`, `wrap-ticket.md:162`) are deliberately absent from this table — they do not touch the pinned-header contract and are not contended by this feature.**

## QA criteria

Carried verbatim from the Brief (`docs/planning/deferred-background-wrap.md`):

```yaml
qa_criteria:
  qa_skip: pure-backend-library
  qa_skip_rationale: >-
    No browser-renderable UI surface. The change is Claude Code hooks (Node/shell)
    plus methodology markdown. Runtime hook behavior is verified by the hooks/tests
    unit suite and the manual two-session E2E protocol named in Verification, neither
    of which the qa-engineer browser/runtime gate can drive.
  viewport: [desktop]
  scenarios: []
  manual_smoke: >-
    Two-session E2E in Verification is the smoke test: stage in S1, confirm
    background enrichment + responsiveness + merged context.md in S2.
```

Unit-level verification (from the Brief's Verification section, binding on Workers): `hooks/tests/` coverage for lock-present -> context.md skip + spillover written; `/wrap`-authored-this-session -> no marker staged (`.last-wrap` session-id match); substantive vs zero-substance staging; atomic marker write. Manual two-session E2E including `--sync`, kill-mid-enrichment -> reclaim after staleness window + `attempts >= 3` give-up, and Stop-during-held-lock (the narrow Part-A window) -> spillover drain with no clobber. **Idempotency check:** force a duplicate claim of the same marker across two sessions and confirm the second run is wasteful but produces a correct, dedup'd context.md (no corruption).

## Trade-offs and constraints

**The simplification, stated plainly:** `.agentic/context.md` is the only genuinely-contended shared doc this feature introduces. Every other written file is single-writer (`.agentic/memory.md`, `AGENTS.md`, `[cwd]/CLAUDE.md` — all `/wrap`-only) or pre-existing append-dedup (root `MEMORY.md`, `.agentic/learnings.md` — untouched by this feature). Single-writer and append-dedup files need no new locking, so the lock is held only around the Part A context.md write window and correctness rests on idempotency rather than a long-lived lock.

**Alternatives considered (before committing to the narrow Part-A-only hold):**
- **Whole-flow continuous lock hold + per-stage refresh + wrap-ticket deferral (the prior plan's Option B):** rejected — it was built to defend the F3 `memory.md`-interleave hazard, which does not exist once `.agentic/memory.md` (single-writer /wrap) and root `MEMORY.md` (append-dedup, never compressed) are correctly distinguished. With no phantom to defend, the whole-flow hold, per-stage refresh, learnings-agent lock-awareness, the pending-learnings buffer, and wrap-ticket deferral are all dead weight.
- **No lock at all (rely purely on idempotency for context.md too):** rejected — two enrichment writes interleaving mid-merge could still clobber the context.md file content (the merge is read-then-write, not append). A narrow lock around that one read-merge-write is the minimal serialization that closes it.
- **Detached headless enrichment (`claude -p` background process):** rejected — Brief non-goal; enrichment must stay inside the conductor's session.
- **Header-date parsing for "wrapped this session":** rejected for the `.last-wrap` session-id sentinel — date parsing is timezone-fragile and cannot distinguish two sessions on the same day.

**Known limitations and things to watch out for:**
- A duplicate enrichment across two sessions is possible (best-effort `claimed_at` + staleness window only reduces it). This is wasteful, not corrupting — idempotency is the guarantee. Document the staleness window value chosen in U5 and note it is advisory.
- The `.stop-deferred-activity.jsonl.draining.<pid>` temp file leaks if the conductor crashes between rename and unlink; the U5 session-start sweep cleans it (fail-open).
- Cross-session spillover records are folded into the draining enrichment's activity block; per-record `session_id` preserves provenance, but the block header reflects the enrichment session, not each spilling session. Expected behavior, noted for reviewers.
- All new `.agentic/` files rely on the `.agentic/*` umbrella ignore; a future explicit-negation block must not accidentally un-ignore them.
- **Do not re-introduce `MEMORY.md` into the locked set.** Root `MEMORY.md`'s concurrency posture is exactly today's; adding it to `wrap.lock`'s scope would serialize learnings-agent against `/wrap` for no benefit and could starve Phase 6 learning capture.

## Open Questions

None.
