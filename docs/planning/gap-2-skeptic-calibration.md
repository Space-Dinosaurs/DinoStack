## Technical Plan: Gap 2 - Skeptic Calibration Drift

### Convergence note - iteration 3

Iteration 2 Skeptic withheld sign-off with 2 NEW Majors + 2 NEW Minors. All addressed:

- **Major 1 (NEW)** (cross-session surfacing gap): Added session-start sweep of `.agentic/events.jsonl` with append-only surfaced-tracker file `.agentic/.meta-divergence-surfaced`. Documented in `content/rules/conventions.md` (canonical session-startup location; no `02-session-startup.md` exists - sections/02 is delegation). Step 10 updated to describe BOTH in-session scan AND session-start sweep. See "API / interface design > Meta-divergence surfacing protocol" and step 10.
- **Major 2 (NEW)** (subagent writes to `.agentic/` violate single-writer): Chose option (a) - dropped the calibration log file entirely. `events.jsonl` already records `meta_review_complete`; `bin/agentic-calibrate` is the queryable surface. Data-model section, step 10, and Trade-offs updated to remove the calibration log.
- **Minor 1 (NEW)** (density divide-by-zero): `agentic-calibrate density` excludes spawns where `diff_lines == 0` from the per-100-lines aggregate; per-row output prints `N/A` for zero-diff rows. Documented in CLI spec.
- **Minor 2 (NEW)** (anti-collision vs Gap 3): Stated explicitly in "Anti-collision" - Gap 2 does NOT touch `content/sections/01-activation-preflight.md` and does NOT create `bin/agentic-status` or `bin/agentic-disable`. Both gaps edit `docs/agentic-engineering.html`; mechanical merge.

### Convergence note - iteration 2

Iteration 1 Skeptic withheld sign-off with 4 Majors + 6 Minors. All addressed:

- **Major 1** (meta-Critical surfacing policy): Section 13 sub-clause "Meta-divergence surfacing" + Phase 6 surfacing logic. See "API / interface design > Meta-divergence surfacing protocol" and Implementation step 11.
- **Major 2** (`bin/agentic-emit` flag conflict): Dropped flag extensions. Skeptic-specific fields are added INSIDE the existing positional `<json_data>` argument by the conductor. Implementation step 7 removed; conductor-side JSON construction documented in "API / interface design > Event payload extension".
- **Major 3** (empty-sign-off rationale theatre): Chose option (a). Rule dropped. Section 5 audit-note + meta-review sampling carry the load. See Trade-offs.
- **Major 4** (Gap 1 docs-sync collision): PR #30 merged at 21016ad on main. Gap 2 rebases on post-#30 main. See "Codebase context > Anti-collision".
- **Minor 1** (manifest header for `bin/agentic-calibrate`): Acceptance criterion in step 8.
- **Minor 2** (Marp .html rebuild same PR): Stated in step 12.
- **Minor 3** (in-band meta-Skeptic latency): Chose option (b) - background fire-and-forget. See "Approach" and step 11.
- **Minor 4** (warming-up baseline): Output line in `/agentic-calibrate density`. See step 9.
- **Minor 5** (counter gameability threat model): Stated once. See "Trade-offs and constraints".
- **Minor 6** (events-log field docs): `content/sections/07-events-log.md` updated. See step 6.

### Approach

Add a calibration layer to the Skeptic protocol that detects drift over time without enlarging the per-spawn review surface. Three mechanisms: (1) per-Skeptic-spawn structured findings counters in the existing events log, (2) a 5% background meta-Skeptic sampling pass on completed sign-offs that runs fire-and-forget after the conductor declares the unit complete, and (3) an inspection CLI (`bin/agentic-calibrate`) that summarizes findings density and meta-divergence rate from `.agentic/events.jsonl`. Original Skeptic sign-off remains binding for merge decisions; meta-divergence on Critical/Major findings is surfaced inline to the user as advisory. No subagent writes to `.agentic/`; all structured state flows through `events.jsonl` (conductor-written) plus the gitignored surfaced-tracker file (also conductor-written).

### Codebase context

Relevant files:

- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/references/skeptic-protocol.md` - canonical Skeptic spec; sections 5, 6, 11 govern findings classification, sign-off format, and audit notes.
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/sections/07-events-log.md` - events log schema and field documentation.
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/commands/implement-ticket.md` - Phase 6 Skeptic loop orchestration; meta-spawn integration point.
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/rules/conventions.md` - canonical session-startup location ("Session startup:" line, ~L18). Session-start sweep for unsurfaced meta-divergence events is added here.
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/bin/agentic-emit` - positional CLI: `<event> <agent> <task_id> <json_data>`. NOT extended via flags.
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/bin/` - location for new `agentic-calibrate` binary; existing bins as style reference.
- `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/docs/agentic-engineering.html` and `docs/slides/skeptic-protocol-slides.md` - docs surfaces requiring sync.

**Anti-collision (Gap 1).** Gap 1 docs sync landed as PR #30 (commit 21016ad on main). Gap 2 branches from post-#30 main; no in-flight collision risk. Standard rebase on `develop`/`development` if branch lifetime exceeds a day.

**Anti-collision (Gap 3).** Gap 2 does NOT touch `content/sections/01-activation-preflight.md` and does NOT create `bin/agentic-status` or `bin/agentic-disable` - those are Gap 3 territory. The only shared surface is `docs/agentic-engineering.html` (Marp rebuild artifact); collisions there are mechanical merges of regenerated HTML and resolve by re-running the Marp build on the merged source.

Conventions to follow: events log is single-writer (conductor); subagents do NOT write to `.agentic/`; JSONL append discipline (`>>`); module manifest header on new non-trivial bins; Marp HTML rebuild must accompany slide source edits in the same PR.

### Data model

No schema migration. Two extensions:

1. **Events log** (`.agentic/events.jsonl`): the existing `spawn_complete` event for `agent: "skeptic"` gains additional fields inside the existing `data` object. A new event type `meta_review_complete` (agent: `skeptic-meta`) is appended by the conductor when meta-Skeptic returns. No subagent writes.
2. **Surfaced-tracker file** (new file, gitignored): `.agentic/.meta-divergence-surfaced` - append-only newline-delimited list of `original_task_id` values whose meta-divergence has been surfaced to the user. Written by the conductor only. Ensures each divergence surfaces at most once across session boundaries.

The previously-proposed `.agentic/skeptic-calibration.md` log is DROPPED. Rationale: it would require a subagent (meta-Skeptic) to write to `.agentic/`, violating the single-writer convention. `events.jsonl` already records the same data structurally, and `bin/agentic-calibrate` is the queryable surface.

### API / interface design

**Event payload extension (binding):**

`spawn_complete` events for `agent == "skeptic"` carry these fields inside `data`:

```json
{
  "ts": "2026-04-30T12:00:00Z",
  "phase": "skeptic-review",
  "event": "spawn_complete",
  "agent": "skeptic",
  "task_id": "<id>",
  "data": {
    "findings_count": {"critical": 0, "major": 1, "minor": 3},
    "diff_lines": 142,
    "signed_off": true,
    "iteration": 2,
    "meta_review": null
  }
}
```

`meta_review` is `null` when the unit is not sampled. When sampled and completed, a SEPARATE follow-up event is appended by the CONDUCTOR (event type: `meta_review_complete`, agent: `skeptic-meta`) carrying:

```json
{
  "data": {
    "original_task_id": "<id>",
    "divergence": {"critical_missed": [], "major_missed": [], "minor_missed": []},
    "agreement": true
  }
}
```

The conductor receives meta-Skeptic's textual divergence report on background-spawn return, parses it, constructs the JSON payload, and emits via `bin/agentic-emit meta_review_complete skeptic-meta <original_task_id> <json_data>`. Meta-Skeptic itself never touches `.agentic/`.

**`bin/agentic-calibrate` CLI:**

```
agentic-calibrate density [--since <ISO8601>] [--task <task_id>]
agentic-calibrate divergence [--since <ISO8601>]
agentic-calibrate help
```

`density` reads `.agentic/events.jsonl`, filters Skeptic spawn_complete events, and prints findings-per-100-diff-lines aggregates plus a per-iteration breakdown.

- **Zero-diff handling:** spawns where `diff_lines == 0` (spec-only or doc-only diffs) are excluded from the aggregate density calculation. Per-row output prints `N/A` in the density column for those rows. The aggregate denominator is the sum of non-zero `diff_lines` only.
- **Warming-up output:** when fewer than 10 spawns are observed (after zero-diff exclusion), prints `warming up: N/10 spawns observed; baseline not yet established.`

`divergence` reads `meta_review_complete` events and prints divergence rate (Critical/Major/Minor missed counts and % of sampled).

