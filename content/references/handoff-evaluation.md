<!--
Purpose: Full reference for Phase 12a of `/ds-implement-ticket` - the
         handoff-evaluation gate that runs after every ticket completes in
         batch, open-goal, and single-ticket-capped modes. Covers the
         goal-met short-circuit, the four handoff triggers (stale-pace,
         operator-pause, wallclock-cap, open-goal-iteration-cap), the
         mode-specific on-trigger writes (batch/single-ticket-capped vs.
         open-goal), and the no-trigger continue/advance paths.

Public API: Read-only reference document, addressed by its retained
            `## Phase 12a: Handoff evaluation (batch, open-goal, and
            single-ticket-capped)` heading. Cross-referenced from
            content/commands/ds-implement-ticket.md at the Phase 12a
            extraction site (pointer paragraph) and from any other section
            that needs the trigger/write detail rather than just the
            phase name "Phase 12a" (used freely elsewhere as a bare
            cross-reference, e.g. Contract sections, Phase 0a-open-goal,
            Phase 6, Phase 12b).

Upstream deps: none (prose reference only; no code, no runtime execution).
               Assumes the reader already has Contract A/B/D (`## Batch
               state contracts` in content/commands/ds-implement-ticket.md)
               and the "Batch-mode escalation routing
               (mark-blocked-and-continue)" subsection (Phase 6) in
               context - both are named, not repeated, here.

Downstream consumers: content/commands/ds-implement-ticket.md (Phase 12a
                      extraction site pointer; Phase 0a-open-goal's
                      "Advance to next iteration" reuse note; Phase 12b's
                      skip conditions, which describe Phase 12a's own
                      pause/exit behavior).

Failure modes: Prose reference; does not auto-execute. A stale copy would
               misdescribe which of the four triggers fired, the
               goal-met short-circuit's precedence over triggers 1-4, or
               the mode-specific `batch-state.json` write shape - keep in
               sync with the live Phase 12a call site whenever the
               trigger set or write contract changes.

Performance: n/a (static reference document).
-->

## Phase 12a: Handoff evaluation (batch, open-goal, and single-ticket-capped)

**Trigger:** `.agentic/batch-state.json` exists (set by Phase 0a when Phase 0 produced ≥ 2 entries during this session) OR set by Phase 0a-open-goal (`goal_mode=open_goal`) OR by the Phase 0a-pre single-ticket-capped carve-out (`max_wallclock_min` alone). Skip when batch-state.json is absent - covers ordinary uncapped single-ticket invocations, unchanged.

After Phase 12 completes for a ticket and BEFORE the conductor advances to the next ticket in the batch, first apply the goal-met short-circuit below, then (if it did not fire) evaluate the four handoff triggers. If a trigger fires, gracefully pause the batch and exit cleanly; if none fire, continue to the next ticket.

**Goal-met short-circuit (open-goal mode, evaluated before triggers 1-4).** If `batch-state.json.mode == "open_goal"` AND `batch-state.json.open_goal.termination_reason == "goal_met"` (set this iteration by Phase 6 "Open-goal condition check"): take the clean COMPLETE exit immediately - set `status: "complete"` on both `batch-state.json` and `.agentic/loop-state-$LOOP_KEY.json` (Contract A), print `OPEN-GOAL LOOP COMPLETE - goal_condition met after N iterations`, and exit the outer loop. Do NOT evaluate triggers 1-4. This guarantees a goal met on the final budgeted iteration (or coincident with a wallclock/iteration cap) records `goal_met`, not `cap_reached_*`, and the operator is not falsely told the goal was unmet. Rationale: `goal_met` is a success terminal state and always takes precedence over any cap/pause trigger that would otherwise fire on the same iteration.

**Triggers (exactly FOUR; any one fires; not evaluated when the goal-met short-circuit above already fired):**

