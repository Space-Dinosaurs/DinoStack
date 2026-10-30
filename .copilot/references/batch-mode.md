<!--
Purpose: Full procedure for multi-ticket batch mode of
         `/ds-implement-ticket`, moved verbatim out of
         content/commands/ds-implement-ticket.md so a single-ticket run
         does not carry it. Covers the Phase 0a-pre batch resume
         decision table and re-plan migration, the Phase 0a batch triage
         flow, and the action list of Phase 6's "Batch-mode escalation
         routing (mark-blocked-and-continue)".

Public API: Read-only reference document, addressed by its retained
            headings. Each section's heading, trigger, and skip text
            (including Phase 0a-pre's single-ticket wallclock carve-out
            and the escalation routing's single-ticket line) stay inline
            in content/commands/ds-implement-ticket.md, followed by a
            one-line `**Procedure:**` pointer to this file. The Phase 6
            heading below is the parent of the moved subsection only.

Upstream deps: none (prose reference only; no code, no runtime execution).
               Assumes Contracts A-C and the `batch-state.json` schema
               (`## Batch state contracts (binding)` in
               content/commands/ds-implement-ticket.md) are in context;
               /ds-ticket-triage Phases 1-3 by reference.

Downstream consumers: content/commands/ds-implement-ticket.md (Phase
                      0a-pre, Phase 0a, and escalation-routing pointer
                      lines); content/references/handoff-evaluation.md
                      (names "Batch-mode escalation routing").

Failure modes: Prose reference; does not auto-execute. A conductor that
               skips the pointer runs a batch without its resume table,
               triage, or blocked-and-continue writes - the inline
               trigger lines exist to make the Read unconditional when
               the trigger holds.

Performance: n/a (static reference document).
-->

## Phase 0a-pre: Batch resume check

**Read** `.agentic/batch-state.json` if present. Apply the decision table below.

| `batch-state.json` state | Action |
|---|---|
| absent | Skip Phase 0a-pre. Fall through to the existing per-ticket Resume check, then Setup, then Phase 0a (which initializes `batch-state.json`). |
| `status=complete` | Print: "Prior batch complete; clearing." Delete the file. Fall through to the existing per-ticket Resume check. |
| `status=stalled` | Print stalled summary (tickets + reasons). Prompt: `resume / fresh / abandon`. On `abandon`: delete file and exit. On `fresh`: delete file and fall through. On `resume`: apply re-plan migration (below) and pick next pending ticket. |
| `status=paused` | Print: `"Batch paused at operator request: [last_summary]."` Prompt: `resume / fresh`. On `fresh`: delete file and fall through. On `resume`: apply re-plan migration and pick next pending ticket. |
| `status=interrupted` | Print: `"Batch interrupted (reason: [interrupt_reason]). N completed, M pending/blocked."` Prompt: `resume / fresh`. On `fresh`: delete file and fall through. On `resume`: apply re-plan migration and pick next pending ticket. |
| `status=active` AND `updated_at > 10 min` ago | Treat as implicit interrupt. Same prompt as `interrupted` row. |
| `status=active` AND `updated_at ≤ 10 min` AND `session_id` matches current | Silent re-entry resume (rare; e.g. `/ds-implement-ticket` re-invoked within the same session). Pick next pending ticket from `tickets[]`. |
| `status=active` AND `updated_at ≤ 10 min` AND `session_id` is null/absent AND the CURRENT session's own id is ALSO null (self-ownership carve-out - see Contract A step 3) | Treat as self-owned: same as the row above (silent re-entry resume). Do NOT force-takeover-prompt or refuse - on a harness that cannot produce a matching session id, two nulls are indistinguishable by construction, so this is the only branch that lets such a harness resume its own batch at all. |
| `status=active` AND `updated_at ≤ 10 min` AND (`session_id` differs OR (`session_id` is null/absent AND the CURRENT session HAS its own non-null id, i.e. the self-ownership carve-out row above does NOT apply)) | If Phase 0 produced ≥ 2 entries: refuse with the verbatim Contract C message. If Phase 0 produced exactly 1 entry: see "N=1 foreign-batch warning" in `ds-implement-ticket.md` §Batch state contracts (binding); this row does not apply (Phase 0a-pre runs only when Phase 0 produced ≥ 2 entries). For N≥2 force-takeover prompts: print `"WARNING: another session (session_id=<X>, updated_at=<Y>) may still be active. Force takeover? (yes/no). Identify the live session via .agentic/batch-state.json updated_at."` and require explicit operator confirmation. |
| Parse failure | Print warning. Prompt: `delete-and-fresh / abort`. On `abort`: exit. On `delete-and-fresh`: delete file and fall through. |
| Inconsistent pair (`batch-state.json` says `active`, the PICKED ticket's own `loop-state-$LOOP_KEY.json` says `interrupted`) | Trust the non-active file. If both are stale-active (>10 min), treat as implicit interrupt for both. Scope this row to the picked ticket's keyed file only - another ticket's keyed file is not part of this pair and must not be consulted. |

**Move ordering hazard (resume case).** On resume, `batch-state.json.tickets[]` is the authoritative ticket cursor and supersedes any Phase 0 output produced in the resuming session. If the operator re-supplied input, compare Phase 0 entries[] against on-disk tickets[]:

- **SUBSET match (all tickets[] IDs are present in entries[], but entries[] has extras):** this is NOT a hazard. The extras were deferred or excluded at original triage time. Note: extras beyond the original deferred set that were not part of the original input are not auto-added on resume - surface them to the operator or run them separately; they are never mis-run. Proceed silently with `batch-state.json.tickets[]` as the cursor.
- **GENUINE divergence (tickets[] contains IDs NOT present in entries[]):** surface the warning below.

```
WARNING: resumed batch tickets[] = [<list>] contain ticket IDs not present in this invocation's Phase 0 entries[] = [<list>].
The on-disk batch state takes precedence on resume. Continue resuming the prior batch, or abandon resume and use the new input?
(continue-resume / abandon-resume-and-use-new-input)
```

On `continue-resume`: discard Phase 0 output, use `batch-state.json.tickets[]`. On `abandon-resume-and-use-new-input`: delete `batch-state.json` and re-run Phase 0a from the new entries.

**Resume composition rule (binding).** If Phase 0a-pre confirms resume of an active batch, it sets the in-memory ticket cursor to the next pending ticket from `tickets[]` BEFORE falling through to the existing per-ticket Resume check. The per-ticket Resume check then runs UNMODIFIED but scoped to the picked ticket's branch and its own `loop-state-$LOOP_KEY.json`, with `LOOP_KEY` derived from the picked ticket id. The two state mechanisms compose: batch resume picks the ticket; per-ticket resume picks the phase within that ticket. They have non-overlapping scopes.

**Re-plan migration on resume.** When the operator confirms resume of any non-active batch state (`stalled`, `paused`, `interrupted`, or stale-`active` treated as interrupted):

1. `git fetch origin`.
2. For each ticket in `tickets[]` with `status` `pending` or `blocked`: re-fetch the tracker record. If the ticket has been merged elsewhere (per tracker status, or per `gh pr list --state merged --head <branch>` returning a non-empty result), append a `replan_log` entry `{ts, action: "drop_merged", ticket_id, detail}` and set the ticket's `status` to `skipped_already_merged`.
3. Run /ds-ticket-triage Phases 1-3 over the surviving pending/blocked tickets to re-sequence. Level 2 investigator (Phase 2b) is gated on `replan_count >= 2`: count `replan_log` entries with `action: "investigator_rerun"`; if the count is >= 2, spawn a real background investigator (including the functional-duplicate brief); otherwise run Level 1 only (conductor-direct). Append the `replan_log` entry `{ts, action: "investigator_rerun", ticket_id: null, detail: "replan #N"}` BEFORE spawning the investigator when it fires. Map the resulting lanes back to the surviving tickets' `cluster_id` and `depends_on` fields (array order); deferred or in-progress-excluded tickets discovered during re-plan are surfaced to the operator and excluded from tickets[].
4. All writes apply Contract A (per-write `session_id` gate) and Contract B (`replan_log[]` read-merge-write preservation). See "Batch state contracts" in `ds-implement-ticket.md` §Batch state contracts (binding).
5. Bump `status` back to `active`. Preserve `wallclock_started_at` from the prior batch (the wallclock cap is per-batch lifetime, not per-session - a batch resumed in a later session continues counting against the original `wallclock_started_at`).

Emit breadcrumb: `[phase: batch-resume | tickets_remaining=K]`.

## Phase 0a: Batch triage (Phase 0 produced ≥ 2 entries)

<!--
Phase 0a manifest:
  Purpose: run /ds-ticket-triage Phases 1-3 (algorithm by reference) over the Phase 0
           entries[], surface triage results to the operator, map lane-assigned tickets
           to batch-state.json, then iterate per-ticket phases 1-12 in array order.
  Public API: reads Phase 0 entries[]; writes .agentic/batch-state.json tickets[]
              (lane-assigned only; deferred and in-progress-excluded are NOT written).
  Upstream deps: /ds-ticket-triage Phases 1-3 (algorithm reference - no copy);
                 investigator (Phase 2b Level 2, conditional on len(entries) <= 20);
                 Phase 0 entries[] (already normalized, no re-normalization).
  Downstream consumers: Phase 0a-pre (resume), Phase 12a (handoff), all per-ticket
                        phases (1-12) which iterate tickets[] in array order.
  Failure modes: soft-fail per ticket in Phase 1 metadata fetch; HEURISTIC_ONLY=true
                 when len(entries)>20; functional-duplicate defer prompts are
                 operator-gated (one prompt per pair after Phase 3).
-->

**Flow:**

1. **Run the /ds-ticket-triage planning algorithm (Phases 1-3) conductor-orchestrated.** Phase 0a feeds its OWN already-normalized `entries[]` directly into triage Phase 1 - triage Phase 0 is NOT re-run (entries are already normalized).

   - **Phase 1 (metadata fetch, conductor-direct, soft-fail):** for each entry, fetch priority, status, story_points, labels, components, assignee, and issuelinks from the tracker (same per-ticket fetch as /ds-ticket-triage Phase 1). Soft-fail per ticket (mark `fetch_failed: true` and proceed). Detect `terminal: true` (Done/Cancelled) and `in_progress: true` (active workflow state) per the /ds-ticket-triage Phase 1 rules.

   - **Phase 2a (DAG + cycle handling, conductor-direct):** build the dependency graph from `blocks`/`is-blocked-by` links, detect cycles (break at lowest-confidence link, defer both with `cycle_warning: true`). External deps noted but not used for lane assignment.

   - **Phase 2b conflict-surface analysis:** Level 1 is always conductor-direct (shared component/label overlap check). Level 2 applies when `len(entries) <= 20`: spawn ONE real background investigator with the full /ds-ticket-triage Phase 2b brief, including the functional-duplicate detection task (bar: "a reasonable engineer would implement them with exactly the same change"). When `len(entries) > 20`: set `HEURISTIC_ONLY=true` and proceed WITHOUT prompting - rationale: the batch was already committed via Phase 0, and prompting mid-initialization wastes operator context.

   - **Phase 3 (Rules 1-4, conductor-direct):** distribute surviving tickets across lanes using the /ds-ticket-triage Phase 3 consume-and-remainder pipeline. Lane cap is fixed at 3 on this path (`--lanes` override is not available for the /ds-implement-ticket integration path).

   The result is an in-memory `triage_result` containing:
   `{lanes[], deferred[], in_progress_excluded[], functional_duplicates[], conflict_warnings[], heuristic_only}`.

2. **Surface triage findings to the operator BEFORE building tickets[].** Present a structured summary covering:

   - **Functional duplicate warnings** (when `functional_duplicates[]` is non-empty): for each pair, print the ticket IDs and the one-sentence reason. Prompt the operator PER PAIR (after all lane assignments are known, since Phase 3 has already run):

     ```
     Functional duplicate detected: <A> + <B> - <summary>
     Both tickets appear to describe the same functional work.
     Action: (defer-first / defer-second / keep-both)
     ```

     On `defer-first`: add ticket A to `deferred[]`, remove it from its lane. On `defer-second`: add ticket B to `deferred[]`, remove it from its lane. On `keep-both`: no change. Do NOT recompute the lane distribution after a defer choice - surgically remove the deferred ticket from its lane only.

   - **Deferred tickets** (from Phase 3 Rule 1 + any operator-deferred duplicates): list each with its reason.

   - **In-progress tickets** (from Phase 1): list each. These are excluded from tickets[] and kickoff.

   - **HEURISTIC_ONLY notice** (when `HEURISTIC_ONLY=true`): "Conflict analysis: Level 1 only (component/label overlap; >20 tickets, investigator pass skipped). Functional-duplicate detection was also skipped."

   After surfacing, map ONLY the lane-assigned tickets to `tickets[]` (deferred and in-progress-excluded tickets are NOT written to tickets[]).

   Map in ARRAY ORDER: lane 1 first, lane 2 next, lane 3 last. Within each lane, chains are topo-sorted (blockers first); parallel tickets within the same lane are sorted priority-descending then ticket_id-ascending. Each entry:
   - `status: "pending"`
   - `cluster_id: "lane-N"` (where N is the lane number)
   - `depends_on: ["<prev-ticket-id>"]` (chain) or `[]` (parallel lane head or independent)

   No `merge_order` field. Array position is the execution cursor.

   Emit breadcrumb: `[phase: batch-triage | triage_algorithm=ticket-triage-phases-1-3 | N tickets | lanes=K | lane_cap=3 | deferred=P | excluded_in_progress=Q | heuristic_only=<bool>]`.

3. **Initialize `.agentic/batch-state.json`** (persistent batch cursor). First apply the Contract C concurrent-batch refusal: if the file already exists with `status=active`, a different `session_id`, and `updated_at` within the last 10 minutes, REFUSE with the verbatim Contract C message and exit. Otherwise, write the initial skeleton:
   - `schema_version: 1`
   - `session_id: <current>`
   - `batch_id: "<first ticket's TICKET_PREFIX>-batch-<ISO8601>-<4hex>"`
   - `status: "active"`
   - `tickets[]`: triage-derived executable cursor; contains only lane-assigned tickets (deferred and in-progress-excluded tickets are not included); in array order as described in step 2 above
   - `wallclock_started_at: now`, `wallclock_cap_min: <env AGENTIC_BATCH_MAX_WALLCLOCK_MIN or 90>`
   - `replan_log: []`
   - `created_at: now`, `updated_at: now`

   Atomic tmp+rename. Apply Contract A on the write (this is a fresh write so no prior `session_id`; the gate effectively passes).

4. Conductor iterates through tickets[] in array order (tickets[] contains only lane-assigned executable tickets; deferred and in-progress-excluded tickets were surfaced in step 2 and are not present), running existing per-ticket phases (1 → 12) for each ticket. **Per-ticket transition writes to `batch-state.json`** (each via Contract A + Contract B):
   - At ticket start: `status: "pending" → "in_progress"`, set `started_at`, update `updated_at`.
   - At ticket complete: `status: "in_progress" → "complete"`, set `ended_at`, `last_summary`, `pr_number`, `branch`.
   - At ticket block: `status → "blocked"` with detail in `last_summary`.
   - At ticket merged-elsewhere skip: `status → "skipped_already_merged"` with `replan_log` append.

**Persistent batch state lives in `.agentic/batch-state.json`. See Phase 0a-pre for the resume protocol.**

## Phase 6: Skeptic review

### Batch-mode escalation routing (mark-blocked-and-continue)

**Action:**
1. Print the Escalation format/stalled summary unchanged and visible.
2. Contract A+B write: find this ticket's/iteration's `tickets[]` entry, set `status:"blocked"`, `last_summary`=one-line synopsis.
3. Print `"Ticket <ticket_id> marked blocked; advancing to next pending ticket in the batch."`; skip Phases 7-12 for this ticket.
4. **Batch mode (`mode=="batch"` or absent):** advance to next `pending` ticket, array order, enter at Phase 1.
5. **Open-goal mode (`mode=="open_goal"`):** do NOT auto-advance - write `open_goal.termination_reason` to the triggering reason (`blocked`, `cap_reached_iterations`, or the equivalent) and STOP the outer loop (surface and wait for human); the `blocked` write in step 2 still happens for audit.