Exit codes: 0 success, 1 missing events log, 2 malformed input.

**Meta-divergence surfacing protocol (binding):**

When meta-Skeptic finds a Critical or Major finding the original Skeptic missed, the conductor surfaces this at the next user-facing turn boundary as a single inline line:

```
META-DIVERGENCE: meta-Skeptic identified [Critical|Major] '<finding-title>' that original Skeptic missed on <task_id>. Original sign-off stands; review recommended before merging.
[phase: meta-divergence-critical]
```

Original sign-off remains binding for the merge decision. Minor-only divergences are NOT surfaced inline; they appear in `agentic-calibrate divergence` output.

**Surfacing has TWO triggers (both binding):**

1. **In-session scan.** At each turn boundary entering Phase 6 or returning from a Worker, the conductor scans `.agentic/events.jsonl` for `meta_review_complete` events whose `original_task_id` is NOT present in `.agentic/.meta-divergence-surfaced`. For any with non-empty `critical_missed` or `major_missed`, emit the META-DIVERGENCE line and append `original_task_id` to the surfaced-tracker file.

2. **Session-start sweep.** On every session boot (first turn of session), the conductor sweeps `.agentic/events.jsonl` for ALL `meta_review_complete` events (across all task_ids) whose `original_task_id` is not in `.agentic/.meta-divergence-surfaced`. Emits META-DIVERGENCE line for each Critical/Major divergence and appends to the tracker. This catches divergences whose meta-Skeptic completed asynchronously after the originating session ended.

Tracker file format: one `original_task_id` per line, append-only. Conductor checks membership by reading the file once per session boot and once per in-session scan; updates by appending. File absent is equivalent to empty set.

**Sampling policy:** 5% of Skeptic sign-offs trigger a meta-review. Selection is deterministic: hash `task_id` + iteration into a uniform 0-99 bucket; trigger if bucket < 5.

**Spawn discipline:** Meta-Skeptic spawns are background fire-and-forget. The conductor declares the unit complete WITHOUT waiting for meta-Skeptic return. On meta-Skeptic return, the conductor (not the subagent) writes the `meta_review_complete` event.

### Implementation steps

1. Branch from post-PR-#30 main: `feature/gap-2-skeptic-calibration`.
2. Edit `content/references/skeptic-protocol.md`: add Section 13 "Calibration mechanisms" covering findings counters, sampling protocol, meta-divergence surfacing protocol (both in-session and session-start triggers), and threat model statement.
3. Edit `content/references/skeptic-protocol.md` Section 5: add cross-reference noting that the audit-note mechanism is the primary defense against rubber-stamp risk; calibration sampling is the secondary backstop.
4. Edit `content/references/skeptic-protocol.md` Section 11: leave sign-off format unchanged (Major 3 resolution: option (a)).
5. Edit `content/commands/implement-ticket.md` Phase 6: after Skeptic sign-off and before declaring unit complete, the conductor (a) constructs the extended `data` JSON payload with `findings_count`, `diff_lines`, `signed_off`, `iteration`, `meta_review: null` and emits via `bin/agentic-emit spawn_complete skeptic <task_id> <json_data>`; (b) computes the deterministic 5% sampling bucket; (c) if sampled, spawns meta-Skeptic in background (fire-and-forget); (d) on meta-Skeptic return (asynchronous), the conductor parses the divergence report and emits `meta_review_complete`.
6. Edit `content/sections/07-events-log.md`: document the Skeptic-specific `spawn_complete` `data` fields (`findings_count`, `diff_lines`, `signed_off`, `iteration`, `meta_review`) and the new `meta_review_complete` event type with its fields. Note that conductor is the single writer for both; meta-Skeptic returns text only. Cross-reference Section 13 of skeptic-protocol.
7. (REMOVED - Major 2 iteration 1 fix; no `bin/agentic-emit` change needed.)
8. Create `bin/agentic-calibrate` (new file, ~150 LOC bash or python). Acceptance criteria: (a) includes module manifest header per `content/rules/module-manifest.md`; (b) implements `density`, `divergence`, `help` subcommands per CLI spec above; (c) `density` excludes `diff_lines == 0` rows from aggregate and prints `N/A` per-row; (d) `density` output includes warming-up line when N < 10 (after zero-diff exclusion).
9. Verify warming-up and zero-diff output by manual fixtures: empty events log -> `warming up: 0/10 spawns observed`; events log with all `diff_lines == 0` rows -> `warming up: 0/10 spawns observed` and per-row `N/A`.
10. Edit `content/commands/implement-ticket.md` Phase 6 surfacing block AND `content/rules/conventions.md` "Session startup" block to add the dual-trigger surfacing logic:
    - **In-session (Phase 6):** at each turn boundary entering Phase 6 or returning from a Worker, scan `.agentic/events.jsonl` for `meta_review_complete` events whose `original_task_id` is not in `.agentic/.meta-divergence-surfaced`; for any with non-empty `critical_missed` or `major_missed`, emit META-DIVERGENCE line and append `original_task_id` to tracker.
    - **Session-start (conventions.md):** on first turn of session, after reading `.agentic/context.md`, sweep `.agentic/events.jsonl` for ALL unsurfaced `meta_review_complete` events; surface each Critical/Major divergence with the META-DIVERGENCE line and append to tracker. Standalone scan, not parallel with other startup tool calls.
    - Tracker file `.agentic/.meta-divergence-surfaced` is gitignored (covered by existing `.agentic/` gitignore block).