1. **Stale-pace pattern.** The last 2 completed tickets each took more than 2× the median wallclock of completed tickets in this batch. Requires ≥5 completed tickets to be meaningful (below this threshold, sample size is too small to be a reliable signal). `pause_reason: "stale_pace"`. **In open-goal mode:** applies UNMODIFIED - `tickets[]` accumulates one synthetic entry per completed iteration, so the ≥5-completed threshold is satisfied by the same array. For `max_iterations < 5` (e.g. a dry-run test with `max_iterations=3`), trigger 1 is structurally inert (never reaches 5) - expected/correct (a loop capped below 5 is too short for a meaningful pace signal, matching the threshold's own rationale). **In single-ticket-capped mode:** structurally inert (one entry, no pace signal past a single completion).
2. **Operator literal "pause the batch".** Case-insensitive substring match against the most recent operator message. `pause_reason: "operator_pause"`. **In open-goal mode:** applies UNMODIFIED - substring match is orthogonal to mode. **In single-ticket-capped mode:** mode-orthogonal and DOES apply - the operator can still pause a single capped run.

   **Invariant (binding).** The conductor MUST NOT write `pause_reason: "operator_pause"` to `batch-state.json` unless the operator's most recent message contains the literal substring `pause the batch` (case-insensitive). Conductor self-doubt about remaining wallclock, context pressure, perceived pace, or "feeling like the operator might want a break" is NOT a valid `operator_pause` trigger. The correct conductor behavior in those subjective cases is to spawn the next ticket and let `wallclock_cap` (trigger 3) fire mechanically if the cap is actually hit. A conductor that paraphrases the operator, infers intent from "I'm tired" / "let's stop soon" / "we're running long", or pauses preemptively to avoid a future cap hit is violating this invariant - the operator's literal words are the authoritative trigger. If an operator phrases a pause request differently (e.g. "stop after this one"), the correct response is to surface a one-line confirmation (`Proceeding to pause the batch after the current ticket - confirm with 'pause the batch' or override with 'continue'.`) and continue executing until the literal substring arrives.
3. **Wallclock cap.** `now - wallclock_started_at >= wallclock_cap_min` (default 90 min unless `AGENTIC_BATCH_MAX_WALLCLOCK_MIN` env override). `wallclock_started_at` is preserved across resume, so the cap is per-batch lifetime, not per-session. `pause_reason: "wallclock_cap"`. **Single-ticket-capped mode:** trigger 3 is the reason this mode exists - same wallclock-blocked-write action as before.
4. **Open-goal iteration cap** (`mode=="open_goal"` only; inert for `batch`/`single_ticket_capped`). `batch-state.json.open_goal.iteration >= batch-state.json.open_goal.max_iterations`. `pause_reason: "open_goal_iteration_cap"`.

**Single-ticket-capped mode summary:** triggers 1 and 4 are structurally inert (no pace signal past a single entry; no iteration concept). Trigger 2 (operator literal "pause the batch") is mode-orthogonal and DOES apply - the operator can still pause a single capped run. Trigger 3 (wallclock cap) is the reason this mode exists.

(Context-pressure auto-detection is explicitly NOT a trigger; the conductor cannot read its own context %. Operators use trigger 2 if context pressure is observed.)

**On trigger - batch and single-ticket-capped modes (`mode != "open_goal"`):** apply Contract A + Contract B and write `batch-state.json` with:
- `status: "paused"`
- `paused_at: now`
- `pause_reason: <trigger>`
- `last_summary` populated for the ticket just completed
- `replan_log[]` preserved (Contract B)

Print the structured remaining-tickets summary:

```
BATCH PAUSED — pause_reason: <trigger>
Completed: <k>/<N> tickets
  ✓ <ticket_id> (PR #<pr_number>)
  ...
Remaining: <N-k> tickets
  · <ticket_id> (depends_on: <list>, status: <status>)
  ...
Resume: /ds-implement-ticket from this directory
```

**Single-ticket-capped mode, trigger 3 only** (triggers 1/4 structurally inert): reuse the "Batch-mode escalation routing" blocked-write, print `SINGLE-TICKET WALLCLOCK CAP REACHED - pause_reason: wallclock_cap`, `status: "paused"`, exit cleanly.

Note: N is the executable-cursor count (lane-assigned tickets only). Deferred and in-progress-excluded tickets were surfaced in Phase 0a step 2 and are not included in N.

Exit cleanly. Do NOT advance to the next ticket. Emit breadcrumb: `[phase: batch-paused | reason=<trigger>]`.

**On trigger - open-goal mode (`mode=="open_goal"`), ANY of the four triggers:** in addition to the existing `batch-state.json{status:"paused", paused_at, pause_reason:<trigger>, last_summary}` write (Contract A+B, unchanged, applies to all 4 as above), ALSO write `open_goal.termination_reason`: trigger 1 → `"paused_stale_pace"`, trigger 2 → `"paused_operator_request"`, trigger 3 → `"cap_reached_wallclock"`, trigger 4 → `"cap_reached_iterations"`. Print header (all 4 triggers): `OPEN-GOAL LOOP PAUSED - pause_reason: <trigger>` (replacing `BATCH PAUSED`); resume line: `Resume: /ds-implement-ticket ... goal_mode=open_goal ... (raise max_iterations/max_wallclock_min to continue, or accept the goal as unmet)`. Single mode-conditional branch covering all four triggers.

**On no trigger, batch and single-ticket-capped modes:** continue to the next ticket in the batch.

**On no trigger, open-goal mode:** the goal-met short-circuit above already handles the `termination_reason == "goal_met"` case before triggers are evaluated, so reaching this branch means the goal was not yet met on this iteration. Apply the "Advance to next iteration" write from Phase 0a-open-goal - Contract A+B write incrementing `open_goal.iteration` AND appending the next `pending` synthetic `tickets[]` entry IN THE SAME WRITE (keeps `iteration == len(tickets[])` intact) - and continue the outer loop at Phase 1.

> Note: see the "Interrupt vs. pause path note" and "Resume banners" paragraphs in `content/commands/ds-implement-ticket.md` §"Phase 12a: Handoff evaluation (batch, open-goal, and single-ticket-capped)" for the `paused_at`/`interrupted_at` distinction and the canonical resume-banner wording. The kernel command file is the SOURCE OF TRUTH for both resume-banner lines (kept there so `scripts/codex-skills.py`'s `documents()` transform, which only reads content/commands/*.md, still sees these operational literals - the `hooks/session-end-wrap.js` path and the `/ds-implement-ticket` resume-banner self-reference both need adapter-specific rewriting); the full print examples above ALSO show the resume line inline, for readability of the complete printed output - if the two ever disagree, the kernel paragraph governs.
