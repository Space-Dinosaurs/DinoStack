<!--
Purpose: Full reference for the Tracker Writeback Helper - the reusable
         subagent invocation pattern that every tracker state-transition
         call site (Phase 11, the 7 W1-W7 sites in
         content/commands/ds-implement-ticket.md, and the awaiting callers
         in ds-ticket-status-sync.md and ds-wrap.md Part F) shares: the
         invocation contract, the forward-only guard's category-rank and
         same-category pipeline sub-rank algorithm, the diagnostic-
         enrichment sub-step, and failure/skip logging formats.

Public API: Read-only reference document, addressed by its retained
            `## Tracker Writeback Helper` heading. Cross-referenced from:
            content/commands/ds-implement-ticket.md (Setup, Phase 2c,
            Phase 11, and the 7 W1-W7 writeback call sites),
            content/commands/ds-ticket-status-sync.md (Preflight and both
            single-ticket/`--all` spawn sites),
            content/commands/ds-wrap.md (Part F Gate/Reconcile),
            content/commands/ds-init-project.md (tracker_state_diagnostic
            config doc).

Upstream deps: none (prose reference only; no code, no runtime execution).
               Assumes the reader already has the "Caller enumeration"
               block (`content/commands/ds-implement-ticket.md` §"Tracker
               Writeback Helper") in context - this reference's own
               precedence note (below) names it as the source of truth
               for the five duplicated statements.

Downstream consumers: content/commands/ds-implement-ticket.md (Phase 11,
                      W1-W7), content/commands/ds-ticket-status-sync.md,
                      content/commands/ds-wrap.md Part F,
                      content/commands/ds-init-project.md.

Failure modes: Prose reference; does not auto-execute. A stale copy would
               misdescribe the forward-only guard's permit/skip outcomes or
               the diagnostic-enrichment contract for every call site at
               once - keep in sync with the live call sites listed above
               whenever the algorithm changes.

Performance: n/a (static reference document).
-->

## Tracker Writeback Helper

Reusable subagent invocation pattern. Used by Phase 11 (existing), the 7 W1-W7 sites in `content/commands/ds-implement-ticket.md`, and awaiting callers - 3 modes of `/ds-ticket-status-sync` (single-ticket, `--all`, `--pending-merge`) plus `/ds-wrap` Part F. Gated on `TRACKER != none`; no-op otherwise.

> Note: five statements in this reference - the awaiting-caller enumeration, `forward_only_guard` applicability, the step 4.d.iv stderr split, the `SKIPPED:` line format, and the "never reads `.agentic/tracker-states.json`" ranking rule - are duplicated verbatim in the "Caller enumeration" block of `content/commands/ds-implement-ticket.md` §"Tracker Writeback Helper". The duplication is intentional and kept in the kernel command file because `scripts/codex-skills.py`'s `documents()` transform only reads `content/commands/*.md`; this reference is a symlinked resource the transform never scans. The kernel "Caller enumeration" block is the SOURCE OF TRUTH for all five - if the two ever disagree, the kernel block governs.

**Invocation contract:**

When the conductor reaches a writeback boundary:
1. Skip entirely if `TRACKER == none`.
2. Spawn the tracker-writeback subagent (Tier 1, `general-purpose`) in background (fire-and-forget; do NOT wait for return before continuing the phase). Fire-and-forget applies at W1-W7 and Phase 11; awaiting callers - 3 modes of `/ds-ticket-status-sync` (single-ticket, `--all`, `--pending-merge`) plus `/ds-wrap` Part F - are enumerated in the guard's step 4.d.iv below.
3. Pass to the subagent:
   - `tracker`: `linear` | `jira`
   - `ticket_id`: from current task context
   - `target_state`: one of the resolved `TRACKER_STATE_*` variables
   - `forward_only_guard`: `true` for every writeback caller - the 7 new sites, Phase 11 (preserving its prior hardcoded `Testing` behavior), and the awaiting callers - 3 modes of `/ds-ticket-status-sync` (single-ticket, `--all`, `--pending-merge`) plus `/ds-wrap` Part F
   - `tracker_state_values`: `{ "IN_PROGRESS": "$TRACKER_STATE_IN_PROGRESS", "IN_REVIEW": "$TRACKER_STATE_IN_REVIEW", "QA": "$TRACKER_STATE_QA", "DEV_COMPLETE": "$TRACKER_STATE_DEV_COMPLETE", "BLOCKED": "$TRACKER_STATE_BLOCKED", "DONE": "$TRACKER_STATE_DONE" }` - the 6 values resolved once in `content/commands/ds-implement-ticket.md` Setup; required by the forward-only guard's same-category pipeline sub-rank
   - `diagnostic_enabled`: `$TRACKER_STATE_DIAGNOSTIC` (boolean, resolved once in `content/commands/ds-implement-ticket.md` Setup; gates the diagnostic-enrichment sub-step of step 5 below)
   - `linear_team_key`: `$TICKET_PREFIX` (Linear only; the team key already resolved in `content/commands/ds-implement-ticket.md` Setup from the `## Linear` `Team:` field - scopes the live `list_workflow_states` call in step 5's diagnostic-enrichment sub-step to the correct team, exactly as Phase 2c's own Fetch step already does for its advisory-only call)
   - `pipeline_order`: the ordered list of pipeline tokens resolved once in `content/commands/ds-implement-ticket.md` Setup as `TRACKER_PIPELINE_ORDER`, defaulting to `["IN_PROGRESS","IN_REVIEW","QA"]`; a declared order may omit `DEV_COMPLETE`, in which case `DEV_COMPLETE` is appended at the trailing position, so the effective list consumed by the guard is always the 4 tokens `IN_PROGRESS`/`IN_REVIEW`/`QA`/`DEV_COMPLETE`. Rank = index within that effective list, consumed by step 4.d.iv's pipeline sub-rank.
   - `dev_complete_declared`: boolean, resolved once in `content/commands/ds-implement-ticket.md` Setup as `TRACKER_DEV_COMPLETE_DECLARED`. `true` when the project declared a dev-complete field (`JIRA_STATE_DEV_COMPLETE`, `State Dev Complete:`, or the overlay's `state_dev_complete`); `false` when `TRACKER_STATE_DEV_COMPLETE` was inherited from the resolved `TRACKER_STATE_DONE`. Consumed by step 4.d.iv: `DEV_COMPLETE` participates in the pipeline sub-rank only when this is `true`. Absent or unparseable is treated as `false` (fail-safe: an inherited value carries no rank, which is the pre-DS-117 behavior).
   - Tracker-specific config: `LINEAR_WORKSPACE`, `LINEAR_QA_ASSIGNEE_ID` for Linear; equivalent for Jira

**Subagent responsibilities (extended for `forward_only_guard`):**

1. **Pre-read current state:**
   - Linear: call `mcp__linear__get_issue` to read the ticket's current state, capturing both `state.type` and `state.name` (e.g. `"In Review"`) from the response.
   - Jira: call `mcp__mcp-atlassian__jira_get_issue` to read the ticket's current status, capturing both `fields.status.statusCategory.key` and `fields.status.name` (e.g. `"In Review"`) from the response.

2. **Field-absence guard.** If the pre-read call succeeds (no MCP/API error) but the returned object omits `state.type` (Linear) or `fields.status.statusCategory.key` (Jira) - a successful call with an incomplete response, not a call failure - treat it identically to the pre-read failure in step 5: **skip** the transition, do not compute any rank, and emit one stderr line: `tracker-writeback: <ticket_id> pre-read succeeded but response omitted the state-type field ('state.type' / 'statusCategory.key') - skipping, no rank assumed.` Absence always routes to skip, never to permit - a missing category must never be read as "already past every target" or "not yet at any target."

3. **Compute category rank** (governs cross-category comparisons only):
   - Linear: `backlog` < `unstarted` < `started` < `completed` < `canceled` < `duplicate`; `canceled` and `duplicate` are both terminal (never overwritten by any automatic transition).
   - Linear defensive fallback (separate from the primary enum above): if a state's `type` is instead spelled `cancelled` (double L) - e.g. a differently-shaped MCP response or a stale cached row - treat it as terminal too. The canonical/primary spelling the Linear API emits is single-L `canceled`; this fallback exists only for robustness against a non-conforming response shape.
   - Jira: `new` < `indeterminate` < `done` (via `statusCategory.key`); a status whose category or name matches cancellation semantics (Won't Do, Cancelled, Duplicate, Will Not Fix) is terminal (never overwritten).

4. **Apply the guard** - category rank first, then a same-category pipeline sub-rank:
   a. If current state is terminal (Linear `canceled` / `duplicate` / defensive `cancelled` (double L), or Jira cancellation-semantic): **skip** unconditionally.
   b. If `category_rank(current) < category_rank(target)`: **permit** (forward move across categories).
   c. If `category_rank(current) > category_rank(target)`: **skip** (backward move across categories - this is what prevents Blocked or In Review from ever overwriting Done).
   d. If `category_rank(current) == category_rank(target)` (the same-category band that holds In Progress / In Review / QA / Blocked on both trackers), apply the **pipeline sub-rank** by case-insensitive exact-name match against the 6 values in `tracker_state_values`:
      - i. If `target_state`'s name case-insensitive-exact-matches the CURRENT state's name: **skip** (idempotent no-op - already there).
      - ii. Else if `target_state` matches `BLOCKED`: **permit** unconditionally. Blocked is always a permitted same-category target on both trackers - a genuine problem signal that must never be silently dropped, regardless of where the tracker's columns happen to sit.
      - iii. Else if the CURRENT state's name matches `BLOCKED`: **permit** unconditionally. Resuming or unblocking a ticket must always be able to move it forward into In Progress, In Review, or QA - Blocked never blocks a later forward transition.
      - iv. Else, look up current and target against `pipeline_order` (an ordered list of the tokens `IN_PROGRESS`/`IN_REVIEW`/`QA`/`DEV_COMPLETE`, each resolved against `tracker_state_values` the same way): rank = index within `pipeline_order`. A declared `pipeline_order` may omit `DEV_COMPLETE`; when it does, `DEV_COMPLETE` is appended at the trailing position before ranking, so the effective list is always 4 tokens. `pipeline_order` defaults to the ordered sequence `IN_PROGRESS` (rank 0) < `IN_REVIEW` (rank 1) < `QA` (rank 2) < `DEV_COMPLETE` (rank 3) - the historical order in which AE's own writeback sites fire (W1 < W2 < W3 < W7) - unless the project declares `JIRA_PIPELINE_ORDER` / `Pipeline order:` in `AGENTS.md` (see `content/commands/ds-implement-ticket.md` Setup), in which case the declared order governs instead. `BLOCKED` and `DONE` are never pipeline tokens and can never be declared as one: `BLOCKED` is resolved earlier by ii/iii, and `DONE` is terminal by construction, so a correctly configured `DONE` is always in the terminal category band and is protected by the cross-category comparison in 4.c rather than by a sub-rank. Giving `DONE` a pipeline rank would be inert in every correct configuration and would, in a misconfiguration where `DONE` names a non-terminal lane, permit an automatic transition into terminal Done - which AE must never fire.
        - **Inherited dev-complete carries no rank.** `DEV_COMPLETE` participates in this sub-rank ONLY when the project DECLARED a dev-complete field (`JIRA_STATE_DEV_COMPLETE`, `State Dev Complete:`, or the overlay's `state_dev_complete`), as reported by the `dev_complete_declared` input. When the value was INHERITED from the resolved `TRACKER_STATE_DONE` because no dev-complete field was declared, it resolves to no pipeline rank and falls through to the skip branch below, exactly as it did before dev-complete existed. This applies to `DEV_COMPLETE` wherever it appears in the comparison, as the CURRENT state's name as well as the target's. Rationale: a project that points its Done field at a non-terminal lane as a workaround has, by construction, not told AE where that lane sits relative to its QA lane - and on a real board the two commonly sit in the opposite order (`Ready for QA` before `QA in Progress`). Ranking an inherited value trailing would let W7 permit a move from the QA lane BACK to the dev-complete lane, undoing W3's own write. Declaring a dev-complete field is the operator's signal that the position is intentional; inheritance is not.
        - **Name collision.** The lookup is a name-to-rank lookup over the pipeline tokens only, so a name that matches a pipeline token resolves to that token's rank regardless of also matching a non-pipeline key such as `DONE`. This rule applies only to a DECLARED `DEV_COMPLETE`; an inherited one has no rank to collide with (see the preceding bullet). When a DECLARED name matches more than one PIPELINE token - for example an operator pointing both `State QA:` and `State Dev Complete:` at the same lane on a short board - it resolves to the HIGHEST such rank.
        - If BOTH names resolve to a pipeline rank: **permit** iff `pipeline_rank(current) < pipeline_rank(target)`; otherwise **skip**.
        - Otherwise (at least one name does not resolve to a pipeline rank - either because it does not match any of the 6 known `tracker_state_values` at all, or because it matches one of the 6 values that has no pipeline rank, e.g. `DONE` or `BLOCKED` reached here only on a misconfigured tracker where that value's category coincides with this same-category band): **skip** unconditionally. Set the return payload's `unmatched_state_name` to that name only when it does not resolve to any of the 6 known `tracker_state_values` at all - a name that resolves to a configured value but simply lacks a pipeline rank is not "unmatched." **Fire-and-forget call sites** (W1-W7, Phase 11 - these never read the subagent's return value) additionally emit ONE stderr line directly here, bounded to at most one line per fire because each fire covers exactly one ticket: `tracker-writeback: <ticket_id> current state '<name>' did not match any configured TRACKER_STATE_* value - skipping same-category comparison.` **Callers that await the result** - 3 modes of `/ds-ticket-status-sync` (single-ticket, `--all`, `--pending-merge`) plus `/ds-wrap` Part F - do NOT get a per-ticket stderr line for this branch; they read `unmatched_state_name` from each ticket's return, accumulate across their sweep, and print exactly ONE aggregate line at the end.
5. **Soft-fail:** any transition error logged to stderr; subagent returns `{ "status": "failed", "errors": [...] }`. Conductor logs and continues; never blocks the phase. A state pre-read failure (MCP/API error) is also a skip: log a one-line warning to stderr and do not proceed. Do not assume any rank when the pre-read fails.

   **Diagnostic enrichment (new, gated on `diagnostic_enabled`; runs strictly AFTER a transition attempt, never before, and can never change whether the write happens).** When step 4 permits a transition, the subagent attempts it using the EXISTING mechanism, completely unchanged from today - Linear: a single `mcp__linear__save_issue` call with `state: target_state`; Jira: discover available transitions via `mcp__mcp-atlassian__jira_get_transitions` on this ticket, then call `mcp__mcp-atlassian__jira_transition_issue` for the matching transition id. **Nothing runs before this attempt - there is no new round-trip on the happy path on either tracker.** (Jira's discovery call is not new API surface introduced by this plan - it is already required to obtain a transition id before any Jira transition can be attempted at all; Linear's `save_issue` remains the single direct call it is today.)

   Only when that attempt does NOT succeed, and only when `diagnostic_enabled` is true, does the subagent attempt - best-effort - to enrich the outcome with a `diagnostic` string, using ONLY a data source positively established as sound for the claim being made on that tracker. **Any failure of this enrichment step itself is swallowed: it degrades the message (`diagnostic` stays `null`), it never changes `status`, `transitioned`, or any other part of the original outcome.**
   - **Jira** - reuse the `jira_get_transitions` result already fetched during the attempt above (no new call). If `target_state` did not match any available transition's target name (this was already known before `jira_transition_issue` was ever called): relabel the outcome `status: "skipped_unconfigured_state"` and set `diagnostic` to: `"'<target_state>' not among the transitions currently available for this ticket (currently in '<current_status>') - available right now: [<comma-separated available transition target names, or "(none)">]. This is a per-ticket snapshot, not the project's full workflow - if '<target_state>' is reachable via a different path, this ticket just isn't there yet. Verify the name in AGENTS.md, or check the tracker directly."`. If instead a matching transition WAS found but the `jira_transition_issue` call itself errored (a genuine API/transient failure - the configured name was fine), leave `status: "failed"` exactly as today; there is nothing meaningful to enrich.
   - **Linear** - make ONE best-effort call to `mcp__linear__list_workflow_states` filtered to `linear_team_key` (team-scoped, genuinely global for this team, confirmed via the `@linear/sdk` `WorkflowState` type). If this call itself fails: swallow it per the rule above - leave `status: "failed"` and `diagnostic: null`. If it succeeds: check whether `target_state` case-insensitive-exact-matches any returned state name. If NOT found: relabel the outcome `status: "skipped_unconfigured_state"` and set `diagnostic` to: `"'<target_state>' not found among <linear_team_key>'s live workflow states - available: [<comma-separated live state names>]."`. If `target_state` WAS found among the live states (the `save_issue` failure had some other cause - transient error, permissions, etc. - the configured name was fine), leave `status: "failed"` with `diagnostic` still attached as informational context, since a live list was already fetched successfully.

   This step can only relabel a `"failed"` outcome to `"skipped_unconfigured_state"` when live data positively confirms the configured name is not currently usable; it can never convert `"failed"` into `"ok"`, and it can never prevent, delay, or retry the original transition attempt.

   Fire-and-forget call sites (W1-W7, Phase 11) emit, for a `"skipped_unconfigured_state"` outcome only, the `diagnostic` text as ONE stderr line: `tracker-writeback: <ticket_id> -> '<target_state>' SKIPPED: <diagnostic>`. A plain `"failed"` outcome (enriched with `diagnostic` or not) continues to use the existing `FAILED:` line format (see "Failure logging" below, extended for this case). Callers that await the result (3 modes of `/ds-ticket-status-sync`, `/ds-wrap` Part F) read `status` and `diagnostic` from the return payload and format them per their own operator-visible-line conventions (see `content/commands/ds-ticket-status-sync.md` and `content/commands/ds-wrap.md` Part F).

**Rejected: fully tracker-derived pipeline order.** A live-fetched global ordering was considered instead of a declarable default. Jira's only available state-enumeration call (`jira_get_transitions` on a probe ticket) returns transitions available from that ticket's CURRENT status only - an edge-local view of the workflow graph, not a global ordering of all states - so no cross-tracker-symmetric live-derived order can be built that works the same way for both currently-supported trackers. A mechanism that only works for one tracker breaks universality; the explicit-declaration-with-fixed-default design above is the soundest project-level alternative.

**This ranking never reads `.agentic/tracker-states.json`.** It uses only the live pre-read of the ticket's own current state (step 1) and the 6 `tracker_state_values` strings resolved once in `content/commands/ds-implement-ticket.md` Setup. The Phase 2c cache remains Phase 2c-only and purely advisory; no writeback subagent reads or writes it.

**Failure logging:** subagent stderr is captured by the conductor's `ds-emit` event; one operator-visible line per failure of the form: `tracker-writeback: <ticket_id> -> '<target_state>' FAILED: <error>`. A `status: "skipped_unconfigured_state"` outcome uses the distinct SKIPPED form defined in step 5's diagnostic-enrichment sub-step instead: `tracker-writeback: <ticket_id> -> '<target_state>' SKIPPED: <diagnostic>`. No block, either form.

For full details of the Phase 11 writeback subagent brief shape, see the Phase 11 block in `content/commands/ds-implement-ticket.md` - the brief is unchanged except for the addition of `target_state`, `forward_only_guard`, `tracker_state_values`, and `pipeline_order` parameters. Phase 11's own Jira `JIRA_QA_TRANSITION`-gated transition mechanism (see "Behavior" in that Phase 11 block - unaffected, unedited by this plan) and its Linear path both additionally receive the diagnostic-enrichment behavior from `## Tracker Writeback Helper` step 5 when a transition attempt does not succeed; this plan does not change what Phase 11 writes or when, only what it reports when it does not write.
