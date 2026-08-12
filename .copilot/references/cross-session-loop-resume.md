<!--
Purpose: Full reference for cross-session loop resume mechanics extracted
         from content/sections/07-cross-session-loop-resume.md. Contains:
         per-ticket loop-state-<LOOP_KEY>.json disk-write discipline (atomic
         tmp+rename at every
         phase transition); resume check on session start; the Stop hook's
         per-turn liveness refresh vs the SessionEnd hook's terminal
         interrupted-status write; resumable phases (automatic and with
         human confirmation); restart-required phases; full Skeptic re-run
         on interruption; Brief/Plan path recording; file hygiene; and
         batch-state coexistence (session_id gate, Stop hook/SessionEnd hook
         mirror, N>=2 invocation guard).

Public API: Read-only reference document. Cross-referenced from:
            content/sections/07-cross-session-loop-resume.md (parent
            section); content/sections/12-protocol-details.md (Cross-session
            loop resume Protocol Details entry).

Upstream deps: content/sections/07-cross-session-loop-resume.md (parent
               section); /ds-implement-ticket Resume check (derives LOOP_KEY)
               and Phase 6 loop initialization
               (writes loop-state-<LOOP_KEY>.json); hooks/stop-context.js (the Stop
               hook - per-turn liveness refresh only via
               hooks/lib/state-mark.js's refreshLiveness) and
               hooks/session-end-wrap.js (the SessionEnd hook - once-per-
               session terminal interrupted-status write and batch-state
               mirror via markInterrupted).

Downstream consumers: conductor (/ds-implement-ticket resume check at session
                      start); the Stop hook (per-turn liveness refresh) and
                      the SessionEnd hook (terminal interrupted-status
                      write); any session that may resume a prior
                      implement-ticket run.

Failure modes: every loop-state file is gitignored and must not be committed -
               BOTH the keyed .agentic/loop-state-<LOOP_KEY>.json and the
               legacy .agentic/loop-state.json. Under /ds-init-project's
               default-deny .agentic/* umbrella, neither needs enumeration -
               they carry no !.agentic/<file> negation and stay ignored by
               default. A hand-authored, non-umbrella (targeted denylist) <!-- false-umbrella-claim-ok -->
               .gitignore is a different shape and needs BOTH patterns
               listed explicitly; the keyed form does not match a bare
               loop-state.json entry, and a repo missing the glob would
               commit its findings_log, last_engineer_summary, and
               session_id.
               Silent Stop hook / SessionEnd hook failure is acceptable -
               the 10-minute implicit-interrupt heuristic handles missed
               writes. Batch-state per-write session_id gate prevents
               orphan-session corruption; EWOULDBLOCK on the scaffolding
               lock is silently skipped.

Performance: Standard (local filesystem reads/writes; no network).
-->

> Parent section: `content/sections/07-cross-session-loop-resume.md`. This file contains the complete body of that section verbatim.

## Cross-session loop resume

Long-running `/ds-implement-ticket` loops can survive rate limits and session exits via a **per-ticket** `.agentic/loop-state-<LOOP_KEY>.json`: <!-- gate-reviewed: still true - the interrupted-mark now lives on the SessionEnd hook rather than the Stop hook, but the survival property this sentence asserts is unchanged -->

- **One file per ticket, keyed.** `LOOP_KEY` is derived exactly once per ticket at the Resume check (from the ticket id, else the session id, else a random terminal floor), recorded in the file's own `loop_key` field, and never re-derived - notably never from the branch name, which the workflow deletes after merge. Two sessions working two different tickets in one checkout therefore write different files and never contend. Two sessions on the SAME ticket derive the same key and still meet the per-write `session_id` gate, which is the case that gate exists for. The single unkeyed `.agentic/loop-state.json` is the LEGACY path: still read, adopted onto a keyed file on resume, then removed - never written fresh.

- **Disk writes at every phase transition.** The conductor writes `.agentic/loop-state-<LOOP_KEY>.json` (atomic: tmp+rename via `.agentic/loop-state-<LOOP_KEY>.json.tmp`, a flat sibling rather than a subdirectory) at initialization and at every phase transition (Skeptic spawn, Skeptic return, Engineer spawn, Engineer return, QA spawn, QA return, quality gate steps, CI fix-loop steps). The `last_phase` and `last_phase_action` fields are the authoritative resume keys.

- **Resume check on session start.** When `/ds-implement-ticket` is invoked, it derives `LOOP_KEY` and checks for `.agentic/loop-state-<LOOP_KEY>.json` before reading AGENTS.md. If `status == "interrupted"` (or `status == "active"` with `last_updated` more than 10 minutes old), the conductor offers resume or fresh start. **The recommendation is the keyed file only - key match is the primary guard, never freshness.** There is no cross-ticket freshness fallback: offering the most recently written file would hand a resuming session another ticket's live state whenever that state was over 10 minutes old, which is routine during a CI wait. Other resumable candidates are named in a single informational line (capped at 3 keys plus `(+M more)`) with no prompt. See `/ds-implement-ticket` Resume check section for the full protocol, including legacy adoption and the null-ticket key families.

- **Stop hook refreshes liveness; SessionEnd hook writes interrupted status.** Neither hook derives a key or hardcodes a path: `hooks/lib/state-mark.js`'s `candidatePaths(cwd)` resolves the candidate set (every `.agentic/loop-state-*.json` newest-mtime-first capped at 100, plus the always-present legacy `.agentic/loop-state.json` and `.agentic/batch-state.json`) and selection is by `session_id` alone. The Stop hook (`hooks/stop-context.js`, wired with `--cadence=turn`) fires once per TURN and only refreshes a candidate's `last_updated` liveness timestamp (via `refreshLiveness`) when that file is `status=active` and positively owned by the current session - it never sets `status: "interrupted"`. The SessionEnd hook (`hooks/session-end-wrap.js`, once per session) writes `status: "interrupted"` on a terminal session-end reason via the same lib's `markInterrupted`, per candidate that exists and is `status == "active"`. Silent failure on either hook is acceptable - the 10-minute implicit-interrupt heuristic handles missed writes.

- **Resumable phases (automatic):** Phase 6/6b Skeptic/QA loop at iteration boundaries (committed Engineer output, clean branch); Phase 7 quality gate when engineer committed (`engineer_returned` / `rerun_pending`).

- **Resumable with human confirmation:** Mid-Engineer (dirty branch) - conductor asks human to discard or commit the partial work.

- **Restart required:** Phases 1-4 (cheap to re-run, no branch side effects). State file is not written until Phase 6 loop initialization.

- **Full Skeptic re-run on interruption.** If a Skeptic is interrupted mid-output, resume re-runs the Skeptic from scratch (last_phase=skeptic, last_phase_action=spawned). Skeptic is read-only and idempotent.

- **Brief/Plan paths recorded.** When a Brief or Plan governs the task, `brief_path`, `plan_path`, and `promotion_tier` (enum: `none`, `brief`, `plan`) are written to `.agentic/loop-state-<LOOP_KEY>.json` at authoring time. On resume, the conductor re-reads the Brief/Plan before spawning the next worker. Mid-flight escalation from Trivial or single-unit Elevated to Brief or Plan tier authors a retroactive Brief before the next engineer spawn (the in-flight engineer is allowed to return; already-completed units are not retroactively re-reviewed). Brief-tier tasks auto-promote to Plan tier on the 3rd resume.

- **File hygiene:** no loop-state file may be committed to git (gitignored) - the keyed `.agentic/loop-state-<LOOP_KEY>.json` and the legacy `.agentic/loop-state.json` alike. Under `/ds-init-project`'s default-deny `.agentic/*` umbrella, neither needs enumeration - both carry no `!.agentic/<file>` negation and stay ignored by default. A hand-authored, non-umbrella (targeted denylist) `.gitignore` is a different shape and needs BOTH patterns listed explicitly, because a keyed file does not match a bare `loop-state.json` entry. <!-- false-umbrella-claim-ok --> The keyed file is set to `status: "complete"` or deleted after the PR is opened. **Interim accumulation note:** because a keyed file is reclaimed only by the next run of *that same ticket*, completed-ticket files accumulate, bounded by the number of distinct ticket ids worked in the checkout. This is disk cost, not a correctness loss - a `complete` file is never a resume candidate, and both cadence functions skip it since they require `status === 'active'`.

- **Batch-state coexistence.** When `/ds-implement-ticket` is invoked with 2 or more ticket IDs, a sibling file `.agentic/batch-state.json` tracks batch-level cursor (which tickets are pending, in-progress, complete, blocked) alongside each ticket's own `loop-state-<LOOP_KEY>.json` phase cursor. Both files carry a `session_id` field written on every conductor write; every write applies a per-write gate that aborts (with an operator-visible warning) in either of two cases: (a) its existing `session_id` belongs to a different session AND that session's liveness-timestamp field (`last_updated` for a keyed loop-state file, `updated_at` for `batch-state.json` - the two files intentionally use different field names for the same concept) is within 10 min - AND, on `batch-state.json` ONLY, `status` is also `active`; or (b) the existing `session_id` is null/absent, regardless of `status` (legacy state from a prior version is force-takeover-eligible - see the self-ownership carve-out in `/ds-implement-ticket` Contract A step 3 for the one exception, when the CURRENT session's own id is also null). Case (a)'s `status=active` precondition is scoped to `batch-state.json` alone: its `touchTimestampOnTerminal: true` (`hooks/lib/state-mark.js`) makes a dead session's file look fresh for 10 minutes, so without the precondition the gate would abort the first write of an approved resume of an interrupted or paused batch. A keyed loop-state file does not carry it - it is already shielded by `touchTimestampOnTerminal: false`, and a live session can legitimately hold a non-`active` keyed file (the Phase 7 stall path sets `status=stalled` and continues to the next ticket), so adding the precondition there would let a foreign session clobber a live session's file. An absent liveness-timestamp field is treated as stale (the gate does not fire), not as fresh. This prevents orphan-session corruption uniformly across both files. Per-ticket keying removes DIFFERENT-ticket contention from this gate entirely (those sessions write different files) but leaves same-ticket contention, which is the case the gate is for. The SessionEnd hook mirrors its loop-state terminal interrupted-mark write to `batch-state.json` via the same best-effort silent-fail discipline (the Stop hook's separate per-turn liveness refresh mirrors similarly, updating `updated_at` instead of setting `status`). Single-ticket Trivial invocations never create `batch-state.json` and remain bit-for-bit unchanged. Only one batch per project root is supported; a second concurrent N≥2 invocation is refused at Phase 0a-pre. N=1 invocations against an active foreign batch warn but do not refuse.
