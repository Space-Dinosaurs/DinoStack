<!--
Purpose: Full procedure for the open-goal loop of `/ds-implement-ticket`,
         moved verbatim out of content/commands/ds-implement-ticket.md so
         a single-ticket run does not carry it. Covers Phase 0a-open-goal
         (resume-vs-fresh classification, advance-to-next-iteration,
         fresh init) and steps 2-4 of Phase 6's "Open-goal condition
         check" (risk_declared write, evaluator scope gate, return
         handling).

Public API: Read-only reference document, addressed by its retained
            headings. Each section's heading, trigger, and skip gate stay
            inline in content/commands/ds-implement-ticket.md, followed by
            a one-line `**Procedure:**` pointer to this file. The Phase 6
            heading below is the parent of the moved subsection only;
            the rest of Phase 6 stays in the command.

Upstream deps: none (prose reference only; no code, no runtime execution).
               Assumes Contracts A-C and the `batch-state.json` schema
               (`## Batch state contracts (binding)` in
               content/commands/ds-implement-ticket.md) are in context.

Downstream consumers: content/commands/ds-implement-ticket.md (Phase
                      0a-open-goal and Phase 6 "Open-goal condition
                      check" pointer lines); content/references/handoff-evaluation.md
                      (Phase 12a advance and goal-met paths reference these steps by name).

Failure modes: Prose reference; does not auto-execute. A conductor that
               skips the pointer runs an open-goal invocation without its
               classification or write steps - the inline trigger lines
               exist to make the Read unconditional when the trigger holds.

Performance: n/a (static reference document).
-->

## Phase 0a-open-goal: Open-goal loop init or resume (conditional)

### Step 0 - resume-vs-fresh classification (before any write). Provably complete partition.

Read `.agentic/batch-state.json` if present.

- Absent, or `mode != "open_goal"`: → Fresh init.
- `mode == "open_goal"`: classify via `termination_reason` first (authoritative when non-null, regardless of `status`); fall back to `status` sub-partition only when `termination_reason == null`.

  **A. `termination_reason` non-null (6 of 7 buckets; resolved without consulting `status`):**
  - `cap_reached_iterations` | `cap_reached_wallclock` → TERMINAL; print:
    ```
    A prior open-goal loop already terminated (reason: <termination_reason>, iteration <N>/<max_iterations>). Starting fresh clears this state. To continue this goal instead, re-invoke with max_iterations and/or max_wallclock_min set HIGHER than the current values (max_iterations=<X>, max_wallclock_min=<Y>). Confirm: fresh-start (delete + reinit) or raise-caps (continue from iteration <N+1>)? (fresh / raise-caps)
    ```
    Offer both `fresh` and `raise-caps`.
  - `blocked` → TERMINAL, fresh ONLY (raise-caps can't unblock a stuck Skeptic loop); prompt adds: "To resume the specific blocked iteration's stuck work instead, use the ordinary per-ticket Resume check against that iteration's own branch - this phase does not do that."
  - `goal_met` → TERMINAL, fresh ONLY (nothing to raise).
  - `paused_stale_pace` | `paused_operator_request` → RESUMABLE.

  **B. `termination_reason == null` (7th bucket; sub-partitioned on `status`, exhaustively):**
  - `status` in `{paused, interrupted}` → RESUMABLE.
  - `status == "active"` → apply Contract A's existing per-write `session_id`-mismatch determination to this READ (same 5-way logic Contract A uses to gate every `batch-state.json` WRITE - including the self-ownership carve-out - applied here as read-time classification):
    - `session_id` non-empty and matches current session → RESUMABLE (same-session continuation; covers crash-mid-advance re-invoked same session).
    - `session_id` non-empty, differs, AND `updated_at` older than 10 min → RESUMABLE, treated as implicitly interrupted (mirrors Phase 0a-pre "status=active AND updated_at>10min → implicit interrupt"). Covers crash-mid-advance surviving into a later session.
    - `session_id` non-empty, differs, AND `updated_at` within last 10 min → REFUSE, verbatim Contract C message: `"Another batch session is active for this project root (session_id=<X>, updated_at=<Y>). Wait for it to finish, kill it and re-invoke, or remove .agentic/batch-state.json and re-invoke."` Exit. (live-foreign-session; closes the null+active Contract-C bypass.)
    - `session_id` null/absent AND the CURRENT session's own id is ALSO null (self-ownership carve-out - see Contract A step 3) → RESUMABLE (self-owned, same as the matching-session row above; no force-takeover prompt - on a harness that cannot produce a matching session id, two nulls are indistinguishable by construction).
    - `session_id` null/absent AND the CURRENT session HAS its own non-null id (i.e. the self-ownership carve-out row above does NOT apply) → force-takeover prompt verbatim (Phase 0a-pre): `"WARNING: another session (session_id=<X>, updated_at=<Y>) may still be active. Force takeover? (yes/no). Identify the live session via .agentic/batch-state.json updated_at."` `yes` → RESUMABLE; `no` → exit/wait. (This is a READ-time classification of the ON-DISK file's null/absent id, distinct from but complementary to Contract A's WRITE-time self-ownership carve-out.)
  - `status == "complete"` → TERMINAL, fresh ONLY (safe default; unexpected/legacy combo).
  - `status == "stalled"` → TERMINAL, fresh ONLY (same rationale).
  - any other/unrecognized `status` → TERMINAL, fresh ONLY (safe default).

**Completeness statement:** every `(termination_reason, status)` pair lands in exactly one of {Fresh init, RESUMABLE, raise-caps-or-fresh (terminal-cap bucket), refuse}. Bucket A resolves 6 of 7 `termination_reason` values without consulting `status`. Bucket B exhaustively covers the 7th value (`null`) across all 5 named `status` enum values + explicit catch-all; `status==active` within bucket B is itself exhaustively partitioned by Contract A's 5-way `session_id`/staleness logic (including the self-ownership carve-out). No pair unclassified.

- On fresh (any TERMINAL branch): delete `batch-state.json` → Fresh init. (force-takeover "no" exits/waits, does NOT go fresh.)
- On raise-caps: refuse unless declared `max_iterations`/`max_wallclock_min` strictly greater than on-disk: `"raise-caps requires re-invoking with max_iterations and/or max_wallclock_min set higher than the existing values (current: max_iterations=<X>, max_wallclock_min=<Y>). Re-invoke with a higher value, or choose fresh."` On success: Contract A write (update, NO Contract C - update not create) setting raised cap(s), `termination_reason:null`, `status:"active"` → Advance to next iteration (idempotency-checked).
- On RESUMABLE (any sub-case incl. force-takeover yes): Contract A write `status:"active"`; do NOT reset `iteration` → Advance to next iteration (idempotency-checked).
- `goal_condition` divergence (unchanged): read from disk on any resume, never re-parsed; differing invocation value prints one-line "on-disk value governs" warning (mirrors Phase 0a-pre GENUINE-divergence pattern), continues.

### Advance to next iteration (idempotency-checked)

Read the last entry in `tickets[]` (if any):
- `tickets[]` empty OR last entry `status == "complete"`: no next-iteration entry yet → apply the IDENTICAL Contract A+B write Phase 12a "On no trigger, GOAL_MET false" performs (increment `open_goal.iteration`, append pending entry) - reused by reference.
- last entry `status` is `"pending"` or `"in_progress"`: a next-iteration entry was ALREADY appended (most likely by Phase 12a's advance-write interrupted before Phase 1 - the crash-mid-advance scenario). Do NOT increment `iteration` or append again - use the existing entry as-is. Prevents double-advance (silent skip/dupe of an iteration).

Either way, fall through to Phase 1 for the iteration corresponding to the last `tickets[]` entry.

### Fresh init (only via the branches above - never unconditional)

**Validation (refuse before Phase 1 on failure):**
- `goal_condition` missing → refuse: `"goal_mode=open_goal requires goal_condition to be declared. Re-invoke with goal_condition set."` Exit.
- `max_iterations` or `max_wallclock_min` missing/non-positive → refuse verbatim (trigger-catalog.md Hard-stop rule 5): `"goal_mode=open_goal requires max_iterations and max_wallclock_min to be declared - no unbounded default is permitted. Re-invoke with both fields set."` Exit.
- `dry_run`, if present, must be literal `true`/`false`; absent defaults to `false`. No refusal on absence.

**Contract C check (before any write):** apply the broadened Contract C check in `ds-implement-ticket.md` §Batch state contracts (binding) (Fresh init is one of the three triggering create-paths) - refuse verbatim if `batch-state.json` is active/foreign-session/recent. Exit on refusal.

**On successful validation (Contract A fresh write):**
1. Initialize `.agentic/batch-state.json`: `mode:"open_goal"`, `batch_id:"open-goal-<ISO8601>-<4hex>"`, `wallclock_cap_min:<max_wallclock_min>`, `wallclock_started_at:now`, `tickets:[]`, `open_goal:{active:true, goal_condition:<string>, iteration:1, max_iterations:<int>, risk_declared:null, termination_reason:null, dry_run:<bool>}`.
2. `loop-state-$LOOP_KEY.json` NOT touched here - initialized normally at Phase 6 loop init exactly as any ordinary iteration (no open-goal fields).
3. Breadcrumb: `[phase: open-goal-init | goal_condition="<condition>" | max_iterations=<N> | max_wallclock_min=<M> | dry_run=<bool>]`.
4. Fall through to Phase 1 for iteration 1.

**Off-by-one note (Minor):** at init, `iteration=1` but `tickets=[]` (len 0) - SOLE momentary exception to `iteration==len(tickets[])`, closed the moment Phase 1 of iteration 1 appends the first synthetic entry. From Phase 1 of iteration 1 onward, the invariant holds continuously.

**Per-iteration ticket lifecycle.** Each iteration's synthetic `tickets[]` entry (`ticket_id:"<goal-slug>-iter-N"`, `cluster_id:"open-goal"`) follows the SAME transition-write pattern ordinary batch tickets use: `pending → in_progress` at Phase 1 start, `in_progress → complete` at Phase 12, or `→ blocked` via "Batch-mode escalation routing" (Phase 6). Every transition applies Contract A + Contract B.

**Interaction with top-level "Resume check (before setup)".** That check derives `LOOP_KEY` and reads `loop-state-$LOOP_KEY.json` before Phase 0, independent of this phase. A mid-iteration interrupted resume jumps to that iteration's resume entry point; Phase 0a-open-goal is never re-entered that session. Step 0 fires only on a normal Phase 0 pass reaching `goal_mode=open_goal`.

## Phase 6: Skeptic review

### Open-goal condition check (clean exit only, `goal_mode=open_goal` invocations only)

2. Set `batch-state.json.open_goal.risk_declared` to this iteration's classification (`low | elevated | trivial`) - Contract A+B write. Satisfies invariant (c) on the DURABLE record (see `content/references/trigger-catalog.md` §Risk and review discipline (c)).
3. **Scope gate (mirrors invariant (e)):** `risk_declared == "elevated"` → spawn `goal-condition-evaluator` (Tier 1/haiku, omit model param) with `goal_condition`, `iteration_evidence_hint` (finding IDs/files + ≤500-char excerpt of this iteration's `quality_gate_results.raw_output` when `goal_condition` plausibly references gate output), `skeptic_signoff_confirmed:true`; no worktree isolation. `low`/`trivial` → no spawn; conductor evaluates directly.
4. **Return handling:** `GOAL_MET:true` → set `open_goal.termination_reason="goal_met"` (Contract A+B); unit still ships normally UNLESS `dry_run==true`; outer loop exits at Phase 12a. `GOAL_MET:false` → status update only; continue at Phase 12a. `BLOCKED`/unavailable/errored/timeout/malformed → conductor-direct evaluation immediately (invariant (e)); **never** the generic Worker-BLOCKED=`cap_reached` escalation from `content/references/subagent-protocol.md` §Loop transition rules.