11. Add meta-Skeptic spawn brief template to `content/references/skeptic-protocol.md` Section 13: meta-Skeptic receives the original diff, the original Skeptic's findings list, and the original sign-off; produces a divergence report as TEXT in its return summary. Spec is observational. Explicitly state: meta-Skeptic does NOT write to `.agentic/`; conductor parses the return text and emits the event.
12. Edit `docs/slides/skeptic-protocol-slides.md` to mention calibration layer (one slide). Rebuild Marp `.html` artifact in the SAME PR. Edit `docs/agentic-engineering.html` synchronously.
13. Update `MEMORY.md` if a stable convention emerges (sampling rate, tracker file location).

**Manifest note:** `bin/agentic-calibrate` is a new non-trivial bin. Manifest header required (per Minor 1 iteration 1).

### Trade-offs and constraints

**Alternatives considered:**

- **Per-spawn meta-review on 100% of sign-offs**: rejected - doubles Skeptic cost for marginal calibration signal; sampling is sufficient for drift detection.
- **In-band (synchronous) meta-Skeptic spawn**: rejected per Minor 3 iteration 1 - 1-3min latency on 5% of sign-offs is user-visible and meta-review is observational only; background fire-and-forget is correct.
- **Empty-sign-off rationales rule (Major 3 iteration 1 option b)**: rejected - format-only rule duplicates Section 5 audit-note. Option (a) chosen for simplicity.
- **Random (non-deterministic) sampling**: rejected - non-deterministic selection prevents retroactive replay and adds RNG state to the conductor.
- **New event types per Skeptic field**: rejected - extending `data` inside existing `spawn_complete` preserves the events log's stable event-type vocabulary.
- **Calibration log file (`.agentic/skeptic-calibration.md`) written by meta-Skeptic** (Major 2 iteration 3 option b): rejected - violates single-writer convention even with conductor-as-parser variant; events.jsonl already carries the same structured data and `agentic-calibrate` is the queryable surface. Adding a duplicate file is pure overhead.
- **In-session-only surfacing** (no session-start sweep): rejected per Major 1 iteration 3 - background meta-Skeptic completing after session end would never surface; cross-session coverage is required for the mechanism to be reliable.

**Threat model for counter gameability:** The deterministic counter and findings density metrics are designed for drift detection in a non-adversarial conductor relationship. They are not cheating-prevention mechanisms. A conductor that wishes to mis-emit findings counts can do so; the threat model is operator self-deception over time, not adversarial spoofing.

**Known limitations:**

- Sampling rate (5%) is hardcoded. If drift signal is too noisy, a follow-up tunes via config.
- Meta-Skeptic spawned fire-and-forget cannot be awaited; if the meta-Skeptic itself fails or is interrupted, the divergence event simply never appears. Acceptable since meta-review is observational.
- `agentic-calibrate` reads only the local events log; no aggregation across machines or sessions.
- Original sign-off remains binding even when meta-divergence flags a Critical. The user MAY pause the merge based on the META-DIVERGENCE notice, but the protocol does not auto-block. Explicit design choice: meta-review is advisory.
- Surfaced-tracker file is project-local and gitignored. A user moving across machines mid-task may see a divergence resurface on the new machine. Acceptable - the surface is idempotent (one inline line) and resurfacing once is preferable to silent loss.

### Open questions

None.
