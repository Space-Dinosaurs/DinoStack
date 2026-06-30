<!--
Purpose: Full reference for cross-session loop resume mechanics extracted
         from content/sections/07-cross-session-loop-resume.md. Contains:
         loop-state.json disk-write discipline (atomic tmp+rename at every
         phase transition); resume check on session start; Stop hook
         interrupted-status write; resumable phases (automatic and with
         human confirmation); restart-required phases; full Skeptic re-run
         on interruption; Brief/Plan path recording; file hygiene; and
         batch-state coexistence (session_id gate, Stop hook mirror, N>=2
         invocation guard).

Public API: Read-only reference document. Cross-referenced from:
            content/sections/07-cross-session-loop-resume.md (parent
            section); content/sections/12-protocol-details.md (Cross-session
            loop resume Protocol Details entry).

Upstream deps: content/sections/07-cross-session-loop-resume.md (parent
               section); /implement-ticket Phase 6 loop initialization
               (writes loop-state.json); hooks/stop-context.js (Stop hook
               that writes interrupted status and batch-state mirror).

Downstream consumers: conductor (/implement-ticket resume check at session
                      start); Stop hook (interrupted-status write); any
                      session that may resume a prior implement-ticket run.

Failure modes: loop-state.json is gitignored and must not be committed.
               Silent Stop hook failure is acceptable - the 10-minute
               implicit-interrupt heuristic handles missed writes. Batch-
               state per-write session_id gate prevents orphan-session
               corruption; EWOULDBLOCK on the scaffolding lock is silently
               skipped.

Performance: Standard (local filesystem reads/writes; no network).
-->

> Parent section: `content/sections/07-cross-session-loop-resume.md`. This file contains the complete body of that section verbatim.

## Cross-session loop resume

Long-running `/implement-ticket` loops can survive rate limits and session exits via `.agentic/loop-state.json`:

- **Disk writes at every phase transition.** The conductor writes `.agentic/loop-state.json` (atomic: tmp+rename) at initialization and at every phase transition (Skeptic spawn, Skeptic return, Engineer spawn, Engineer return, QA spawn, QA return, quality gate steps). The `last_phase` and `last_phase_action` fields are the authoritative resume keys.

- **Resume check on session start.** When `/implement-ticket` is invoked, it checks for `.agentic/loop-state.json` before reading AGENTS.md. If `status == "interrupted"` (or `status == "active"` with `last_updated` more than 10 minutes old), the conductor offers resume or fresh start. See `/implement-ticket` Resume check section for the full protocol.

- **Stop hook writes interrupted status.** The Stop hook writes `status: "interrupted"` to `.agentic/loop-state.json` on session exit if the file exists and `status == "active"`. Silent failure is acceptable - the 10-minute implicit-interrupt heuristic handles missed writes.

- **Resumable phases (automatic):** Phase 6/6b Skeptic/QA loop at iteration boundaries (committed Engineer output, clean branch); Phase 7 quality gate when engineer committed (`engineer_returned` / `rerun_pending`).

- **Resumable with human confirmation:** Mid-Engineer (dirty branch) - conductor asks human to discard or commit the partial work.

- **Restart required:** Phases 1-4 (cheap to re-run, no branch side effects). State file is not written until Phase 6 loop initialization.

- **Full Skeptic re-run on interruption.** If a Skeptic is interrupted mid-output, resume re-runs the Skeptic from scratch (last_phase=skeptic, last_phase_action=spawned). Skeptic is read-only and idempotent.

- **Brief/Plan paths recorded.** When a Brief or Plan governs the task, `brief_path`, `plan_path`, and `promotion_tier` (enum: `none`, `brief`, `plan`) are written to `.agentic/loop-state.json` at authoring time. On resume, the conductor re-reads the Brief/Plan before spawning the next worker. Mid-flight escalation from Trivial or single-unit Elevated to Brief or Plan tier authors a retroactive Brief before the next engineer spawn (the in-flight engineer is allowed to return; already-completed units are not retroactively re-reviewed). Brief-tier tasks auto-promote to Plan tier on the 3rd resume.

- **File hygiene:** `.agentic/loop-state.json` must not be committed to git (gitignored). It is set to `status: "complete"` or deleted after the PR is opened.

- **Batch-state coexistence.** When `/implement-ticket` is invoked with 2 or more ticket IDs, a sibling file `.agentic/batch-state.json` tracks batch-level cursor (which tickets are pending, in-progress, complete, blocked) alongside `loop-state.json`'s per-ticket phase cursor. Both files carry a `session_id` field written on every conductor write; every write applies a per-write gate that aborts (with an operator-visible warning) if the file's existing `session_id` belongs to a different session whose `last_updated` is within 10 min, OR if the existing `session_id` is null/absent (legacy state from a prior version is force-takeover-eligible). This prevents orphan-session corruption uniformly across both files. The Stop hook mirrors its `loop-state.json` interrupted-mark write to `batch-state.json` via the same best-effort silent-fail discipline. Single-ticket Trivial invocations never create `batch-state.json` and remain bit-for-bit unchanged. Only one batch per project root is supported; a second concurrent N≥2 invocation is refused at Phase 0a-pre. N=1 invocations against an active foreign batch warn but do not refuse.
