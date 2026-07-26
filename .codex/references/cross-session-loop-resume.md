<!--
Purpose: Full reference for cross-session loop resume mechanics extracted
         from content/sections/07-cross-session-loop-resume.md. Contains:
         loop-state.json disk-write discipline (atomic tmp+rename at every
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
               section); /ds-implement-ticket Phase 6 loop initialization
               (writes loop-state.json); hooks/stop-context.js (the Stop
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

Failure modes: loop-state.json is gitignored and must not be committed.
               Silent Stop hook / SessionEnd hook failure is acceptable -
               the 10-minute implicit-interrupt heuristic handles missed
               writes. Batch-state per-write session_id gate prevents
               orphan-session corruption; EWOULDBLOCK on the scaffolding
               lock is silently skipped.

Performance: Standard (local filesystem reads/writes; no network).
-->

> Parent section: `content/sections/07-cross-session-loop-resume.md`. This file contains the complete body of that section verbatim.

## Cross-session loop resume

Long-running `/ds-implement-ticket` loops can survive rate limits and session exits via `.agentic/loop-state.json`: <!-- gate-reviewed: still true - the interrupted-mark now lives on the SessionEnd hook rather than the Stop hook, but the survival property this sentence asserts is unchanged -->

- **Disk writes at every phase transition.** The conductor writes `.agentic/loop-state.json` (atomic: tmp+rename) at initialization and at every phase transition (Skeptic spawn, Skeptic return, Engineer spawn, Engineer return, QA spawn, QA return, quality gate steps). The `last_phase` and `last_phase_action` fields are the authoritative resume keys.

- **Resume check on session start.** When `/ds-implement-ticket` is invoked, it checks for `.agentic/loop-state.json` before reading AGENTS.md. If `status == "interrupted"` (or `status == "active"` with `last_updated` more than 10 minutes old), the conductor offers resume or fresh start. See `/ds-implement-ticket` Resume check section for the full protocol.

- **Stop hook refreshes liveness; SessionEnd hook writes interrupted status.** The Stop hook (`hooks/stop-context.js`, wired with `--cadence=turn`) fires once per TURN and only refreshes `.agentic/loop-state.json`'s `last_updated` liveness timestamp (via `hooks/lib/state-mark.js`'s `refreshLiveness`) when the file is `status=active` and positively owned by the current session - it never sets `status: "interrupted"`. The SessionEnd hook (`hooks/session-end-wrap.js`, once per session) writes `status: "interrupted"` on a terminal session-end reason via the same lib's `markInterrupted`, if the file exists and `status == "active"`. Silent failure on either hook is acceptable - the 10-minute implicit-interrupt heuristic handles missed writes.

- **Resumable phases (automatic):** Phase 6/6b Skeptic/QA loop at iteration boundaries (committed Engineer output, clean branch); Phase 7 quality gate when engineer committed (`engineer_returned` / `rerun_pending`).

- **Resumable with human confirmation:** Mid-Engineer (dirty branch) - conductor asks human to discard or commit the partial work.

- **Restart required:** Phases 1-4 (cheap to re-run, no branch side effects). State file is not written until Phase 6 loop initialization.

- **Full Skeptic re-run on interruption.** If a Skeptic is interrupted mid-output, resume re-runs the Skeptic from scratch (last_phase=skeptic, last_phase_action=spawned). Skeptic is read-only and idempotent.

- **Brief/Plan paths recorded.** When a Brief or Plan governs the task, `brief_path`, `plan_path`, and `promotion_tier` (enum: `none`, `brief`, `plan`) are written to `.agentic/loop-state.json` at authoring time. On resume, the conductor re-reads the Brief/Plan before spawning the next worker. Mid-flight escalation from Trivial or single-unit Elevated to Brief or Plan tier authors a retroactive Brief before the next engineer spawn (the in-flight engineer is allowed to return; already-completed units are not retroactively re-reviewed). Brief-tier tasks auto-promote to Plan tier on the 3rd resume.

- **File hygiene:** `.agentic/loop-state.json` must not be committed to git (gitignored). It is set to `status: "complete"` or deleted after the PR is opened.

- **Batch-state coexistence.** When `/ds-implement-ticket` is invoked with 2 or more ticket IDs, a sibling file `.agentic/batch-state.json` tracks batch-level cursor (which tickets are pending, in-progress, complete, blocked) alongside `loop-state.json`'s per-ticket phase cursor. Both files carry a `session_id` field written on every conductor write; every write applies a per-write gate that aborts (with an operator-visible warning) in either of two cases: (a) its existing `session_id` belongs to a different session AND that session's liveness-timestamp field (`last_updated` for `loop-state.json`, `updated_at` for `batch-state.json` - the two files intentionally use different field names for the same concept) is within 10 min - AND, on `batch-state.json` ONLY, `status` is also `active`; or (b) the existing `session_id` is null/absent, regardless of `status` (legacy state from a prior version is force-takeover-eligible - see the self-ownership carve-out in `/ds-implement-ticket` Contract A step 3 for the one exception, when the CURRENT session's own id is also null). Case (a)'s `status=active` precondition is scoped to `batch-state.json` alone: its `touchTimestampOnTerminal: true` (`hooks/lib/state-mark.js`) makes a dead session's file look fresh for 10 minutes, so without the precondition the gate would abort the first write of an approved resume of an interrupted or paused batch. `loop-state.json` does not carry it - it is already shielded by `touchTimestampOnTerminal: false`, and a live session can legitimately hold a non-`active` `loop-state.json` (the Phase 7 stall path sets `status=stalled` and continues to the next ticket), so adding the precondition there would let a foreign session clobber a live session's file. An absent liveness-timestamp field is treated as stale (the gate does not fire), not as fresh. This prevents orphan-session corruption uniformly across both files. The SessionEnd hook mirrors its `loop-state.json` terminal interrupted-mark write to `batch-state.json` via the same best-effort silent-fail discipline (the Stop hook's separate per-turn liveness refresh mirrors similarly, updating `updated_at` instead of setting `status`). Single-ticket Trivial invocations never create `batch-state.json` and remain bit-for-bit unchanged. Only one batch per project root is supported; a second concurrent N≥2 invocation is refused at Phase 0a-pre. N=1 invocations against an active foreign batch warn but do not refuse.
