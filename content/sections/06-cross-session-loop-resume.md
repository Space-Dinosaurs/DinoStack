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
